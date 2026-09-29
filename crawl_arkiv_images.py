#!/usr/bin/env python3
"""
Photographs from the RAÄ archive (Arkivsök, via K-samsök) for every site.

The relation list is not a match. It also returns a neighbour's picture.
A photo is kept only when every monument its own record names is this
site and no other. The modern lamning uuid and the old FMIS number are
the same claim when that number rebuilds to exactly one site. A number
that rebuilds to two sites is not used: measured 2026-09-28, 1,166 of
293,885 numbers, median 3.7 km apart. A Wikipedia page beside the number
is not a second monument.

One request per site, then one more per candidate. Sites already checked are
skipped, so an interrupt resumes. Writes src/data/arkiv_images.sqlite and
nothing else. build_places.py copies the kept rows into the photo list.

    python3 crawl_arkiv_images.py
    python3 crawl_arkiv_images.py --status
    python3 crawl_arkiv_images.py --limit 200
    python3 crawl_arkiv_images.py --top 20000
"""

import argparse
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from queue import Empty, Queue

import paths

API = "https://kulturarvsdata.se/ksamsok/api"
UA = "Fornlamningar/1.0 (franco.may@etraveligroup.com)"
LAM = re.compile(
    r"https?://kulturarvsdata\.se/raa/lamning/([0-9a-f-]{36})")
# Same shape as build_labels.FMIS_RE. The 14 digits are the old object id.
FMI = re.compile(r"raa/fmi/(?:html/)?(\d{14})")
LABEL = re.compile(r"<pres:itemLabel>([^<]*)</pres:itemLabel>")
VIS = re.compile(
    r'<ksam:visualizes[^>]*rdf:resource="([^"]+)"'
    r"|<ksam:visualizes[^>]*>([^<]*)</ksam:visualizes>"
    r"|<visualizes>([^<]*)</visualizes>")
THUMB = re.compile(
    r'<pres:src type="thumbnail">([^<]+)</pres:src>'
    r"|<thumbnailSource>([^<]+)</thumbnailSource>"
    r"|<thumbnail>([^<]+)</thumbnail>")
LOW = re.compile(
    r'<pres:src type="lowres">([^<]+)</pres:src>'
    r"|<lowresSource>([^<]+)</lowresSource>")
PAGE = re.compile(
    r'<pres:representation format="HTML">([^<]+)</pres:representation>')
# The photo's own licence. itemLicense is the catalogue record, which K-samsök
# stamps CC0, and reading it credited the picture as "1.0".
MEDIA_LIC = re.compile(
    r"mediaLicenseUrl[^>]*rdf:resource=\"([^\"]+)\""
    r"|<(?:ksam:|pres:)?mediaLicenseUrl[^>]*>(https?://[^<]+)"
    r"|mediaLicense[^>]*rdf:resource=\"([^\"]+)\""
    r"|<(?:ksam:|pres:)?mediaLicense[^>]*>(https?://[^<]+)")
BYLINE = re.compile(r"<(?:ksam:|pres:)?byline[^>]*>([^<]+)")
COPYRIGHT = re.compile(r"<(?:ksam:|pres:)?copyright[^>]*>([^<]+)")
MEDIA = re.compile(r"<mediaType>([^<]+)</mediaType>")

SCHEMA = """
CREATE TABLE IF NOT EXISTS checked (
    uuid     TEXT PRIMARY KEY,
    n_rel    INTEGER,
    n_kept   INTEGER,
    error    TEXT,
    checked_at TEXT
);
CREATE TABLE IF NOT EXISTS photos (
    uuid        TEXT NOT NULL,
    record_uri  TEXT NOT NULL,
    label       TEXT,
    thumb_url   TEXT,
    image_url   TEXT,
    page_url    TEXT,
    licence     TEXT,
    licence_url TEXT,
    author      TEXT,
    media_type  TEXT,
    fetched_at  TEXT,
    PRIMARY KEY (uuid, record_uri)
);
"""


def first(pattern, text):
    m = pattern.search(text)
    if not m:
        return None
    return next((g.strip() for g in m.groups() if g), None)


