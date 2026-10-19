"""Apply one decision.json to the admin API.

    review/.venv/bin/python review/apply.py <dir>     # dir holds decision.json and photos.json

The agent decides, this writes. One place for the writes means one place
that checks them, whatever model made the decision.

The place is verified, by_agent, only when every write went through. A
failed write leaves it open so it is not signed off half done.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse

from dossier import api


def _post(path, body, log):
    try:
        res = api("POST", path, body, timeout=120)
        log.append({"ok": True, "path": path, "action": body.get("action")})
        return res
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:200]
        # A kill between the write and the verify leaves the photo in place.
        # Adding it again has to count as done, or the place never closes.
        if err.code == 422 and "already in the drawer" in detail:
            log.append({"ok": True, "path": path, "action": body.get("action"),
                        "note": "already there"})
            return {"ok": True}
        log.append({"ok": False, "path": path, "action": body.get("action"),
                    "error": f"{err.code} {detail}"})
    except Exception as err:
        log.append({"ok": False, "path": path, "action": body.get("action"),
                    "error": str(err)[:200]})
    return None


def _commons(raw):
    """A wiki URL. The server reads `File:…` as a file: URL and rejects it."""
    s = raw.strip()
    name = re.sub(r"(?i)^file:", "", s).strip()
    if name == s.strip():
        return s
    return "https://commons.wikimedia.org/wiki/File:" + urllib.parse.quote(
        name.replace(" ", "_")
    )


def _url_key(url):
    return (url or "").strip().rstrip("/").lower()


def _ints(value):
    out = []
    for v in value or []:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


def apply(work, uuid, dry=False, backend=None, model=None):
    path = os.path.join(work, "decision.json")
    if not os.path.exists(path):
        return {"ok": False, "error": "no decision.json", "writes": []}
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except json.JSONDecodeError as err:
        return {"ok": False, "error": f"decision.json: {err}", "writes": []}
    with open(os.path.join(work, "photos.json"), encoding="utf-8") as f:
        photos = {int(k): v for k, v in json.load(f).items()}
    pages, officials, have_urls = {}, {}, set()
    place_path = os.path.join(work, "place.json")
    if os.path.exists(place_path):
        with open(place_path, encoding="utf-8") as f:
            for t in json.load(f).get("texts") or []:
                if t.get("url"):
                    have_urls.add(_url_key(t["url"]))
    if os.path.exists(os.path.join(work, "pages.json")):
        with open(os.path.join(work, "pages.json"), encoding="utf-8") as f:
            pages = {p["n"]: p for p in json.load(f)}
    if os.path.exists(os.path.join(work, "official.json")):
        with open(os.path.join(work, "official.json"), encoding="utf-8") as f:
            officials = {o["o"]: o for o in json.load(f)}

    plan = []
    skip = set(_ints(d.get("skip")))
    for n in _ints(d.get("prioritize")):
        p = photos.get(n)
        if p and n not in skip and not p.get("prioritized"):
            plan.append(("/place", {"action": "prioritize_photo", "place": uuid,
                                    "source": p["source"], "file": p["file"],
                                    "prioritized": True}))
    for n in sorted(skip):
        p = photos.get(n)
        if p:
            plan.append(("/place", {"action": "skip_photo", "place": uuid,
                                    "source": p["source"], "file": p["file"],
                                    "skipped": True}))
    for f in d.get("add_commons") or []:
        if isinstance(f, str) and f.strip():
            plan.append(("/photos", {"action": "add", "place": uuid,
                                    "file": _commons(f)}))
    for o in d.get("add_official") or []:
        # "O3", 3, or {"url": ..., "page": ...}
        if isinstance(o, (int, str)) and not (isinstance(o, str) and o.startswith("http")):
            try:
                found = officials.get(int(str(o).lstrip("Oo")))
            except ValueError:
                found = None
            o = {"url": found["url"], "page": found["page"]} if found else None
        if isinstance(o, dict) and o.get("url"):
            body = {"action": "official", "place": uuid, "url": o["url"]}
            if o.get("page"):
                body["page"] = o["page"]
            plan.append(("/photos", body))
    for s in d.get("add_sources") or []:
        # {"page": 2}: a page the dossier already fetched, as it was cut out.
        if isinstance(s, (int, str)) and str(s).isdigit():
            s = {"page": int(s)}
        if isinstance(s, dict) and s.get("page") is not None and not s.get("url"):
            try:
                p = pages.get(int(s["page"]))
            except (TypeError, ValueError):
                p = None
            if not p:
                continue
            s = {"url": p["url"], "title": s.get("title") or p["title"],
                 **({} if p.get("wikipedia") else
                    {"body_file": s.get("body_file") or f"page{p['n']}.txt"})}
        if not isinstance(s, dict) or not s.get("url"):
            continue
        if _url_key(s["url"]) in have_urls:
            continue
        have_urls.add(_url_key(s["url"]))
        body = {"action": "add", "place": uuid, "url": s["url"]}
        if s.get("title"):
            body["title"] = str(s["title"])[:300]
        if s.get("body_file"):
            fp = os.path.join(work, os.path.basename(s["body_file"]))
            if os.path.exists(fp):
                with open(fp, encoding="utf-8") as f:
                    body["body"] = f.read()[:200000]
        elif s.get("body"):
            body["body"] = str(s["body"])[:200000]
        plan.append(("/sources", body))
    # Only a source added through the admin can be removed. A pipeline
    # source_id here is a write that fails and leaves the place open.
    added = set()
    if os.path.exists(place_path):
        with open(place_path, encoding="utf-8") as f:
            added = {t["added_id"] for t in json.load(f).get("texts") or [] if t.get("added_id")}
    for i in _ints(d.get("remove_sources")):
        if i in added:
            plan.append(("/sources", {"action": "remove", "id": i}))
    title = d.get("title")
    if isinstance(title, str) and title.strip():
        plan.append(("/place", {"action": "set_title", "place": uuid,
                                "title": title.strip()[:200]}))
    if d.get("uninteresting") is True:
        plan.append(("/place", {"action": "uninteresting", "place": uuid,
                                "uninteresting": True}))
    if d.get("aside") is True:
        plan.append(("/compare", {"action": "aside", "place": uuid}))
    flag = d.get("flag")
    if isinstance(flag, str) and flag.strip():
        plan.append(("/flags", {"action": "add", "place": uuid,
                                "note": flag.strip()[:2000]}))

    if dry:
        return {"ok": True, "dry": True, "decision": d,
                "plan": [[p, b] for p, b in plan], "writes": []}

    log = []
    for p, b in plan:
        _post(p, b, log)
    failed = [w for w in log if not w["ok"]]
    verified = False
    if not failed:
        body = {"action": "verify", "place": uuid, "by_agent": True}
        kind = {"local": "local", "agent": "cursor", "cursor": "cursor"}.get(backend)
        if kind:
            body["backend"] = kind
        if model:
            body["model"] = model
        res = _post("/place", body, log)
        verified = bool(res and res.get("verified_by_agent") is True)
        if res and not verified:
            _post("/place", {"action": "clear_verified", "place": uuid}, log)
    return {"ok": verified, "decision": d, "writes": log,
            "error": None if verified else "not verified"}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("apply.py <dir> <uuid> [--dry]")
    if not os.environ.get("FL_AGENT_TOKEN"):
        from manager import ensure_token
        ensure_token()
    print(json.dumps(apply(sys.argv[1], sys.argv[2], dry="--dry" in sys.argv),
                     ensure_ascii=False, indent=1))
