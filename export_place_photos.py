"""Write every photograph we hold, for the admin's fl_photos table.

    python3 export_place_photos.py                 # -> /tmp/fl_photos.jsonl.gz
    python3 export_place_photos.py --out /tmp/x.gz

The app does not read this. It still receives six photographs, chosen later
from the ones a person marked here. The loader is
../franco-may/scripts/load-fl-photos.cjs, because that is where the
database credential lives; this side only reads places.sqlite.

WHICH PLACES: every cluster, under its representative uuid. That is the id
the admin page and the phone both use, and it is the uuid the published
descriptions are keyed by.

WHICH PHOTOS: every usable image with a URL a browser can request,
including geosearch. A county PDF name with no URL is left out. The order
is the same one the app uses when nobody has marked anything, so the first
thumbnails on the page are the ones that would ship today.

A Commons file is stored as a 320px Special:FilePath. The admin browser can
ask for that width. The phone cannot, and it never sees this URL: it still
rebuilds the thumbnail Commons itself returned. An archive record keeps the
thumbnail the crawl stored. For SHFA that file is the original jpeg.
"""
import argparse
import gzip
import json
import os
import sqlite3
import urllib.parse

import paths

ORDER = """
    CASE i.source WHEN 'commons_wikidata' THEN 0
                  WHEN 'arkiv' THEN 1
                  WHEN 'county_pdf' THEN 2
                  WHEN 'county_page' THEN 3
                  ELSE 4 END, i.image_id
"""


def thumb_for(file, thumb, image):
    if file.startswith("File:"):
        name = urllib.parse.quote(file[5:], safe="-_.!~*'()")
        return (
            "https://commons.wikimedia.org/wiki/Special:FilePath/"
            f"{name}?width=320"
        )
    return thumb or image or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/fl_photos.jsonl.gz")
    args = ap.parse_args()

    db = sqlite3.connect(f"file:{paths.PLACES}?mode=ro", uri=True)
    rows = db.execute(f"""
        SELECT f.uuid, i.cluster_id, i.source, i.file, i.author, i.licence,
               i.page_url, i.thumb_url, i.image_url
          FROM images i
          JOIN features f ON f.cluster_id = i.cluster_id
         WHERE i.usable = 1
           AND i.file IS NOT NULL AND i.file <> ''
           AND i.source <> 'county_pdf'
           AND f.uuid IS NOT NULL AND f.uuid <> ''
         ORDER BY i.cluster_id, {ORDER}
    """)
    seen = set()
    n = 0
    places = set()
    ord_of = {}
    with gzip.open(args.out, "wt", encoding="utf-8") as out:
        for uuid, cid, source, file, author, licence, page, thumb, image in rows:
            key = (uuid, source, file)
            if key in seen:
                continue
            url = thumb_for(file, thumb, image)
            if not url:
                continue
            seen.add(key)
            n_ord = ord_of.get(uuid, 0)
            ord_of[uuid] = n_ord + 1
            out.write(json.dumps({
                "place_uuid": uuid,
                "cluster_id": cid,
                "source": source,
                "file": file,
                "thumb": url,
                "page": page or None,
                "author": author or None,
                "licence": licence or None,
                "ord": n_ord,
            }, ensure_ascii=False) + "\n")
            n += 1
            places.add(uuid)
    print(f"{n} photographs for {len(places)} places "
          f"-> {args.out} ({os.path.getsize(args.out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
