#!/usr/bin/env python3
"""Move or withdraw comments that describe a different remain, and the rating with them.

Reads the JEV flags in ~/fl-scratch/comment_flags.jsonl. A comment moves only
when one nearby register record is clearly the thing it describes, and the
map pin for that record is a different place. Otherwise, if the comment is
about something the register does not have here, both the comment and the
rating are withdrawn. A comment that does describe this place is left alone.

Withdrawing is `comment_delete` and `rating_delete` in the contribution log.
Moving is those two, then a new comment and a new rating on the other place.
Same author, so the phone still shows them as yours.

    python apply_comment_fixes.py            # print the plan
    python apply_comment_fixes.py --apply    # write it
"""

import argparse
import json
import math
import re
import sqlite3
import uuid

import paths
from crawl_contributions import database_url, query

FLAGS = __import__("os").path.expanduser("~/fl-scratch/comment_flags.jsonl")

# Judged by reading the comment against the sites around the pin.
# move's second value is the lamningsnummer of the remain it actually describes.
HAND = {
    "L2017:9032": ("keep",),  # cows, a path, the lake
    "L2003:5127": ("delete",),
    "L1996:723": ("delete",),
    "L2010:135": ("keep",),  # the sound, not the fort
    "L1945:9107": ("keep",),  # skiing past the houses
    "L2017:1870": ("move", "L2017:1376"),
    "L2015:4886": ("delete",),
    "L1989:5451": ("delete",),
    "L1979:3234": ("keep",),
    # The chamber grave is already a member of this pin.
    "L1969:1488": ("keep",),
    "L2015:9723": ("move", "L2014:1993"),
    "L1963:2281": ("keep",),
    "L1968:2060": ("keep",),  # the view from the hill
    "L2014:1694": ("delete",),
    # The four remaining stones are this grave field, not Gårdlösa.
    "L1991:4887": ("keep",),
    "L2019:2802": ("move", "L2015:9358"),
    "L1975:9055": ("move", "L1975:9068"),
    "L2022:5624": ("keep",),  # the walk up the mountain
    "L2016:5813": ("delete",),
    "L2011:5664": ("delete",),
    "L1973:2944": ("delete",),
    "L1963:1637": ("delete",),
    "L1983:6409": ("delete",),
    "L1954:2747": ("keep",),
    "L1964:4421": ("delete",),
    "L1948:8779": ("move", "L1951:5081"),
    "L1996:7843": ("move", "L1996:445"),
    "L1961:369": ("delete",),
    "L2021:8868": ("delete",),
    "L1969:4003": ("keep",),  # camping, sunset, swimming
    # The furnace site is already a member of this pin.
    "L2006:2659": ("keep",),
    "L1980:4864": ("move", "L1980:4706"),
    "L1957:9633": ("delete",),
    "L1966:8694": ("delete",),
    "L1953:6468": ("delete",),
    "L1966:9012": ("keep",),
    "L2013:1260": ("delete",),
    "L1969:5473": ("keep",),
    # U379 stands in this cluster. U380 and U381 are the next pin.
    "L2015:2808": ("keep",),
    "L1989:3041": ("delete",),
    "L1977:7981": ("keep",),
    # The execution site is already a member of this pin.
    "L2000:2448": ("keep",),
    "L1961:8834": ("delete",),
    "L1961:9411": ("delete",),
    "L1997:6368": ("delete",),
    "L1955:3092": ("delete",),
    # The bridge is already a member of this pin.
    "L1991:3797": ("keep",),
    "L1965:7209": ("delete",),
    "L2012:3391": ("delete",),
    "L1960:7252": ("keep",),
    "L2013:2714": ("keep",),
    "L2012:407": ("delete",),
    "L1977:1622": ("delete",),
    "L2023:6639": ("delete",),
    # The cup marks are the carving already on this pin.
    "L1987:1339": ("keep",),
    "L1973:2438": ("keep",),
    "L1973:2422": ("keep",),
    "L1944:2700": ("keep",),
    "L1983:3133": ("keep",),  # the walk along the rod line
    "L2016:7393": ("delete",),
    "L1963:9924": ("delete",),
    "L1953:2287": ("keep",),  # the forest and the lake
    "L1958:492": ("keep",),  # a quiet place to camp
    "L1978:1896": ("delete",),
    # The passage grave is already a member of this pin.
    "L1962:5064": ("keep",),
    # The text is the Seby runestone. "Ekeby fornborg" is where the
    # visitor was headed, and the stone is already on this pin.
    "L1957:9686": ("keep",),
    # The text is about the memorial stones. "slott" is how a review
    # described them, not a castle 378 m away.
    "L1987:8155": ("delete",),
    # Landscape, or the visit, and not some other remain.
    "L1990:4657": ("keep",),  # an empty field and a cross
    "L1988:5411": ("keep",),  # the park
    "L1951:1185": ("keep",),  # the hill and the view
    "L1955:4360": ("keep",),  # the walk over the rocks
    "L1977:8517": ("keep",),  # the view south
    "L1975:851": ("keep",),   # the sea and the sunset
}

