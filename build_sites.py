#!/usr/bin/env python3
"""
Stage 1 + 2: turn the raw K-samsok JSON cache and the GeoPackage into one
structured `sites` table, one row per UUID.

Reads (both read-only, safe to run while the crawler is still working):
    src/data/ksamsok_raw.sqlite      parsed for descriptions and metadata
    src/data/fornlamningar_full.gpkg parsed for geometry across all three layers

Writes:
    src/data/sites.sqlite

This is a full rebuild rather than an incremental job: parsing is cheap because
the expensive network stage is already cached, so correctness beats resumability
here. Re-run it freely whenever the parser changes or the crawl advances.

Usage:
    python build_sites.py                 # full rebuild
    python build_sites.py --limit 5000    # quick pass while iterating
    python build_sites.py --progress-json # emit JSONL progress for the runner UI
"""

import argparse
import json
import os
import re
import sqlite3
import struct
import sys
import time
import zlib

from dims import parse_dims

import paths

RAW_DB = paths.RAA_API
GPKG = paths.RAA_EXPORT
OUT_DB = paths.WORK

LAYERS = {
    "PS_NationalMonuments_point": "P",
    "PS_NationalMonuments_line": "L",
    "PS_NationalMonuments_poly": "A",
}

# Appended by RAA to descriptions that carry no real content of their own.
BOILERPLATE = (
    "Beskrivningen är inte kvalitetssäkrad. Information kan saknas, "
    "vara felaktig eller inaktuell. Se även Inventeringsbok."
)

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
GML_COORD_RE = re.compile(r">\s*([-\d.]+)\s*,\s*([-\d.]+)\s*<")
# A description is "substantive" if it states a measurement.
MEASURE_RE = re.compile(r"\d+([.,]\d+)?\s*(m|cm|meter)\b", re.I)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def value_of(node):
    """Scalar for a JSON-LD value.

    Values arrive as {"@value": x}, {"@id": x}, a bare literal, or a *list* of
    any of those -- e.g. a site with several itemKeywords. Lists are joined so
    every field stays bindable as a single SQLite column.
    """
    if isinstance(node, list):
        parts = [value_of(x) for x in node]
        parts = [str(p) for p in parts if p is not None]
        return "; ".join(dict.fromkeys(parts)) or None
    if isinstance(node, dict):
        return node.get("@value") or node.get("@id")
    return node


def code_of(node):
    """Trailing authority code from a URI: .../municipality#1480 -> '1480'."""
    v = value_of(node)
    if not v:
        return None
    return v.rsplit("#", 1)[-1] if "#" in v else v.rsplit("/", 1)[-1]


def as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


# --------------------------------------------------------------------------- #
# stage 1: parse one K-samsok response
# --------------------------------------------------------------------------- #

