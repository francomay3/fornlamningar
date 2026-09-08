# fornlämningar

Data pipeline for a free app for finding and visiting Swedish archaeological
sites. It turns Riksantikvarieämbetet's register of ~312,000 recorded remains
into ~10,000 ranked, clustered map pins.

The app itself is a separate repo (`franco-may`, Next.js + MapLibre); this one
only writes the vector tiles it reads.

[PIPELINE.md](PIPELINE.md) is the real document: what each stage does, what was
measured, and which hypotheses turned out to be wrong.

## Run it

```sh
./run_pipeline.sh                 # all stages, ~4 min
./run_pipeline.sh --from 5        # re-score and re-tile only
./run_pipeline.sh --top 30000     # export more pins
```

Stage 0 checks the inputs first: it rebuilds the OSM extracts by itself, and
refuses to guess about the two expensive ones.

## Stages

| # | script | output |
|---|--------|--------|
| — | `crawl_ksamsok.py` | `ksamsok_raw.sqlite` — raw K-samsök JSON-LD, resumable, run once |
| 1 | `build_sites.py` | `sites` — parsed records, geometry, parsed dimensions (`dims.py`) |
| 2 | `build_clusters.py` | `clusters` — one row per place a visitor drives to, not per stone |
| 3 | `build_labels.py` | `labels` — weak labels from Wikidata plus `hand_labels.csv` |
| 4 | `build_signals.py` | `signals` — distances to roads, buildings, boards, OSM sites |
| 5 | `build_scores.py` | `scores` — L2 logistic regression (`logistic.py`) |
| 6 | `build_tiles.py` | vector tiles, straight into the frontend repo |

`sample_for_review.py` draws stratified samples to hand-verify; its verdicts go
into `hand_labels.csv`.

## Two scores

`score_intrinsic` judges a site only by what it *is* — class, size, description,
access. `score_full` also credits Wikipedia articles and photographs.

The app uses `score_intrinsic`. Every documentation-derived signal correlates
strongly with fame, and fame is exactly what an app for *finding* places must
not assume: the sites worth surfacing are the ones nobody has written up yet.

## Data

Tracked in git LFS, because nothing here can produce them:

- `src/data/fornlamningar_full.gpkg` — the RAÄ export, seeds the crawl
- `src/data/signs/` — Kungsbacka's sign layer, kept as evidence of a dead end
- `hand_labels.csv` — the only ground truth not derived from documentation

Everything else under `src/data/` is ignored: caches that cost a network
round-trip to rebuild (`ksamsok_raw.sqlite`, `osm/`, `wikidata_cache/`) and
`sites.sqlite`, which is a pure function of the two and rebuilds in minutes.
See the data policy in [.gitignore](.gitignore).