# Filled in main before any worker starts. Read-only after that.
FMIS_UNIQUE = {}
FMIS_COLLIDING = set()


def load_fmis(conn):
    """Old FMIS id -> one uuid, and the ids that rebuild to more than one.

    The key is the same one build_labels.fmis_index uses. A colliding id is
    not a match: the digits alone cannot say which of the two places the
    photograph is of.
    """
    groups = {}
    q = """SELECT uuid, parish_code, raa_number FROM sites
           WHERE raa_number IS NOT NULL AND parish_code IS NOT NULL"""
    for uuid, pc, rn in conn.execute(q):
        m = re.match(r"^.*?\s(\d+)(?::(\d+))?$", rn.strip())
        if not m:
            continue
        key = f"10{int(pc):04d}{int(m.group(1)):04d}{int(m.group(2) or 0):04d}"
        groups.setdefault(key, set()).add(uuid)
    unique, colliding = {}, set()
    for key, uuids in groups.items():
        if len(uuids) == 1:
            unique[key] = next(iter(uuids))
        else:
            colliding.add(key)
    return unique, colliding


def monuments(text):
    """The lamningar this record says it depicts, and whether that is ambiguous.

    A unique old FMIS id counts as the uuid it rebuilds to. A colliding id
    makes the whole record unusable. A number we do not hold, or a Wikipedia
    page, is not a second monument.
    """
    out = set()
    ambiguous = False
    for groups in VIS.findall(text):
        raw = next((g for g in groups if g), "")
        m = LAM.search(raw)
        if m:
            out.add(m.group(1))
            continue
        f = FMI.search(raw)
        if not f:
            continue
        fid = f.group(1)
        if fid in FMIS_COLLIDING:
            ambiguous = True
        elif fid in FMIS_UNIQUE:
            out.add(FMIS_UNIQUE[fid])
    return out, ambiguous


def licence_url(body):
    """The image licence, never the CC0 stamp on the catalogue record."""
    found = [g for groups in MEDIA_LIC.findall(body) for g in groups if g]
    cc = [u for u in found if "creativecommons.org" in u]
    return (cc or found or [None])[0]


def licence_name(url):
    if not url:
        return None
    u = url.lower()
    if "publicdomain/zero" in u or u.rstrip("/").endswith("#cc0"):
        return "CC0"
    if "publicdomain/mark" in u:
        return "Public Domain Mark"
    if "/inc/" in u or u.rstrip("/").endswith("#inc"):
        return "In copyright"
    m = re.search(r"licenses/([a-z-]+)/(\d+\.\d+)", u)
    if m:
        return f"CC {m.group(1).upper()} {m.group(2)}"
    frag = u.rsplit("#", 1)[-1].rstrip("/")
    if frag in ("by", "by-sa", "by-nc", "by-nd", "by-nc-sa", "by-nc-nd"):
        return f"CC {frag.upper()}"
    return None


def author_of(body):
    name = first(BYLINE, body) or first(COPYRIGHT, body)
    return name.strip() if name else None


def fetch(url, timeout):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/rdf+xml, application/xml"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def relations(uuid, timeout):
    q = urllib.parse.urlencode({
        "method": "getRelations", "version": "1.1",
        "relation": "isVisualizedBy", "maxCount": "100",
        "inferSameAs": "yes", "objectId": f"raa/lamning/{uuid}",
    })
    root = ET.fromstring(fetch(API + "?" + q, timeout))
    rels = root.find("relations")
    if rels is None:
        return []
    return [rel.text for rel in rels.findall("relation") if rel.text]


def keep(uuid, body, uri):
    named, ambiguous = monuments(body)
    if ambiguous or named != {uuid}:
        return None
    label = first(LABEL, body)
    if label and "inventeringsbok" in label.lower():
        return None
    media = first(MEDIA, body)
    if media and not media.startswith("image/"):
        return None
    thumb = first(THUMB, body)
    image = first(LOW, body) or thumb
    if not (thumb or image):
        return None
    lic_url = licence_url(body)
    return {
        "uuid": uuid,
        "record_uri": uri,
        "label": label,
        "thumb_url": thumb or image,
        "image_url": image or thumb,
        "page_url": first(PAGE, body),
        "licence": licence_name(lic_url),
        "licence_url": lic_url,
        "author": author_of(body),
        "media_type": media,
    }


