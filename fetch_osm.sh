#!/usr/bin/env bash
# Build the OSM inputs that stage 4 (build_signals.py) needs.
#
# These live under src/data/osm/ and are gitignored: together they are ~2.3 GB,
# and unlike hand labels they are fully reproducible -- which was only true in
# principle until this script existed. The extractions used to be ad-hoc
# ogr2ogr invocations typed at a shell, so a fresh clone could not rebuild
# them. Reconstructed here from the layer schemas of the files they produced.
#
# Needs: gdal (brew install gdal). If ogr2ogr segfaults, the usual culprit is
# a broken abseil/re2: `brew reinstall re2 abseil`.
#
# Note on the source host: geofabrik is unreachable from behind some proxies,
# so this pulls from download.openstreetmap.fr, which serves the same extract.
#
# Everything is reprojected to EPSG:3006 (SWEREF99 TM) because build_signals
# does all its distance work in projected metres.
#
# Usage:
#   ./fetch_osm.sh            # download if absent, then extract what is missing
#   ./fetch_osm.sh --force    # re-extract even if the .gpkg already exists

set -euo pipefail

DIR="src/data/osm"
PBF="$DIR/sweden-latest.osm.pbf"
URL="https://download.openstreetmap.fr/extracts/europe/sweden-latest.osm.pbf"
FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

command -v ogr2ogr >/dev/null || { echo "ogr2ogr not found (brew install gdal)" >&2; exit 1; }
mkdir -p "$DIR"

if [[ ! -s "$PBF" ]]; then
  echo "── downloading Sweden extract (~900 MB)"
  curl -fL --retry 3 -o "$PBF.part" "$URL"
  mv "$PBF.part" "$PBF"
fi
echo "pbf: $(du -h "$PBF" | cut -f1)"

# out | osm layer | -nln | -select | -where
# `tourism` and `historic` are not promoted to columns by GDAL's default
# osmconf.ini, so they can only be matched inside the other_tags hstore.
extract() {
  local out="$DIR/$1.gpkg"; shift
  local layer="$1"; shift
  local nln="$1"; shift
  local sel="$1"; shift
  local where="$1"; shift
  if [[ -s "$out" && $FORCE -eq 0 ]]; then
    echo "── $out exists, skipping (--force to rebuild)"
    return
  fi
  echo "── $out  ($layer where $where)"
  rm -f "$out"
  ogr2ogr -f GPKG "$out" "$PBF" "$layer" \
    -nln "$nln" -t_srs EPSG:3006 -select "$sel" -where "$where" \
    -progress -oo INTERLEAVED_READING=YES
}

extract sweden_ways   lines         ways   osm_id,highway,name 'highway IS NOT NULL'
extract buildings     multipolygons b      osm_id,building     'building IS NOT NULL'
# tourism=information alone yields 14,818 -- it includes route markers, maps
# and guideposts. The conjunction with information=board gives exactly the
# 7,018 features the pipeline was measured on (verified: identical osm_ids).
extract boards        points        boards osm_id,name,other_tags \
  'other_tags LIKE '"'"'%"tourism"=>"information"%'"'"' AND other_tags LIKE '"'"'%"information"=>"board"%'"'"''
# Matching only the bare `historic` key misses 1,039 of the 8,258 points the
# pipeline was measured on: sub-keys (historic:power, historic:railway),
# `archaeological_site` standing on its own, and attractions carrying a
# lifecycle prefix (abandoned:tourism, was:tourism). The three clauses below
# reproduce all five layers exactly -- verified osm_id for osm_id.
HIST="other_tags LIKE '%historic%'
   OR other_tags LIKE '%archaeological_site%'
   OR other_tags LIKE '%tourism%=>%attraction%'"

extract historic_pt   points        feat   osm_id,name,other_tags "$HIST"
extract historic_poly multipolygons feat   osm_id,name,other_tags "$HIST"

