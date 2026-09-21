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
#   ./run_pipeline.sh --skip-long      # stages 1-9 only: the old ~4 min run
#   ./run_pipeline.sh --concurrency 3  # parallel generation (see below)
#   ./run_pipeline.sh --no-pull        # do not mirror the contribution log
#
# A FULL RUN IS NOW HOURS, NOT MINUTES. Stages 10 and 11 generate and then
# translate the descriptions with a local model; on this machine that is most
# of a day for a set that has not been generated before. Both are restartable
# and skip what is already done, so interrupting one is cheap. `--skip-long`
# is the pipeline as it was before they were added.
#
# While it runs:
#   python3 pipeline_progress.py           # stage, %, measured rate, ETA
#   python3 pipeline_progress.py --watch
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
# 6,000 SINCE 2026-09-18, down from 10,000. Measured on the cumulative
# capture curve: by rank 3,548 the export already holds 100% of the places
# with a Wikipedia article and 100% of those with a photograph, and by 5,000
# it holds 99.7% of everything Franco has verified. Past that only OSM keeps
# accruing, so the second half of a 10,000 export was almost entirely
# uncorroborated intrinsic guesses. Franco's call.
#
# NOT DEFAULTED IN build_tiles.py, because `--top` there defaults to None -- the
# -- the whole country -- and this runner passed nothing. So a plain
# `./run_pipeline.sh` overwrote the export with 126,087 clusters and 99,536
# shard entries where the app expects a bounded set, in the OTHER repo,
# silently.
# It happened on 2026-09-17. The number the app ships is the number the
# runner should default to; pass --top to override it deliberately.
TOP="--top 6000"
# Descriptions ship outside the tiles now, so there is nothing to truncate.
TILE_ARGS="${TILE_ARGS:-}"
# Parallel requests to Ollama. 1 by default because raising it past
# OLLAMA_NUM_PARALLEL makes the server queue rather than parallelise, which
# looks like a speed-up in the request count and is not one.
CONCURRENCY="${CONCURRENCY:-1}"
# Stop before generation, i.e. the old four-minute pipeline.
SKIP_LONG=0
# Mirror the contribution log before scoring. On by default: user ratings are
# an input to the score now, so a run that skipped this would rank on stale
# data without saying so. --no-pull is for when the network is the problem.
PULL=1
APP_DIR="${APP_DIR:-../fornlamningar-app}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from) FROM="$2"; shift 2 ;;
    --json) JSON="--progress-json"; shift ;;
    --top) TOP="--top $2"; shift 2 ;;
    --all-clusters) TOP=""; shift ;;
    --tile-args) TILE_ARGS="$2"; shift 2 ;;
    --concurrency) CONCURRENCY="$2"; shift 2 ;;
    --skip-long) SKIP_LONG=1; shift ;;
    --no-pull) PULL=0; shift ;;
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
  # SOURCES BEFORE SIGNALS, and this order is load-bearing. The corpus used
  # to be built at stage 7, after scoring at stage 6, which meant "a
  # Wikipedia article and a county plan mention this place" could not be a
  # scoring feature no matter how obviously it should be -- the table did not
  # exist yet when the score was computed. build_signals.doc_source_counts()
  # reads it now, so it has to come first. build_sources only needs the
  # clusters from stage 2; it reads neither signals nor scores.
  "5:sources:build_sources.py"
  "6:signals:build_signals.py"
  "7:score:build_scores.py"
  "8:places:build_places.py"
  # --- the long tail. Everything above is ~4 minutes; these two are hours.
  #
  # They are here because Franco asked for "running the pipeline" to mean
  # running all of it, and the argument against -- that a four-minute job you
  # can re-run casually turns into one nobody runs -- is answered by
  # --skip-long rather than by leaving the product half-built. The default is
  # the whole thing; the short loop is one flag away.
  #
  # Both are RESTARTABLE and skip what is already done, so an interrupted run
  # costs the place it was on and nothing else.
  "9:descriptions:build_descriptions.py"
  "10:translate:build_descriptions.py --translate"
  # THE EXPORT COMES AFTER THE TEXT, and it did not on the first attempt.
  # build_tiles.py writes the per-shard description JSON that both the web map
  # and -- through sync-assets.sh -- the app's SQLite bases are built from. Run
  # before generation, as stage 9, it exported the PREVIOUS generation's text:
  # a full run would spend fourteen hours writing descriptions and then ship
  # the old ones, in both repos, with nothing failing. Caught by looking at
  # what franco-may actually had in its working tree.
  "11:tiles:build_tiles.py"
  # Assets live in the app repo, styles and all. Runs there.
  "12:assets:sync-assets.sh"
  "13:release:make_release.py"
)

