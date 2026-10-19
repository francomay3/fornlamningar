"""Everything an agent reads about one place, fetched before it starts.

    review/.venv/bin/python review/dossier.py <uuid>      # build one into fl-review/probe

The agent used to spend most of its turns fetching: the place three times,
each thumbnail as a separate read, the same searches again. The fetching
is deterministic, so it happens here, once. What is left for the agent is
the judgement.

Writes, into the agent's workspace:

    place.json   the admin desk response, untouched
    sheet.jpg    every photograph not skipped, numbered, on one image
    pageN.txt    when the register is the only source: the search results,
                 fetched, the article text cut out of each page
    official.jpg photographs found on those pages when the page is a Swedish
                 authority, numbered O1, O2...
    dossier.md   what the agent reads first

Runs the Commons nearby search when the place has no photograph that is
not skipped. That write is the one the agent would have made first, and it
ships nothing until a photograph is prioritized.
"""

import concurrent.futures
import io
import json
import os
import queue
import re
import shutil
import sys
import threading
import urllib.parse
import urllib.request

import trafilatura
from lxml import etree
from PIL import Image, ImageDraw, ImageFont


class _Xml:
    """The one thread that may touch libxml2.

    libxml2 aborts the process if two threads parse at once. Every site
    running in parallel calls `call`. The downloads, the models and the
    Cursor agents do not go through here. Only the parse does, and this
    thread runs those one at a time.
    """

    def __init__(self):
        self._q = queue.Queue()
        threading.Thread(target=self._serve, name="libxml2", daemon=True).start()

    def _serve(self):
        while True:
            fn, args, box = self._q.get()
            try:
                box.put((True, fn(*args)))
            except Exception as err:
                box.put((False, err))

    def call(self, fn, *args):
        box = queue.Queue(1)
        self._q.put((fn, args, box))
        ok, value = box.get()
        if not ok:
            raise value
        return value


_xml = _Xml()

API = os.environ.get("FL_API", "https://franco-may.com/api/fornlamningar")
UA = "fornkoll-review/1.0 (https://franco-may.com)"
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130 Safari/537.36")

CELL = 300
COLS = 6
MAX_PHOTOS = 48
REGISTER_KINDS = ("register", "register_vegetation")
MAX_PAGES = 4
MAX_OFFICIAL = 12
# The same list the photos route accepts for action "official".
OFFICIAL_HOSTS = ("lansstyrelsen.se", "raa.se", "riksantikvarieambetet.se",
                  "kulturarvsdata.se", "kringla.nu", "digitaltmuseum.se", "dimu.org")
# Results that are never an article about a place.
NOT_ARTICLES = ("facebook.com", "instagram.com", "youtube.com", "tiktok.com",
                "hitta.se", "eniro.se", "booking.com", "google.", "ratsit.se",
                "merinfo.se", "allabolag.se", "hemnet.se", "blocket.se")


def official(url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in OFFICIAL_HOSTS)


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA,
                                               "Accept-Language": "sv,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        kind = res.headers.get("Content-Type") or ""
        return res.read(4_000_000), kind, res.geturl()


def _read_html(html, final):
    """Runs only on the libxml2 thread."""
    text = trafilatura.extract(html, url=final, include_comments=False,
                               include_tables=True, favor_recall=True) or ""
    meta = trafilatura.extract_metadata(html)
    title = (meta.title if meta and meta.title else "") or final
    images = []
    if official(final):
        xml = trafilatura.extract(html, url=final, output_format="xml",
                                  include_images=True, favor_recall=True)
        seen = set()
        if xml:
            try:
                root = etree.fromstring(xml.encode())
                for g in root.iter("graphic"):
                    src = g.get("src") or ""
                    if not src:
                        continue
                    src = urllib.parse.urljoin(final, src)
                    low = src.lower()
                    if (src in seen or low.endswith((".svg", ".gif"))
                            or "logo" in low or "icon" in low):
                        continue
                    seen.add(src)
                    images.append((src, g.get("alt") or g.get("title") or ""))
            except etree.XMLSyntaxError:
                pass
    return title.strip(), text.strip(), images


def fetch_page(url):
    """(title, article text, [(image url, alt)]) or None."""
    try:
        raw, kind, final = _get(url)
    except Exception:
        return None
    if "html" not in kind:
        return None
    try:
        return _xml.call(_read_html, raw.decode("utf-8", "replace"), final)
    except Exception:
        return None


def _token():
    value = os.environ.get("FL_AGENT_TOKEN", "").strip()
    if not value:
        sys.exit("FL_AGENT_TOKEN is not set")
    return value