# Points of interest that turned out to predict a visit, and the measurement
# that chose them. ADDED 2026-09-21 after sweeping every `key=value` in these
# eight OSM keys (722 of them, 678k points) against Franco's own visits.
#
# The crude table was topped by amenity=ice_cream (26.7x), bar (25.2x), pub
# (24.6x), cinema, taxi, clock, bank, dentist and driving_school. None of
# those makes a grave field worth the trip: they mark a TOWN. And the labels
# are Franco's visits, which are themselves biased toward towns, roads and
# whatever Google has heard of -- so any tag that merely co-occurs with
# urbanity inherits that bias whole and would have been shipped as insight.
#
# So the lifts below are stratified on building density (OSM's 3.9M building
# polygons, independent of every tag being tested) and pooled with
# Mantel-Haenszel. The adjustment splits the table cleanly in two: the town
# markers lose 3.3-4.2x of their lift, and these keep theirs.
#
#   tag                      adjusted   crude   shrink   clusters
#   historic=stone              13.3    20.0     1.5x        124
#   historic=ruins               9.0    13.5     1.5x        946
#   historic=memorial            8.5    17.0     2.0x      1,395
#   historic=rune_stone          8.2    15.4     1.9x      1,373
#   historic=mine                7.8     8.1     1.0x         97
#   historic=monument            7.7    18.0     2.3x        385
#   historic=tomb                6.5    11.9     1.8x        197
#   natural=cave_entrance        6.0     7.2     1.2x        252
#   natural=spring               5.9     7.2     1.2x        417
#   tourism=viewpoint            4.9     8.3     1.7x      2,323
#   information=board            4.9     7.4     1.5x      6,686   (already used)
#   leisure=picnic_table         3.5     6.5     1.9x      5,639
#   amenity=bench                3.6     6.5     1.8x      7,880
#
# The three near-1.0 shrinks are the interesting ones: a mine, a cave mouth
# and a spring are rural, so there was nothing for the control to remove.
#
# They go in ONE layer with a `kind` column rather than one file per family,
# because build_signals wants one grid per family and the families will be
# retuned; a new file per experiment is how a data directory rots.
POI="other_tags LIKE '%\"historic\"=>\"memorial\"%'
  OR other_tags LIKE '%\"historic\"=>\"monument\"%'
  OR other_tags LIKE '%\"historic\"=>\"stone\"%'
  OR other_tags LIKE '%\"historic\"=>\"rune_stone\"%'
  OR other_tags LIKE '%\"historic\"=>\"tomb\"%'
  OR other_tags LIKE '%\"historic\"=>\"ruins\"%'
  OR other_tags LIKE '%\"historic\"=>\"mine\"%'
  OR other_tags LIKE '%\"historic\"=>\"wayside_cross\"%'
  OR other_tags LIKE '%\"natural\"=>\"cave_entrance\"%'
  OR other_tags LIKE '%\"natural\"=>\"spring\"%'
  OR other_tags LIKE '%\"tourism\"=>\"viewpoint\"%'
  OR other_tags LIKE '%\"tourism\"=>\"picnic_site\"%'
  OR other_tags LIKE '%\"leisure\"=>\"picnic_table\"%'
  OR other_tags LIKE '%\"leisure\"=>\"firepit\"%'
  OR other_tags LIKE '%\"amenity\"=>\"bench\"%'
  OR other_tags LIKE '%\"amenity\"=>\"shelter\"%'"

extract osm_poi       points        poi    osm_id,name,other_tags "$POI"

# Parking. Franco asked whether it is worth having, and the honest answer is
# that we do not know yet -- but we can find out, and the wrong source was
# already tried once: Trafikverket's `Rastplatser` are motorway rest areas
# with toilets and a petrol pump, nowhere near a grave field. amenity=parking
# includes the gravel pull-in at the end of a forest track, which is what
# actually exists at these places. Points and polygons both, because a car
# park is mapped either way depending on who mapped it.
# NOTE the two different filters, and they are not interchangeable. The
# comment above about other_tags is true of `tourism` and `historic`; it is
# NOT true of `amenity`, which GDAL promotes to a real column on
# multipolygons but not on points. Filtering the polygon layer on other_tags
# returned 0 features and looked exactly like "Sweden maps no car parks as
# areas" -- a plausible zero, which is the failure mode worth fearing.
extract parking_pt    points        park   osm_id,name,other_tags \
  'other_tags LIKE '"'"'%"amenity"=>"parking%'"'"''
extract parking_poly  multipolygons park   osm_id,amenity,name \
  "amenity LIKE 'parking%'"

# Feature counts these filters produced when stage 4 was calibrated. OSM
# grows, so newer extracts should come out slightly above these; a number far
# BELOW one of them means a filter or the source extract has changed.
echo
echo "layer            size   rows (calibrated)"
for spec in "sweden_ways:ways:2304476" "buildings:b:3904620" "boards:boards:7018" \
            "historic_pt:feat:8258" "historic_poly:feat:576" \
            "parking_pt:park:16128" "parking_poly:park:279426" \
            "osm_poi:poi:70212"; do
  IFS=: read -r f lyr expect <<<"$spec"
  n=$(python3 -c "import sqlite3,sys;print(sqlite3.connect('file:$DIR/$f.gpkg?mode=ro',uri=True).execute('select count(*) from \"$lyr\"').fetchone()[0])")
  printf "%-16s %5s  %9s (%s)\n" "$f.gpkg" "$(du -h "$DIR/$f.gpkg" | cut -f1)" "$n" "$expect"
done