# Dropping the long tail has to happen HERE, after STAGES is defined. It was
# first written up beside the flag parsing, which is before STAGES exists: the
# slice silently produced nothing, STAGES was then defined in full, and
# `--skip-long` generated descriptions anyway. Caught by running it.
if (( SKIP_LONG )); then
  keep=()
  for entry in "${STAGES[@]}"; do
    IFS=: read -r _num name _ <<<"$entry"
    case "$name" in
      descriptions|translate) ;;
      *) keep+=("$entry") ;;
    esac
  done
  STAGES=("${keep[@]}")
fi

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

# ---------------------------------------------------------------------------
# Pre-flight, and the reason it exists.
#
# With generation in the pipeline a run is hours, not minutes, and every
# dependency it needs is checked HERE rather than when the stage that needs it
# is reached. The failure this prevents is specific and happened in spirit
# already: fourteen hours of generation, then the assets stage aborts on a
# missing resvg, `set -e` takes the script down, and the release is never
# written. Everything below is a second to check and an evening to discover.
preflight_fail=0
need_stage() { [[ ",$stage_names," == *",$1,"* ]]; }

stage_names=""
for entry in "${STAGES[@]}"; do
  IFS=: read -r num name _ <<<"$entry"
  (( num < FROM )) && continue
  stage_names="${stage_names:+$stage_names,}$name"
done

if need_stage descriptions || need_stage translate; then
  model="$(python3 -c 'import describe_place as d; print(d.DEFAULT_MODEL)')"
  host="$(python3 -c 'import describe_place as d; print(d.HOST)')"
  if ! tags="$(curl -fsS --max-time 10 "$host/api/tags" 2>/dev/null)"; then
    echo "pre-flight: no Ollama at $host -- start it, or pass --skip-long" >&2
    preflight_fail=1
  elif ! grep -q "$model" <<<"$tags"; then
    echo "pre-flight: Ollama is up but has no $model -- \`ollama pull $model\`" >&2
    preflight_fail=1
  else
    echo "── pre-flight: ollama $model at $host"
  fi
fi

if need_stage assets; then
  command -v resvg >/dev/null || {
    echo "pre-flight: resvg not found (brew install resvg), needed by the assets stage" >&2
    preflight_fail=1; }
  [[ -x "$APP_DIR/scripts/sync-assets.sh" ]] || {
    echo "pre-flight: no $APP_DIR/scripts/sync-assets.sh" >&2
    preflight_fail=1; }
fi

(( preflight_fail )) && exit 1

# ---------------------------------------------------------------------------
# Stage 0f: the contribution log.
#
# Before stage 1, because build_labels.py turns these events into labels and
# build_scores.py ranks on them: a rating somebody left in the app moves a
# place up or down, and the tiles are cut from that ranking. Pulling after
# scoring would mean every run shipped yesterday's opinions.
#
# By cursor, so it is cheap on every run and not only the first. Failure is
# NOT fatal: the log is a mirror, the previous pull is still on disk, and
# refusing to derive anything because a network was down would be the wrong
# trade for a machine that is meant to run this unattended.
if (( PULL )) && (( FROM <= 1 )); then
  echo "── stage 0f: contributions (pull by cursor)"
  if ! python3 crawl_contributions.py; then
    echo "   ! pull failed -- continuing with the log already on disk" >&2
  fi
fi

top_n="$(sed -n 's/.*--top \([0-9]*\).*/\1/p' <<<"$TOP")"
python3 pipeline_progress.py --begin-run "$stage_names" --top "${top_n:-0}"

