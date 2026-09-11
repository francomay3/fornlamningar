#!/usr/bin/env python3
"""
Harvest the county boards' own lists of ancient monuments worth visiting.

This is the closest thing to ground truth the project has found. Nine or ten
of Sweden's 21 county administrative boards publish the fornlamningar they
actively maintain and signpost -- "Fornvardsobjekt", "Fornvardsomraden",
"Besoksvarda fornlamningar", "Historia pa plats" -- and those lists are
written by county antiquarians deciding where to spend a maintenance budget.
That is a judgement about visit-worthiness, made by people who have stood on
the sites, published as open geodata.

For scale: the model is currently fitted against 40 hand labels and 5,184
Wikidata proxies. Gavleborg alone publishes 38 objects, 32 of which join to
our register. Ten counties at that rate is several hundred authoritative
positives.

TWO BIASES TO KEEP IN VIEW, because they are baked in and cannot be fixed by
being careful later:

    Positives only.  Nobody publishes "these are not worth visiting". These
    labels can raise sites, never lower them, so they cannot replace the
    verified negatives.

    Geography.  Coverage is per county and uneven. A site in Gavleborg can be
    labelled; one in Norrbotten cannot, because its county publishes nothing.
    Fed in raw, a model learns the characteristics of the counties that happen
    to publish -- their commonest classes, their terrain, their parish naming.
    Weighting or stratifying by county is a decision to make on purpose.

HOW THE MATCHING WORKS. Two independent routes, and they corroborate rather
than compete:

    BY NUMBER   The description field usually holds the RAA designation --
                "Arsunda 9", "Rogsta 1, 2, 3" -- which is parish plus the
                number in `sites.raa_number` ("Arsunda 9:5"). Exact when it
                parses; it failed on 6 of Gavleborg's 38, mostly rows whose
                description was blank.

    BY GEOMETRY The county objects carry their own coordinates, so anything
                within MATCH_RADIUS_M of one of our sites is a candidate. This
                catches the blank-description rows and confirms the parsed
                ones.

Discovery goes through the catalogue's CSW rather than a hard-coded list of
URLs, so a county that publishes next year gets picked up by re-running this.

    NOTE on a server bug: the catalogue is GeoNetwork, and its CQL_TEXT
    handler passes the search term to a Java string formatter. A `%` wildcard
    therefore crashes it -- `UnknownFormatConversionException: Conversion =
    'F'` when searching `%Fornvard%`. `*` works and is what this uses.

Usage:
    python crawl_lansstyrelsen.py --discover
    python crawl_lansstyrelsen.py --fetch
    python crawl_lansstyrelsen.py --join
    python crawl_lansstyrelsen.py --status
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import paths

SITES_DB = paths.WORK
OUT_DB = paths.LANSSTYRELSEN

CSW = ("https://ext-geodatakatalog.lansstyrelsen.se/GeodataKatalogen/"
       "srv/swe/csw")
UA = ("fornlamningar-pipeline/1.0 "
      "(https://github.com/framay/fornlamningar; franco.may@etraveligroup.com)")

# What to look for in the catalogue. Deliberately broad: the counties have not
# agreed on a name for this, so the same thing is called Fornvardsobjekt,
# Fornvardsomrade, Fornvardsplats, Besoksvarda fornlamningar and Historia pa
# plats depending on who published it.
SEARCH_TERMS = [
    # Actively maintained monuments: the strongest signal here.
    "Fornvård",
    "Besöksvärda",
    "Besöksplatser",
    # Vasternorrland calls its recommendations "tips", which is as explicit a
    # statement of visit-worthiness as any authority publishes.
    "Fornlämningar tips",
    # Signposted sites.
    "Kulturmiljöskyltar",
    "Infoskyltar",
    # Curated county heritage programmes: weaker, and classified apart.
    "Kulturmiljöprogram",
    "Kulturminnesvård",
    "Kulturreservat",
]

# Anything further than this from one of our sites is a different place. 150 m
# is generous on purpose: the county polygons are maintenance AREAS, so their
# centroid can sit well off any single monument inside them.
MATCH_RADIUS_M = 150

# Counties that publish their recommendations as a PDF folder rather than as
# geodata. Halland is the only one found so far, and it is worth the special
# case for two reasons.
#
# First, the join is EXACT. The folder says so itself: "Darfor har vi lagt
# till platsernas fornlamningsnummer om sadana finns" -- so it carries
# `L1996:1589` style numbers, which is the `sites.lamningsnummer` primary key.
# 63 of 71 numbers matched, with no parsing heuristic and no proximity guess.
# That makes these the most reliable labels in this whole file, ahead of
# everything harvested from a shapefile.
#
# Second, the folder states its selection criterion outright, and it is our
# target variable in the county's own words: sites were chosen so "de ska ha
# tillganglig information, antingen genom en skylt eller pa internet och att
# de ska vara tamligen tillgangliga for besok" -- they must have accessible
# information, by sign or online, and be reasonably accessible to visit.
PDF_SOURCES = [
    ("N", "Tips på medeltida besöksmål i Hallands län",
     "https://www.lansstyrelsen.se/download/18.6fa4735719ed45ea927e1a94/"
     "1782999546313/Tips%20p%C3%A5%20medeltida%20bes%C3%B6ksm%C3%A5l%20i%20"
     "Hallands%20l%C3%A4n_2026_TGA.pdf"),
    ("N", "Tips på kulturhistoriska besöksmål i Hallands län",
     "https://www.lansstyrelsen.se/download/18.6fa4735719ed45ea927e1811/"
     "1782999249781/Tips%20p%C3%A5%20kulturhistoriska%20bes%C3%B6ksm%C3%A5l"
     "%20i%20Hallands%20l%C3%A4n%202026_2_TGA.pdf"),
]

LAMNING_RE = re.compile(r"L\d{4}:\d+")

# Per-site visitor pages on lansstyrelsen.se, linked from the counties' own
# geodata (the OBJEKTLANK and URL_GIS_VG fields).
#
# 119 distinct ones, which is a ninth of what a first count suggested: that
# count was of ROWS, and several objects link to the same page while 308 more
# point at an intranet host nobody outside the authority can reach. Worth
# saying, because 119 is still the best prose in the corpus and 1,100 was not
# a real number.
#
# They are worth the crawl because of what they are for. The register
# describes what is present; these were written to get somebody to the place,
# so they mention the walk, the parking and what you can actually see:
#
#   "Har ligger fornlamningarna som ett parlband langs den forna havsviken
#    ... Det ar ocksa ett fint naturomrade med eklandskap, vatmark och rikt
#    fagelliv."
PAGE_HOST = "lansstyrelsen.se"
PAGE_MARKERS = ("/besoksmal/", "/besok-och-upptack/")

# Above this bounding-box area, "the site is inside the polygon" stops being a
# statement about the site.
#
# Measured over everything harvested, bounding-box area in km2:
#
#     fornvard  n=3,797   p50 0.0000   p90 0.075   p99   0.44   max     24
#     reservat  n=39      p50 0.1219   p90 4.704   p99  12.75   max     13
#     program   n=3,321   p50 0.1768   p90 7.000   p99 165.49   max 17,282
#
# The two populations barely overlap, which is the whole justification for a
# single number: a maintenance polygon is hectares, a kulturmiljoprogram area
# is a landscape. The worst case was "Skanelinjen Per Albin-linjen", the
# WWII defence line across Skane -- 17,282 km2 containing 1,715 register
# sites, every one of which a naive containment pass called "recommended by
# the county board". Unfiltered, `program` produced 22,382 of 24,312
# containment matches and the total came out at 17,613 clusters, 7% of the
# country.
#
# Bigger areas are still recorded, as `in_landscape`. That is a real and
# different signal -- this place sits in a designated cultural landscape --
# and it is kept under its own name so it can never be mistaken for a
# recommendation.
MAX_CONTAIN_KM2 = 1.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id          TEXT PRIMARY KEY,       -- catalogue uuid
    title       TEXT,
    county      TEXT,                   -- 'X', 'N', 'O' ... from the Lst prefix
    rest_url    TEXT,                   -- ArcGIS REST layer, queryable
    atom_url    TEXT,
    download    TEXT,
    kind        TEXT,                   -- 'fornvard' | 'infoskylt' | 'reservat'
    n_features  INTEGER,
    fetched_at  TEXT,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS objects (
    dataset_id  TEXT NOT NULL,
    obj_id      TEXT NOT NULL,
    name        TEXT,
    obj_type    TEXT,
    description TEXT,                   -- usually the RAA designation
    lon         REAL,                   -- centroid; for bucketing only
    lat         REAL,
    -- The full GeoJSON geometry, because for an AREA dataset the right
    -- question is which register sites fall INSIDE the maintained area, not
    -- which one is nearest its centroid. A maintenance polygon around a grave
    -- field contains twenty graves and its centroid is on none of them.
    geom        TEXT,
    props       TEXT,                   -- the rest, as JSON
    PRIMARY KEY (dataset_id, obj_id)
);
CREATE INDEX IF NOT EXISTS idx_obj_ll ON objects(lon, lat);

CREATE TABLE IF NOT EXISTS matches (
    dataset_id  TEXT NOT NULL,
    obj_id      TEXT NOT NULL,
    uuid        TEXT NOT NULL,
    -- 'number' is an exact parse of the RAA designation; 'geometry' is a
    -- proximity match. Kept distinct so a later stage can trust them
    -- differently instead of inheriting one blended confidence.
    -- 'contains' (the site falls inside the county polygon), 'number' (its
    -- RAA designation parsed and matched) or 'geometry' (nearest within
    -- MATCH_RADIUS_M). Kept apart so a later stage can trust them
    -- differently rather than inheriting one blended confidence.
    how         TEXT NOT NULL,
    distance_m  REAL,
    raa_number  TEXT,
    -- The cluster the site belongs to, and THIS is the unit a county
    -- judgement is really about. "Sorbygravfaltet i Arsunda" is one place;
    -- the RAA number group Arsunda 9 holds five records -- a grave field, two
    -- bloomery remains, a bloomery site and a hunting pit. Labelling all five
    -- as worth visiting labels the hunting pit too. One cluster, one label.
    cluster_id  TEXT,
    PRIMARY KEY (dataset_id, obj_id, uuid, how)
);
CREATE INDEX IF NOT EXISTS idx_m_uuid ON matches(uuid);
"""


