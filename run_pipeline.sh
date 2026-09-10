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
#   ./run_pipeline.sh              # all stages
#   ./run_pipeline.sh --from 4     # resume from stage 4 (skip parse/cluster/labels)
#   ./run_pipeline.sh --json       # emit JSONL progress instead of human output
#   ./run_pipeline.sh --top 30000  # tiles from the 30k best-scoring clusters
#   ./run_pipeline.sh --from 6 --top 30000 --tile-args "--max-desc 200"
#
# Missing inputs are handled before stage 1; see the stage 0 block below.

set -euo pipefail

FROM=1
JSON=""
# Stage 6 only. Ranking always runs over every cluster; TOP just decides how
# many of the best ones get exported as tiles.
TOP=""
# Descriptions ship outside the tiles now, so there is nothing to truncate.
TILE_ARGS="${TILE_ARGS:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from) FROM="$2"; shift 2 ;;
    --json) JSON="--progress-json"; shift ;;
    --top) TOP="--top $2"; shift 2 ;;
    --tile-args) TILE_ARGS="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

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

if (( FROM <= 4 )); then
  require_input src/data/fornlamningar_full.gpkg \
    "the RAA GeoPackage export. Tracked in git LFS: try \`git lfs pull\`"
  require_input src/data/ksamsok_raw.sqlite \
    "the crawl cache (~4 h, 311,845 responses). Rebuild: python3 crawl_ksamsok.py"

  for f in sweden_ways buildings boards historic_pt historic_poly; do
    if [[ ! -s "src/data/osm/$f.gpkg" ]]; then
      echo "── stage 0: osm inputs missing, running ./fetch_osm.sh"
      ./fetch_osm.sh
      break
    fi
  done
fi

STAGES=(
  "1:parse:build_sites.py"
  "2:cluster:build_clusters.py"
  "3:labels:build_labels.py"
  "4:signals:build_signals.py"
  "5:score:build_scores.py"
  "6:tiles:build_tiles.py"
)

start_all=$SECONDS
for entry in "${STAGES[@]}"; do
  IFS=: read -r num name script <<<"$entry"
  (( num < FROM )) && continue
  echo "── stage $num: $name ($script)"
  t0=$SECONDS
  # build_scores has no --progress-json; pass the flag only where supported.
  if [[ "$name" == "tiles" ]]; then
    # shellcheck disable=SC2086
    python3 "$script" $TOP $TILE_ARGS
  elif [[ -n "$JSON" ]] && grep -q "progress-json" "$script"; then
    python3 "$script" $JSON
  else
    python3 "$script"
  fi
  echo "   done in $((SECONDS - t0))s"
done
echo "── pipeline complete in $((SECONDS - start_all))s"