def parse_response(body: str) -> dict:
    """Flatten one JSON-LD graph into a single dict of scalar fields."""
    graph = json.loads(body)["@graph"]

    # Rule: locate nodes by @type. Node order is NOT stable across responses.
    entity = next((n for n in graph if n.get("@type") == "ksam:Entity"), None)
    context = next((n for n in graph if n.get("@type") == "ksam:Context"), None)

    # Typed sub-nodes, keyed by their ksam:type discriminator. Note ksam:type is
    # {"@language": "sv", "@value": "Placering"} -- read @value, not @id.
    desc, spec, number, name = {}, {}, {}, {}
    for n in graph:
        t = n.get("@type")
        key = value_of(n.get("ksam:type"))
        if not key:
            continue
        if t == "ksam:ItemDescription":
            desc.setdefault(key, value_of(n.get("ksam:desc")))
        elif t == "ksam:ItemSpecification":
            spec.setdefault(key, value_of(n.get("ksam:spec")))
        elif t == "ksam:ItemNumber":
            number.setdefault(key, value_of(n.get("ksam:number")))
        elif t == "ksam:ItemName":
            name.setdefault(key, value_of(n.get("ksam:name")))

    # WGS84 coordinates, from the GML embedded in the Context (or the root).
    lon = lat = None
    for n in graph:
        raw = n.get("ksam:coordinates") or n.get("ksam:presentation")
        if not raw:
            continue
        m = GML_COORD_RE.search(str(value_of(raw)))
        if m:
            lon, lat = float(m.group(1)), float(m.group(2))
            break

    beskrivning = (desc.get("Beskrivning") or "").strip()
    stripped = beskrivning.replace(BOILERPLATE, "").strip()
    dims = parse_dims(stripped)
    raa = number.get("RAÄ-nummer")

    e = entity or {}
    c = context or {}
    return {
        # identity
        "inspireid": None,  # filled from the GeoPackage
        "lamningsnummer": number.get("Lämningsnummer"),
        "raa_number": raa,
        # RAA-nummer prefix groups sub-parts of one site: "Askim 268:2" -> "Askim 268"
        "raa_group": raa.rsplit(":", 1)[0] if raa and ":" in raa else raa,
        "url": f"https://app.raa.se/open/fornsok/lamning/{{uuid}}",
        # classification
        "class_sv": value_of(e.get("ksam:itemClassName")) or name.get("Lämningstyp"),
        "item_super_type": code_of(e.get("ksam:itemSuperType")),
        "subjects": ",".join(
            sorted(filter(None, (code_of(s) for s in as_list(e.get("ksam:subject")))))
        )
        or None,
        # descriptions
        "beskrivning": stripped or None,
        "beskrivning_is_boilerplate": 1 if (beskrivning and not stripped) else 0,
        "has_measurements": 1 if MEASURE_RE.search(stripped) else 0,
        "description_len": len(stripped),
        # Physical size, parsed out of the Swedish text. Size is what separates
        # an 18 m rose from a 1.3 m stone with one groove -- both are the same
        # class_sv, and the labels cannot tell them apart without this.
        "dim_len_m": dims[0],
        "dim_height_m": dims[1],
        "dim_area_m2": dims[2],
        "skadestatus": desc.get("Skadestatus"),
        "placering": desc.get("Placering"),
        "undersokningsstatus": desc.get("Undersökningsstatus"),
        "terrang": desc.get("Terräng"),
        "orientering": desc.get("Orientering"),
        "referens": desc.get("Referens"),
        # assessment
        "antikvarisk_bedomning": spec.get("Antikvarisk bedömning"),
        "aktualitetsstatus": spec.get("Aktualitetsstatus"),
        # naming
        "title": value_of(e.get("ksam:itemTitle")),
        "keyword": value_of(e.get("ksam:itemKeyword")),
        # geography: separate columns plus stable authority codes
        "parish": value_of(c.get("ksam:parishName")),
        "parish_code": code_of(c.get("ksam:parish")),
        "municipality": value_of(c.get("ksam:municipalityName")),
        "municipality_code": code_of(c.get("ksam:municipality")),
        "county": value_of(c.get("ksam:countyName")),
        "county_code": code_of(c.get("ksam:county")),
        "province": value_of(c.get("ksam:provinceName")),
        "province_code": code_of(c.get("ksam:province")),
        # API coordinates (WGS84)
        "lon": lon,
        "lat": lat,
        # provenance
        "build_date": value_of(e.get("ksam:buildDate")),
        "last_changed": value_of(e.get("ksam:lastChangedDate"))
        or value_of(e.get("ksam:lastChanged")),
        "data_quality": code_of(e.get("ksam:dataQuality")),
        "organization": value_of(e.get("ksam:serviceOrganization")),
    }


# --------------------------------------------------------------------------- #
# stage 2: geometry from the GeoPackage
# --------------------------------------------------------------------------- #

def gpkg_envelope(blob):
    """(minx, maxx, miny, maxy) from a GeoPackage geometry header, or None.

    Header: magic(2) version(1) flags(1) srs_id(4) then the envelope. Bits 1-3
    of the flags byte give the envelope type; 1 means four doubles (XY).
    """
    if len(blob) < 8:
        return None
    env_type = (blob[3] >> 1) & 0x07
    if env_type != 1 or len(blob) < 40:
        return None
    return struct.unpack("<4d", blob[8:40])


def gpkg_point(blob):
    """(x, y) for a header-plus-WKB point with no envelope, else None."""
    env_type = (blob[3] >> 1) & 0x07
    if env_type != 0 or len(blob) < 29:
        return None
    # WKB: byte order(1) type(4) x(8) y(8)
    order = "<" if blob[8] == 1 else ">"
    wkb_type = struct.unpack(order + "I", blob[9:13])[0]
    if wkb_type != 1:
        return None
    return struct.unpack(order + "2d", blob[13:29])