def get(url, params=None, raw=False, timeout=60):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
        return body if raw else body.decode("utf-8", "replace")
    except Exception as e:
        print(f"    ! {type(e).__name__}: {str(e)[:90]}")
        return None


def csw_search(term, max_records=60):
    """(id, title) for catalogue records matching `term`."""
    xml = get(CSW, {
        "service": "CSW", "version": "2.0.2", "request": "GetRecords",
        "typeNames": "csw:Record", "resultType": "results",
        "elementSetName": "brief",
        "outputSchema": "http://www.opengis.net/cat/csw/2.0.2",
        "constraintLanguage": "CQL_TEXT",
        "constraint_language_version": "1.1.0",
        # `*`, not `%` -- see the note in the module docstring.
        "constraint": f"AnyText like '*{term}*'",
        "maxRecords": max_records,
    })
    if not xml or "ExceptionText" in xml:
        return []
    ids = re.findall(r"<dc:identifier>([^<]+)</dc:identifier>", xml)
    titles = re.findall(r"<dc:title>([^<]+)</dc:title>", xml)
    return list(zip(ids, titles))


def csw_record(rec_id):
    """Distribution URLs out of one record's full ISO metadata."""
    xml = get(CSW, {
        "service": "CSW", "version": "2.0.2", "request": "GetRecordById",
        "id": rec_id, "elementSetName": "full",
        "outputSchema": "http://www.isotc211.org/2005/gmd",
    })
    if not xml:
        return {}
    urls = re.findall(r"<gmd:URL>([^<]+)</gmd:URL>", xml)
    out = {"rest": None, "atom": None, "download": None}
    for u in urls:
        low = u.lower()
        if "/arcgis/rest/services/" in low and "mapserver" in low:
            out["rest"] = out["rest"] or u
        elif low.endswith(".xml") and "/atom" in low:
            out["atom"] = out["atom"] or u
        elif low.endswith((".zip", ".gpkg")):
            out["download"] = out["download"] or u
    return out


def classify(title):
    t = title.lower()
    if "skylt" in t:
        return "infoskylt"
    if "kulturreservat" in t:
        return "reservat"
    if ("fornvård" in t or "besöksvärda" in t or "besöksplatser" in t
            or "historia på plats" in t or "fornlämningar tips" in t):
        return "fornvard"
    # Curated county heritage programmes. Weaker than fornvard -- they select
    # for historical significance rather than for being worth the trip -- so
    # they are kept as their own kind and must not be pooled with it.
    if "kulturmiljöprogram" in t or "kulturminnesvård" in t:
        return "program"
    return None


def county_of(title):
    """The county letter out of an 'LstX ...' title."""
    m = re.match(r"^Lst([A-ZÅÄÖ]{1,2})\b", title)
    return m.group(1) if m else None


def discover(out):
    seen = {}
    for term in SEARCH_TERMS:
        print(f"catalogue: *{term}*")
        for rec_id, title in csw_search(term):
            kind = classify(title)
            if not kind or rec_id in seen:
                continue
            # WebbGIS and StoryMap records are viewers, not data. They are
            # kept out rather than fetched and found empty: their only
            # distribution URL is an HTML page.
            if "webbgis" in title.lower() or "storymap" in title.lower() \
               or "webbkarta" in title.lower() or "karttjänst" in title.lower():
                continue
            seen[rec_id] = (title, kind)
    print(f"\n{len(seen)} candidate datasets")
    for rec_id, (title, kind) in sorted(seen.items(), key=lambda x: x[1][0]):
        urls = csw_record(rec_id)
        out.execute("""
            INSERT INTO datasets (id, title, county, rest_url, atom_url,
                                  download, kind)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              title=excluded.title, county=excluded.county,
              rest_url=excluded.rest_url, atom_url=excluded.atom_url,
              download=excluded.download, kind=excluded.kind
        """, (rec_id, title, county_of(title), urls.get("rest"),
              urls.get("atom"), urls.get("download"), kind))
        flag = "REST" if urls.get("rest") else \
               ("zip" if urls.get("download") else
                ("atom" if urls.get("atom") else "--"))
        print(f"  [{flag:4}] {kind:10} {title}")
        time.sleep(0.2)
    out.commit()


