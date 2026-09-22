# Notes for whoever works on this next

Read [README.md](README.md) for what the pipeline is, [NOMENCLATURA.md](NOMENCLATURA.md)
for the words, [PIPELINE.md](PIPELINE.md) for measurements that must not be
re-decided. This file is only the operational bits that are not in those.

## Repos

| path | what it is |
|---|---|
| `fornlamningar` (here) | the pipeline. Remote: `github.com/francomay3/fornlamningar` |
| `../fornlamningar-app` | the Android app. **No git remote.** Do not invent one |
| `../franco-may` | web map and the sync API the phone calls (`https://franco-may.com`). The name does not start with `fornlamningar-` and it is still the third repo |
| `../fornlamningar-google` | **not a codebase.** Two CSVs left after a finished Google Maps review fetch (`fornlamningar.csv`, `comentarios.csv`). The scripts were deleted on purpose. Do not recreate them, and do not join those reviews onto RAÄ — that was left to Franco |

## The full run, 2026-09-21

```
./run_pipeline.sh --desc-args --force      # started 16:23, detached (parent pid 1)
```

Finished 2026-09-22 14:01, **21 h 43 m**. Thirteen stages; two of them are the
whole cost:

```
signals    10m 51s      descriptions   9h 12m
score         54s       translate     12h 11m
places        14s       tiles+assets+release   15s for all three
```

Output: generation 11, `src/data/releases/11/`, `releases/latest -> 11`,
12,274 Swedish descriptions and 10,649 English. On the phone since 14:12.

`--desc-args --force` puts `--force` on the Swedish generation stage only;
translate does not receive it. Never start a second runner while a
`run_pipeline.sh` pid is alive: both write `generated.sqlite`.

Four operational things that cost time on this run and will cost it again:

* **Do not edit `run_pipeline.sh` while it is running.** Bash reads the file
  by offset as it goes, so a commit mid-run shifts those offsets and the rest
  parses as garbage. `c161c52` landed six hours in. The data stages still
  finished, but the script wrote generation 10, wrote 11 with the same bytes,
  and died before printing `pipeline complete`. 10 is a duplicate, left in
  place because a release directory is immutable.
* **`src/data/pipeline_run.log` is not this run's log.** It is an older one,
  and its tail ends in a perfectly plausible `pipeline complete` naming
  generation 3 — which is exactly the kind of stale output that gets believed.
  A detached run writes to `/private/tmp/pipeline_full.log`; the path is not in
  the repo, and `lsof -p <pid of bash run_pipeline.sh>` is how it was found.
  Trust `releases/latest` and `src/data/generation`, which are current by
  construction.
* **The monitor is the way to read progress**, not the log:

  ```
  python3 pipeline_progress.py            # --watch to follow
  ```

  On a run that has already finished it prints `no sign of life for Nm`. That
  is a false alarm: it counts silence without checking whether every stage is
  done. Read the stage list above it, not the warning.
* **Counting rows is not counting progress.** Under `--force` the monitor once
  reported 98.5% at minute one of a fourteen-hour run, because it counted
  `prompt_version` — which every already-existing row matched. It now counts
  `created_at >= <run stamp>`. A monitor that cannot tell "finished" from "was
  already there" manufactures confidence.

## Getting that run onto the phone

The phone does not download a release. `make_release.py` writes
`src/data/releases/<generation>/` and stops. Its own comment says upload is
undecided (R2 vs Vercel Blob) and it touches no network. The app bundles
`assets/data/` and recopies them when `ASSET_VERSION` changes, so new
descriptions reach the phone only inside a new APK. There is no recorded way
to push a release to the phone without a USB install, and no upload step for
`src/data/releases/` should be invented.

```
cd ../fornlamningar-app
npm run build:android
npm run install:android
```

`npm run` is what every install here has used. Yarn still owns `node_modules`
(see the app README); do not `npm install`. The device is `RFCY20FC1VP`
(`SM_S931B`, Galaxy S25) over USB; `adb` is
`~/Library/Android/sdk/platform-tools/adb`. On 2026-09-22 it came up
`unauthorized` until the prompt on the phone was accepted — nothing on the
computer can tap it.

Whether the APK actually contains the new data is a separate question from
whether the build succeeded, and `../fornlamningar-app/AGENTS.md` has the two
commands that answer it. Short version: a build that takes twenty seconds
rebuilt nothing, and that is fine as long as `sync-assets.sh` ran before it.
