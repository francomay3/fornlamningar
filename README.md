# fornlämningar

Data pipeline for **Fornkoll**, a free app for finding and visiting Swedish
archaeological sites. It turns Riksantikvarieämbetet's register of ~312,000
recorded remains into 251,029 clustered places, ranks them, and exports the
best 10,000 as map pins.

7,111 of those 10,000 carry a generated visitor description and 5,388 of
those are also in English; the rest show the register's own survey text,
which is often a single line ("Kyrkoruin."). That gap is a long local-model
run away, not a missing feature.

Three repos, and it is worth being precise about which is which, because this
file used to get it wrong:

| repo | what it is |
|---|---|
| **fornlamningar** (here) | the pipeline. Python, near-stdlib, no service |
| **fornlamningar-app** | the app people install. React Native (Expo) + MapLibre, Android |
| **franco-may** | a personal site that hosts two things: a web version of the map, and the sync backend (`/api/fornlamningar/*`, Postgres) |

This repo writes into `franco-may` — vector tiles and description shards — and
`fornlamningar-app`'s own `sync-assets.sh` reads from both.

[PIPELINE.md](PIPELINE.md) is the real document: what each stage does, what was
measured, and which hypotheses turned out to be wrong. It stops at `scores`;
everything after that (sources, places, descriptions, the app) is here and in
[TODO.md](TODO.md).

## Run it

```sh
./run_pipeline.sh                  # all stages, ~4 min
./run_pipeline.sh --from score     # re-score onward
./run_pipeline.sh --top 30000      # export more pins than the default 10,000
./run_pipeline.sh --all-clusters   # every cluster; NOT what ships
```

`--from` takes a stage **name** as well as a number. Use the name: the numbers
have shifted once already and anybody with `--from 4` in their fingers
silently skipped a different stage.

Stage 0 checks the inputs first. It rebuilds the OSM extracts by itself and
refuses to guess about the two expensive ones — the RAÄ export and the
four-hour crawl cache.

## The five tiers

Names in [paths.py](paths.py) say where a file's authority comes from, which
is the only thing you need in order to answer "may I delete this".

| tier | files | may I delete it |
|---|---|---|
| **RAW** | `raa_export.gpkg`, `raa_api.sqlite`, `wikimedia.sqlite`, `lansstyrelsen.sqlite` | only if you are willing to re-fetch. The crawl is 4 h and rude to repeat |
| **EXPENSIVE** | `generated.sqlite` | it is derived, and it is thirteen hours of local model time. Tracked in LFS for that reason |
| **WORK** | `work.sqlite` | yes. `./run_pipeline.sh` rebuilds it in ~4 min |
| **PRODUCT** | `places.sqlite` | yes, but it is the thing we are building: one row per visitable place, with its text, images and the provenance of both |
| **PAYLOAD** | the tiles, the shards, the app's `assets/data/` | yes, always. Pure function of PRODUCT, regenerated on every export |

## Stages

Crawls are not stages. They are resumable, run-once jobs, kept out of the
runner because they are slow and rude to repeat: `crawl_ksamsok.py` (4 h,
311,845 responses), `crawl_wikimedia.py`, `crawl_lansstyrelsen.py`.

| # | name | script | output |
|---|---|---|---|
| 1 | parse | `build_sites.py` | `sites` — parsed records, geometry, parsed dimensions (`dims.py`) |
| 2 | cluster | `build_clusters.py` | `clusters` — one row per place a visitor drives to, not per stone |
| 3 | join | `crawl_lansstyrelsen.py --join` | re-points the county-board matches at the clusters that exist NOW. Only the join; no HTTP |
| 4 | labels | `build_labels.py` | `labels` — weak labels from Wikidata plus `hand_labels.csv` |
| 5 | signals | `build_signals.py` | `signals` — distances to roads, buildings, boards, OSM sites |
| 6 | score | `build_scores.py` | `scores` — L2 logistic regression (`logistic.py`) |
| 7 | sources | `build_sources.py` | `sources` — everything anybody has written about each place, with licence and provenance |
| 8 | places | `build_places.py` | `features`, `images` — the product, one row per place |
| 9 | tiles | `build_tiles.py` | vector tiles and description shards, into `franco-may` |

Two things run outside the runner on purpose:

* **`build_descriptions.py`** generates the visitor descriptions with a local
  model. Resumable, ~10–14 h for the country, and never started implicitly.
  `describe_place.py` holds the prompt and the payload; `--lang en` does the
  translation pass over what Swedish already produced.
* **`sample_for_review.py`** draws stratified samples to hand-verify. Its
  verdicts go into `hand_labels.csv`.

## Two scores

`score_intrinsic` judges a site only by what it *is* — class, size,
description, access. `score_full` also credits Wikipedia articles and
photographs.

The app uses `score_intrinsic`. Every documentation-derived signal correlates
strongly with fame, and fame is exactly what an app for *finding* places must
not assume: the sites worth surfacing are the ones nobody has written up yet.

## One rule, one file

[families.py](families.py) is the only place allowed to hold a rule about
classes — which family a class belongs to, which classes are excluded and what
can rescue them, and which member represents a cluster. That is not tidiness:
the representative rule once lived in four scripts and the copies drifted,
which pointed 19,881 clusters' "show in Fornsök" button at a different
monument than the one the text described.

## Data

See the data policy in [.gitignore](.gitignore), which explains every entry.
Tracked in git LFS is only what no script can produce, plus `generated.sqlite`:

- `src/data/raa_export.gpkg` — the RAÄ export, seeds the crawl
- `src/data/generated.sqlite` — our own descriptions
- `src/data/signs/` — Kungsbacka's sign layer, kept as evidence of a dead end
- `hand_labels.csv` — the only ground truth not derived from documentation

There is no national sign dataset. That was checked with a county
antiquarian, and it is why the pipeline reasons about signs from intrinsic
evidence instead.