def fetch_rest(out, ds_id, title, url):
    """Pull every feature from an ArcGIS REST layer as WGS84 GeoJSON."""
    gj = get(url.rstrip("/") + "/query", {
        "where": "1=1", "outFields": "*", "returnGeometry": "true",
        "outSR": "4326", "f": "geojson",
    })
    if not gj:
        return 0
    try:
        feats = json.loads(gj).get("features") or []
    except json.JSONDecodeError:
        print(f"    ! not geojson: {gj[:80]}")
        return 0

    n = 0
    for i, f in enumerate(feats):
        p = f.get("properties") or {}
        lon, lat = centroid(f.get("geometry"))
        # Field names differ by county -- NAMN/Namn/namn, BESKRIVNIN/BESKRIVNING
        # -- so they are matched case-insensitively on a prefix rather than
        # listed exhaustively, which would need one branch per publisher.
        out.execute("""
            INSERT OR REPLACE INTO objects
              (dataset_id, obj_id, name, obj_type, description, lon, lat,
               geom, props)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (ds_id, str(pick(p, "objectid", "id", "originalid") or i),
              pick(p, "namn", "name"), pick(p, "objtyp", "typ", "type"),
              pick(p, "beskrivnin", "beskrivning", "beskr"),
              lon, lat, json.dumps(f.get("geometry"), ensure_ascii=False),
              json.dumps(p, ensure_ascii=False)))
        n += 1
    return n


def pick(props, *prefixes):
    """First value whose key starts with one of `prefixes`, ignoring case."""
    low = {k.lower(): v for k, v in props.items()}
    for pre in prefixes:
        for k, v in low.items():
            if k.startswith(pre) and v not in (None, ""):
                return v
    return None


def centroid(geom):
    """A representative lon/lat for any GeoJSON geometry.

    The mean of the coordinates, which for a maintenance polygon is roughly
    its middle -- good enough to find candidate sites within 150 m, and never
    used as the position of anything we display. (The pipeline learned the
    hard way that a mean is not a place; see build_clusters.py.)
    """
    if not geom:
        return None, None
    xs, ys = [], []

    def walk(c):
        if not c:
            return
        if isinstance(c[0], (int, float)):
            xs.append(c[0])
            ys.append(c[1])
        else:
            for part in c:
                walk(part)

    walk(geom.get("coordinates"))
    if not xs:
        return None, None
    return sum(xs) / len(xs), sum(ys) / len(ys)


def atom_zip(url):
    """The shapefile URL an INSPIRE ATOM download feed points at.

    Half the counties publish only this way: a tiny ATOM document whose one
    useful link is a zipped shapefile on ext-dokument. Following it is two
    lines and it doubles the number of counties we can read.
    """
    xml = get(url)
    if not xml:
        return None
    for href in re.findall(r'href="([^"]+)"', xml):
        if href.lower().endswith(".zip"):
            return href.replace("&amp;", "&")
    return None


def fetch_zip(out, ds_id, title, zip_url):
    """Download a zipped shapefile and read it through ogr2ogr as GeoJSON.

    ogr2ogr rather than a Python shapefile reader because the pipeline already
    depends on it for the OSM extracts, it reads straight out of the zip with
    /vsizip/, and it reprojects to WGS84 on the way out -- these come in
    SWEREF99 TM and getting that conversion subtly wrong is exactly the kind
    of bug that shows up as pins 200 km into the Baltic.
    """
    import os
    import subprocess
    import tempfile

    blob = get(zip_url, raw=True, timeout=300)
    if not blob:
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        zp = os.path.join(tmp, "d.zip")
        with open(zp, "wb") as f:
            f.write(blob)
        gj = os.path.join(tmp, "d.geojson")
        r = subprocess.run(
            ["ogr2ogr", "-f", "GeoJSON", "-t_srs", "EPSG:4326", gj,
             f"/vsizip/{zp}"],
            capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(gj):
            print(f"    ! ogr2ogr: {(r.stderr or '').strip()[:110]}")
            return 0
        with open(gj, encoding="utf-8") as f:
            feats = json.load(f).get("features") or []

    n = 0
    for i, f in enumerate(feats):
        p = f.get("properties") or {}
        lon, lat = centroid(f.get("geometry"))
        out.execute("""
            INSERT OR REPLACE INTO objects
              (dataset_id, obj_id, name, obj_type, description, lon, lat,
               geom, props)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (ds_id, str(pick(p, "objectid", "id", "originalid") or i),
              pick(p, "namn", "name"), pick(p, "objtyp", "typ", "type"),
              pick(p, "beskrivnin", "beskrivning", "beskr"),
              lon, lat, json.dumps(f.get("geometry"), ensure_ascii=False),
              json.dumps(p, ensure_ascii=False)))
        n += 1
    return n


def fetch_pdfs(out):
    """Pull lamningsnummer, and the paragraph each sits under, out of a folder.

    The layout is consistent: a numbered heading with the place name and a
    sentence or two, then a line reading "Fornlamningsnummer:" and the
    numbers. So the text above each number block is the county's own
    description of why the place is worth visiting -- kept, because it is
    better prose than anything the register holds and it says what a visitor
    will see.
    """
    import os
    import subprocess
    import tempfile

    for county, title, url in PDF_SOURCES:
        ds_id = f"pdf:{county}:{title}"
        out.execute("""
            INSERT INTO datasets (id, title, county, download, kind)
            VALUES (?,?,?,?,'fornvard')
            ON CONFLICT(id) DO UPDATE SET download=excluded.download
        """, (ds_id, title, county, url))
        print(f"  {title}")
        blob = get(url, raw=True, timeout=300)
        if not blob:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            pdf = os.path.join(tmp, "f.pdf")
            with open(pdf, "wb") as f:
                f.write(blob)
            txt = os.path.join(tmp, "f.txt")
            r = subprocess.run(["pdftotext", "-layout", pdf, txt],
                               capture_output=True, text=True)
            if not os.path.exists(txt):
                print(f"    ! pdftotext: {(r.stderr or '').strip()[:100]}")
                continue
            with open(txt, encoding="utf-8") as f:
                lines = f.read().split("\n")

        # Entries are delimited by a numbered heading, and the two folders
        # put the prose on OPPOSITE sides of the numbers:
        #
        #   kulturhistoriska    "35. Tyludden. Langs Prins Bertils stig..."
        #                       ...text...
        #                       "Fornlamningsnummer:"  L1996:1589, ...
        #
        #   medeltida           "2. Hunehals borg"
        #                       "Fornlamningsnummer: L1997:4707"
        #                       ...text...
        #
        # So walking backwards from the number -- which is what the first
        # version did -- captured everything in one folder and nothing but the
        # heading in the other. Taking the whole block between one heading and
        # the next gets both, and does not care which order a third folder
        # might choose.
        heads = [i for i, ln in enumerate(lines)
                 if re.match(r"^\s*\d+\.\s+\S", ln)]
        n = 0
        for hi, start_i in enumerate(heads):
            stop = heads[hi + 1] if hi + 1 < len(heads) else len(lines)
            block = lines[start_i:stop]
            nums = LAMNING_RE.findall("\n".join(block))
            if not nums:
                continue
            name = re.match(r"^\s*\d+\.\s+(.+?)\s*$", block[0]).group(1)
            # The heading often runs straight into the first sentence
            # ("35. Tyludden. Langs Prins Bertils stig..."), so only the part
            # up to the first full stop is treated as the name.
            name = name.split(". ")[0].strip(" .")

            body, link, credits = [], None, []
            for ln in block[1:]:
                s = ln.strip()
                if not s or s.isdigit():          # blank, or a page number
                    continue
                if s.lower().startswith("fornlämningsnummer"):
                    continue
                if LAMNING_RE.fullmatch(s.rstrip(",. och")):
                    continue
                m = re.match(r"^Läs mer:\s*(\S+)", s)
                if m:
                    link = m.group(1)
                    continue
                if s.lower().startswith(("foto ", "foto:", "karta")):
                    # Not prose, but not nothing either: this is the photo
                    # credit, and the first version dropped it on the floor
                    # while keeping the paragraph it belonged to. Captured
                    # here so fetch_pdf_images() and anyone rendering the
                    # entry can attribute the picture.
                    cm = FOTO_RE.search(s)
                    if cm:
                        credits.append(cm.group(1).strip(" .:"))
                    continue
                body.append(s)
            blurb = " ".join(body)

            for num in nums:
                out.execute("""
                    INSERT OR REPLACE INTO objects
                      (dataset_id, obj_id, name, obj_type, description,
                       lon, lat, geom, props)
                    VALUES (?,?,?,?,?,NULL,NULL,NULL,?)
                """, (ds_id, num, name, "pdf-tips", num,
                      json.dumps({"blurb": blurb[:2000],
                                  "read_more": link,
                                  "photo_credit": "; ".join(credits) or None},
                                 ensure_ascii=False)))
                n += 1
        out.execute("UPDATE datasets SET n_features=?, note='pdf', "
                    "fetched_at=datetime('now') WHERE id=?", (n, ds_id))
        out.commit()
        print(f"    {n} lämningsnummer")