def load_geometry(gpkg_path):
    """uuid -> geometry summary, merged across all three layers."""
    src = sqlite3.connect(f"file:{gpkg_path}?mode=ro", uri=True)
    geo = {}
    for layer, tag in LAYERS.items():
        sql = (
            f'SELECT inspireid, legalfoundationdocument, geom FROM "{layer}" '
            "WHERE legalfoundationdocument IS NOT NULL"
        )
        for inspireid, doc, blob in src.execute(sql):
            m = UUID_RE.search(doc or "")
            if not m:
                continue
            uuid = m.group(0)
            g = geo.setdefault(
                uuid,
                {
                    "inspireid": inspireid,
                    "layers": set(),
                    "e": None,
                    "n": None,
                    "w": None,
                    "h": None,
                },
            )
            g["layers"].add(tag)
            # Prefer the point layer's own coordinates for the centroid.
            if tag == "P":
                g["inspireid"] = inspireid
                pt = gpkg_point(blob) if blob else None
                if pt:
                    g["e"], g["n"] = pt
            env = gpkg_envelope(blob) if blob else None
            if env:
                minx, maxx, miny, maxy = env
                g["w"], g["h"] = maxx - minx, maxy - miny
                if g["e"] is None:
                    g["e"], g["n"] = (minx + maxx) / 2, (miny + maxy) / 2
    src.close()
    return geo


# --------------------------------------------------------------------------- #
# output schema
# --------------------------------------------------------------------------- #

SCHEMA = """
DROP TABLE IF EXISTS sites;
CREATE TABLE sites (
    uuid TEXT PRIMARY KEY,
    inspireid TEXT, lamningsnummer TEXT, raa_number TEXT, raa_group TEXT, url TEXT,
    class_sv TEXT, item_super_type TEXT, subjects TEXT,
    beskrivning TEXT, beskrivning_is_boilerplate INTEGER,
    has_measurements INTEGER, description_len INTEGER,
    dim_len_m REAL, dim_height_m REAL, dim_area_m2 REAL,
    skadestatus TEXT, placering TEXT, undersokningsstatus TEXT,
    terrang TEXT, orientering TEXT, referens TEXT,
    antikvarisk_bedomning TEXT, aktualitetsstatus TEXT,
    title TEXT, keyword TEXT, has_name INTEGER,
    parish TEXT, parish_code TEXT, municipality TEXT, municipality_code TEXT,
    county TEXT, county_code TEXT, province TEXT, province_code TEXT,
    lon REAL, lat REAL,
    has_point INTEGER, has_line INTEGER, has_polygon INTEGER,
    geom_types TEXT, geom_type_count INTEGER,
    centroid_e REAL, centroid_n REAL,
    env_width_m REAL, env_height_m REAL, env_area_m2 REAL,
    build_date TEXT, last_changed TEXT, data_quality TEXT, organization TEXT
);
"""

INDEXES = """
CREATE INDEX idx_sites_class      ON sites(class_sv);
CREATE INDEX idx_sites_raa_group  ON sites(raa_group);
CREATE INDEX idx_sites_placering  ON sites(placering);
CREATE INDEX idx_sites_lonlat     ON sites(lon, lat);
CREATE INDEX idx_sites_geom       ON sites(geom_types);
CREATE INDEX idx_sites_muni       ON sites(municipality_code);
"""

COLUMNS = [
    "uuid", "inspireid", "lamningsnummer", "raa_number", "raa_group", "url",
    "class_sv", "item_super_type", "subjects", "beskrivning",
    "beskrivning_is_boilerplate", "has_measurements", "description_len",
    "dim_len_m", "dim_height_m", "dim_area_m2",
    "skadestatus", "placering", "undersokningsstatus", "terrang", "orientering",
    "referens", "antikvarisk_bedomning", "aktualitetsstatus", "title", "keyword",
    "has_name", "parish", "parish_code", "municipality", "municipality_code",
    "county", "county_code", "province", "province_code", "lon", "lat",
    "has_point", "has_line", "has_polygon", "geom_types", "geom_type_count",
    "centroid_e", "centroid_n", "env_width_m", "env_height_m", "env_area_m2",
    "build_date", "last_changed", "data_quality", "organization",
]


