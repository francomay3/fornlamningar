# Pipeline plan: from national dataset to visitable sites

> **What this document is, and what it is not.**
>
> It is the RECORD: what was measured, what was decided and why, and which
> hypotheses turned out to be wrong. That is why it is not rewritten as the
> code changes -- a measurement does not stop being true because the thing it
> was measuring moved.
>
> It is NOT a description of the pipeline as it stands. It reaches as far as
> `scores`; everything after that -- the corpus (`build_sources.py`), the
> product (`build_places.py`), the generated descriptions
> (`build_descriptions.py`, `describe_place.py`) and the app -- is in
> [README.md](README.md) and [TODO.md](TODO.md).
>
> Database and file names here are the ones of the time. `sites.sqlite` is now
> `work.sqlite`, `ksamsok_raw.sqlite` is `raa_api.sqlite`,
> `fornlamningar_full.gpkg` is `raa_export.gpkg`; [paths.py](paths.py) is the
> current list and says which tier each one belongs to.

Goal: from 311,847 registered archaeological remains, produce a ranked, filtered
set of places that are actually worth travelling to and can be found on arrival.

Everything below is designed around one principle: **acquisition is expensive and
happens once; derivation is cheap and happens many times.** Every stage writes to
its own table, is independently resumable, and never destroys its input.

---

## Measured facts (established, not assumed)

These numbers come from live sampling and shape every decision that follows.

| Fact | Value | Source |
|---|---|---|
| Distinct UUIDs in the GeoPackage | 311,847 | all 3 layers, deduplicated |
| K-samsök API latency | ~75 ms p50, flat to 40 req/s | 1,250-request probe |
| Response size | 10.9 KB raw, 2.3 KB zlib (5.3x) | 846-row sample |
| `Placering = Synlig ovan mark` | **96.8%** | 5,991-site sample |
| `Antikvarisk bedömning = Fornlämning` | **99.6%** | 5,991-site sample |
| Sites with a folk name (`sitename`) | ~1.5% | GeoPackage |
| OSM `historic=archaeological_site` in Sweden | 2,374 | Overpass |
| …of those, with `ref:raa` | **2** | Overpass |
| …of those, with `wikidata` | 243 | Overpass |
| OSM information boards (all) | 6,949 | Overpass |
| OSM boards with `board_type=history` | 1,435 | Overpass |
| Sites with a board within 200 m | **1.03%** (~3,071) | sampled |
| OSM `highway` ways in Sweden | **2,304,476** (763,097 km) | GDAL/PBF |
| OSM `information=board` nodes | **7,018** | GDAL/PBF |
| **dist_to_way_m**, positives vs rest | median **18 m vs 84 m** = **4.71x** | national |
| within 50 m of a way | **76%** of positives vs 36% | national |
| dist_to_board_m, positives vs rest | median 1,884 m vs 2,998 m = 1.59x | national |
| **Boilerplate-only descriptions** | **25.6%** (52,506 of 204,744) | parsed |
| Sites with a real description | 74.4%, mean 427 chars | parsed |
| Wikidata items joinable by UUID (`P1260`) | **145,102** | SPARQL |
| …of those with **≥1 Wikipedia sitelink** | **2,048** clean, **1,967** in the GeoPackage | SPARQL |
| Wikidata `P1262` (RAÄ number) coverage | 295 items total | SPARQL |

### Geometry (a UUID may appear in several layers)

| geometry | UUIDs | share |
|---|---|---|
| point only | 207,971 | 66.7% |
| **polygon only** | **87,561** | **28.1%** |
| line only | 13,269 | 4.3% |
| point + polygon | 2,195 | 0.7% |
| line + polygon | 705 | 0.2% |
| point + line + polygon | 80 | 0.0% |
| point + line | 66 | 0.0% |
| **more than one geometry type** | **3,046** | **1.0%** |

**28.1% of sites have no point representation at all.** The previous
`fornlamningar_points.sqlite` was built only from the point layer's 219,639 rows
and therefore silently dropped 87,561 sites — disproportionately the *large*
ones (gravfält, fornborgar, settlement areas), i.e. exactly the visitable ones.
The crawler is seeded from all three layers, so all 311,847 UUIDs are covered.

Worked example — Fjärås 81:1 / **Frodestenen** (`eddd2aa1-…`), class `Gravfält`:
appears as `L1997:2648-1` in the point layer *and* `L1997:2648-2` in the polygon
layer, envelope **236 m × 453 m**. The `-1`/`-2` suffix distinguishes geometry
representations, not sub-monuments.