RULES = [
    (r"kvarn|mölla|molla", "Kvarn"),
    (r"kyrkoruin", "Kyrka/kapell"),
    (r"källa|trefaldighets", "Källa med tradition"),
    (r"fornborg", "Fornborg"),
    (r"runsten|runristning|runinskrift", "Runristning"),
    (r"hällristning|skålgrop|skalgrop", "Hällristning"),
    (r"skeppssättning|skeppsättning|stone ship", "Stenkrets/stenrad"),
    (r"gånggrift|ganggrift|\bdös\b|hällkista", "Stenkammargrav"),
    (r"gravfält|gravfalt", "Gravfält"),
    (r"\bkloster", "Kloster"),
    (r"kyrkstall|hospital|\bpark\b|\bfyr\b|restaurang", None),
    (r"\bkyrka|\bkapell", "Kyrka/kapell"),
    (r"fästning|\bskans\b", "Fästning/skans"),
    (r"\bslott\b", "Slott/herresäte"),
    (r"stenbro", "Bro"),
    (r"luftvärn|skyttevärn", "Stridsvärn"),
    (r"\bröse\b", "Röse"),
    (r"labyrint", "Labyrint"),
    (r"domarring", "Stenkrets/stenrad"),
]


def subject(text):
    t = text.lower()[:280]
    for pat, cls in RULES:
        if re.search(pat, t):
            return cls
    return "??"