def emit(as_json, **kw):
    if as_json:
        sys.stdout.write(json.dumps(kw) + "\n")
        sys.stdout.flush()
    else:
        msg = kw.get("message")
        if msg:
            print(msg)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, help="parse only N responses (for iteration)")
    p.add_argument("--raw", default=RAW_DB)
    p.add_argument("--gpkg", default=GPKG)
    p.add_argument("--out", default=OUT_DB)
    p.add_argument("--progress-json", action="store_true",
                   help="emit JSONL progress events on stdout")
    args = p.parse_args()
    J = args.progress_json

    for path in (args.raw, args.gpkg):
        if not os.path.exists(path):
            sys.exit(f"missing input: {path}")

    emit(J, event="stage", name="geometry", message="Loading geometry from GeoPackage...")
    t0 = time.time()
    geo = load_geometry(args.gpkg)
    emit(J, event="done", name="geometry", count=len(geo),
         message=f"  {len(geo):,} UUIDs with geometry in {time.time()-t0:.0f}s")

    raw = sqlite3.connect(f"file:{args.raw}?mode=ro", uri=True)
    total = raw.execute(
        "SELECT COUNT(*) FROM responses WHERE raw_json IS NOT NULL"
    ).fetchone()[0]
    if args.limit:
        total = min(total, args.limit)

    out = sqlite3.connect(args.out)
    out.execute("PRAGMA journal_mode=WAL")
    out.executescript(SCHEMA)

    emit(J, event="stage", name="parse", total=total,
         message=f"Parsing {total:,} cached responses...")

    sql = "SELECT uuid, raw_json, compression FROM responses WHERE raw_json IS NOT NULL"
    if args.limit:
        sql += f" LIMIT {args.limit}"

    batch, done, failed = [], 0, 0
    t0 = time.time()
    ins = f"INSERT OR REPLACE INTO sites ({','.join(COLUMNS)}) VALUES ({','.join('?'*len(COLUMNS))})"

    for uuid, blob, comp in raw.execute(sql):
        done += 1
        try:
            body = zlib.decompress(blob).decode("utf-8") if comp == "zlib" else (
                blob if isinstance(blob, str) else blob.decode("utf-8")
            )
            rec = parse_response(body)
        except Exception as exc:  # a malformed response must not kill the run
            failed += 1
            if failed <= 5:
                emit(J, event="warn", uuid=uuid, error=str(exc),
                     message=f"  ! {uuid}: {exc}")
            continue

        rec["url"] = rec["url"].format(uuid=uuid)
        rec["has_name"] = 1 if (rec["title"] or rec["keyword"]) else 0

        g = geo.get(uuid)
        if g:
            L = g["layers"]
            rec["inspireid"] = g["inspireid"]
            rec["has_point"] = int("P" in L)
            rec["has_line"] = int("L" in L)
            rec["has_polygon"] = int("A" in L)
            rec["geom_types"] = "".join(sorted(L))
            rec["geom_type_count"] = len(L)
            rec["centroid_e"], rec["centroid_n"] = g["e"], g["n"]
            rec["env_width_m"], rec["env_height_m"] = g["w"], g["h"]
            rec["env_area_m2"] = (g["w"] * g["h"]) if g["w"] and g["h"] else None
        else:
            for k in ("has_point", "has_line", "has_polygon", "geom_type_count"):
                rec[k] = 0
            for k in ("geom_types", "centroid_e", "centroid_n",
                      "env_width_m", "env_height_m", "env_area_m2"):
                rec[k] = None

        batch.append(tuple([uuid] + [rec[c] for c in COLUMNS[1:]]))
        if len(batch) >= 2000:
            with out:
                out.executemany(ins, batch)
            batch.clear()
            emit(J, event="progress", done=done, total=total,
                 rate=round(done / max(time.time() - t0, 1e-3), 1))
            if not J:
                sys.stderr.write(f"\r  {done:,}/{total:,}  "
                                 f"{done/max(time.time()-t0,1e-3):.0f}/s   ")
                sys.stderr.flush()

    if batch:
        with out:
            out.executemany(ins, batch)
    if not J:
        sys.stderr.write("\n")

    out.executescript(INDEXES)
    out.commit()

    n = out.execute("SELECT COUNT(*) FROM sites").fetchone()[0]
    emit(J, event="done", name="parse", rows=n, failed=failed,
         seconds=round(time.time() - t0, 1),
         message=f"Wrote {n:,} rows to {args.out} in {time.time()-t0:.0f}s "
                 f"({failed} unparseable)")
    out.close()


if __name__ == "__main__":
    main()
