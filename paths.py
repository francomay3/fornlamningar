"""Every database path in the pipeline, and what tier each one belongs to.

Before this file each script carried its own string constant, so renaming a
database meant editing twenty scripts and hoping. More importantly the names
said what a file CONTAINED, which told you nothing about whether you were
allowed to delete it. These names say where the file's authority comes from,
which is the only thing you need to know to answer that question.

    RAW       Downloaded from someone else. We never edit it, only re-fetch
              it. Expensive in wall-clock and rude to re-request casually, so
              it stays on disk indefinitely and out of git.

    EXPENSIVE Ours, but costly to reproduce -- generated.sqlite is thirteen
              hours of local model time. Derived in principle, cache in
              practice, and tracked in LFS for that reason.

    WORK      Ours and cheap. `run_pipeline.sh` rebuilds it in about four
              minutes, so it is never precious and never committed. Every
              measurement, signal and score lives here.

    PRODUCT   places.sqlite. One row per visitable place, with the text,
              the images and the provenance of both. This is the thing we
              are actually building; the app is a way to look at it.

    PAYLOAD   What ships to a phone. Pure function of PRODUCT, regenerated
              on every export, and small enough that it is disposable.
"""

import os

DATA = "src/data"

# --- RAW -------------------------------------------------------------------
RAA_EXPORT = os.path.join(DATA, "raa_export.gpkg")      # the RAA export
RAA_API = os.path.join(DATA, "raa_api.sqlite")          # 311,845 API responses
LANSSTYRELSEN = os.path.join(DATA, "lansstyrelsen.sqlite")
WIKIMEDIA = os.path.join(DATA, "wikimedia.sqlite")

# --- EXPENSIVE -------------------------------------------------------------
GENERATED = os.path.join(DATA, "generated.sqlite")      # model output

# --- WORK ------------------------------------------------------------------
WORK = os.path.join(DATA, "work.sqlite")                # sites, clusters,
                                                        # signals, scores

# What build_tiles.py hands to tippecanoe. Cheap and derived, but named here
# because the app's sync-assets.sh REQUIRES it to still be on disk after an
# export -- see run_pipeline.sh, which passes --keep-geojson for that reason.
GEOJSON = os.path.join(DATA, "tiles_input.geojsonl")

# --- PRODUCT ---------------------------------------------------------------
# features, images, sources, generation_sources. The corpus is not a side
# table: one place's rows are the reason its description reads the way it
# does, so they live in the same file as the description.
PLACES = os.path.join(DATA, "places.sqlite")

# --- PAYLOAD ---------------------------------------------------------------
WEB = os.path.expanduser("~/projects/franco-may")
TILES = os.path.join(WEB, "public/tiles")
DESCRIPTIONS = os.path.join(WEB, "public/descriptions")
FILTER_FAMILIES = os.path.join(WEB, "app/fornlamningar/filterFamilies.ts")

# There is no constant for the app's assets/data on purpose. The only thing
# that writes there is the app repo's own sync-assets.sh, which is bash and
# cannot read this file; a Python name for it would be a second copy of a
# path with nothing importing it -- which is what the deleted APP_DATA was.


def ro(path):
    """A read-only URI, so a reader cannot create the file by opening it.

    sqlite3.connect() on a missing path silently makes an empty database,
    which is how src/data/labels.sqlite came to exist as a zero-byte file
    that looked like a real one.
    """
    return f"file:{path}?mode=ro"