class Limiter:
    def __init__(self, rps):
        self.interval = 1.0 / rps if rps else 0
        self._lock = threading.Lock()
        self._next = time.monotonic()

    def wait(self):
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + self.interval
        delay = slot - time.monotonic()
        if delay > 0:
            time.sleep(delay)


def recredit(out, rps, timeout):
    """Re-read author and licence for photos already stored.

    The relation crawl is not repeated. Only the record we already decided
    belongs to the site.
    """
    uris = [r[0] for r in out.execute("SELECT DISTINCT record_uri FROM photos")]
    print(f"re-reading credits on {len(uris):,} records", flush=True)
    limiter = Limiter(rps)
    n = missed = 0
    for uri in uris:
        limiter.wait()
        try:
            body = fetch(uri, timeout)
        except Exception as exc:
            missed += 1
            print(f"  fail {uri} {exc}", flush=True)
            continue
        lic_url = licence_url(body)
        out.execute(
            "UPDATE photos SET author=?, licence=?, licence_url=? WHERE record_uri=?",
            (author_of(body), licence_name(lic_url), lic_url, uri))
        n += 1
        if n % 200 == 0:
            out.commit()
            print(f"  {n:,}/{len(uris):,}", flush=True)
    out.commit()
    print(f"updated {n:,}   failed {missed:,}", flush=True)


def top_members(conn, n):
    """Member uuids of the N best clusters, same cut the map export uses."""
    ids = [r[0] for r in conn.execute("""
        SELECT c.cluster_id FROM clusters c
        JOIN scores sc ON sc.cluster_id = c.cluster_id
        WHERE c.lon IS NOT NULL
          AND sc.excluded_hard = 0 AND sc.excluded_soft = 0
        ORDER BY sc.score_full DESC
        LIMIT ?
    """, (n,))]
    uuids = []
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        uuids += [r[0] for r in conn.execute(
            "SELECT uuid FROM site_clusters WHERE cluster_id IN (%s)"
            % ",".join("?" * len(chunk)), chunk)]
    return uuids


def fmis_candidates(out, uuids):
    """Sites in that set where a relation came back and was not kept.

    A finished pass stamps rule='fmis1', so a rerun continues with the rest.
    Sites that kept every relation already have nothing left to recover.
    """
    cols = {r[1] for r in out.execute("PRAGMA table_info(checked)")}
    if "rule" not in cols:
        out.execute("ALTER TABLE checked ADD COLUMN rule TEXT")
        out.commit()
    cand = []
    for i in range(0, len(uuids), 400):
        chunk = uuids[i:i + 400]
        cand += [r[0] for r in out.execute(
            """SELECT uuid FROM checked
               WHERE uuid IN (%s)
                 AND n_rel > n_kept
                 AND error IS NULL
                 AND (rule IS NULL OR rule != 'fmis1')"""
            % ",".join("?" * len(chunk)), chunk)]
    return cand