def api(method, path, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.load(res)


def _small(url):
    # Commons serves a fixed ladder of widths; 330 is on it.
    return re.sub(r"/\d+px-", "/330px-", url, count=1)


def _fetch_image(url):
    for candidate in (_small(url), url) if "/thumb/" in url else (url,):
        try:
            req = urllib.request.Request(candidate, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as res:
                img = Image.open(io.BytesIO(res.read()))
                img.load()
                return img.convert("RGB")
        except Exception:
            continue
    return None


def commons_sizes(files):
    """{"File:x.jpg": (width, height)} for the originals, 50 per request."""
    out = {}
    files = [f for f in files if f.startswith("File:")]
    for i in range(0, len(files), 50):
        q = urllib.parse.urlencode({"action": "query", "format": "json", "prop": "imageinfo",
                                    "iiprop": "size", "titles": "|".join(files[i:i + 50])})
        try:
            req = urllib.request.Request("https://commons.wikimedia.org/w/api.php?" + q,
                                         headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as res:
                body = json.load(res)
        except Exception:
            continue
        query = body.get("query") or {}
        names = {n["to"]: n["from"] for n in query.get("normalized") or []}
        for page in (query.get("pages") or {}).values():
            info = (page.get("imageinfo") or [{}])[0]
            if info.get("width"):
                title = page.get("title") or ""
                out[names.get(title, title)] = (info["width"], info["height"])
    return out


def contact_sheet(photos, path, images=None, sizes=None, save_dir=None):
    """photos: [(label, thumb_url, prioritized)]. Returns how many drew.

    Every image fills its cell, so a small thumbnail does not read as a bad
    photograph. `sizes`, by label, is the original's size, written under it.
    """
    if not photos:
        return 0
    sizes = sizes or {}
    if images is None:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            images = list(pool.map(lambda p: _fetch_image(p[1]), photos))
    if save_dir:
        os.makedirs(save_dir, exist_ok=True)
        for (label, _, _), img in zip(photos, images):
            if img is not None:
                img.save(os.path.join(save_dir, f"{label}.jpg"), quality=85)
    rows = (len(photos) + COLS - 1) // COLS
    sheet = Image.new("RGB", (COLS * CELL, rows * CELL), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 34)
        small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
    except OSError:
        font = small = ImageFont.load_default()
    drawn = 0
    for i, ((number, _, prioritized), img) in enumerate(zip(photos, images)):
        x, y = (i % COLS) * CELL, (i // COLS) * CELL
        if img is not None:
            scale = min((CELL - 6) / img.width, (CELL - 6) / img.height)
            img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                             Image.LANCZOS)
            sheet.paste(img, (x + (CELL - img.width) // 2, y + (CELL - img.height) // 2))
            drawn += 1
        else:
            draw.text((x + 60, y + CELL // 2), "sin imagen", fill="gray", font=font)
        if number in sizes:
            w, h = sizes[number]
            text = f"{w}×{h}"
            box = draw.textbbox((x + 6, y + CELL - 30), text, font=small)
            draw.rectangle((box[0] - 3, box[1] - 3, box[2] + 3, box[3] + 3), fill="black")
            draw.text((x + 6, y + CELL - 30), text, fill="white", font=small)
        label = f"{number}{'*' if prioritized else ''}"
        box = draw.textbbox((x + 6, y + 6), label, font=font)
        draw.rectangle((box[0] - 4, box[1] - 4, box[2] + 4, box[3] + 4), fill="black")
        draw.text((x + 6, y + 6), label, fill="yellow", font=font)
        draw.rectangle((x, y, x + CELL - 1, y + CELL - 1), outline="gray")
    sheet.save(path, quality=82)
    return drawn


def _clip(text, n):
    text = (text or "").strip()
    return text if len(text) <= n else text[:n].rstrip() + " …"


def build(uuid, out, kind=""):
    """Fill `out` with this place's files. Whatever was there goes first."""
    os.makedirs(out, exist_ok=True)
    for name in os.listdir(out):
        fp = os.path.join(out, name)
        if os.path.isfile(fp):
            os.remove(fp)
        elif name == "thumbs":
            shutil.rmtree(fp)

    place = api("GET", f"/place?id={uuid}")
    actions = []
    live = [a for a in place.get("archive") or [] if not a.get("skipped")]
    if not live:
        try:
            got = api("POST", "/photos", {"action": "nearby", "place": uuid})
            actions.append(f"nearby: {got.get('found', 0)} encontradas, {got.get('added', 0)} nuevas")
            place = api("GET", f"/place?id={uuid}")
            live = [a for a in place.get("archive") or [] if not a.get("skipped")]
        except Exception as err:
            actions.append(f"nearby falló: {err}")

    place["_kind"] = kind
    with open(os.path.join(out, "place.json"), "w", encoding="utf-8") as f:
        json.dump(place, f, ensure_ascii=False, indent=1)

    title = place.get("title") or ""
    texts = place.get("texts") or []
    only_register = all((t.get("kind") or "") in REGISTER_KINDS for t in texts)

    searches = []
    if only_register and title:
        town = place.get("municipality") or ""
        # "Slott/herresäte" -> "slott". The kind is what keeps a farm name
        # from returning estate agents and the weather.
        what = (kind.split("/")[0].strip().lower() if kind else "")
        if not what and texts:
            head = re.match(r"\s*([A-ZÅÄÖa-zåäö-]{4,})\s*[,.]", texts[0].get("body") or "")
            what = head.group(1).lower() if head else ""
        queries = (f"{title} {what} {town}".strip(), f'"{title}" {what}'.strip())
        for q in dict.fromkeys(q for q in queries if q):
            try:
                res = api("GET", "/web-search?q=" + urllib.parse.quote(q))
                searches.append((q, res.get("results") or []))
            except Exception as err:
                searches.append((q, [{"title": f"error: {err}", "url": "", "snippet": ""}]))

    pages = []
    official_photos = []
    if searches:
        known = {t.get("url") for t in texts if t.get("url")}
        name = title.lower()
        stem = name[:-2] if name.endswith(("en", "et")) else name
        place_words = [w for w in (what, town.lower()) if w]
        ranked = {}
        for _, results in searches:
            for i, r in enumerate(results):
                u = r.get("url") or ""
                if (not u or u in known or any(bad in u for bad in NOT_ARTICLES)
                        or u.lower().endswith(".pdf")):
                    continue
                said = f"{r.get('title') or ''} {r.get('snippet') or ''}".lower()
                score = 0
                if official(u):
                    score += 4
                if "wikipedia.org/wiki/" in u:
                    score += 3
                if stem and stem in said:
                    score += 2
                score += sum(1 for w in place_words if w in said)
                score -= i * 0.05
                # The name alone is a farm, a street, an estate agent.
                if score >= 2.9:
                    ranked[u] = max(ranked.get(u, -99), score)
        urls = sorted(ranked, key=ranked.get, reverse=True)[:MAX_PAGES]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            fetched = list(pool.map(fetch_page, urls))
        seen_text = set()
        for u, got in zip(urls, fetched):
            if not got or len(got[1]) < 200:
                continue
            title_p, text_p, imgs = got
            wiki = "wikipedia.org/wiki/" in u
            if wiki and title_p.lower().startswith(("lista", "list of")):
                # The whole list is not about this place. Its paragraph is.
                paras = [p for p in text_p.split("\n") if stem and stem in p.lower()]
                if not paras:
                    continue
                text_p = "\n".join(paras)
                wiki = False
            key = text_p[:500]
            if key in seen_text:
                continue
            seen_text.add(key)
            n = len(pages) + 1
            with open(os.path.join(out, f"page{n}.txt"), "w", encoding="utf-8") as f:
                f.write(text_p + "\n")
            pages.append({"n": n, "url": u, "title": title_p, "chars": len(text_p),
                          "wikipedia": wiki, "text": text_p})
            for src, alt in imgs:
                if len(official_photos) < MAX_OFFICIAL:
                    official_photos.append({"url": src, "alt": alt, "page": u, "page_n": n})
        with open(os.path.join(out, "pages.json"), "w", encoding="utf-8") as f:
            json.dump([{k: v for k, v in p.items() if k != "text"} for p in pages],
                      f, ensure_ascii=False, indent=1)

    official_drawn = 0
    if official_photos:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            imgs = list(pool.map(lambda o: _fetch_image(o["url"]), official_photos))
        # A logo or a button is small. A photograph of the place is not.
        keep = [(o, im) for o, im in zip(official_photos, imgs)
                if im is not None and min(im.size) >= 250]
        official_photos = []
        for i, (o, im) in enumerate(keep, 1):
            o["o"] = i
            o["size"] = f"{im.width}x{im.height}"
            official_photos.append((o, im))
        official_drawn = contact_sheet(
            [(f"O{o['o']}", o["url"], False) for o, _ in official_photos],
            os.path.join(out, "official.jpg"),
            images=[im for _, im in official_photos],
            sizes={f"O{o['o']}": im.size for o, im in official_photos},
            save_dir=os.path.join(out, "thumbs"),
        )
        official_photos = [o for o, _ in official_photos]
        with open(os.path.join(out, "official.json"), "w", encoding="utf-8") as f:
            json.dump(official_photos, f, ensure_ascii=False, indent=1)

    numbered = [(i + 1, a) for i, a in enumerate(live[:MAX_PHOTOS])]
    with open(os.path.join(out, "photos.json"), "w", encoding="utf-8") as f:
        json.dump({n: a for n, a in numbered}, f, ensure_ascii=False, indent=1)
    sizes = commons_sizes([a.get("file") or "" for _, a in numbered])
    by_number = {n: sizes[a["file"]] for n, a in numbered if a.get("file") in sizes}
    sheet_path = os.path.join(out, "sheet.jpg")
    drawn = contact_sheet(
        [(n, a.get("thumb") or "", a.get("prioritized")) for n, a in numbered],
        sheet_path,
        sizes=by_number,
        save_dir=os.path.join(out, "thumbs"),
    )
    with open(os.path.join(out, "sizes.json"), "w", encoding="utf-8") as f:
        json.dump(by_number, f)

    md = []
    md.append(f"# {title or '(sin título)'}  ({kind or '?'})")
    md.append("")
    md.append(f"uuid {uuid} · {place.get('municipality') or '?'} · "
              f"{place.get('lat')}, {place.get('lon')} · {place.get('fornsok')}")
    if place.get("title_override"):
        md.append(f"El título ya fue corregido a mano: {place['title_override']}")
    if actions:
        md.append("Hecho antes de empezar: " + "; ".join(actions))
    md.append("")
    md.append("## Texto publicado")
    md.append(_clip(place.get("content") or "(ninguno)", 1500))
    md.append("")
    md.append(f"## Fuentes ({len(texts)})")
    for i, t in enumerate(texts, 1):
        body = t.get("body") or ""
        head = (f"[{i}] {t.get('kind')} · {t.get('title') or '(sin título)'} · "
                f"{len(body)} caracteres")
        if t.get("url"):
            head += f" · {t['url']}"
        if t.get("added_id"):
            head += f" · added_id {t['added_id']}"
        md.append(head)
        limit = 4000 if (t.get("kind") or "") in REGISTER_KINDS else 400
        md.append("    " + _clip(body, limit).replace("\n", "\n    "))
    md.append("")
    md.append(f"## Fotos ({len(live)} sin skipear; en sheet.jpg {drawn} dibujadas, * = priorizada)")
    for n, a in numbered:
        size = f" · {by_number[n][0]}×{by_number[n][1]}" if n in by_number else ""
        md.append(f"{n:>2}{'*' if a.get('prioritized') else ' '} {a.get('source')} · {a.get('file')}{size}")
    if len(live) > MAX_PHOTOS:
        md.append(f"   (+{len(live) - MAX_PHOTOS} más, no están en la hoja)")
    skipped = [a for a in place.get("archive") or [] if a.get("skipped")]
    if skipped:
        md.append(f"Skipeadas antes: {len(skipped)}")
    if searches:
        md.append("")
        md.append("## Búsqueda web (la única fuente es el registro)")
        for q, results in searches:
            md.append(f"q: {q}")
            for r in results[:8]:
                snippet = re.sub(r"<[^>]+>", "", r.get("snippet") or "")
                md.append(f"- {r.get('title')} · {r.get('url')}")
                if snippet:
                    md.append(f"    {_clip(snippet, 220)}")
        md.append("")
        md.append(f"## Páginas ya bajadas ({len(pages)})")
        if not pages:
            md.append("Ninguna de las páginas de arriba dio texto.")
        for p in pages:
            md.append(f"[página {p['n']}] {p['title']} · {p['url']} · {p['chars']} caracteres"
                      f"{' · Wikipedia' if p['wikipedia'] else ''} · page{p['n']}.txt")
            md.append("    " + _clip(p["text"], 700).replace("\n", "\n    "))
    if official_photos:
        md.append("")
        md.append(f"## Fotos en páginas oficiales ({len(official_photos)}, en official.jpg)")
        for o in official_photos:
            md.append(f"O{o['o']} · {o['size']} · página {o['page_n']} · {o['alt'] or '(sin texto)'}")
    path = os.path.join(out, "dossier.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    return {
        "dir": out,
        "dossier": path,
        "sheet": sheet_path if drawn else None,
        "official_sheet": os.path.join(out, "official.jpg") if official_drawn else None,
        "place": place,
        "numbered": numbered,
        "searches": searches,
        "pages": pages,
        "official": official_photos,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if not os.environ.get("FL_AGENT_TOKEN"):
        from manager import ensure_token
        ensure_token()
    import tempfile
    got = build(sys.argv[1], os.path.join(tempfile.gettempdir(), "fl-review", "probe"))
    print(got["dossier"])
    print(got["sheet"])