# ---------------------------------------------------------------------------
# Skotselplaner: one management plan per maintained monument
#
# 206 PDFs under ext-dokument.lansstyrelsen.se/skane/Skotselplaner_Fornvard/,
# each linked from the Skane fornvard object it describes, so the county has
# already done the join -- no proximity guessing. Three things in them that
# exist nowhere else in this pipeline:
#
#   1. "Status for skylt" -- whether the place HAS A SIGN, and a comment
#      saying what is wrong with it. Kungsbacka's antikvarie told us no
#      national sign layer exists, and that is still true; this is one county
#      keeping its own list for its own objects. 206 rows is not a country,
#      but it is the only ground truth on signage we have ever found.
#   2. "Status for P-plats" -- parking, the thing OSM only lets us guess at
#      by distance.
#   3. A "Beskrivning" written to be read, plus "Malsattning" and
#      "Skotselanvisning" -- what the county is trying to make the place look
#      like, which is as close to "what will I see when I get there" as any
#      source we hold.
# ---------------------------------------------------------------------------

PLAN_PREFIX = "http://ext-dokument.lansstyrelsen.se/skane/Skotselplaner_Fornvard/"

# The label column of the header table. Listed explicitly rather than parsed
# as "two or more spaces" because several PDFs wrap a long label onto its own
# line with the value above it (M198 puts "Gravhog" before "Typ enligt RAA"),
# and a generic splitter reads those as a field named Gravhog.
PLAN_FIELDS = [
    "Fornvardsobjekt", "Namn", "Kommun", "Socken", "Prioritet",
    "Typ enligt RAA", "Skotselavtal", "Skotsel", "Avtalsperiod", "Flora",
    "Besiktigad datum", "Areal (ha)", "Utford vard", "Status for skylt",
    "Skylt kommentar", "Status for P-plats", "P-plats kommentar",
    "Markagares medgivande", "Upprattad datum", "Reviderad datum",
    "Handlaggare", "RI-omrade", "Kategori", "Tidsalder",
]
PLAN_SECTIONS = ["Beskrivning", "Malsattning", "Skotselanvisning",
                 "Tillganglighet", "Ovrigt"]

UUID_RE = re.compile(r"/lamning/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}"
                     r"-[0-9a-f]{4}-[0-9a-f]{12})", re.I)

