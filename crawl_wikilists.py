#!/usr/bin/env python3
"""
The Swedish Wikipedia's own lists of fornlamningar, one per socken.

WHY THIS EXISTS, AND WHY IT IS NOT THE SAME AS build_labels.py.

build_labels asks WIKIDATA which sites have been written about. That only
ever finds a place that somebody bothered to make a Wikidata ITEM for. These
lists are a different population: they are the Wiki Loves Monuments tables,
generated from RAA's own export and then edited by hand for fifteen years,
and they carry three things per monument that nobody put in Wikidata:

    namn     the folk name. 10,121 entries have one.
    artikel  a Swedish Wikipedia article ABOUT THIS MONUMENT. 1,509.
    bild     a Commons photograph. 3,879.

Measured 2026-09-21 against what we already hold: 1,062 names, 181 articles
and 859 photographs are NEW. On the 6,000 places that ship, 1,190 of the
4,976 with no name at all get one -- which is the difference between a pin
called "Uraniborg" and a pin called "Slott/herresate".

THE JOIN IS THE OLD FMIS ID. Every row carries `id`, the pre-2018 14-digit
identifier: "10" then the four-digit socken code, the four-digit
lamningsnummer and the four-digit object number. That is the same key
build_labels.fmis_index() already reconstructs from `parish_code` and
`raa_number`, so the two stages resolve identically and an ambiguous key is
skipped in both. 134,284 of 145,286 entries resolve.

IS THE PHOTO A SIGNAL? Yes, and a good one. Adjusted for building density
(see fetch_osm.sh for why that adjustment is not optional), a WLM photograph
multiplies P(Franco went) by 27.6x -- about the same as the Wikidata
photograph we already use, at 29.7x. The number that decides it is neither
of those: restricted to photographs that are NOT in Wikidata, the lift is
still 12.0x over 746 clusters. It is not a duplicate of a feature we have.

Worth being clear about what it measures, though. A WLM photograph means
somebody physically went there with a camera, which is nearer to a visit
than to an encyclopaedia entry -- but the people who go are the people who
can get there and have heard of it, and Franco's labels have exactly that
bias too. The lift is real; part of it is the two biases agreeing.

RAW tier: downloaded from someone else, never edited here, re-fetchable.

Reads:  sv.wikipedia.org (996 list pages, ~45 MB of wikitext)
        src/data/work.sqlite  (sites, for the FMIS key)
Writes: src/data/wikilists.sqlite

Usage:
    python3 crawl_wikilists.py            # fetch and parse
    python3 crawl_wikilists.py --status
    python3 crawl_wikilists.py --no-fetch # re-parse the cached wikitext
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

import paths

OUT_DB = os.path.join(paths.DATA, "wikilists.sqlite")
CACHE = os.path.join(paths.DATA, "wikilists_cache.json")
API = "https://sv.wikipedia.org/w/api.php"
UA = "Fornlamningar-Pipeline/1.0 (https://github.com/francomay3/fornlamningar)"
PREFIX = "Lista över fornlämningar i"

SCHEMA = """
CREATE TABLE IF NOT EXISTS monuments (
    uuid       TEXT PRIMARY KEY,       -- ours, resolved from fmis_id
    fmis_id    TEXT,
    raa_nr     TEXT,
    -- The three fields worth crossing the network for. Empty string is
    -- stored as NULL so a consumer can test one thing.
    namn       TEXT,
    artikel    TEXT,                   -- sv.wikipedia page title
    bild       TEXT,                   -- Commons file name, no File: prefix
    typ        TEXT,
    lat        REAL, lon REAL,
    page       TEXT,                   -- which list it came from
    fetched_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_wl_namn    ON monuments(namn);
CREATE INDEX IF NOT EXISTS idx_wl_artikel ON monuments(artikel);
CREATE INDEX IF NOT EXISTS idx_wl_bild    ON monuments(bild);

-- Entries whose FMIS id resolves to nothing we hold, kept rather than
-- dropped. They are not noise: 11,002 of them, and they are the honest
-- measure of how far the lists reach past our crawl. Without the row there
-- is no way to tell "we looked and it is not ours" from "we never looked".
CREATE TABLE IF NOT EXISTS unresolved (
    fmis_id    TEXT PRIMARY KEY,
    raa_nr     TEXT, namn TEXT, artikel TEXT, bild TEXT,
    reason     TEXT                    -- 'no match' | 'ambiguous key'
);
"""

TPL = re.compile(r"\{\{\s*FMIS\s*\|(.*?)\}\}", re.S | re.I)
# The parameters are written "\n | namn      = value", so the separator is a
# newline and a pipe with arbitrary space between. Splitting on the bare
# "\n|" silently matches nothing and yields one giant field -- which is what
# it did on the first attempt, producing zero rows from 45 MB of input.
FIELD_SEP = re.compile(r"\n\s*\|")
# A few dozen entries wrap the value in a comment to hide a red link:
# "artikel = <!--Neptuni akrar-->". That is the editors saying the article
# does not exist yet, so it is not an article.
COMMENT = re.compile(r"<!--.*?-->", re.S)


def api(**kw):
    kw.setdefault("format", "json")
    kw.setdefault("formatversion", 2)
    url = API + "?" + urllib.parse.urlencode(kw)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def list_pages():
    out, cont = [], None
    while True:
        kw = dict(action="query", list="allpages", apprefix=PREFIX,
                  apnamespace=0, aplimit=500)
        if cont:
            kw["apcontinue"] = cont
        d = api(**kw)
        out += [p["title"] for p in d["query"]["allpages"]]
        cont = d.get("continue", {}).get("apcontinue")
        if not cont:
            return out


def fetch_all(titles, batch=40):
    """Wikitext for every list, forty pages per request.

    Forty because that is the API's limit for a non-bot client, and the
    whole set is 45 MB -- under a minute. There is no resume and none is
    needed at that size; a failed batch is reported and skipped, and
    re-running re-fetches everything.
    """
    out, t0 = {}, time.time()
    for i in range(0, len(titles), batch):
        chunk = titles[i:i + batch]
        try:
            d = api(action="query", prop="revisions", rvprop="content",
                    rvslots="main", titles="|".join(chunk))
        except Exception as exc:
            print(f"  ! batch at {i} failed ({exc}); skipped")
            continue
        for p in d["query"]["pages"]:
            try:
                out[p["title"]] = p["revisions"][0]["slots"]["main"]["content"]
            except (KeyError, IndexError):
                pass
        if i % 400 == 0:
            print(f"  {i:,}/{len(titles):,}  {time.time()-t0:.0f}s", flush=True)
    return out


def clean(v):
    v = COMMENT.sub("", v or "").strip()
    return v or None


def parse(wikitext):
    rows = []
    for page, text in wikitext.items():
        for m in TPL.finditer(text):
            d = {}
            for part in FIELD_SEP.split(m.group(1)):
                if "=" not in part:
                    continue
                k, _, v = part.partition("=")
                d[k.strip().lower()] = v
            fid = clean(d.get("id"))
            if not fid:
                continue
            def num(k):
                try:
                    return float(clean(d.get(k)) or "")
                except ValueError:
                    return None
            rows.append({
                "fmis_id": fid, "raa_nr": clean(d.get("raä-nr")),
                "namn": clean(d.get("namn")), "artikel": clean(d.get("artikel")),
                "bild": clean(d.get("bild")), "typ": clean(d.get("typ")),
                "lat": num("lat"), "lon": num("long"), "page": page,
            })
    return rows


def fmis_index(conn):
    """The same key build_labels builds, from the same two columns.

    Deliberately duplicated rather than imported: build_labels reaches the
    network at import time under some flags, and a crawler should not depend
    on a scoring stage. If the rule ever changes it has to change in both
    places, which is why it is stated the same way in both.
    """
    key = {}
    q = """SELECT uuid, parish_code, raa_number FROM sites
           WHERE raa_number IS NOT NULL AND parish_code IS NOT NULL"""
    for uuid, pc, rn in conn.execute(q):
        m = re.match(r"^.*?\s(\d+)(?::(\d+))?$", rn.strip())
        if not m:
            continue
        k = f"10{int(pc):04d}{int(m.group(1)):04d}{int(m.group(2) or 0):04d}"
        key.setdefault(k, []).append(uuid)
    return key


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=OUT_DB)
    p.add_argument("--work", default=paths.WORK)
    p.add_argument("--no-fetch", action="store_true",
                   help="re-parse the cached wikitext instead of downloading")
    p.add_argument("--status", action="store_true")
    a = p.parse_args()

    conn = sqlite3.connect(a.out)
    conn.executescript(SCHEMA)

    if a.status:
        n = conn.execute("SELECT COUNT(*) FROM monuments").fetchone()[0]
        print(f"{n:,} monuments resolved to a uuid")
        for f in ("namn", "artikel", "bild"):
            c = conn.execute(
                f"SELECT COUNT(*) FROM monuments WHERE {f} IS NOT NULL").fetchone()[0]
            print(f"  {f:<8} {c:>7,}")
        u = conn.execute("SELECT COUNT(*) FROM unresolved").fetchone()[0]
        print(f"{u:,} entries the register does not have")
        return

    if a.no_fetch and os.path.exists(CACHE):
        print(f"using cached {CACHE}")
        wikitext = json.load(open(CACHE))
    else:
        print(f"listing pages with prefix {PREFIX!r}...")
        titles = list_pages()
        print(f"  {len(titles):,} list pages")
        wikitext = fetch_all(titles)
        json.dump(wikitext, open(CACHE, "w"))
        print(f"  {sum(len(v) for v in wikitext.values())/1e6:.1f} MB cached")

    rows = parse(wikitext)
    print(f"{len(rows):,} FMIS entries parsed")

    if not os.path.exists(a.work):
        sys.exit(f"{a.work} not found -- run build_sites.py first")
    key = fmis_index(sqlite3.connect(paths.ro(a.work), uri=True))

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    ok, amb, miss = [], [], []
    for r in rows:
        u = key.get(r["fmis_id"])
        if not u:
            miss.append(r)
        elif len(u) > 1:
            # Same rule as build_labels: attaching somebody else's name or
            # photograph to a place is a wrong fact, which is worse than a
            # missing one.
            amb.append(r)
        else:
            ok.append((u[0], r["fmis_id"], r["raa_nr"], r["namn"], r["artikel"],
                       r["bild"], r["typ"], r["lat"], r["lon"], r["page"], now))

    with conn:
        conn.execute("DELETE FROM monuments")
        conn.executemany("INSERT OR REPLACE INTO monuments VALUES "
                         "(?,?,?,?,?,?,?,?,?,?,?)", ok)
        conn.execute("DELETE FROM unresolved")
        conn.executemany(
            "INSERT OR REPLACE INTO unresolved VALUES (?,?,?,?,?,?)",
            [(r["fmis_id"], r["raa_nr"], r["namn"], r["artikel"], r["bild"],
              "ambiguous key" if r in amb else "no match")
             for r in amb + miss])

    print(f"\nresolved   {len(ok):>7,}")
    print(f"ambiguous  {len(amb):>7,}")
    print(f"not ours   {len(miss):>7,}")
    for f in ("namn", "artikel", "bild"):
        c = conn.execute(
            f"SELECT COUNT(*) FROM monuments WHERE {f} IS NOT NULL").fetchone()[0]
        print(f"  with {f:<8} {c:>7,}")
    conn.close()


if __name__ == "__main__":
    main()