# A sampler for the whole run, so `pipeline_progress.py` has history to
# compute a rate from whenever it is asked -- rather than only from the
# moment somebody first looked.
python3 - <<'SAMPLER' &
import subprocess, time
while True:
    subprocess.run(["python3", "pipeline_progress.py", "--sample"])
    time.sleep(60)
SAMPLER
sampler_pid=$!
# Killed on every exit path, including the error ones. Without this a failed
# run leaves a python process sampling a finished pipeline forever.
cleanup() {
  kill "$sampler_pid" 2>/dev/null || true
  wait "$sampler_pid" 2>/dev/null || true
}
trap cleanup EXIT

start_all=$SECONDS
for entry in "${STAGES[@]}"; do
  IFS=: read -r num name script <<<"$entry"
  # The entry may carry its own flags (`crawl_lansstyrelsen.py --join`), so
  # the first word is the file to test with grep and the rest are arguments.
  read -r file args <<<"$script"
  (( num < FROM )) && continue
  echo "── stage $num: $name ($script)"
  t0=$SECONDS
  python3 pipeline_progress.py --begin-stage "$name"
  # build_scores has no --progress-json; pass the flag only where supported.
  if [[ "$name" == "descriptions" ]]; then
    # shellcheck disable=SC2086
    python3 build_descriptions.py $TOP --concurrency "$CONCURRENCY"
  elif [[ "$name" == "translate" ]]; then
    # shellcheck disable=SC2086
    python3 build_descriptions.py --translate $TOP --concurrency "$CONCURRENCY"
  elif [[ "$name" == "assets" ]]; then
    [[ -x "$APP_DIR/scripts/sync-assets.sh" ]] || {
      echo "   ! no $APP_DIR/scripts/sync-assets.sh -- skipping" >&2
      python3 pipeline_progress.py --end-stage "$name" "$((SECONDS - t0))"
      continue
    }
    # Non-fatal, like release below: by the time these run, the hours of
    # generation are already committed to generated.sqlite. Taking the script
    # down here would lose the summary and the release for a reason that is
    # repairable in a minute by hand.
    ( cd "$APP_DIR" && ./scripts/sync-assets.sh ) || \
      echo "   ! assets failed -- rerun: (cd $APP_DIR && ./scripts/sync-assets.sh)" >&2
  elif [[ "$name" == "release" ]]; then
    APP="$APP_DIR" python3 make_release.py || \
      echo "   ! release failed -- rerun: python3 make_release.py" >&2
  elif [[ "$name" == "tiles" ]]; then
    # --keep-geojson ALWAYS, and not as an option. The app's sync-assets.sh
    # requires src/data/tiles_input.geojsonl to still be there afterwards, so
    # a clean run without it deleted the file the app build needs -- with the
    # failure landing in the other repo, an hour later.
    # shellcheck disable=SC2086
    python3 "$file" --keep-geojson $TOP $TILE_ARGS
    # THE ENGLISH SHARDS ARE PART OF THE EXPORT, and until 2026-09-19 they
    # were a command in a comment in the app's sync-assets.sh -- so the
    # pipeline spent five hours translating and then shipped whatever English
    # somebody had exported by hand three days earlier. The symptom was mild
    # enough to miss: descriptions.en.db held 3,524 of 5,627 entries and 792
    # of those were still Swedish, which reads as "the translation is
    # incomplete" rather than "the export is stale".
    # shellcheck disable=SC2086
    python3 "$file" --lang en --desc-out src/data/shards/descriptions-en \
      --skip-tippecanoe $TOP $TILE_ARGS
  elif [[ -n "$JSON" ]] && grep -q "progress-json" "$file"; then
    # shellcheck disable=SC2086
    python3 "$file" $args $JSON
  else
    # shellcheck disable=SC2086
    python3 "$file" $args
  fi
  python3 pipeline_progress.py --end-stage "$name" "$((SECONDS - t0))"
  echo "   done in $((SECONDS - t0))s"
done
python3 pipeline_progress.py --end-run
echo "── pipeline complete in $((SECONDS - start_all))s"