### Signal strength, measured against the label set

**Critical caveat: 1,185 of 1,425 notables (83%) are `Runristning`.** Swedish
Wikipedia has systematic per-runestone coverage, so "has a Wikipedia article" is
approximately "is a runestone". Every signal must therefore be measured with
runestones **excluded**, or the model becomes a runestone detector.

De-confounded measurements (204,744 parsed sites; `Runristning` excluded leaves
202,943 sites and 240 notables). `sigma` is the deviation of the observed count
from the base-rate expectation:

| Signal | notable% | base% | lift | sigma | Verdict |
|---|---|---|---|---|---|
| **Has folk name** | 34.17% | 4.00% | **8.54x** | +23.8 | **Strongest signal found** |
| **Multi-geometry (>1 layer)** | 5.00% | 1.12% | **4.45x** | +5.7 | **Strong** |
| **Has a polygon** | 4.17% | 1.09% | **3.81x** | +4.6 | **Strong** |
| Description > 300 chars | 63.75% | 37.03% | 1.72x | +8.6 | Solid |
| Has measurements | 87.08% | 72.65% | 1.20x | +5.0 | Weak but real |
| Boilerplate-only description | 11.25% | 25.85% | **0.44x** | -5.2 | Real negative, half as strong as it first appeared |
| Polygon envelope **area** | — | — | ~1.2x lift | — | **Near noise. Not a signal** |

Results are stable when `Hällristning` is also excluded (name 8.34x,
multi-geometry 4.65x), so they are not an artifact of one class.

**How the confounded numbers misled** — recorded so the mistake is not repeated:

| Signal | All classes | Runristning excluded |
|---|---|---|
| Has folk name | 3.15x | **8.54x** |
| Multi-geometry | 0.76x | **4.45x** |
| Has polygon | 0.65x | **3.81x** |
| Boilerplate-only | 0.18x | 0.44x |

Runestones are almost always unnamed single points with good descriptions, so
including them *diluted* the name signal, *inverted* both geometry signals, and
*exaggerated* the description signal.

**Do not derive the class blacklist from these labels.** `Hällristning` scores
0.17% notable / 0.2x lift, yet rock carvings include **Tanum, a UNESCO World
Heritage Site**. Use `named%` per class plus human judgement; treat Wikipedia
labels as a weak third input. Where naming and notability agree the exclusion is
safe (`Kolningsanläggning` 0.1% named / 0 notables; `Härd` 0.2% / 0.03%). Where
they disagree, trust naming.

### Classes where naming and Wikipedia disagree

Zero Wikipedia articles but heavily named — locally known, nationally
undocumented. This is the population the label set is blind to, and the reason
the hand-labelled test set matters:

| class | n | notable | named% |
|---|---|---|---|
| Lägenhetsbebyggelse | 1,959 | 0 | 65.3% |
| Källa med tradition | 624 | 1 | 62.0% |
| Fartygs-/båtlämning | 598 | 0 | 45.5% |
| Naturföremål/-bildning med bruk | 597 | 1 | 42.5% |
| Offerkast | 329 | 0 | 33.4% |
| Gränsmärke | 1,046 | 0 | 24.5% |

### Class blacklist candidates (naming and notability agree)

| class | n | share | notable | named% |
|---|---|---|---|---|
| Stensättning | 60,553 | 29.6% | 17 | 2.0% |
| Fångstgrop | 18,151 | 8.9% | 0 | 1.2% |
| Härd | 11,962 | 5.8% | 4 | 0.2% |
| **Kolningsanläggning** | **11,870** | **5.8%** | **0** | **0.1%** |
| Vägmärke | 9,360 | 4.6% | 1 | 0.8% |
| Skärvstenshög | 4,630 | 2.3% | 0 | 0.8% |
| Boplats | 3,278 | 1.6% | 0 | 1.0% |
| Kemisk industri | 2,733 | 1.3% | 0 | 1.0% |
| Boplatsgrop | 2,070 | 1.0% | 0 | 0.3% |
| Kokgrop | 1,347 | 0.7% | 0 | 0.3% |