PLAN_SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    obj         TEXT PRIMARY KEY,       -- 'M322', the county's own object id
    url         TEXT NOT NULL,
    name        TEXT,
    kommun      TEXT,
    socken      TEXT,
    raa_type    TEXT,
    priority    TEXT,
    -- Verbatim, not normalised to a boolean. The vocabulary is a human's
    -- ("Finns OK", "Problem", "Behovs ej", blank) and collapsing it here
    -- would throw away the difference between "no sign needed" and "the sign
    -- is broken", which is exactly the distinction a visitor cares about.
    sign        TEXT,
    sign_note   TEXT,
    parking     TEXT,
    parking_note TEXT,
    inspected   TEXT,
    revised     TEXT,
    category    TEXT,
    period      TEXT,
    description TEXT,
    goal        TEXT,
    care        TEXT,
    props       TEXT,
    fetched_at  TEXT
);
CREATE TABLE IF NOT EXISTS plan_sites (
    obj         TEXT NOT NULL,
    uuid        TEXT,                   -- from the plan's own Fornsok links
    lamning     TEXT,                   -- 'L1989:9819'
    PRIMARY KEY (obj, uuid, lamning)
);
"""


def _deaccent(s):
    """For label matching only -- pdftotext is reliable on a/o umlauts but
    the field list above is written in ASCII so it stays greppable."""
    for a, b in (("\u00e5", "a"), ("\u00e4", "a"), ("\u00f6", "o"),
                 ("\u00c5", "A"), ("\u00c4", "A"), ("\u00d6", "O")):
        s = s.replace(a, b)
    return s


def parse_plan(text):
    """Header fields, prose sections and register ids out of one plan."""
    lines = [ln.rstrip() for ln in text.split("\n")]
    flat = _deaccent("\n".join(lines))

    fields = {}
    for ln in lines:
        raw = ln.strip()
        # Match the LABEL against a de-accented copy, but slice the VALUE out
        # of the raw line. Deaccenting the whole line and slicing from that
        # was the first version, and it wrote "Behovs ej" and "Vastra Hoby"
        # into the database -- stripping the diacritics out of Swedish names
        # we intend to show a Swedish user. _deaccent() is one-to-one on
        # length, so the offset carries across unchanged.
        flat_ln = _deaccent(raw)
        for lab in PLAN_FIELDS:
            if flat_ln.startswith(lab):
                val = raw[len(lab):].strip()
                if val:
                    fields.setdefault(lab, val)
                break

    # Sections: from a heading line to the next heading. The headings are
    # centred, so they arrive as a lot of leading whitespace and one word.
    heads = []
    for i, ln in enumerate(lines):
        s = _deaccent(ln).strip()
        if s in PLAN_SECTIONS:
            heads.append((i, s))
    # The register-id block ends the prose wherever it starts.
    end = len(lines)
    for i, ln in enumerate(lines):
        s = _deaccent(ln).strip()
        if s.rstrip(":") in ("Fornsok", "Forn-ID") or s.startswith("Forn-ID"):
            end = min(end, i)
    sections = {}
    for hi, (i, name) in enumerate(heads):
        stop = heads[hi + 1][0] if hi + 1 < len(heads) else end
        body = " ".join(x.strip() for x in lines[i + 1:stop] if x.strip())
        if body:
            sections[name] = re.sub(r"\s{2,}", " ", body)

    uuids = sorted(set(m.lower() for m in UUID_RE.findall(text)))
    nums = sorted(set(LAMNING_RE.findall(text)))
    return fields, sections, uuids, nums


def fetch_plans(out):
    import os
    import subprocess
    import tempfile

    out.executescript(PLAN_SCHEMA)
    out.commit()

    # The links are already in the objects table; the county did the join.
    links = {}
    for ds_id, obj_id, props in out.execute(
            "SELECT dataset_id, obj_id, props FROM objects "
            "WHERE props IS NOT NULL"):
        try:
            p = json.loads(props)
        except json.JSONDecodeError:
            continue
        if not isinstance(p, dict):
            continue
        for v in p.values():
            if isinstance(v, str) and PLAN_PREFIX.split("//")[1] in v:
                u = v.split("#")[0].strip()
                links.setdefault(u, (ds_id, obj_id))

    todo = [u for u in sorted(links)
            if not out.execute("SELECT 1 FROM plans WHERE url=? AND "
                               "description IS NOT NULL", (u,)).fetchone()]
    print(f"{len(links):,} management plans, {len(todo):,} to fetch")

    ok = signs = parks = 0
    for i, url in enumerate(todo, 1):
        # Six of these filenames contain a space ("M46 a.pdf"), which urllib
        # rejects outright rather than escaping. The unescaped form stays the
        # database key -- it is what the county published.
        blob = get(urllib.parse.quote(url, safe=":/?&=%"), raw=True,
                   timeout=120)
        if not blob:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            pdf = os.path.join(tmp, "p.pdf")
            with open(pdf, "wb") as f:
                f.write(blob)
            txt = os.path.join(tmp, "p.txt")
            subprocess.run(["pdftotext", "-layout", pdf, txt],
                           capture_output=True, text=True)
            if not os.path.exists(txt):
                continue
            with open(txt, encoding="utf-8", errors="replace") as f:
                text = f.read()

        fields, sec, uuids, nums = parse_plan(text)
        # The FILENAME is the key, not the Fornvardsobjekt field. Six objects
        # are split across several plans ("M46 a.pdf" .. "M46 d.pdf") and all
        # four say Fornvardsobjekt M46 inside, so keying on the field silently
        # collapsed four documents into one row. The parsed field is still in
        # props for anyone who wants to group them back together.
        obj = url.rsplit("/", 1)[-1]
        if obj.lower().endswith(".pdf"):
            obj = obj[:-4]
        sign = fields.get("Status for skylt")
        park = fields.get("Status for P-plats")
        out.execute("""
            INSERT OR REPLACE INTO plans
              (obj, url, name, kommun, socken, raa_type, priority,
               sign, sign_note, parking, parking_note, inspected, revised,
               category, period, description, goal, care, props, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
        """, (obj, url, fields.get("Namn"), fields.get("Kommun"),
              fields.get("Socken"), fields.get("Typ enligt RAA"),
              fields.get("Prioritet"), sign, fields.get("Skylt kommentar"),
              park, fields.get("P-plats kommentar"),
              fields.get("Besiktigad datum"), fields.get("Reviderad datum"),
              fields.get("Kategori"), fields.get("Tidsalder"),
              sec.get("Beskrivning"), sec.get("Malsattning"),
              sec.get("Skotselanvisning"),
              json.dumps(fields, ensure_ascii=False)))
        for u in uuids or [None]:
            for n in nums or [None]:
                if u or n:
                    out.execute("INSERT OR IGNORE INTO plan_sites VALUES "
                                "(?,?,?)", (obj, u, n))
        ok += 1
        signs += bool(sign)
        parks += bool(park)
        if i % 20 == 0:
            out.commit()
            print(f"  {i:,}/{len(todo):,}")
        time.sleep(0.3)
    out.commit()

    n, desc, uu = out.execute("""
        SELECT COUNT(*), SUM(description IS NOT NULL),
               (SELECT COUNT(DISTINCT uuid) FROM plan_sites
                 WHERE uuid IS NOT NULL) FROM plans""").fetchone()
    print(f"  {ok:,} parsed; {n:,} plans, {desc or 0:,} with a description, "
          f"{uu:,} register uuids named directly")
    print(f"  sign status on {signs:,}; parking status on {parks:,}")


# The licence each county declares in the catalogue, mapped to what we can
# write in an attribution line. Swedish, because that is what the metadata
# says; "inga tillampliga villkor" ("no applicable conditions") is a
# statement about access constraints and NOT a licence grant, so it is not in
# this table -- a dataset whose only constraint line says that stays
# unresolved rather than being read as permission.
LICENCE_MAP = [
    (re.compile(r"erk[äa]nnande.*4\.0|\bcc[ -]?by[ -]?4\.0", re.I),
     ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/")),
    (re.compile(r"erk[äa]nnande.*dela.*lika|\bcc[ -]?by[ -]?sa", re.I),
     ("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/")),
    (re.compile(r"\bcc0\b|public domain|noll 1\.0", re.I),
     ("CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/")),
]


def fetch_licences(out):
    """Read the licence out of each dataset's own catalogue metadata.

    Every county row in the corpus was parked at usable = 0 because nobody
    had checked whether we are allowed to republish the text. The answer was
    in the metadata the whole time: ISO 19139 carries it in
    MD_LegalConstraints, and most of these say "Creative commons Erkannande
    4.0 Internationell" -- CC BY 4.0, which we can use with attribution.

    Datasets that declare nothing usable stay unresolved. That is the honest
    outcome for them, not a default of yes.
    """
    try:
        out.execute("ALTER TABLE datasets ADD COLUMN licence TEXT")
    except sqlite3.OperationalError:
        pass                            # already added by an earlier run
    ids = [r[0] for r in out.execute(
        "SELECT id FROM datasets WHERE id NOT LIKE 'pdf:%'")]
    print(f"{len(ids)} catalogue records")
    found = 0
    for i, rec in enumerate(ids, 1):
        xml = get(CSW, {"service": "CSW", "version": "2.0.2",
                        "request": "GetRecordById", "id": rec,
                        "elementSetName": "full",
                        "outputSchema": "http://www.isotc211.org/2005/gmd"})
        lic = None
        if xml:
            texts = [re.sub(r"<[^>]+>", "", m).strip() for m in re.findall(
                r"<gmd:otherConstraints[^>]*>(.*?)</gmd:otherConstraints>",
                xml, re.S)]
            for t in texts:
                for rx, val in LICENCE_MAP:
                    if rx.search(t):
                        lic = val
                        break
                if lic:
                    break
        out.execute("UPDATE datasets SET licence=? WHERE id=?",
                    (lic[0] if lic else None, rec))
        found += bool(lic)
        if i % 10 == 0:
            out.commit()
            print(f"  {i}/{len(ids)}")
        time.sleep(0.3)
    out.commit()
    print(f"  {found} of {len(ids)} declare a licence we can act on")
    for lic, n in out.execute("SELECT COALESCE(licence,'(unresolved)'), "
                              "COUNT(*) FROM datasets GROUP BY 1 ORDER BY 2 "
                              "DESC"):
        print(f"    {n:3d}  {lic}")


# ---------------------------------------------------------------------------
# Photographs inside the county folders
#
# 117 embedded JPEGs across the two Halland PDFs, most around 1300x900 at
# 220 ppi -- usable, not thumbnails. They are not URLs, so the only way to
# have them is to hold the bytes.
#
# Attribution is the hard part and the first version of the text parser made
# it worse: it had a line that skipped anything starting with "foto", so the
# credit was thrown away while the prose it belonged to was kept. There is
# not much of it -- 15 credits for 117 images, because the folders credit a
# caption rather than a file -- but a credit we discard is one we can never
# reconstruct, and these PDFs declare no licence at all, so every image
# lands with usable = 0 until that is resolved.
# ---------------------------------------------------------------------------

IMAGE_DIR = os.path.join("src", "data", "images", "county_pdf")
FOTO_RE = re.compile(r"\bfoto[:\s]+([^.\n]{2,70})", re.I)

PDF_IMAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS pdf_images (
    dataset_id  TEXT NOT NULL,
    page        INTEGER NOT NULL,
    seq         INTEGER NOT NULL,
    local_path  TEXT NOT NULL,
    -- The entry this page belongs to. A folder puts one place per page, so
    -- the page IS the join key; where a page names no lamningsnummer (the
    -- nature-reserve entries do not) these stay NULL rather than being
    -- attached to whichever number happened to be nearest.
    lamning     TEXT,
    heading     TEXT,
    credit      TEXT,
    width       INTEGER, height INTEGER, bytes INTEGER,
    PRIMARY KEY (dataset_id, page, seq)
);
"""



def plan_clusters(out, work_db):
    """plan id -> {cluster_id}, by the two routes a plan can be joined.

    Lives here, once, because it was written twice: build_sources.py and
    build_places.py each grew their own copy and the second one only used
    the uuid route, so it silently resolved 68 places where the first
    resolved 156. A join this fiddly gets exactly one implementation.

    Route 1, and the good one: the plan prints its own Fornsok links, so the
    key is the register's own uuid.
    Route 2, for the plans that print none: whichever clusters the county
    object that links the pdf was itself matched to.
    """
    w = sqlite3.connect(f"file:{work_db}?mode=ro", uri=True)
    cl = dict(w.execute("SELECT uuid, cluster_id FROM site_clusters"))

    direct = {}
    for obj, uuid in out.execute("SELECT obj, uuid FROM plan_sites "
                                 "WHERE uuid IS NOT NULL"):
        if uuid in cl:
            direct.setdefault(obj, set()).add(cl[uuid])

    url_of = dict(out.execute("SELECT url, obj FROM plans"))
    obj_clusters = {}
    for ds_id, obj_id, cid in out.execute(
            "SELECT dataset_id, obj_id, cluster_id FROM matches "
            "WHERE how <> 'in_landscape' AND cluster_id IS NOT NULL"):
        obj_clusters.setdefault((ds_id, obj_id), set()).add(cid)

    fallback = {}
    for ds_id, obj_id, props in out.execute(
            "SELECT dataset_id, obj_id, props FROM objects "
            "WHERE props IS NOT NULL"):
        try:
            pr = json.loads(props)
        except json.JSONDecodeError:
            continue
        if not isinstance(pr, dict):
            continue
        for v in pr.values():
            if not isinstance(v, str) or "Skotselplaner_Fornvard" not in v:
                continue
            plan = url_of.get(v.split("#")[0].strip())
            if plan:
                fallback.setdefault(plan, set()).update(
                    obj_clusters.get((ds_id, obj_id), set()))

    return {plan: (direct.get(plan) or fallback.get(plan) or set())
            for plan in set(direct) | set(fallback)}


def fetch_pdf_images(out):
    import glob
    import os as _os
    import subprocess
    import tempfile

    out.executescript(PDF_IMAGE_SCHEMA)
    out.commit()
    _os.makedirs(IMAGE_DIR, exist_ok=True)

    total = 0
    for county, title, url in PDF_SOURCES:
        ds_id = f"pdf:{county}:{title}"
        print(f"  {title}")
        blob = get(url, raw=True, timeout=300)
        if not blob:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            pdf = _os.path.join(tmp, "f.pdf")
            with open(pdf, "wb") as f:
                f.write(blob)

            # Page-by-page text, so an image can be tied to the entry it
            # illustrates. pdftotext separates pages with a form feed.
            r = subprocess.run(["pdftotext", "-layout", pdf, "-"],
                               capture_output=True, text=True)
            pages = r.stdout.split("\f")

            stem = _os.path.join(tmp, "img")
            subprocess.run(["pdfimages", "-j", "-p", pdf, stem],
                           capture_output=True, text=True)
            files = sorted(glob.glob(stem + "-*"))

            n = 0
            for path in files:
                base = _os.path.basename(path)
                m = re.match(r"img-(\d+)-(\d+)\.", base)
                if not m:
                    continue
                page, seq = int(m.group(1)), int(m.group(2))
                txt = pages[page - 1] if 0 < page <= len(pages) else ""
                nums = LAMNING_RE.findall(txt)
                head = None
                for ln in txt.split("\n"):
                    hm = re.match(r"^\s*\d+\.\s+(.+?)\s*$", ln)
                    if hm:
                        head = hm.group(1).split(". ")[0].strip(" .")
                        break
                cm = FOTO_RE.search(txt)
                credit = cm.group(1).strip(" .:") if cm else None

                dest = _os.path.join(IMAGE_DIR,
                                     f"{county}-{page:03d}-{seq:03d}"
                                     + _os.path.splitext(base)[1])
                with open(path, "rb") as src, open(dest, "wb") as dst:
                    data = src.read()
                    dst.write(data)
                out.execute("""
                    INSERT OR REPLACE INTO pdf_images
                      (dataset_id, page, seq, local_path, lamning, heading,
                       credit, width, height, bytes)
                    VALUES (?,?,?,?,?,?,?,NULL,NULL,?)
                """, (ds_id, page, seq, dest, nums[0] if nums else None,
                      head, credit, len(data)))
                n += 1
            out.commit()
            total += n
            print(f"    {n} images")

    with_lam, with_credit, mb = out.execute("""
        SELECT SUM(lamning IS NOT NULL), SUM(credit IS NOT NULL),
               SUM(bytes) FROM pdf_images""").fetchone()
    print(f"  {total} images; {with_lam or 0} tied to a lamningsnummer, "
          f"{with_credit or 0} with a credit, {(mb or 0)/1e6:.1f} MB")

PAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    url         TEXT PRIMARY KEY,
    county      TEXT,
    title       TEXT,
    text        TEXT,
    photo_credit TEXT,
    http_status INTEGER,
    fetched_at  TEXT
);
CREATE TABLE IF NOT EXISTS page_objects (
    url         TEXT NOT NULL,
    dataset_id  TEXT NOT NULL,
    obj_id      TEXT NOT NULL,
    PRIMARY KEY (url, dataset_id, obj_id)
);
"""


def page_urls(out):
    """(url, dataset_id, obj_id) for every visitor page a county links to."""
    found = []
    for ds_id, obj_id, props in out.execute(
            "SELECT dataset_id, obj_id, props FROM objects "
            "WHERE props IS NOT NULL"):
        try:
            p = json.loads(props)
        except json.JSONDecodeError:
            continue
        if not isinstance(p, dict):
            continue
        for v in p.values():
            if not isinstance(v, str) or not v.lower().startswith("http"):
                continue
            u = v.split("#")[0].strip()
            low = u.lower()
            if PAGE_HOST not in low or low.endswith(".pdf"):
                continue
            # The intranet hosts answer only from inside the authority.
            if "intralink" in low or "m.lst.se" in low:
                continue
            if any(mk in low for mk in PAGE_MARKERS):
                found.append((u, ds_id, obj_id))
    return found


def page_text(html_doc):
    """The editorial text of a lansstyrelsen.se page.

    Cut to <main> first. These pages are 200 KB of which the article is two
    percent: a language picker, a mega-menu, a cookie banner and a footer of
    contact details for all 21 counties. Without the cut, every page would
    "contain" the words Karlskrona and Ostersund and the model would cheerfully
    work them into the prose.
    """
    import html as _html

    m = re.search(r"(?is)<main[^>]*>(.*?)</main>", html_doc)
    doc = m.group(1) if m else html_doc
    doc = re.sub(r"(?is)<(script|style|nav|form|footer|aside)[^>]*>.*?</\1>",
                 " ", doc)
    # Paragraph and heading boundaries become newlines before the tags go, so
    # sentences from different blocks do not run together into nonsense.
    doc = re.sub(r"(?i)</(p|h[1-6]|li|div|tr)>", "\n", doc)
    txt = _html.unescape(re.sub(r"<[^>]+>", " ", doc))

    credit = None
    lines = []
    for raw in txt.split("\n"):
        s = " ".join(raw.split())
        if len(s) < 25:
            continue
        low = s.lower()
        if low.startswith("foto"):
            credit = credit or s
            continue
        # Boilerplate that survives the <main> cut on some pages.
        if low.startswith(("hitta ", "sök", "dela sidan", "kontakta oss",
                           "om webbplatsen", "till toppen")):
            continue
        lines.append(s)
    # Duplicates are common: the preamble is often repeated as a meta summary.
    seen, out_lines = set(), []
    for s in lines:
        if s not in seen:
            seen.add(s)
            out_lines.append(s)
    return "\n".join(out_lines), credit


def fetch_pages(out):
    out.executescript(PAGE_SCHEMA)
    out.commit()
    links = page_urls(out)
    uniq = sorted({u for u, _, _ in links})
    print(f"{len(links):,} links to {len(uniq):,} distinct visitor pages")
    for url, ds_id, obj_id in links:
        out.execute("INSERT OR IGNORE INTO page_objects VALUES (?,?,?)",
                    (url, ds_id, obj_id))
    out.commit()

    todo = [u for u in uniq
            if not out.execute("SELECT 1 FROM pages WHERE url=? AND text "
                               "IS NOT NULL", (u,)).fetchone()]
    print(f"{len(todo):,} to fetch")
    got = 0
    for i, url in enumerate(todo, 1):
        doc = get(url, timeout=45)
        if not doc:
            out.execute("INSERT OR REPLACE INTO pages (url, http_status, "
                        "fetched_at) VALUES (?,0,datetime('now'))", (url,))
            continue
        title = None
        m = re.search(r"(?is)<title>(.*?)</title>", doc)
        if m:
            title = m.group(1).split("|")[0].strip()
        text, credit = page_text(doc)
        out.execute("""
            INSERT OR REPLACE INTO pages
              (url, county, title, text, photo_credit, http_status, fetched_at)
            VALUES (?,?,?,?,?,200,datetime('now'))
        """, (url, re.search(r"lansstyrelsen\.se/([a-z-]+)/", url).group(1)
              if re.search(r"lansstyrelsen\.se/([a-z-]+)/", url) else None,
              title, text, credit))
        got += 1
        if i % 25 == 0:
            out.commit()
            print(f"  {i:,}/{len(todo):,}")
        time.sleep(0.4)
    out.commit()
    n, chars = out.execute("SELECT COUNT(*), SUM(LENGTH(text)) FROM pages "
                           "WHERE text IS NOT NULL AND text <> ''").fetchone()
    print(f"  {got:,} fetched; {n:,} pages hold {(chars or 0):,} characters "
          f"({(chars or 0)//max(n,1):,} each)")


def fetch(out):
    rows = out.execute("SELECT id, title, rest_url, atom_url, download "
                       "FROM datasets WHERE id NOT LIKE 'pdf:%'").fetchall()
    print(f"{len(rows)} datasets")
    for ds_id, title, rest, atom, dl in rows:
        print(f"  {title}")
        n, how = 0, None
        if rest:
            n, how = fetch_rest(out, ds_id, title, rest), "rest"
        if n == 0:
            # Falls through to the zip whenever REST gave nothing, which
            # covers both "no REST layer" and "REST host refuses us".
            z = dl or (atom_zip(atom) if atom else None)
            if z:
                n, how = fetch_zip(out, ds_id, title, z), "zip"
        out.execute("UPDATE datasets SET n_features=?, note=?, "
                    "fetched_at=datetime('now') WHERE id=?", (n, how, ds_id))
        out.commit()
        print(f"    {n:,} objects" + (f" via {how}" if how else " -- nothing"))
        time.sleep(0.3)


DESIG = re.compile(r"^([A-ZÅÄÖÉ][A-Za-zÅÄÖÅåäöé\-\s]*?)\s+([\d]+(?:\s*[,:]\s*\d+)*)\s*$")


def parse_designation(text):
    """('Rogsta', ['1','2','3']) from 'Rogsta 1, 2, 3'. None if it is prose."""
    if not text:
        return None
    t = " ".join(str(text).split())
    m = DESIG.match(t)
    if not m:
        return None
    parish = m.group(1).strip()
    nums = re.findall(r"\d+", m.group(2))
    return (parish, nums) if parish and nums else None


def rings_of(geom):
    """Every outer/inner ring of a (Multi)Polygon, as coordinate lists."""
    if not geom:
        return []
    gt = geom.get("type")
    c = geom.get("coordinates") or []
    if gt == "Polygon":
        return c
    if gt == "MultiPolygon":
        return [ring for poly in c for ring in poly]
    return []


def point_in_rings(lon, lat, rings):
    """Even-odd ray casting.

    Even-odd rather than winding order, because it handles holes for free: a
    point inside an inner ring crosses an even number of edges overall and
    correctly comes out false. Written here rather than pulled from shapely,
    which would be a compiled dependency for thirty lines.
    """
    inside = False
    for ring in rings:
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i][0], ring[i][1]
            x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
            if (y1 > lat) != (y2 > lat):
                # x of the edge at this latitude.
                xx = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
                if lon < xx:
                    inside = not inside
    return inside


def bbox_of(rings):
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def bbox_km2(bb):
    import math
    mid = (bb[1] + bb[3]) / 2
    return ((bb[2] - bb[0]) * 111.32 * math.cos(math.radians(mid))
            * (bb[3] - bb[1]) * 111.32)


def join(sites, out):
    """Match county objects to register sites, then to clusters.

    Three passes per object, most trustworthy first. All matches are kept --
    agreement between them is evidence, and a later stage can weight them --
    but `contains` is the one to believe for area datasets and `number` for
    the ones that publish an RAA designation.
    """
    import math

    objs = out.execute("SELECT dataset_id, obj_id, description, lon, lat, geom "
                       "FROM objects").fetchall()
    print(f"{len(objs):,} county objects to match")

    # A coarse 0.02-degree grid over our sites, so each object costs a handful
    # of bucket lookups instead of 311,844 distance computations.
    grid = {}
    for uuid, lon, lat in sites.execute(
            "SELECT uuid, lon, lat FROM sites WHERE lon IS NOT NULL"):
        grid.setdefault((int(lon / 0.02), int(lat / 0.02)), []).append(
            (uuid, lon, lat))
    cluster_of = dict(sites.execute("SELECT uuid, cluster_id FROM site_clusters"))

    def nearby(lon, lat, pad=1):
        gx, gy = int(lon / 0.02), int(lat / 0.02)
        for dx in range(-pad, pad + 1):
            for dy in range(-pad, pad + 1):
                yield from grid.get((gx + dx, gy + dy), ())

    n = {"contains": 0, "in_landscape": 0, "lamningsnummer": 0,
         "number": 0, "geometry": 0}
    out.execute("DELETE FROM matches")

    def add(ds, oid, uuid, how, dist=None, raa=None):
        out.execute("INSERT OR REPLACE INTO matches VALUES (?,?,?,?,?,?,?)",
                    (ds, oid, uuid, how, dist, raa, cluster_of.get(uuid)))
        n[how] += 1

    for ds_id, obj_id, desc, lon, lat, geom_json in objs:
        geom = json.loads(geom_json) if geom_json else None
        rings = rings_of(geom)

        # 1. Inside the polygon. For a maintenance AREA this is not a guess:
        #    the county drew a boundary and everything in it is what they
        #    maintain.
        if rings:
            bb = bbox_of(rings)
            if bb:
                how = ("contains" if bbox_km2(bb) <= MAX_CONTAIN_KM2
                       else "in_landscape")
                pad = max(1, int((bb[2] - bb[0]) / 0.02) + 1)
                for uuid, slon, slat in nearby((bb[0] + bb[2]) / 2,
                                               (bb[1] + bb[3]) / 2, pad):
                    if not (bb[0] <= slon <= bb[2] and bb[1] <= slat <= bb[3]):
                        continue
                    if point_in_rings(slon, slat, rings):
                        add(ds_id, obj_id, uuid, how)

        # 2a. An exact lamningsnummer, which is our primary key. Only the
        #     PDF folders publish these, and they are the most reliable
        #     labels here -- no parsing, no proximity.
        if desc and LAMNING_RE.fullmatch(desc.strip()):
            row = sites.execute("SELECT uuid FROM sites WHERE "
                                "lamningsnummer=?", (desc.strip(),)).fetchone()
            if row:
                add(ds_id, obj_id, row[0], "lamningsnummer")

        # 2b. The published RAA designation.
        parsed = parse_designation(desc)
        if parsed:
            parish, nums = parsed
            for num in nums:
                for uuid, raa in sites.execute(
                        "SELECT uuid, raa_number FROM sites WHERE parish=? "
                        "AND raa_number LIKE ?",
                        (parish, f"{parish} {num}:%")):
                    add(ds_id, obj_id, uuid, "number", raa=raa)

        # 3. Nearest site to the centroid, as the fallback for point datasets
        #    and for objects whose description is blank.
        if lon is not None:
            best = None
            for uuid, slon, slat in nearby(lon, lat):
                d = math.hypot((slat - lat) * 111320,
                               (slon - lon) * 111320
                               * math.cos(math.radians(lat)))
                if d <= MATCH_RADIUS_M and (best is None or d < best[1]):
                    best = (uuid, d)
            if best:
                add(ds_id, obj_id, best[0], "geometry", dist=best[1])

    out.commit()
    for how in ("lamningsnummer", "contains", "number", "geometry",
                "in_landscape"):
        print(f"  {n[how]:>7,} matches by {how}")
    sites_n, clusters_n, objs_n = out.execute(
        "SELECT COUNT(DISTINCT uuid), COUNT(DISTINCT cluster_id), "
        "COUNT(DISTINCT dataset_id || obj_id) FROM matches "
        "WHERE how <> 'in_landscape'").fetchone()
    print(f"\n  {sites_n:,} register sites in {clusters_n:,} clusters, "
          f"from {objs_n:,} county objects "
          f"({len(objs) - objs_n:,} matched nothing)")
    print("  clusters are the unit a label should use; see the schema comment")
    land = out.execute("SELECT COUNT(DISTINCT cluster_id) FROM matches "
                       "WHERE how='in_landscape'").fetchone()[0]
    print(f"  plus {land:,} clusters inside a designated cultural landscape "
          f"(a weaker, separate signal)")


def status(out):
    rows = out.execute("""
        SELECT kind, county, title, n_features,
               (SELECT COUNT(DISTINCT uuid) FROM matches m
                 WHERE m.dataset_id = d.id) AS sites
        FROM datasets d ORDER BY kind, county
    """).fetchall()
    print(f"{len(rows)} datasets")
    for kind, county, title, n, s in rows:
        print(f"  {kind:10} {str(county or '-'):3} {str(n or '-'):>6} objs  "
              f"{str(s or '-'):>6} sites  {title}")
    tot = out.execute("SELECT COUNT(DISTINCT uuid) FROM matches").fetchone()[0]
    print(f"\n{tot:,} distinct register sites named by a county board")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sites-db", default=SITES_DB)
    p.add_argument("--out", default=OUT_DB)
    p.add_argument("--discover", action="store_true")
    p.add_argument("--fetch", action="store_true")
    p.add_argument("--join", action="store_true")
    p.add_argument("--all", action="store_true")
    p.add_argument("--pages", action="store_true")
    p.add_argument("--plans", action="store_true")
    p.add_argument("--licences", action="store_true")
    p.add_argument("--images", action="store_true")
    p.add_argument("--status", action="store_true")
    args = p.parse_args()

    out = sqlite3.connect(args.out)
    out.executescript(SCHEMA)
    out.commit()

    if args.discover or args.all:
        discover(out)
    if args.fetch or args.all:
        fetch(out)
        fetch_pdfs(out)
    if args.pages or args.all:
        fetch_pages(out)
    if args.plans or args.all:
        fetch_plans(out)
    if args.licences or args.all:
        fetch_licences(out)
    if args.images or args.all:
        fetch_pdf_images(out)
    if args.join or args.all:
        sites = sqlite3.connect(f"file:{args.sites_db}?mode=ro", uri=True)
        join(sites, out)
    if args.status or not (args.discover or args.fetch or args.join
                           or args.pages or args.plans
                           or args.licences
                           or args.images or args.all):
        status(out)


if __name__ == "__main__":
    main()