def main():
    global FMIS_UNIQUE, FMIS_COLLIDING
    p = argparse.ArgumentParser()
    p.add_argument("--status", action="store_true")
    p.add_argument("--recredit", action="store_true")
    p.add_argument("--limit", type=int)
    p.add_argument("--top", type=int,
                   help="re-read the N best clusters and keep a photo whose "
                        "only monument is a unique old FMIS id")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--rps", type=float, default=12)
    p.add_argument("--timeout", type=float, default=30)
    args = p.parse_args()

    out = sqlite3.connect(paths.ARKIV_IMAGES)
    out.executescript(SCHEMA)
    out.commit()
    if args.status:
        n, with_photo, photos = out.execute(
            "SELECT COUNT(*), SUM(n_kept > 0), "
            "(SELECT COUNT(*) FROM photos) FROM checked").fetchone()
        print(f"checked {n:,}   sites with a photo {with_photo or 0:,}   "
              f"photos {photos:,}")
        return
    if args.recredit:
        recredit(out, args.rps, args.timeout)
        return

    sites = sqlite3.connect(paths.ro(paths.WORK), uri=True)
    FMIS_UNIQUE, FMIS_COLLIDING = load_fmis(sites)
    print(f"{len(FMIS_UNIQUE):,} unique old ids, "
          f"{len(FMIS_COLLIDING):,} colliding", flush=True)
    if args.top:
        members = top_members(sites, args.top)
        todo = fmis_candidates(out, members)
        if args.limit:
            todo = todo[:args.limit]
        print(f"{len(todo):,} sites to re-read in the top {args.top:,} "
              f"({len(members):,} member sites)", flush=True)
    else:
        # A failed site is checked again on the next run. A finished one is not.
        out.execute("DELETE FROM checked WHERE error IS NOT NULL")
        out.commit()
        done = {r[0] for r in out.execute("SELECT uuid FROM checked")}
        todo = [u for (u,) in sites.execute("SELECT uuid FROM sites") if u not in done]
        if args.limit:
            todo = todo[:args.limit]
        total_sites = sites.execute("SELECT COUNT(*) FROM sites").fetchone()[0]
        print(f"{len(todo):,} sites to check, {len(done):,} already done, "
              f"{total_sites:,} in the register")
    if not todo:
        return

    limiter = Limiter(args.rps)
    work = Queue()
    for u in todo:
        work.put(u)
    results = Queue()
    stop = threading.Event()

    def worker():
        while not stop.is_set():
            try:
                uuid = work.get_nowait()
            except Empty:
                return
            limiter.wait()
            try:
                uris = relations(uuid, args.timeout)
                kept = []
                for uri in uris:
                    limiter.wait()
                    body = fetch(uri, args.timeout)
                    row = keep(uuid, body, uri)
                    if row:
                        kept.append(row)
                results.put((uuid, len(uris), kept, None))
            except Exception as exc:
                results.put((uuid, 0, [], f"{type(exc).__name__}: {exc}"))

    threads = [threading.Thread(target=worker, daemon=True)
               for _ in range(args.workers)]
    for t in threads:
        t.start()

    started = time.monotonic()
    n = 0
    try:
        while n < len(todo):
            uuid, n_rel, kept, err = results.get()
            with out:
                if args.top and err:
                    # Leave n_rel in place so the next run retries this site.
                    out.execute(
                        "UPDATE checked SET error=?, checked_at=datetime('now') "
                        "WHERE uuid=?", (err, uuid))
                elif args.top:
                    out.execute("DELETE FROM photos WHERE uuid=?", (uuid,))
                    out.execute(
                        "UPDATE checked SET n_rel=?, n_kept=?, error=NULL, "
                        "rule='fmis1', checked_at=datetime('now') WHERE uuid=?",
                        (n_rel, len(kept), uuid))
                else:
                    out.execute(
                        "INSERT OR REPLACE INTO checked "
                        "(uuid, n_rel, n_kept, error, checked_at) "
                        "VALUES (?,?,?,?,datetime('now'))",
                        (uuid, n_rel, len(kept), err))
                out.executemany(
                    "INSERT OR REPLACE INTO photos "
                    "(uuid, record_uri, label, thumb_url, image_url, page_url, "
                    " licence, licence_url, author, media_type, fetched_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))",
                    [(r["uuid"], r["record_uri"], r["label"], r["thumb_url"],
                      r["image_url"], r["page_url"], r["licence"],
                      r["licence_url"], r["author"], r["media_type"])
                     for r in kept])
            n += 1
            if n % 50 == 0 or n == len(todo):
                elapsed = time.monotonic() - started
                rate = n / elapsed if elapsed else 0
                left = (len(todo) - n) / rate if rate else 0
                photos = out.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
                print(f"  {n:,}/{len(todo):,}  {photos:,} photos  "
                      f"{rate:.1f}/s  {left/3600:.1f}h left", flush=True)
    except KeyboardInterrupt:
        stop.set()
        print("stopped; rerun to resume")
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=2)


if __name__ == "__main__":
    main()
