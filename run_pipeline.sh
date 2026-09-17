#!/usr/bin/env bash
# Run the derivation pipeline end to end.
#
# This replaces the job-runner UI that was originally planned as Stage 7. That
# made sense when we expected a long, flaky crawl needing live monitoring. In
# practice the crawl ran once (4 h, 311,845 responses, 2 dead) and the whole
# derivation takes ~4 minutes with no failure modes worth a dashboard.
#
# The crawl itself is NOT here: it is a separate, resumable, run-once job
# (`python3 crawl_ksamsok.py`). Everything below derives from its cache and is
# safe to re-run at any time.
#
# Usage:
#   ./run_pipeline.sh                # all stages
#   ./run_pipeline.sh --from signals # resume from a stage, by name or number
#   ./run_pipeline.sh --json         # emit JSONL progress instead of human output
#   ./run_pipeline.sh --top 30000    # tiles from the 30k best-scoring clusters
#   ./run_pipeline.sh --all-clusters # every cluster (126k) -- NOT what ships
#   ./run_pipeline.sh --from tiles --top 30000 --tile-args "--max-desc 200"
#
# --from takes a NAME as well as a number, and the name is the one to use: the
# numbers shifted the day the product stages below were added, and anybody who
# had `--from 4` in their fingers silently skipped a different stage.
#
# Missing inputs are handled before stage 1; see the stage 0 block below.

set -euo pipefail

FROM=1
JSON=""
# The tiles stage only. Ranking always runs over every cluster; TOP just
# decides how many of the best ones get exported as tiles.
#
# 10,000 BY DEFAULT, because `build_tiles.py --top` defaults to None -- the
# whole country -- and this runner passed nothing. So a plain
# `./run_pipeline.sh` overwrote the export with 126,087 clusters and 99,536
# shard entries where the app expects 10,000, in the OTHER repo, silently.
# It happened on 2026-09-17. The number the app ships is the number the
# runner should default to; pass --top to override it deliberately.
TOP="--top 10000"
# Descriptions ship outside the tiles now, so there is nothing to truncate.
TILE_ARGS="${TILE_ARGS:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from) FROM="$2"; shift 2 ;;
    --json) JSON="--progress-json"; shift ;;
    --top) TOP="--top $2"; shift 2 ;;
    --all-clusters) TOP=""; shift ;;
    --tile-args) TILE_ARGS="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

# THE PRODUCT STAGES USED TO BE MISSING, and that was the worst kind of gap:
# `paths.py` calls places.sqlite "the thing we are actually building" and
# nothing in the runner built it. Worse, build_labels.py and build_sources.py
# read `lansstyrelsen.matches.cluster_id`, which only the manual `--join`
# refreshes -- so a rebuild that moved clusters used a month-old mapping and
# said nothing.
#
# `join` is only the join: it re-points the county-board matches at the
# clusters that exist now, and re-runs no HTTP. The crawls themselves
# (crawl_wikimedia.py, crawl_lansstyrelsen.py without --join) stay out, beside
# crawl_ksamsok.py: they are RAW, they are slow, and they are rude to repeat.
STAGES=(
  "1:parse:build_sites.py"
  "2:cluster:build_clusters.py"
  "3:join:crawl_lansstyrelsen.py --join"
  "4:labels:build_labels.py"
  "5:signals:build_signals.py"
  "6:score:build_scores.py"
  "7:sources:build_sources.py"
  "8:places:build_places.py"
  "9:tiles:build_tiles.py"
)

# --from by name. Resolved against STAGES so the two can never disagree.
if [[ -n "$FROM" && ! "$FROM" =~ ^[0-9]+$ ]]; then
  want="$FROM"
  FROM=""
  for entry in "${STAGES[@]}"; do
    IFS=: read -r num name _ <<<"$entry"
    [[ "$name" == "$want" ]] && FROM="$num"
  done
  if [[ -z "$FROM" ]]; then
    echo "unknown stage: $want" >&2
    printf 'stages:' >&2
    for entry in "${STAGES[@]}"; do
      IFS=: read -r num name _ <<<"$entry"
      printf ' %s(%s)' "$name" "$num" >&2
    done
    echo >&2
    exit 2
  fi
fi

# ---------------------------------------------------------------------------
# Stage 0: inputs.
#
# Everything under src/data/ that git ignores falls into one of two buckets,
# and they get different treatment here.
#
#   Cheap to rebuild -> rebuilt automatically. The OSM extracts are a download
#   plus five ogr2ogr runs; fetch_osm.sh skips whatever already exists, so
#   this costs nothing on a warm checkout.
#
#   Expensive or irreplaceable -> we refuse to guess. The K-samsok cache is
#   four hours of rate-limited crawling and the GeoPackage is the RAA export
#   that seeds it. Silently starting a four-hour crawl because a file was
#   missing would be a nasty surprise, so we print the command and stop.
# ---------------------------------------------------------------------------
require_input() {
  [[ -s "$1" ]] && return
  echo "missing required input: $1" >&2
  echo "  $2" >&2
  exit 1
}

# The raw inputs are needed by parse (the GeoPackage and the crawl cache) and
# by signals (the OSM extracts), so the check covers everything up to signals.
# It used to be the literal 4, which was signals before the product stages
# were added -- exactly the drift --from by name is meant to stop.
signals_num=1
for entry in "${STAGES[@]}"; do
  IFS=: read -r num name _ <<<"$entry"
  [[ "$name" == "signals" ]] && signals_num="$num"
done

if (( FROM <= signals_num )); then
  require_input src/data/raa_export.gpkg \
    "the RAA GeoPackage export. Tracked in git LFS: try \`git lfs pull\`"
  require_input src/data/raa_api.sqlite \
    "the crawl cache (~4 h, 311,845 responses). Rebuild: python3 crawl_ksamsok.py"

  for f in sweden_ways buildings boards historic_pt historic_poly; do
    if [[ ! -s "src/data/osm/$f.gpkg" ]]; then
      echo "── stage 0: osm inputs missing, running ./fetch_osm.sh"
      ./fetch_osm.sh
      break
    fi
  done
fi

start_all=$SECONDS
for entry in "${STAGES[@]}"; do
  IFS=: read -r num name script <<<"$entry"
  # The entry may carry its own flags (`crawl_lansstyrelsen.py --join`), so
  # the first word is the file to test with grep and the rest are arguments.
  read -r file args <<<"$script"
  (( num < FROM )) && continue
  echo "── stage $num: $name ($script)"
  t0=$SECONDS
  # build_scores has no --progress-json; pass the flag only where supported.
  if [[ "$name" == "tiles" ]]; then
    # --keep-geojson ALWAYS, and not as an option. The app's sync-assets.sh
    # requires src/data/tiles_input.geojsonl to still be there afterwards, so
    # a clean run without it deleted the file the app build needs -- with the
    # failure landing in the other repo, an hour later.
    # shellcheck disable=SC2086
    python3 "$file" --keep-geojson $TOP $TILE_ARGS
  elif [[ -n "$JSON" ]] && grep -q "progress-json" "$file"; then
    # shellcheck disable=SC2086
    python3 "$file" $args $JSON
  else
    # shellcheck disable=SC2086
    python3 "$file" $args
  fi
  echo "   done in $((SECONDS - t0))s"
done
echo "── pipeline complete in $((SECONDS - start_all))s"
