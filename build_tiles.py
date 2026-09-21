#!/usr/bin/env python3
"""
Export scored clusters as tippecanoe vector tiles for the frontend.

The frontend lives in a separate repo (franco-may, Next.js + MapLibre) and
already reads tippecanoe tiles. This reproduces the contract its existing tiles
declare in metadata.json:

    layer:  archaeological_sites
    fields: uuid, label, class, family, score, stars
            (clustered / point_count / sqrt_point_count are added by tippecanoe)

`score` is consumed by the frontend only as a MapLibre `symbol-sort-key`, so
only the ordering matters. We emit a 0-100 percentile because it is readable
when debugging.

One feature per CLUSTER, not per site: a gravfalt of 40 stensattningar is one
place a visitor drives to, and should be one pin.

Reads:  src/data/work.sqlite
Writes: the --out directory (defaults to the frontend repo)

Usage:
    python build_tiles.py --out /tmp/tiles-test      # dry run somewhere safe
    python build_tiles.py                            # straight into franco-may
    python build_tiles.py --max-desc 0                # full descriptions
    python build_tiles.py --score full                # rank known places higher
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time

from families import CLASS_BLACKLIST, FAMILY, FAMILY_ICON, FAMILY_ORDER
from titles import resolve_title
from periods import period_for

import paths

DB = paths.WORK
DEFAULT_OUT = paths.TILES
DEFAULT_DESC_OUT = paths.DESCRIPTIONS
DEFAULT_GROUPS_OUT = paths.FILTER_FAMILIES
AI_DB = paths.GENERATED
GEOJSON = paths.GEOJSON
LAYER = "archaeological_sites"

# Matches the options recorded in the frontend's existing metadata.json, so the
# map keeps behaving the same way.
TIPPECANOE_OPTS = [
    # maxzoom 14, NOT `-zg`. With `-zg` tippecanoe picked maxzoom 9, and
    # `--cluster-densest-as-needed` merges nearby points at low zoom and places
    # the merged feature at the AVERAGE position -- Hunehals borg landed 595 m
    # from its true location with point_count=2. Because MapLibre overzooms the
    # deepest tile it has, that displacement then persists at EVERY zoom level.
    # At z14 features are unclustered and positions are exact to well under a
    # metre, while clustering still declutters the low zooms.
    "-z14", "-Z0", "--force", "--preserve-input-order",
    # Disable the default gamma rate-thinning (--drop-rate 2.5). It dropped
    # 9,999 of 10,000 features at z0-z9 -- the map went blank on zoom out --
    # and it chose WHICH to drop by nothing but arrival order spacing, so the
    # single survivor was not even a notable site. We decide visibility
    # ourselves in assign_minzoom() and hand tippecanoe a per-feature
    # tippecanoe.minzoom, which it always honours.
    "--drop-rate=1",
    # NO clustering. `--cluster-distance=5` used to merge anything within 5 px
    # into one feature carrying a point_count -- so the browser never received
    # the individual candidates. Decoded, the z0 tile held 11 features standing
    # in for all 10,000 points. That made client-side reselection impossible:
    # when a filter hid an icon, there was nothing in the tile to put in its
    # place, so the map just gained a hole. It also averaged positions, which
    # is how Hunehals borg once landed 595 m from its true location.
    #
    # `--drop-densest-as-needed` is the safety net instead: if a tile ever
    # exceeds the 500 KB vector-tile budget it DROPS the densest features
    # rather than merging them, so no position is ever invented. Measured worst
    # tile with the current settings is 218 KB, so it should stay dormant.
    "--drop-densest-as-needed", "--extend-zooms-if-still-dropping",
    # Tiles served as plain static files from Next.js `public/` arrive without a
    # Content-Encoding header, so MapLibre cannot know they are gzipped and
    # fails with "Unable to parse the tile". Write them raw instead: a .pbf must
    # start with protobuf bytes (1a86...), not the gzip magic (1f8b...).
    "--no-tile-compression",
]


# Star rating: percentile buckets, not a linear rescale of the raw score.
#
# The raw score is a power-law decay -- median 0.07, 85% of clusters below
# 0.50, and a long thin tail. Mapping worst..best linearly onto 0..5 would put
# ~9,500 of the exported 10,000 at zero stars and three at five, which is
# useless as a filter and misleading as a display.
#
# Buckets over the RANK inside the exported set fix both: every band has
# members by construction, and "3 stars and up" means a definite thing ("the
# better half of what the app ships"). The cutoffs are cumulative percentiles
# from the top, and `score` below is already exactly that percentile.
#
# There is no zero-star band. A site we know little about is not a bad site,
# and one star already says "least remarkable of the ten thousand we picked".
STAR_CUTOFFS = (
    (90.0, 5),   # top 10%
    (70.0, 4),   # next 20%
    (40.0, 3),   # next 30%
    (15.0, 2),   # next 25%
)


def stars_for(percentile):
    """1..5 from a best-first percentile (100 = best in the exported set)."""
    for cut, stars in STAR_CUTOFFS:
        if percentile >= cut:
            return stars
    return 1


def one_line(text, limit):
    """RAA descriptions are hard-wrapped mid-word; collapse to one line."""
    if not text:
        return ""
    t = " ".join(text.split())
    if limit and len(t) > limit:
        return t[:limit].rsplit(" ", 1)[0] + "…"
    return t


# Points per tile edge used as the thinning grid. Each tile is cut into
# CELLS_PER_TILE^2 cells and at most one point per cell may appear at that
# zoom, so density is bounded everywhere while coverage stays even -- a
# national top-N instead would leave whole regions blank at mid zooms.
# 24 puts cells ~21 px apart (512/24), which is about the tightest spacing at
# which map pins stay distinguishable. 12 was visibly too sparse when zooming
# out; 8 emptied the regional zooms again.
CELLS_PER_TILE = 24


def assign_minzoom_by_family(rows, maxzoom, cells_per_tile=CELLS_PER_TILE):
    """Run the thinning grid once per family, not once over everything.

    Thinning globally means a tile contains, for each patch of ground, only the
    single best cluster of ANY family. Hide that one with a filter and the
    patch goes empty -- there is no runner-up in the tile to promote. Per
    family, every family has its own well-spread set at every zoom, so any
    filter selection (always a union of families) stays evenly covered and
    MapLibre's collision engine does the final pick by score.

    The cost is bounded and small: a family with few members is simply fully
    visible from z0. Measured on the top 10,000 it takes the export from
    12.3 MB to 14.6 MB, worst tile 71 KB -> 218 KB.
    """
    buckets = {}
    for i, r in enumerate(rows):
        buckets.setdefault(FAMILY.get(r["dominant_class"] or "", "misc"),
                           []).append(i)
    out = [maxzoom] * len(rows)
    for idxs in buckets.values():
        sub = [rows[i] for i in idxs]
        for i, z in zip(idxs, assign_minzoom(sub, maxzoom, cells_per_tile)):
            out[i] = z
    return out


def assign_minzoom(rows, maxzoom, cells_per_tile=CELLS_PER_TILE):
    """Give every row the lowest zoom at which it can be shown.

    Greedy, best-first: walking zooms from the top down, a point becomes
    visible at the first zoom where no better-scoring point has already taken
    its grid cell. `rows` must already be sorted best-first.

    The result is that zooming out never empties the map -- it only thins it,
    and what survives is the best thing in each area rather than an arbitrary
    sample.
    """
    import math

    xy = []
    for r in rows:
        lon, lat = r["lon"], r["lat"]
        x = (lon + 180.0) / 360.0
        # Web-mercator y, clamped off the poles where the projection diverges.
        s = math.sin(math.radians(max(-85.05, min(85.05, lat))))
        y = 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
        xy.append((x, y))

    minzoom = [maxzoom] * len(rows)
    for z in range(maxzoom + 1):
        n = (1 << z) * cells_per_tile
        taken = set()
        for i, (x, y) in enumerate(xy):
            if minzoom[i] < z:
                continue          # already visible at a lower zoom
            cell = (int(x * n), int(y * n))
            if cell in taken:
                continue          # a better point owns this cell at this zoom
            taken.add(cell)
            minzoom[i] = z
    return minzoom


def load_dims(db, rows):
    """Parsed dimensions of the member this cluster wears.

    Joined on clusters.rep_uuid. It used to pick "the best-described member"
    with its own ORDER BY, which omitted the blacklist clause the other
    copies had -- so the measurements in the sheet could describe a different
    stone than the title, the icon and the text above them. A sheet reading
    "Gånggrift -- 1.2 m" where the 1.2 m belongs to a nearby clearance cairn
    is worse than no measurement, because it looks like a fact.
    """
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out = {}
    for cid, a, b, c in conn.execute("""
            SELECT c.cluster_id, s.dim_len_m, s.dim_height_m, s.dim_area_m2
              FROM clusters c JOIN sites s ON s.uuid = c.rep_uuid"""):
        out[cid] = (a, b, c)
    conn.close()
    return out


def load_resolved_names(work_db, wiki_db):
    """cluster_id -> the place's name, by titles.resolve_title.

    The SAME rule describe_place.payload uses, because the alternative was
    two rules and they fought: this function replaces an override that used
    clusters.name directly, which is the register's folk name. For Li
    gravfält the model correctly returned "Li gravfält" and the override
    replaced it with "Frodestenen" -- the standing stone inside the grave
    field -- so the fix for titles burying names reintroduced the same bug
    from the other side.

    Still needed even though the generator now resolves the name itself:
    8,749 of the 8,899 descriptions were written before that change and
    carry a generic heading.
    """
    w = sqlite3.connect(f"file:{work_db}?mode=ro", uri=True)
    names = dict(w.execute("SELECT cluster_id, name FROM clusters "
                           "WHERE name IS NOT NULL"))
    wiki = {}
    if os.path.exists(wiki_db):
        wm = sqlite3.connect(f"file:{wiki_db}?mode=ro", uri=True)
        cl = dict(w.execute("SELECT uuid, cluster_id FROM site_clusters"))
        for uuid, title in wm.execute("SELECT uuid, title FROM wiki_articles "
                                      "WHERE lang = 'sv'"):
            cid = cl.get(uuid)
            if cid:
                wiki.setdefault(cid, title)
    out = {}
    for cid in set(names) | set(wiki):
        t, _src = resolve_title(wiki.get(cid), names.get(cid))
        if t:
            out[cid] = t
    return out


# Photographs, per place, for the carousel in the app's sheet.
MAX_PHOTOS = 6


def load_images(places_db):
    """{cluster_id: [{f, by, lic, url}]} -- Commons files we are sure about.

    GEOSEARCH IS DELIBERATELY EXCLUDED, and it is 11,718 of the 15,650 rows.
    Those are files whose own coordinates fall within a radius of the site,
    which the crawler's own comment already calls "a good guess, still a
    guess". It is a worse guess than that reads: the busiest place in the
    set is a runestone in Uppsala whose geosearch photos include "Portrait
    bust of a woman (1st century AD)" -- a museum object a few hundred
    metres away. On a phone, under a heading with the place's name, that is
    not a near miss, it is a wrong caption.

    The cost of leaving them out is small and was measured before deciding:
    of the 6,000 places that ship, 2,880 have a photograph we are sure of
    and only 67 more would be added by trusting the radius. Sixty-seven
    places against a museum bust on a grave field is not a trade.

    They are not deleted, only unshipped. `distance_m` is NULL on every row
    -- the crawler had it from the API and dropped it -- so there is
    currently no way to rank or cut them. Backfilling that is what would
    let them in, and it is in the TODO.

    THE URL TRAVELS AS THREE SHORT FIELDS, not as a URL. The stored ones
    average 409 bytes a row -- 4.5 MB of payload -- and almost all of that
    is a constant prefix, the file name repeated twice, and utm parameters.
    What actually varies is the two-level hash directory and the rendered
    width:

        https://upload.wikimedia.org/wikipedia/commons/thumb/1/12/
               Bohus-Castle6.jpg/960px-Bohus-Castle6.jpg?utm_source=...
                              ^^^^                 ^^^

    so `h` is "1/12", `w` is 960, and the phone rebuilds the rest.

    THE FIRST ATTEMPT USED Special:FilePath/<file>?width=N INSTEAD, which is
    tidier and does not need the hash -- and it shipped a sheet full of grey
    boxes. Two reasons, and the second is the one that matters: it is a
    double redirect ending on another host, and Wikimedia has begun refusing
    arbitrary thumbnail widths outright ("Use thumbnail sizes listed on
    ...", HTTP 400 -- 640 is refused for files where 250 and 500 are served).
    Rebuilding a width nobody has rendered is guessing; `w` here is the width
    Commons ITSELF returned when the crawler asked, so it is known to exist.

    `w` is absent for a file small enough that Commons served the original
    with no thumbnail, and then the path has no /thumb/ segment either.
    """
    if not os.path.exists(places_db):
        return {}
    c = sqlite3.connect(f"file:{places_db}?mode=ro", uri=True)
    out = {}
    q = """SELECT cluster_id, file, author, licence, licence_url, page_url,
                  source, thumb_url, image_url
           FROM images
           WHERE usable = 1 AND source <> 'commons_geosearch'
             AND file IS NOT NULL AND file <> ''
           -- Wikidata's own designation first, then a county folder, then
           -- an editor's list entry. All three are somebody asserting THIS
           -- picture is THIS place; the order is how directly.
           ORDER BY cluster_id,
                    CASE source WHEN 'commons_wikidata' THEN 0
                                WHEN 'county_pdf' THEN 1
                                WHEN 'county_page' THEN 2
                                ELSE 3 END, image_id"""
    thumb_re = re.compile(r"/commons/thumb/([0-9a-f]/[0-9a-f]{2})/([^/]+)/(\d+)px-")
    full_re = re.compile(r"/commons/([0-9a-f]/[0-9a-f]{2})/([^/?]+)")
    no_hash = 0
    for (cid, f, author, lic, lic_url, page_url, _src,
         thumb_url, image_url) in c.execute(q):
        got = out.setdefault(cid, [])
        if len(got) >= MAX_PHOTOS:
            continue
        # The percent-encoded token out of the URL, not the display name:
        # re-encoding "Tycho Brahe's ..." on the phone is a second place for
        # the escaping to differ from Commons'.
        m = thumb_re.search(thumb_url or "")
        if m:
            e = {"f": m.group(2), "h": m.group(1), "w": int(m.group(3))}
        else:
            m = full_re.search(thumb_url or image_url or "")
            if not m:
                no_hash += 1
                continue
            e = {"f": m.group(2), "h": m.group(1)}
        # A licence that nobody stated is a licence we cannot honour, so the
        # row travels without one and the UI shows the file name as credit.
        # Same discipline as `sources`: stored, and shown only when known.
        if author:
            e["by"] = author[:120]
        if lic:
            e["lic"] = lic
        if lic_url:
            e["licurl"] = lic_url
        if page_url:
            e["page"] = page_url
        got.append(e)
    c.close()
    n = sum(len(v) for v in out.values())
    extra = f", {no_hash} skipped with no usable URL" if no_hash else ""
    print(f"  {n:,} photographs across {len(out):,} places "
          f"(geosearch excluded; see load_images){extra}")
    return out


def load_ai_descriptions(path):
    """Read the generated visitor descriptions, if any exist yet.

    Optional by design. The file is built by build_descriptions.py over hours
    of local model time and lives outside work.sqlite precisely so the
    pipeline can be rebuilt without it; so this stage has to work whether it
    is there, half-finished, or absent. Whatever is missing falls back to the
    raw register text.

    Rows a check flagged are skipped: a number that could not be traced back
    to the source, or a reach for "mysterious". Not something to ship, and the
    raw Swedish is at least true.

    `dims` (and the older `dim-in-prose`) is exempt. It only records that the
    model put more measurements in the prose than the one the prompt allows,
    when the size is also shown as subtext -- a blemish, not a falsehood, and
    it fires on about a fifth of rows. Treating it as a failure would throw
    away a fifth of good descriptions.

    BOTH names are listed, and that is not tidiness. The flag was renamed
    from the boolean `dim-in-prose` to the counting `dims:N` so the rate
    could be measured, and this set was not updated -- so `dims:3` stripped
    to `dims`, missed the exemption, and 29 perfectly good descriptions
    silently stopped being exported. The old name stays for rows generated
    before the rename.
    """
    cosmetic = {"dim-in-prose", "dims"}
    if not os.path.exists(path):
        return {}
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT cluster_id, title, content, title_en, content_en, flags "
            "FROM ai_descriptions WHERE content <> ''").fetchall()
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()
    out = {}
    for cid, title, content, title_en, content_en, flags in rows:
        real = {f.split(":")[0] for f in (flags or "").split(",") if f} - cosmetic
        if real:
            continue
        out[cid] = {"sv": (title, content), "en": (title_en, content_en)}
    skipped = len(rows) - len(out)
    print(f"  {len(out):,} generated descriptions available"
          + (f", {skipped:,} skipped as flagged" if skipped else ""))
    return out


def write_descriptions(rows, out_dir, shard_chars, max_desc, ai=None,
                       lang="en", dims=None, resolved=None, images=None):
    """Write descriptions as uuid-sharded JSON, outside the tiles.

    Description text was 60% of every tile's bytes: the same export weighs
    16.4 MB with it inline and 6.0 MB without. And it was dead weight -- a
    visitor reads one description per click, but paid for a few hundred of
    them on every tile fetch.

    Sharding on the first `shard_chars` of the uuid gives 256 files of ~26 KB
    for 10,000 clusters. Small enough that a click costs one tiny request,
    numerous enough that no single file is wasteful, and the frontend derives
    the path straight from the uuid it already has -- no manifest to keep in
    sync. They are immutable static files, so the browser caches each shard
    after the first click in its neighbourhood.

    Truncation is off by default now. Inline, 120 characters was the most we
    could afford; out here the full RAA text costs nothing at map load.
    """
    ai = ai or {}
    shards, n_ai = {}, 0
    for r in rows:
        uuid = r["uuid"] or ""
        if not uuid:
            continue
        entry = {}
        got = ai.get(r["cluster_id"])
        if got:
            # Swedish is the canonical text; fall back to it if the English
            # pass has not reached this row yet. Half-translated is fine --
            # every place still has something true to show.
            title, content = got.get(lang) or (None, None)
            if not content:
                title, content = got["sv"]
            # A generated title beats the fallback label, which for an
            # unnamed place is just its class.
            #
            # But a FOLK NAME beats the generated title, and this used to go
            # the other way. The model writes from the register text, so when
            # that text does not repeat the name it writes what it sees:
            #
            #   Frodestenen        -> "Gravfält med 160 fornlämningar"
            #   Kungsbacken        -> "Gravfält med 10 högar"
            #   Blankehög          -> "Hög"
            #
            # 125 of the 1,577 named places in the export lost their name
            # that way, and the map label is the same string, so a stone that
            # people have called Frodestenen for centuries appeared as a
            # count of graves. Where the generated title already contains the
            # name -- 1,452 of 1,577 -- it is richer, so it stays.
            # The generated title is dropped, not kept as a subtitle: the
            # shard schema in sync-assets.sh has six fixed columns and would
            # have discarded a seventh key without a word. What it was
            # carrying -- "160 fornlämningar" -- is in the content text
            # anyway.
            name = (resolved or {}).get(r["cluster_id"]) or r["name"]
            if name and title and name.lower() not in title.lower():
                entry["title"] = name
            elif title:
                entry["title"] = title
            entry["content"] = content
            n_ai += 1
        else:
            text = one_line(r["best_description"], max_desc)
            if not text:
                continue
            entry["content"] = text
            entry["raw"] = True     # untranslated register text, for the UI

        # Size travels as numbers, not prose. dims.py already parsed it out of
        # the Swedish text for 91% of eligible places, so there is no reason to
        # let a model restate it and no reason to bake a language into it --
        # the frontend renders it as subtext in whatever locale it is showing.
        d = (dims or {}).get(r["cluster_id"])
        if d and any(d):
            entry["size"] = {k: v for k, v in
                             zip(("across_m", "high_m", "area_m2"), d) if v}

        # Age is the one thing on a pin that is not derived from the register:
        # K-samsok has no dating field at all and the free text names a period
        # in under 4% of entries. It comes from the reviewed table in
        # periods.py, and `basis` says whether the register stated it or the
        # class implies it, so the UI can hedge accordingly.
        pics = (images or {}).get(r["cluster_id"])
        if pics:
            entry["images"] = pics

        per = period_for(r["dominant_class"], r["best_description"])
        if per:
            entry["period"] = {"text": per[0] if lang == "sv" else per[1],
                               "basis": per[2]}

        shards.setdefault(uuid[:shard_chars].lower(), {})[uuid] = entry

    if os.path.isdir(out_dir):
        for fn in os.listdir(out_dir):
            if fn.endswith(".json"):
                os.remove(os.path.join(out_dir, fn))
    os.makedirs(out_dir, exist_ok=True)
    total = 0
    for key, payload in shards.items():
        path = os.path.join(out_dir, f"{key}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        total += os.path.getsize(path)
    n = sum(len(v) for v in shards.values())
    print(f"  {n:,} descriptions in {len(shards)} shards "
          f"({n_ai:,} generated, {n - n_ai:,} raw register text), "
          f"{total/1e6:.1f} MB total, {total/max(len(shards),1)/1024:.0f} KB "
          f"each -> {out_dir}")


def write_families(rows, path):
    """Emit the filter families, their classes, and live counts.

    The frontend used to hard-code 19 class names. Four of them were not in
    the export at all, so those checkboxes did nothing, while 82 classes fell
    into a single "Other" bucket -- including Fornborg, which is 813 clusters.
    Generated from the export, the list cannot drift from the data.

    Each family also carries the classes actually present inside it, best
    represented first, which is what the app's nested checkboxes offer once a
    family is opened. Only classes with at least one cluster in the export
    appear: a checkbox that can never match anything is worse than no
    checkbox, which is the exact bug the hard-coded list had.

    Family display names are deliberately NOT here: only the id ships, and
    each frontend resolves it (the app through its own sv.json, the web demo
    through a table next to its page). This file used to carry the English
    string from FAMILY_LABEL, which quietly made the pipeline the owner of UI
    copy in one language -- so the app could not be translated without
    regenerating data, and a text change meant re-running an export.

    Class names are different and DO ship: `class_sv` is the register's own
    term for the thing, not a phrase we wrote. Translating those is a data
    problem, not a formatting one, and there is no English column to fall back
    on.
    """
    # Counted once per star threshold, not once overall.
    #
    # A count next to a checkbox exists so you can tell a filter that will
    # empty the map from one that will not, and a count that ignores the star
    # threshold does the opposite: "Kust och sjofart 22" with a 4-star
    # threshold on, when four survive it, is worse than no number at all.
    #
    # Five numbers rather than a live recount, because a site has exactly one
    # class -- so choosing other families cannot change this family's count,
    # and the star threshold is the only filter that crosses. That makes the
    # whole cross-product five columns wide, which is a few kilobytes and no
    # runtime cost, instead of parsing 2.3 MB in the app to recount on every
    # tap.
    #
    # counts[i] is the number surviving `stars >= i + 1`, so counts[0] is the
    # unfiltered total.
    def empty():
        return [0, 0, 0, 0, 0]

    n_rows = len(rows)
    fam_counts, cls_counts = {}, {}
    for i, r in enumerate(rows):
        cls = r["dominant_class"] or ""
        fam = FAMILY.get(cls, "misc")
        stars = stars_for(round(100.0 * (n_rows - i) / n_rows, 2))
        fc = fam_counts.setdefault(fam, empty())
        cc = cls_counts.setdefault(fam, {}).setdefault(cls, empty()) if cls else None
        for k in range(stars):
            fc[k] += 1
            if cc is not None:
                cc[k] += 1
    present = [f for f in FAMILY_ORDER if fam_counts.get(f, empty())[0]]

    def js(value):
        return json.dumps(value, ensure_ascii=False)

    blocks = []
    for f in present:
        # Descending count, then name, so the order is stable across runs
        # even when two classes tie.
        classes = sorted(cls_counts.get(f, {}).items(),
                         key=lambda kv: (-kv[1][0], kv[0]))
        inner = "".join(
            f"      {{ id: {js(c)}, counts: {js(n)} }},\n" for c, n in classes)
        blocks.append(
            f"  {{\n"
            f"    id: {js(f)},\n"
            f"    icon: {js(FAMILY_ICON[f])},\n"
            f"    counts: {js(fam_counts[f])},\n"
            f"    classes: [\n{inner}    ],\n"
            f"  }},")

    with open(path, "w", encoding="utf-8") as f:
        f.write("// GENERATED by build_tiles.py -- do not edit by hand.\n"
                "// Families present in the exported tiles, with the classes\n"
                "// inside each and their cluster counts.\n"
                "//\n"
                "// The family is the unit the exporter thins by, which is\n"
                "// what makes hiding a family backfill instead of leaving\n"
                "// holes. Narrowing to individual classes is finer than that\n"
                "// and has to re-thin on the device; see thinning.ts.\n"
                "export type FilterClass = {\n"
                "  /** The register's own Swedish class name, used as label. */\n"
                "  id: string;\n"
                "  /** counts[i] survives `stars >= i + 1`; [0] is the total. */\n"
                "  counts: number[];\n"
                "};\n\n"
                "export type FilterFamily = {\n"
                "  /** Resolve to a display name in the frontend, not here. */\n"
                "  id: string;\n"
                "  /** Glyph name; served as "
                "/fornlamningar-icons/svg/<icon>.svg */\n"
                "  icon: string;\n"
                "  /** counts[i] survives `stars >= i + 1`; [0] is the total. */\n"
                "  counts: number[];\n"
                "  /** Present in the export, best represented first. */\n"
                "  classes: FilterClass[];\n"
                "};\n\n"
                "export const FILTER_FAMILIES: FilterFamily[] = [\n"
                + "\n".join(blocks) + "\n];\n\n"
                "export const ALL_FAMILY_IDS = FILTER_FAMILIES.map(f => f.id);\n")
    n_cls = sum(len(cls_counts.get(f, {})) for f in present)
    print(f"  {len(present)} filter families, {n_cls} classes -> {path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=DB)
    p.add_argument("--out", default=DEFAULT_OUT, help="tile output directory")
    p.add_argument("--geojson", default=GEOJSON)
    # FULL BY DEFAULT since 2026-09-18. It used to be intrinsic, on the
    # argument that crediting documentation cannot find the undocumented --
    # which is true and was answered by measuring rather than by choosing:
    # against `county excluding wikidata`, the one label set with no overlap
    # with those fields, full beats intrinsic 0.7781 to 0.7343. That number
    # only became trustworthy once score_full stopped being a naive sum of
    # correlated log-lifts; see the long note in build_scores.py.
    #
    # intrinsic is still emitted and is still the honest discovery score. Pass
    # --score intrinsic to export it.
    p.add_argument("--score", choices=("intrinsic", "full"), default="full",
                   help="full = credits Wikipedia, photos, OSM and visitor "
                        "confirmation, decorrelated (default); "
                        "intrinsic = discovery only, ignores documentation")
    p.add_argument("--max-desc", type=int, default=0,
                   help="truncate descriptions; 0 keeps the full RAA text. "
                        "These now ship OUTSIDE the tiles, so there is no "
                        "reason to truncate unless you want shorter popups")
    p.add_argument("--desc-out", default=DEFAULT_DESC_OUT,
                   help="directory for the sharded description files")
    p.add_argument("--ai-db", default=AI_DB,
                   help="generated visitor descriptions; used when present")
    p.add_argument("--no-ai-desc", action="store_true",
                   help="ignore the generated descriptions and ship the raw "
                        "RAA text for everything")
    p.add_argument("--lang", choices=("en", "sv"), default="sv",
                   help="which generated text to ship; Swedish is canonical "
                        "and is used as the fallback either way")
    # The DEFAULT is what ships, so it has to be the language the app is in.
    # run_pipeline.sh does not pass --lang, so leaving this at "en" meant any
    # full rebuild would quietly switch the app back to English -- the same
    # trap that made build_scores.py refit with the worse model for a while.
    # Swedish is also the canonical text: it is what the model wrote from the
    # source, with no translation pass in between to go wrong.
    p.add_argument("--desc-shard-chars", type=int, default=2,
                   help="uuid prefix length used as the shard key; 2 gives "
                        "256 shards")
    p.add_argument("--groups-out", default=DEFAULT_GROUPS_OUT,
                   help="TS file listing the filter families and their counts")
    p.add_argument("--include-excluded", action="store_true",
                   help="also emit blacklisted / soft-excluded clusters")
    p.add_argument("--min-score", type=float, default=None,
                   help="drop clusters below this raw score")
    p.add_argument("--top", type=int, default=None,
                   help="keep only the N best-scoring clusters. Ranking happens "
                        "over ALL clusters first, so the cut is national, not "
                        "per-region")
    p.add_argument("--maxzoom", type=int, default=14,
                   help="must match the -z in TIPPECANOE_OPTS")
    p.add_argument("--cells-per-tile", type=int, default=CELLS_PER_TILE,
                   help="thinning grid resolution; higher = denser low zooms")
    p.add_argument("--keep-geojson", action="store_true")
    p.add_argument("--skip-tippecanoe", action="store_true")
    args = p.parse_args()

    if not os.path.exists(args.db):
        sys.exit(f"missing {args.db} - run ./run_pipeline.sh first")
    if not args.skip_tippecanoe and not shutil.which("tippecanoe"):
        sys.exit("tippecanoe not found (brew install tippecanoe)")

    score_col = f"sc.score_{args.score}"
    where = ["c.lon IS NOT NULL"]
    if not args.include_excluded:
        where += ["sc.excluded_hard = 0", "sc.excluded_soft = 0"]
    if args.min_score is not None:
        where.append(f"{score_col} >= {args.min_score}")

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"""
        SELECT c.cluster_id, c.name, c.dominant_class, c.n_sites,
               c.lon, c.lat, c.best_description,
               {score_col} AS score,
               -- The representative site, READ rather than recomputed.
               -- build_clusters.py decides it once and stores it; this used
               -- to be a copy of that ORDER BY, which is how three other
               -- copies of the same rule came to disagree.
               c.rep_uuid AS uuid
        FROM clusters c
        JOIN scores sc ON sc.cluster_id = c.cluster_id
        WHERE {' AND '.join(where)}
        ORDER BY {score_col} DESC
        {f'LIMIT {args.top}' if args.top else ''}
    """).fetchall()
    conn.close()

    if not rows:
        sys.exit("no clusters matched the filters")
    orphans = sorted({r["dominant_class"] for r in rows
                      if r["dominant_class"] and r["dominant_class"] not in FAMILY})
    if orphans:
        sys.exit(f"classes with no family in families.py: {orphans}")
    n = len(rows)
    print(f"exporting {n:,} clusters"
          + (f" (top {args.top:,})" if args.top else "")
          + f" (score_{args.score}, desc limit {args.max_desc or 'none'})")
    if args.top:
        print(f"  score range kept: {rows[0]['score']:.2f} .. {rows[-1]['score']:.2f}")

    minzoom = assign_minzoom_by_family(rows, args.maxzoom,
                                       args.cells_per_tile)
    hist = {}
    for z in minzoom:
        hist[z] = hist.get(z, 0) + 1
    cum = 0
    shown = []
    for z in sorted(hist):
        cum += hist[z]
        shown.append(f"z{z}:{cum:,}")
    print("  visible by zoom (cumulative): " + "  ".join(shown))
    star_hist = {}
    for i in range(n):
        s = stars_for(round(100.0 * (n - i) / n, 2))
        star_hist[s] = star_hist.get(s, 0) + 1
    print("  stars: " + "  ".join(f"{s}*:{star_hist.get(s, 0):,}"
                                  for s in (5, 4, 3, 2, 1)))

    os.makedirs(os.path.dirname(args.geojson) or ".", exist_ok=True)
    t0 = time.time()
    named = 0
    with open(args.geojson, "w", encoding="utf-8") as f:
        for i, r in enumerate(rows):
            cls = r["dominant_class"] or ""
            pct = round(100.0 * (n - i) / n, 2)
            if r["name"]:
                label = r["name"]
                named += 1
            elif (r["n_sites"] or 1) > 1:
                label = f"{cls} ({r['n_sites']})"   # e.g. "Gravfalt (12)"
            else:
                label = cls or "Fornlamning"
            f.write(json.dumps({
                "type": "Feature",
                "geometry": {"type": "Point",
                             "coordinates": [round(r["lon"], 6),
                                             round(r["lat"], 6)]},
                "properties": {
                    "uuid": r["uuid"] or "",
                    "label": label,
                    "class": cls,
                    # The filter granularity has to match the thinning
                    # granularity, so ship the family rather than making the
                    # frontend expand 153 class names back into groups.
                    "family": FAMILY.get(cls, "misc"),
                    # Percentile, best-first. Ordering is all the frontend
                    # uses it for (symbol-sort-key).
                    "score": pct,
                    # The same percentile bucketed for display and filtering.
                    # Derived here rather than in the app so that "5 stars"
                    # means the same thing everywhere, and so the app never
                    # sees the raw score it would be tempted to render.
                    "stars": stars_for(pct),
                },
                "tippecanoe": {"minzoom": minzoom[i]},
            }, ensure_ascii=False) + "\n")
    gj = os.path.getsize(args.geojson) / 1e6
    print(f"  geojsonl {gj:.1f} MB, {named:,} with a folk name "
          f"({time.time()-t0:.0f}s)")

    ai = {} if args.no_ai_desc else load_ai_descriptions(args.ai_db)
    write_descriptions(rows, args.desc_out, args.desc_shard_chars,
                       args.max_desc, ai, args.lang, load_dims(args.db, rows),
                       load_resolved_names(args.db, paths.WIKIMEDIA),
                       load_images(paths.PLACES))
    write_families(rows, args.groups_out)

    if args.skip_tippecanoe:
        print(f"  kept {args.geojson}")
        return

    out = os.path.expanduser(args.out)
    os.makedirs(out, exist_ok=True)
    cmd = ["tippecanoe", *TIPPECANOE_OPTS, "-l", LAYER, "-e", out, args.geojson]
    print("  " + " ".join(cmd))
    subprocess.run(cmd, check=True)

    total = sum(os.path.getsize(os.path.join(d, fn))
                for d, _, fs in os.walk(out) for fn in fs)
    tiles = sum(len([f for f in fs if f.endswith(".pbf")])
                for _, _, fs in os.walk(out))
    print(f"\n{tiles:,} tiles, {total/1e6:.1f} MB -> {out}")
    # The web app pins the tile URL with a cache-busting query parameter, and
    # NOTHING updates it -- it is a hand edit in page.tsx that was sitting
    # uncommitted at v=16 while the committed value was v=13. Ship tiles
    # without bumping it and every returning browser serves the old ones,
    # which looks like the build not having worked. Printed rather than
    # patched: having the data pipeline rewrite the app's source is the kind
    # of coupling that breaks the day someone reformats that line.
    print("   REMEMBER: bump ?v=N on the tiles URL in "
          "franco-may/app/fornlamningar/page.tsx, or browsers keep the "
          "old tiles")
    if not args.keep_geojson:
        os.remove(args.geojson)


if __name__ == "__main__":
    main()