def hav(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class World:
    def __init__(self):
        self.work = sqlite3.connect(paths.ro(paths.WORK), uri=True)
        self.places = sqlite3.connect(paths.ro(paths.PLACES), uri=True)
        self.src = sqlite3.connect(paths.ro(paths.CONTRIBUTIONS), uri=True)

    def cluster(self, uuid):
        row = self.work.execute(
            "SELECT cluster_id FROM site_clusters WHERE uuid = ?", (uuid,)
        ).fetchone()
        return row[0] if row else None

    def pin_of_lamn(self, lamn):
        row = self.work.execute(
            "SELECT uuid FROM sites WHERE lamningsnummer = ?", (lamn,)
        ).fetchone()
        if not row:
            return None
        cl = self.cluster(row[0])
        if not cl:
            return row[0]
        feat = self.places.execute(
            "SELECT uuid FROM features WHERE cluster_id = ? AND excluded = 0",
            (cl,),
        ).fetchone()
        return feat[0] if feat else row[0]

    def classes_near(self, it, classes):
        lat, lon = it["lat"], it["lon"]
        cur = self.cluster(it["uuid"])
        rows = []
        for cls in classes:
            rows += self.work.execute(
                """
                SELECT uuid, lamningsnummer, lat, lon FROM sites
                 WHERE class_sv = ?
                   AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
                """,
                (cls, lat - 0.03, lat + 0.03, lon - 0.06, lon + 0.06),
            ).fetchall()
        same = False
        diff = []
        for u, num, slat, slon in rows:
            if u == it["uuid"]:
                continue
            metres = hav(lat, lon, slat, slon)
            if metres > 2000:
                continue
            cl = self.cluster(u)
            if cl == cur:
                if metres <= 800:
                    same = True
                continue
            dest = self.pin_of_lamn(num)
            if not dest or dest == it["uuid"]:
                same = True
                continue
            diff.append((metres, num, dest))
        diff.sort()
        return same, diff


def classes_for(subj):
    if subj == "Stridsvärn":
        return ["Stridsvärn", "Område med militära anläggningar"]
    if subj == "Slott/herresäte":
        return ["Slott/herresäte", "Borg", "Fästning/skans"]
    if subj == "Fästning/skans":
        return ["Fästning/skans", "Borg", "Slott/herresäte"]
    if subj == "Kvarn":
        return ["Kvarn", "Småindustriområde"]
    return [subj]


def decide(world, it):
    """('keep',) or ('delete',) or ('move', dest_uuid)."""
    hand = HAND.get(it["lamn"])
    if hand:
        if hand[0] != "move":
            return hand
        dest = world.pin_of_lamn(hand[1])
        if not dest or dest == it["uuid"]:
            return ("keep",)
        return ("move", dest)
    subj = subject(it["comment"])
    if subj == it["class"] or (subj == "??" and (it["conf"] or 0) < 0.4):
        return ("keep",)
    if subj is None:
        return ("delete",)
    if subj == "??":
        return ("keep",)
    same, diff = world.classes_near(it, classes_for(subj))
    if same and (not diff or diff[0][0] > 400):
        return ("keep",)
    if not diff:
        return ("delete",)
    best = diff[0]
    second = diff[1][0] if len(diff) > 1 else 99999
    if best[0] <= 800 and second > best[0] + 350:
        return ("move", best[2])
    return ("keep",)


def load_items():
    src = sqlite3.connect(paths.ro(paths.CONTRIBUTIONS), uri=True)
    items = []
    for line in open(FLAGS, encoding="utf-8"):
        rec = json.loads(line)
        if rec.get("choice") != "no":
            continue
        comment = rating = author = None
        stars = visited = None
        for kind, event_id, payload, who in src.execute(
            """
            SELECT kind, event_id, payload, author FROM events
             WHERE place_uuid = ? AND kind IN ('comment', 'rating')
            """,
            (rec["uuid"],),
        ):
            body = json.loads(payload)
            author = who
            if kind == "comment":
                comment = (event_id, body.get("body") or "")
            else:
                rating = event_id
                stars = body.get("stars")
                visited = body.get("visited")
        if not comment or not rating or stars is None:
            continue
        items.append({
            "uuid": rec["uuid"],
            "lamn": rec["lamningsnummer"],
            "class": rec["class_sv"],
            "conf": rec.get("confidence") or 0,
            "lat": rec["lat"],
            "lon": rec["lon"],
            "comment": comment[1],
            "comment_id": comment[0],
            "rating_id": rating,
            "stars": stars,
            "visited": visited,
            "author": author,
        })
    src.close()
    return items


def events_for(it, action):
    author = it["author"]
    out = []
    out.append({
        "kind": "comment_delete",
        "place_uuid": it["uuid"],
        "author": author,
        "payload": {"target_event_id": it["comment_id"]},
    })
    out.append({
        "kind": "rating_delete",
        "place_uuid": it["uuid"],
        "author": author,
        "payload": {"target_event_id": it["rating_id"]},
    })
    if action[0] == "move":
        rating = {"stars": it["stars"]}
        if it["visited"] is not None:
            rating["visited"] = it["visited"]
        out.append({
            "kind": "comment",
            "place_uuid": action[1],
            "author": author,
            "payload": {"body": it["comment"]},
        })
        out.append({
            "kind": "rating",
            "place_uuid": action[1],
            "author": author,
            "payload": rating,
        })
    return out


def write(url, batch):
    records = []
    for i, ev in enumerate(batch, start=1):
        records.append({
            "i": i,
            "event_id": str(uuid.uuid4()),
            "kind": ev["kind"],
            "place_uuid": ev["place_uuid"],
            "author": ev["author"],
            "payload": json.dumps(ev["payload"], ensure_ascii=False),
        })
    n = len(records)
    rows = query(url, """
        WITH bump AS (
          UPDATE fl_event_seq SET v = v + $1 WHERE id = 1 RETURNING v
        ),
        ins AS (
          INSERT INTO fl_events
            (seq, event_id, kind, place_uuid, author, payload)
          SELECT b.v - $1 + x.i,
                 x.event_id::uuid,
                 x.kind,
                 x.place_uuid,
                 x.author,
                 x.payload::jsonb
            FROM bump b
            CROSS JOIN jsonb_to_recordset($2::jsonb) AS x(
              i int, event_id text, kind text,
              place_uuid text, author text, payload text
            )
          RETURNING seq::text AS seq, event_id::text AS event_id, kind,
                    place_uuid, author, payload::text AS payload,
                    server_ts::text AS server_ts
        )
        SELECT * FROM ins ORDER BY seq
    """, [n, json.dumps(records)])
    return rows


def mirror(rows):
    conn = sqlite3.connect(paths.CONTRIBUTIONS)
    conn.executemany(
        """
        INSERT OR REPLACE INTO events
          (seq, event_id, kind, place_uuid, author, payload, client_ts, server_ts)
        VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
        """,
        [
            (int(r["seq"]), r["event_id"], r["kind"], r["place_uuid"],
             r["author"], r["payload"], r["server_ts"])
            for r in rows
        ],
    )
    top = max(int(r["seq"]) for r in rows)
    conn.execute(
        "UPDATE sync SET cursor = MAX(cursor, ?), at = datetime('now') WHERE id = 1",
        (top,),
    )
    conn.commit()
    conn.close()


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    world = World()
    plan = []
    counts = {"keep": 0, "delete": 0, "move": 0}
    for it in load_items():
        action = decide(world, it)
        counts[action[0]] += 1
        if action[0] == "keep":
            continue
        plan.append((it, action))
    print(
        f"{counts['move']} to move, {counts['delete']} to withdraw, "
        f"{counts['keep']} left as they are"
    )
    if not args.apply:
        return
    batch = []
    for it, action in plan:
        batch.extend(events_for(it, action))
    print(f"writing {len(batch)} events", flush=True)
    rows = write(database_url(), batch)
    mirror(rows)
    print(f"wrote {len(rows)} events, seq through {rows[-1]['seq']}")


if __name__ == "__main__":
    main()