**`Stensättning`: soft-blacklist.** It is 29.6% of the dataset, and an
independent, non-Wikipedia signal confirms it is weak — under the *photograph*
label (Wikidata P18) it scores **0.26x lift** (151 photographed of 60,553), versus
`Gravfält` 2.71x and `Hög` 1.68x. The photographed examples are unnamed with
short descriptions; nothing stands out.

But it is not *zero* the way `Härd` (0 photographed) and `Kolningsanläggning`
(0 photographed) are: 1,215 are named and 151 are photographed. So exclude it by
default and keep it behind an escape hatch — `has_name OR photographed OR
board-proximate OR sitelinks > 0`. That drops ~59,000 sites of noise while
retaining the handful with independent positive evidence.

### Per-class lift under the photograph signal

Independent of Wikipedia article bias:

| class | n | photographed | lift |
|---|---|---|---|
| Gravfält | 267 | 7 | **2.71x** |
| Hög | 11,859 | 193 | **1.68x** |
| Hällristning | 18,741 | 114 | 0.63x |
| Röse | 14,587 | 88 | 0.62x |
| Stensättning | 60,553 | 151 | 0.26x |
| Fångstgrop | 18,151 | 2 | 0.01x |
| Härd | 11,962 | **0** | 0.00x |
| Kolningsanläggning | 11,870 | **0** | 0.00x |

Note `Hällristning` recovers to 0.63x here versus 0.2x under sitelinks — further
evidence that the Wikipedia labels understate rock carvings.

**Two conclusions that drive the design:**

1. *Visibility and legal status are not filters.* At 96.8% and 99.6% they remove
   almost nothing. The real discriminators are **folk name**, **class**,
   **geometry richness**, **board proximity** and **description quality**.
2. *Presence in Wikidata is worthless; sitelinks are gold.* 143,051 of the
   145,102 joinable items have zero sitelinks — they are a bulk FMIS import.
   The 2,048 with sitelinks are genuinely notable, joined by exact UUID, and
   graded (1–32 sitelinks). This is the calibration set.

---

## Data sources

| # | Source | Size | Status | Join key |
|---|---|---|---|---|
| A | `fornlamningar_full.gpkg` | 183 MB | have | `inspireid`, UUID from `legalfoundationdocument` |
| B | K-samsök raw JSON | ~0.65 GB compressed | crawling | UUID |
| C | OSM Sweden PBF | 906 MB | have | spatial only |
| D | Overpass targeted layers | a few MB | have boards | spatial only |
| E | Wikidata SPARQL (`P1260`) | ~10 MB | to do | **UUID (exact)** |
| F | Wikidata images (P18) + Commons | small | **done** | UUID / QID |

Sources C–F are all free and unmetered. B is the only expensive one, and it is
being cached permanently so it never needs repeating.

---

## Stage 0 — Acquire (mostly done)

| Step | Output | State |
|---|---|---|
| 0a GeoPackage | `src/data/fornlamningar_full.gpkg` | done |
| 0b K-samsök crawl | `src/data/ksamsok_raw.sqlite` | **running** |
| 0c OSM extract | `src/data/osm/sweden-latest.osm.pbf` | done, verified |
| 0d Overpass layers | boards / arch sites / wikidata-tagged | boards done |
| 0e Wikidata dump | UUID → QID, sitelinks, Commons cat, image | **done** |
| 0f Photograph labels | Wikidata P18, 3,136 sites | **done** |

**On finishing 0b:** compact the database, which currently wastes 45% to page
padding (2.3 KB rows on 4 KB pages, one row per page):

```
PRAGMA page_size=65536; VACUUM;
```

~1.35 GB → ~0.75 GB. Run only after the crawl exits.

**0e is the highest-value remaining step.** One SPARQL query returns UUID →
QID, sitelink count, and Commons category for 145k items. It is the only source
that joins to our data by exact identifier rather than by distance.

---

## Stage 1 — Parse (raw JSON → structured sites)

One row per UUID, derived from source B. Fully re-runnable offline; the raw
cache means a parser bug costs minutes, not another crawl.

Extract per site:

- **Identity** — uuid, inspireid, `Lämningsnummer`, `RAÄ-nummer`, Fornsök URL
- **Classification** — `itemClassName` (lämningstyp), `itemSuperType`, subjects
- **Description** — `Beskrivning`, plus `Skadestatus`, `Placering`,
  `Undersökningsstatus`, `Terräng`, `Orientering`, `Referens`
- **Assessment** — `Antikvarisk bedömning`, `Aktualitetsstatus`
- **Name** — `itemTitle`, `itemKeyword`
- **Geography** — WGS84 lon/lat from the GML in `ksam:coordinates`; parish,
  municipality, county, province **as separate columns with authority codes**
  (`.../municipality#1480`), not one concatenated string
- **Provenance** — `buildDate`, `lastChanged`, `dataQuality`, organisation

### Parser rules (each learned from an actual failure)

1. **Select nodes by `@type`, never by array index.** The `ksam:Entity` root was
   observed at index 0, 3, and 12 across four responses.
2. **`ksam:type` is `{"@language":"sv","@value":"Placering"}`** — read `@value`.
   Reading it as `@id` silently yields zero matches for everything.
3. **Blank-node IDs (`_:2b5293…`) are regenerated on every request.** Valid only
   for resolving references *within* one response. Never persist them, never key
   on them, never diff responses byte-wise.
4. **Strip the boilerplate disclaimer** (*"Beskrivningen är inte
   kvalitetssäkrad…"*) and set `description_is_boilerplate` when nothing else
   remains. Two of four sampled sites had *only* this text. Feeding it to an LLM
   is what produced the earlier hallucinated descriptions.
5. **`RAÄ-nummer` lives in `ItemNumber[type="RAÄ-nummer"]`.** The previous run
   wrote empty strings for all 1,491 rows and lost it.

**Verify:** every UUID in the raw table produces a row; count non-null per field
and eyeball the low-coverage ones; confirm `RAÄ-nummer` is populated this time.

---

## Stage 2 — Geometry

A UUID is **not** one point. It may carry a point, a line, a polygon, or several
at once, and 28.1% have no point at all. This stage must reduce all three layers
to one row per UUID that keeps the shape information rather than discarding it.

Per UUID, store:

- `has_point`, `has_line`, `has_polygon` — presence per layer
- `geom_types` — the combination (`P`, `A`, `L`, `AP`, `AL`, …)
- `centroid_e`, `centroid_n` — SWEREF99 TM metres; from the point if present,
  otherwise the polygon/line centroid
- `lon`, `lat` — WGS84, free from source B for every crawled site
- `env_width_m`, `env_height_m`, `env_area_m2` — from the GeoPackage envelope
  header (flags byte, bits 1–3; envelope type 1 = 4 doubles at offset 8)
- `polygon_wkb` (or a simplified ring) for the sites where edge distance matters

Notes:

- The GeoPackage columns named `longitude`/`latitude` **hold easting and northing
  in metres** (EPSG:3006), not degrees. This bug shipped last time.
- K-samsök returns a **single** coordinate even for area sites, so extent must
  come from the GeoPackage. The API coordinate is fine as a label anchor, not as
  geometry.
- **Store both** WGS84 degrees and SWEREF99 metres. Do all distance maths in
  SWEREF99 — metres are already metres, no cosine-latitude correction, no
  haversine.
- For any site not crawled, reproject SWEREF99 TM → WGS84.

**Distance to a polygon must be measured to its nearest edge, not its centroid.**
For a 453 m-tall polygon a board at the northern edge sits ~230 m from the
centroid — outside a 200 m threshold while physically *at* the site. The measured
1.03% board-proximity rate therefore **understates** coverage for the 28% that
are areas, and must be recomputed edge-wise in Stage 4.

---

## Stage 3 — Cluster (sites → destinations)

The unit a visitor cares about is a *place*, not a database record. A gravfält of
40 stensättningar is one destination sharing one signpost. Cluster **before**
scoring so signals aggregate correctly and nothing is double-counted.

- **Primary key: RAÄ-nummer prefix.** `Askim 268:1` and `Askim 268:2` are
  sub-parts of one registered site. Authoritative, free, from Stage 1.
- **Fallback: spatial clustering** (DBSCAN, ~100–200 m) where RAÄ-numbers are
  missing — **constrained to compatible classes**, so a charcoal pit is not
  merged into a burial mound.
- **Do not** use the `inspireid` suffix. Verified useless: 206,221 of 219,639
  points are `-1`, and only 1,498 L-number bases have more than one point. The
  suffix marks geometry parts, not related monuments.

Outputs a `clusters` table plus a site→cluster mapping. Per cluster: centroid,
member count, class mix, dominant class.

---

## Stage 4 — Signals

One table, keyed on cluster (with a site-level equivalent). **Store raw
measurements, never points.** Weighting belongs in a view, computed at query
time, so re-tuning is a query rewrite rather than a re-derivation.

| Group | Columns |
|---|---|
| Intrinsic | `class`, `class_is_visitable`, `description_len`, `description_is_boilerplate`, `has_measurements`, `has_name` |
| **Geometry** | `geom_types`, `geom_type_count`, `has_polygon`, `env_area_m2`, `env_width_m`, `env_height_m` |
| Access (OSM) | `dist_to_way_m` **(roads ∪ trails, 4.71x)**, `dist_to_board_m` (1.59x) |
| OSM identity | `osm_archsite_within_50m`, `osm_type`, `osm_wikidata_qid` |
| Wikidata | `wikidata_qid`, `sitelink_count`, `has_sv_wikipedia`, `has_en_wikipedia`, `commons_category` |
| Commons | `photo_count` |
| Density | `cluster_size`, `neighbors_500m`, `neighbors_1km` |

`geom_type_count > 1` and `has_polygon` earn **large** positive weights
(de-confounded lift **4.45x** and **3.81x**). Note this only became visible after
excluding runestones — with all classes included both signals read as *negative*
(0.76x, 0.65x). `env_area_m2` is retained for display and filtering, **not** as a
ranking signal — measured lift is ~1.2x. Having a polygon matters; how big it is
does not.

Plus **one `*_checked_at` timestamp per source group**, nullable. This makes each
source independently backfillable and resumable — same LEFT JOIN pending-set
pattern as the crawler. A Wikidata failure must not strand the OSM work.

---

### Stage 4 build notes (implemented)

**`dist_to_way_m` is the union of roads and trails**, not roads alone. Measured
separately: union **4.71x** national (18 m vs 84 m median), trails only 2.05x on
the Falkoping sample. Splitting them would penalise sites that are legitimately
trail-access-only, and the union is simply the better signal.

**Nearest *vertex* is not nearest *point*.** OSM vertices are dense in curves and
sparse on straights, so a site 30 m from the middle of a 1 km straight road
measures ~500 m against raw vertices. Every segment is densified to <=20 m
spacing (53,746,812 points nationally), bounding the error to ~10 m. The
densification is fully vectorised -- a per-segment Python loop over ~23M segments
is not viable.

**NULL distances mean "farther than the 5 km search cap", not "unknown".**
62,394 clusters have a NULL `dist_to_board_m` because the nearest board is over
5 km away. Scoring must treat NULL as *far*, not as missing data, or those
clusters get silently excluded from comparisons.

**Extraction is cheap.** `ogr2ogr` reads the 906 MB PBF and writes the
SWEREF99 way layer in **29 seconds**; boards in 5 seconds. There was no need for
`osmium`.

## Stage 5 — Labels

The calibration problem is solved by data, not by manual hunting.

**Primary label set: the UUID-joined Wikidata items with ≥1 sitelink** — 2,048
after cleaning, of which **1,967 match a UUID in the GeoPackage**. Better than
the 243 OSM-tagged sites on every axis:

- 8x larger
- joined on **exact UUID**, no spatial matching or ambiguity
- **graded** (1–15 sitelinks) rather than binary, so it trains a ranking
- independent of OSM mapper-density bias

Supporting weak positives: 2,374 OSM archaeological sites; ~3,071 board-proximate
sites. Negatives: random sample of the remaining ~308,000.

**Hand-label 20–30 sites you know personally as a *test* set only.** With 30
labels you cannot fit 15 weights — the rule of thumb is ~10 examples per feature,
supporting about 3. Fit on the weak labels; use your own judgement to check
whether the result is measuring visit-worthiness or merely fame.

Store in a `labels` table with `source` and `confidence`, so weak and hand labels
never get mixed.

### Extracting the label set (gotchas found in practice)

- The property is **`P1260`** ("Swedish Open Cultural Heritage URI"), *not*
  `P1262` ("RAÄ number", only 295 items in all of Wikidata).
- Values are stored as bare strings like `raa/lamning/<uuid>`, not full URLs, and
  **some carry an `html/` infix** (`raa/lamning/html/<uuid>`). Extract the UUID
  with a regex rather than a path split, or ~0.5% are silently lost.
- Use `?i wikibase:sitelinks ?c` for the graded count. Filtering `?c > 0` is what
  separates the 2,048 real articles from the 143,051 empty import stubs.
- ~81 labelled UUIDs do not appear in the GeoPackage (deprecated or superseded
  records). Left-join; do not assume a match.

**This label set is also the evaluation harness.** Every proposed signal should be
checked against it before being weighted — that is how multi-geometry was
confirmed (1.8x) and polygon area was demoted (1.2x, near noise). Measure first,
weight second.

### Known bias in every label source

All of these measure **documentation**, not **visit-worthiness**. Wikipedia
favours the famous (big runestones, royal mounds); OSM favours the well-mapped
south. A remote, unsignposted, genuinely spectacular site scores zero everywhere.
This is the plan's central weakness and the reason the hand-labelled test set
matters more than its size suggests.

---

## Stage 6 — Score

**Two axes, kept separate.** "Can I get there and find it?" and "is it worth the
trip?" need different evidence, and collapsing them to one number destroys both.

- **Accessibility** — board proximity, path/parking distance, visibility, class
- **Notability** — **folk name (8.54x, the dominant signal)**, multi-geometry
  (4.45x), has-polygon (3.81x), description length (1.72x), sitelinks, Commons
  photos, OSM presence, cluster size

**Filters as predicates, not deletions.** Compute all signals for all 311,847
rows and express every filter as `WHERE`. You will revise the 200 m radius and
the class blacklist repeatedly; if a filter ran destructively you could never
measure what it cost.

**Hard filters** (justified — near-certain exclusions):
- class on the invisible blacklist (`Kolningsanläggning`, `Fångstgrop`, `Härd`,
  `Fossil åkermark`, settlement remains)
- `Placering != Synlig ovan mark` (removes only 3.2%, but they are true negatives)
- `Antikvarisk bedömning = Ej kulturhistorisk lämning`

**Description quality: moderate weight, not a hard filter.**
`beskrivning_is_boilerplate` measures **0.44x** de-confounded (the headline 0.18x
was largely a runestone artifact — runestones nearly always have descriptions).
Gating on it removes 25.6% of sites at a cost of
**4.7% of known notables** (67 of 1,425), and a `has_name` escape hatch rescues
only 8 of those 67. Kungsringen is the cautionary case: a named site with a folk
name, a `Begravningsplats` class, and *nothing but* the disclaimer for a
description. Absence of a description means RAA never wrote one up — not that the
place is dull.

Use it as a large negative weight; gate on it only in Track A, where precision
matters more than recall.

**Not a hard filter: board proximity.** OSM board coverage tracks mapper density,
not sign density. As a gate it caps output at ~3,071 and systematically discards
well-signposted northern sites. Large positive weight instead.

**Run two tracks and compare:**
- **Track A** — board-gated, ~3,071 clusters, high precision. Ship this first.
- **Track B** — no board, but strong notability. Recovers what OSM has not mapped.

If Track B's top 200 stand up as well as Track A's, the gate was costing real
sites. That comparison is the experiment worth running.

**Watch `Vägmärke` (4.2% of all sites).** Milestones sit beside roads, which is
where information boards live — a false-positive generator built into the board
signal.

**Geometry weights, per measurement:** `geom_type_count > 1` gets a small
positive; `line + polygon` slightly more; `env_area_m2` gets none. Resist the
intuition that big polygons are better sites — it was tested and it is not
supported.

---

### Stage 6 results (implemented)

Weights are log-lifts measured at runtime on a **train half** of the labels and
evaluated on the held-out half. Runestones excluded from fitting.

| feature | lift | weight | sigma |
|---|---|---|---|
| `board_le_200` | **10.20x** | +2.32 | +17.8 |
| `has_name` | **5.22x** | +1.65 | +18.3 |
| `board_le_1km` | 3.71x | +1.31 | +15.3 |
| `way_le_25` | 2.13x | +0.75 | +11.8 |
| `desc_gt_300` | 1.93x | +0.66 | +12.5 |
| `way_le_100` | 1.55x | +0.44 | +12.0 |
| `multi_geometry` | 1.50x | +0.40 | +1.2 (not significant) |
| `multi_site` | 1.41x | +0.34 | +4.3 |
| `visible` | 1.03x | +0.03 | +3.5 |
| `all_boilerplate` | 0.65x | -0.44 | -4.1 |
| `soft_blacklist` | 0.62x | -0.48 | -4.6 |
| `way_remote` (>500 m) | 0.16x | -1.86 | -5.0 |
| `blacklisted` | **0.03x** | -3.66 | -12.5 |

**Held-out validation of `score_intrinsic`** (no label-derived features):
**AUC 0.8319**, 400 test positives among 149,442 clusters.

| k | recall | precision | lift |
|---|---|---|---|
| 100 | 2.5% | 10.00% | **37.4x** |
| 500 | 7.5% | 6.00% | 22.4x |
| 1000 | 11.0% | 4.40% | 16.4x |
| 5000 | 34.2% | 2.74% | 10.2x |

68,431 of 151,291 clusters (45.2%) survive the filters.

**Leakage discipline.** `sitelinks`, `has_image` and `has_commons` ARE the label
sources, so they cannot be validated against the labels without circularity.
Two scores are therefore emitted: `score_intrinsic` (no label-derived features,
honestly validatable) and `score_full` (adds them, better for production ranking
because an article genuinely is evidence).

**Signals measured and dropped:**
- `neighbors_1km` -- **0.94x lift, sigma -0.7. No signal at all.** Spatial density
  of other remains says nothing about whether a place is worth visiting. This was
  an intuitive favourite and it is simply not supported.
- `env_area_m2` -- ~1.2x. Having a polygon matters slightly; its size does not.
- `multi_geometry` survives at 1.50x but **sigma +1.2 is not significant** at
  cluster level, despite 4.45x at site level. Clustering absorbs it.

**Class tuning still open.** The top undocumented results include
`Hyttområde`, `Hammarområde`, `Dammvall`, `Vägmärke`, `Gränsmärke` and
`Lägenhetsbebyggelse` -- industrial and boundary markers that are well-described
and roadside but arguably not destinations. Whether they belong is a judgement
call, not a data question.

### Ground truth: the board signal does not measure signage

Six hand-verified sites (`hand_labels.csv`) overturned an assumption. Four are
confirmed **to have signs on site**, yet their nearest OSM board is 1,134-3,029 m
away -- and this is in Kungsbacka, which has **6x the national board density**
(4.10 vs 0.69 boards per 100 km2). So it is not a local mapping gap:
`tourism=information` nodes in OSM sit at trailheads, nature reserves and town
centres, **not at fornlamningar**.

The 10-12x lift is real, but it proxies "in a visited area", not "is signposted".
Access weights are therefore capped at **+/-1.2** (`ACCESS_WEIGHT_CAP`). Capping
improved both the held-out metric and the ground truth simultaneously:

| | AUC | recall@100 lift | Fjaaraas 41 rank | Hanhals 65 rank |
|---|---|---|---|---|
| before class/keyword weights | 0.832 | 37.4x | 16,244 | 27,266 |
| + class weights | 0.879 | 41.1x | 3,345 | 19,471 |
| + description keywords | 0.878 | 56.0x | 656 | 19,896 |
| + capped access weights | **0.886** | **63.4x** | **416** | **2,856** |

Absence of a board carries almost no information. Presence still earns a bonus.

### Unmerged Wikidata duplicates are a false-negative source

**Hunehals borg** (`L1997:4707`) has Swedish and Norwegian Wikipedia articles on
`Q10527196` -- which carries **no P1260 and no P1262**. The RAA-linked item
`Q29367947` is a separate, empty FMIS import stub with zero sitelinks. The UUID
join therefore lands on the stub and labels a notable castle as a negative.

Mitigation not yet implemented: a spatial join against Wikidata items that have
coordinates and sitelinks. A probe found only 403 Swedish heritage items with
both an article and coordinates under a narrow `P31` filter, so the recall gain
may be modest; a broader class list is worth trying.

## Stage 7 — the runner, and the app

### The pipeline runner was dropped, deliberately

The original plan bundled two unrelated things under "Stage 7": a Jenkins-style
**job runner** for the pipeline, and the **app frontend**. They have opposite
verdicts.

The runner is **not built and should not be**. It was scoped when the crawl was
expected to be long and flaky, needing live monitoring and error triage. What
actually happened:

| assumed | actual |
|---|---|
| long, fragile crawl with retries | 4 h, run once, 311,845 responses, **2 dead** |
| heavy derivation | **~4 minutes**, all five stages |
| errors to triage | zero failures across 311k requests |

A Fastify + SSE + job-DAG + state-DB + dashboard is days of work to orchestrate
five scripts that finish in four minutes and do not fail. The genuinely valuable
part -- resumability -- already lives inside the crawler as a derived pending
set. Progress is already legible on stdout.

Replaced by **`run_pipeline.sh`** (~30 lines): runs the five stages in order with
per-stage timing, `--from N` to resume mid-chain, and `--json` to emit JSONL for
any future UI. The crawl stays a separate run-once job.

```
./run_pipeline.sh                # all stages, ~4 min
./run_pipeline.sh --from score   # re-score onward
```

That verdict held. What changed is the stage count: the runner now has nine,
because the stages that build the product were missing from it for a month --
see README.md. `--from` takes a name because the numbers shifted when they
were added.

### The app is built, and it is not the web

This section used to describe the product as a frontend in the `franco-may`
Next.js site, and that is the one thing in this document worth correcting
rather than annotating, because it names the wrong artefact.

**The product is an Android app**, `fornlamningar-app`: React Native (Expo) +
MapLibre, installed on a phone, working in a field with no signal. The web
map in `franco-may` still exists and is useful, but it is not what the
project is for -- the problem that started this was Fornsök's map being
unusable **on mobile**.

What the plan above got right, and what it got wrong, both worth keeping:

- **Map.** Right that 245,860 clusters must never ship as JSON. Wrong about
  the mechanism: the app ships the top 10,000 as a single 2.6 MB GeoJSON
  source and lets MapLibre tile it ON DEVICE, which is better than the
  tippecanoe tiles the web uses -- tippecanoe decides at BUILD time which
  points survive each zoom, and the device decides at RENDER time, which is
  what lets hiding a family backfill the space with the next-best site
  instead of leaving a hole.
- **Ranking.** As planned: `score_intrinsic`.
- **Filters.** As planned, plus one the plan could not have predicted: stars,
  which are the model's percentile until visitors have rated a place and the
  visitors' mean afterwards.
- **Per site.** As planned, and the description is generated rather than the
  register's raw text wherever one exists.
- **Signage.** Confirmed: there is no dataset, checked with a county
  antiquarian. Crowdsourced in-app through the question queue, as planned.
- **AI descriptions.** Built, and NOT limited to the shortlist: 9,220 places
  have one, generated by a local model in ~13 h, with the sources and the
  payload hash recorded so a description knows what it was built from. The
  prompt does forbid inference beyond the sources, which was the right
  instinct.

## Open decisions

1. ~~**PBF parser.**~~ **Resolved.** GDAL 3.12.2 is working (after
   `brew reinstall re2 abseil`) and ships the **OSM driver** (`ogrinfo --formats`
   lists `OSM -vector- (rov)`), plus GPKG and reprojection. No `osmium`,
   `pyosmium` or `pyproj` needed — `ogr2ogr` covers the PBF, the GeoPackage and
   SWEREF99 -> WGS84 in one already-installed tool.
2. **Class blacklist contents.** Needs a pass over the full class distribution
   once the crawl finishes, ideally with your own judgement per class.
3. **Cluster radius** (100 m? 200 m?) and which classes may merge.
3b. **Polygon edge distance** — needs real geometry, not just envelopes, for the
   ~90,000 polygon sites. Envelope-based distance is a cheap first approximation;
   decide whether exact ring distance is worth the extra work.
4. **Keep or drop `raw_json`** after Stage 1 stabilises. Dropping reclaims
   ~0.65 GB; keeping means parser changes never require re-crawling.
5. **Per-county fornvårdsprogram** from Länsstyrelsernas Geodatakatalog — 21
   separate datasets, uneven, some access-restricted (`Felaktig behörighet` when
   tried). Worth it only for target counties.
6. ~~**AI descriptions.**~~ **Built.** See `build_descriptions.py` and
   `describe_place.py`, and the section above for what the plan got wrong
   about them.

---

## Storage budget

| Artifact | Size | Versioned? |
|---|---|---|
| `fornlamningar_full.gpkg` | 183 MB | yes (LFS), it is the seed |
| `ksamsok_raw.sqlite` | ~0.75 GB after VACUUM | **no** — gitignored cache |
| `sweden-latest.osm.pbf` | 906 MB | **no** — gitignored cache |
| Parsed sites + signals + clusters | tens of MB | **yes** — the actual work |

Both large caches are already in `.gitignore`. Only derived tables belong in
version control; committing 1.7 GB of regenerable cache to LFS is the trap that
cost disk space before.
