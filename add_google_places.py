#!/usr/bin/env python3
"""Google Maps places that were never linked to a register record.

One shot, not a pipeline stage. The coordinates are drawn once from the
place id and stored. A later pipeline run does not move them, and it
does not rebuild `sites`, so these rows stay. A hand `build_sites.py`
drops `sites` and calls `ensure_stored` afterwards, so the rows come
back. `build_sources.py` reads this file for the investigation note,
the Wikipedia lead and the other pages.

The set is the unassigned rows of fornlamningar.csv with at least 3 stars
and more than 4 reviews. Each place gets a new uuid. The comment is stored
as an investigation source. Wikipedia is added when a search hit is actually
this place. Nearby Commons photographs, photographs on that article, and a
Commons search for the name go to the admin drawer.

Rerunning is safe: a place id already in google_places.jsonl is skipped,
and the database inserts ignore a row that is already there.
"""

import csv
import gzip
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import uuid

import paths
from crawl_contributions import database_url
from crawl_wikimedia import DELAY, GEO_RADIUS_M, commons_meta, cut_tail, get, section_of

CSV = os.path.expanduser("~/projects/fornlamningar-google/fornlamningar.csv")
OUT = os.path.join(paths.DATA, "google_places.jsonl")
DESC_DIR = os.path.join(paths.WEB, "public", "descriptions")
# The admin account the earlier corrections were written under.
ADDED_BY = "vQCtnlYDZPa5uilEqDT8IVwA5V92"
BYSA = ("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/")
# 90% of the Rayleigh draw falls inside 5 m. Drawn from the place id, so
# the pin does not move the next time this file is read.
JITTER_SIGMA_M = 5 / math.sqrt(-2 * math.log(0.1))
NEARBY = 24
ARTICLE_PHOTOS = 12
SEARCH_PHOTOS = 8
MAX_PHOTOS = 36
MIN_PX = 120

STOP = frozenset("""
kyrka kyrkoruin church ruin ruiner grav grave gravfalt hog hogarna
bastion skans skansen fortet
stone sten runsten runestone castle slott borg fornborg museum park
old gamla gammal nya nya new stora lilla norra sodra ostra vastra
sankt saint santa the och med vid from sweden sverige ancient historical
historic monument site plats village torp kapell chapel hill mound
stones rocks rock and den det att som till fran from area naturreservat
nature reserve viking vikingatid
""".split())
BAD_LICENCE = ("non-free", "nonfree", "fair use", "all rights reserved",
               "copyrighted")
CLASS = frozenset("""
stenbrott stenbrottet gruva gruvan kvarn kvarnen kyrka kyrkan borg borgen
slott slottet grotta grottan grottor hog hogen gravfalt gravfalten ruin
ruinen bro bron kapell kapellet tingsplats batteri fort borgruin
kyrkoruin kastal kastalen
""".split())
SKIP_HOST = ("google.", "facebook.", "instagram.", "twitter.", "x.com",
             "youtube.", "tiktok.", "pinterest.", "tripadvisor.")


def fold(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def wiki_ok(google_title, article_title):
    """True when the article is about this place, not a namesake.

    Compared as whole words. A substring check matched "A-Borg" to
    "Lisa Borg", because "a borg" sits inside "lisa borg".
    """
    gw = [t for t in fold(google_title).split() if t]
    aw = [t for t in fold(article_title).split() if t]
    if not gw or not aw:
        return False
    if gw == aw:
        return True
    if len(gw) >= 2 and any(
            aw[i:i + len(gw)] == gw for i in range(len(aw) - len(gw) + 1)):
        return True
    def content(words):
        return [t for t in words if t not in STOP and len(t) >= 3]

    def same(a, b):
        """`a` is the place's word, `b` the article's.

        The article may add an ending ("Eketorp" / "Eketorps", "Ale" /
        "Ales"). Stripping an -s off the place name is only allowed for a
        long stem, so "Alfreds" does not become the person Alfred Nobel.
        "Askeryds" still reaches "Askeryd".
        """
        if a == b:
            return True
        if len(a) >= 4 and b.startswith(a):
            return True
        if len(a) >= 3 and b == a + "s":
            return True
        if a.endswith("s") and len(a) >= 8 and b == a[:-1]:
            return True
        return False

    # The place's own name has to open the article. One shared word later
    # in the title is how "Alfreds källa" became the person Berndt Alfreds
    # and a coastal battery became a Bofors gun. The exception is an article
    # titled like "Stenbrottet i Askeryd" for the place "Askeryds stenbrott".
    gw_c = content(gw)
    aw_c = content(aw)
    if not gw_c or not aw_c:
        return False
    opens = same(gw_c[0], aw_c[0]) or (
        aw_c[0] in CLASS and any(same(gw_c[0], w) for w in aw_c[1:]))
    if not opens:
        return False
    # "Alfreds källa" must not take the article "Alfrēds Ginters": every
    # word of the article has to be the place's name or a class word.
    for word in aw_c:
        if word in CLASS:
            continue
        if any(same(g, word) for g in gw_c):
            continue
        return False
    return True


def place_uuid(place_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "google-place:" + place_id))


def jitter(place_id, lat, lng):
    digest = hashlib.sha256(place_id.encode()).digest()
    u1 = int.from_bytes(digest[:8], "big") / 2**64
    u2 = int.from_bytes(digest[8:16], "big") / 2**64
    u1 = min(max(u1, 1e-12), 1 - 1e-12)
    radius = JITTER_SIGMA_M * math.sqrt(-2 * math.log(u1))
    theta = 2 * math.pi * u2
    north = radius * math.cos(theta)
    east = radius * math.sin(theta)
    return (lat + north / 111320,
            lng + east / (111320 * math.cos(math.radians(lat))))


def sweref(lon, lat):
    """SWEREF99 TM. Checked against sites.centroid_e/n, under a centimetre."""
    a = 6378137.0
    f = 1 / 298.257222101
    k0 = 0.9996
    lon0 = math.radians(15)
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    phi = math.radians(lat)
    lam = math.radians(lon)
    n = a / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = ep2 * math.cos(phi) ** 2
    big_a = (lam - lon0) * math.cos(phi)
    e4 = e2 * e2
    e6 = e4 * e2
    m = a * (
        (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
        - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
        + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
        - (35 * e6 / 3072) * math.sin(6 * phi)
    )
    east = 500000 + k0 * n * (
        big_a + (1 - t + c) * big_a ** 3 / 6
        + (5 - 18 * t + t * t + 72 * c - 58 * ep2) * big_a ** 5 / 120
    )
    north = k0 * (
        m + n * math.tan(phi) * (
            big_a ** 2 / 2
            + (5 - t + 9 * c + 4 * c * c) * big_a ** 4 / 24
            + (61 - 58 * t + t * t + 600 * c - 330 * ep2) * big_a ** 6 / 720
        )
    )
    return east, north


def candidates():
    out = []
    with open(CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("assigned_uuid") or "").strip():
                continue
            try:
                rating = float(r["rating"])
                reviews = float(r["reviews"])
            except (TypeError, ValueError):
                continue
            if rating >= 3 and reviews > 4:
                out.append(r)
    return out


def done_ids():
    if not os.path.exists(OUT):
        return set()
    ids = set()
    with open(OUT, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                ids.add(json.loads(line)["place_id"])
    return ids


def load_records():
    if not os.path.exists(OUT):
        return []
    with open(OUT, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def wiki_search(lang, title):
    j = get(f"https://{lang}.wikipedia.org/w/api.php", {
        "action": "query", "format": "json", "list": "search",
        "srsearch": title, "srlimit": 3,
    })
    time.sleep(DELAY)
    hits = ((j or {}).get("query") or {}).get("search") or []
    for hit in hits:
        if wiki_ok(title, hit.get("title") or ""):
            return hit["title"]
    return None


def wiki_page(lang, title, google_title):
    j = get(f"https://{lang}.wikipedia.org/w/api.php", {
        "action": "query", "format": "json", "redirects": 1,
        "prop": "extracts|images|pageprops|extlinks",
        "explaintext": 1, "exsectionformat": "wiki",
        "imlimit": 20, "ellimit": 8, "ppprop": "wikibase_item",
        "titles": title,
    })
    time.sleep(DELAY)
    pages = ((j or {}).get("query") or {}).get("pages") or {}
    page = next(iter(pages.values()), None)
    if not page or page.get("missing") is not None and "extract" not in page:
        return None
    extract = cut_tail((page.get("extract") or "").strip())
    if not extract:
        return None
    resolved = page.get("title") or title
    if not wiki_ok(google_title, resolved):
        return None
    qid = (page.get("pageprops") or {}).get("wikibase_item")
    images = [im.get("title") for im in page.get("images") or []
              if (im.get("title") or "").startswith("File:")]
    links = []
    for el in page.get("extlinks") or []:
        url = el.get("*") or el.get("url")
        if url:
            links.append(url)
    return {
        "lang": lang,
        "title": resolved,
        "url": f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(resolved.replace(' ', '_'))}",
        "extract": extract,
        "qid": qid,
        "images": images[:ARTICLE_PHOTOS + 8],
        "links": links,
    }


def official_site(qid):
    if not qid:
        return None
    j = get("https://www.wikidata.org/w/api.php", {
        "action": "wbgetentities", "format": "json", "ids": qid,
        "props": "claims",
    })
    time.sleep(DELAY)
    claims = (((j or {}).get("entities") or {}).get(qid) or {}).get("claims") or {}
    for claim in (claims.get("P856") or [])[:2]:
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(value, str) and value.startswith("http"):
            return value
    return None


def useful_link(url):
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return False
    host = host.lower()
    if any(s in host for s in SKIP_HOST):
        return False
    return host.endswith((
        "raa.se", "lansstyrelsen.se", "kulturarvsdata.se",
        "digitaltmuseum.se", "wikidata.org", "sofi.se",
        "riksantikvarieambetet.se",
    )) or "fornsok" in host


def link_title(url):
    path = urllib.parse.urlparse(url).path.strip("/")
    tail = path.split("/")[-1] if path else urllib.parse.urlparse(url).hostname
    return urllib.parse.unquote(tail).replace("_", " ")[:180] or url


def commons_search(title):
    j = get("https://commons.wikimedia.org/w/api.php", {
        "action": "query", "format": "json", "list": "search",
        "srsearch": title, "srnamespace": 6, "srlimit": SEARCH_PHOTOS,
    })
    time.sleep(DELAY)
    hits = ((j or {}).get("query") or {}).get("search") or []
    return [h["title"] for h in hits if (h.get("title") or "").startswith("File:")]


def geosearch(lat, lon):
    j = get("https://commons.wikimedia.org/w/api.php", {
        "action": "query", "format": "json", "list": "geosearch",
        "gscoord": f"{lat}|{lon}", "gsradius": GEO_RADIUS_M,
        "gslimit": NEARBY, "gsnamespace": 6,
    })
    time.sleep(DELAY)
    found = {}
    for g in ((j or {}).get("query") or {}).get("geosearch") or []:
        title = g.get("title")
        if title and title not in found:
            found[title] = g.get("dist")
    return found


def imageinfo(titles):
    out = {}
    for i in range(0, len(titles), 20):
        chunk = titles[i:i + 20]
        j = get("https://commons.wikimedia.org/w/api.php", {
            "action": "query", "format": "json",
            "titles": "|".join(chunk),
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
            "iiurlwidth": 800,
        })
        time.sleep(DELAY)
        pages = ((j or {}).get("query") or {}).get("pages") or {}
        for page in pages.values():
            info = (page.get("imageinfo") or [None])[0]
            title = page.get("title")
            if info and title:
                out[title] = info
    return out


def licence_ok(name):
    if not name:
        return True
    low = name.lower()
    return not any(bad in low for bad in BAD_LICENCE)


def photo_row(title, info, source, distance):
    lic, lic_url, author, _credit = commons_meta(info)
    if not licence_ok(lic):
        return None
    width = info.get("width")
    height = info.get("height")
    if width and height and max(width, height) < MIN_PX:
        return None
    if author:
        author = author[:180]
    return {
        "source": source,
        "file": title,
        "thumb": info.get("thumburl"),
        "page": info.get("descriptionurl"),
        "author": author,
        "licence": lic,
        "licence_url": lic_url,
        "image_url": info.get("url"),
        "width": width,
        "height": height,
        "distance_m": distance,
    }


def research(row):
    place_id = row["placeId"]
    title = (row.get("title") or "").strip()
    lat0 = float(row["lat"])
    lng0 = float(row["lng"])
    lat, lng = jitter(place_id, lat0, lng0)
    east, north = sweref(lng, lat)
    wiki = None
    for lang in ("sv", "en"):
        hit = wiki_search(lang, title)
        if hit:
            wiki = wiki_page(lang, hit, title)
            if wiki:
                break
    web = []
    images = []
    if wiki:
        seen = set()
        for url in wiki["links"]:
            if not useful_link(url) or url in seen:
                continue
            seen.add(url)
            web.append({
                "title": link_title(url),
                "url": url,
                "body": f"Länkad från Wikipedia ({wiki['lang']}): {wiki['title']}.",
            })
            if len(web) >= 4:
                break
        site = official_site(wiki.get("qid"))
        if site and site not in seen and useful_link(site):
            web.append({
                "title": link_title(site),
                "url": site,
                "body": f"Officiell webbplats i Wikidata, från Wikipedia ({wiki['lang']}): {wiki['title']}.",
            })
        images = list(wiki["images"])
    named = commons_search(title)
    nearby = geosearch(lat, lng)
    wanted = []
    origin = {}
    for file in images:
        if file not in origin:
            origin[file] = "hand"
            wanted.append(file)
    for file in named:
        stem = file.split(":", 1)[-1].rsplit(".", 1)[0].replace("_", " ")
        if file not in origin and wiki_ok(title, stem):
            origin[file] = "hand"
            wanted.append(file)
    for file in nearby:
        if file not in origin:
            origin[file] = "geosearch"
            wanted.append(file)
    wanted = wanted[:MAX_PHOTOS + 10]
    infos = imageinfo(wanted) if wanted else {}
    photos = []
    for file in wanted:
        info = infos.get(file)
        if not info:
            continue
        dist = nearby.get(file)
        item = photo_row(file, info, origin[file], dist)
        if item and item.get("thumb"):
            photos.append(item)
        if len(photos) >= MAX_PHOTOS:
            break
    return {
        "place_id": place_id,
        "uuid": place_uuid(place_id),
        "cluster_id": "google:" + place_id,
        "title": title,
        "lat": lat,
        "lon": lng,
        "google_lat": lat0,
        "google_lng": lng0,
        "rating": float(row["rating"]),
        "reviews": int(float(row["reviews"])),
        "comment": (row.get("comment") or "").strip(),
        "wikipedia": (
            {k: wiki[k] for k in ("lang", "title", "url", "extract")}
            if wiki else None
        ),
        "web": web,
        "photos": photos,
        "centroid_e": east,
        "centroid_n": north,
    }


# A title the name rules get wrong, or that the rules cannot see.
# Checked before the rules. The key is the Google title, exact.
CLASS_BY_TITLE = {
    "A-Borg": "Övrigt",
    "Anundshög skog": "Hög",
    "Arendala tingsplats": "Samlingsplats",
    "Bautastenen": "Grav markerad av sten/block",
    "Birger Jarl's Tower": "Borg",
    "Björkö-Birka (Island in Lake Mälaren with remnants of the former trading town Birka)": "Boplatsområde",
    "Björnråkskällaren": "Grotta",
    "Blybergs nya porfyrbrott": "Brott/täkt",
    "Bombkratern Borgholm Slottsskogen": "Övrigt",
    "Bombnedslag i Slottsparken": "Övrigt",
    "Bonnstan": "Kyrkstad",
    "Border stone Sweden": "Gränsmärke",
    "Bronsalder pa Gotland": "Stenkrets/stenrad",
    "Brännvinsmuren": "Hägnad",
    "Brötastenen fornminne parkerinng": "Runristning",
    "Casimirsborg": "Slott/herresäte",
    "Castle Mill": "Kvarn",
    "Dackestenen i Rabbe": "Minnesmärke",
    "Delary industriminnen": "Industri övrig",
    "Direktörsbostaden Sala silvergruva": "Övrigt",
    "DR 262 Fosiestenen": "Runristning",
    "Drakamöllans dödisgrop": "Naturminne",
    "Drakmärket": "Naturminne",
    "Dösen vid Grindarna": "Stenkammargrav",
    "Eldstaden": "Övrigt",
    "falekvarna": "Kvarn",
    "Fatmomakke": "Kyrkstad",
    "Forsmöllans kraftstation": "Industri övrig",
    "Fort on Kyrkåsberget": "Övrigt",
    "Fängelsehålan, Häxprocesserna i Torsåker": "Grotta",
    "Försvarsplats Gråberget 1": "Militär anläggning övrig",
    "Försvarsplats Gråberget 2": "Militär anläggning övrig",
    "Försvarsplats Marskärsudden": "Militär anläggning övrig",
    "Gamla Byn, Avesta": "Övrigt",
    "Gathenhielmska Stenen": "Minnesmärke",
    "Gelb gjuteri": "Gjuteri",
    "Glamstenen": "Naturminne",
    "Göta kanal-monumentet": "Minnesmärke",
    "Grönlandval Femstenaberg": "Övrigt",
    "Gullbron (Runriket)": "Bro",
    "Hammarshage hällar": "Naturminne",
    "Helvetesfallet": "Naturminne",
    "Hemlingestenen": "Minnesmärke",
    "Hjälmare docka": "Varv/slip",
    "Hovrahällarna": "Naturminne",
    "Hundgravarna i Borghamn": "Grav övrig",
    "Hällorna, Björkåsen": "Naturminne",
    "Hängesten": "Naturminne",
    "Häxberget": "Avrättningsplats",
    "Internetkulturminne: Du Simmar Ur Bild, Kaj": "Övrigt",
    "Jordbodalen Stenen": "Naturminne",
    "Jordkulan": "Lägenhetsbebyggelse",
    "judgments stones": "Övrigt",
    "Jungfrutornet": "Stadsvall/stadsmur",
    "Järntorgsbrunnen": "Övrigt",
    "Järnåldersboplats": "Boplatsområde",
    "Järnåldersbyn Hogslaby": "Boplatsområde",
    "Jättens port": "Naturminne",
    "Jättestugan": "Stenkammargrav",
    "Jättetallen": "Naturminne",
    "Kalle Runristare": "Minnesmärke",
    "Kanonberget": "Övrigt",
    "Kanonudden": "Minnesmärke",
    "Karl X Gustavs mur": "Hägnad",
    "Kastellet Stockholm": "Fästning/skans",
    "Kaupung’s Prehistoric Castle (fort)": "Fornborg",
    "King's Hall": "Övrigt",
    "Klocktornet": "Övrigt",
    "Kolebacka": "Övrigt",
    "Krigsbron i Norrhult": "Bro",
    "Kruttorn, provskjutningsplats för kanoner": "Militär anläggning övrig",
    "Kungastenen": "Minnesmärke",
    "Kutkäldu Tingstäde": "Källa med tradition",
    "Kvarnagården Håcksvik": "Kvarn",
    "Kvarnlämning i Helge å, uppströms Hästberga kraftverk": "Kvarn",
    "Kvarntornet (The Mill Tower tower)": "Kvarn",
    "Kvekgården": "Bytomt/gårdstomt",
    "Kyrkbacken": "Övrigt",
    "Kyrkbinge Såg": "Träindustri",
    "Kyrkstenarna": "Naturminne",
    "Käppalaställningen": "Stridsvärn",
    "Kåkstan": "Lägenhetsbebyggelse",
    "Kårebolssätern": "Fäbod",
    "Lancastern, Easy Elsie": "Övrigt",
    "Lappkyrkan": "Offerplats",
    "Lappsten": "Gränsmärke",
    "Lilla Trollkyrkan": "Naturminne",
    "Linköpings lokstall": "Industri övrig",
    "Littorinas Stenar": "Naturminne",
    "Lokstallarna": "Industri övrig",
    "Lonely Tree Baskemölla": "Övrigt",
    "Lucifers Kyrka": "Grotta",
    "Luffarstenen": "Naturminne",
    "Lundeberga kyrka (grotta)": "Grotta",
    "Långhus": "Husgrund, förhistorisk/medeltida",
    "Långhuset i Viskan": "Husgrund, förhistorisk/medeltida",
    "Lützowstenen": "Minnesmärke",
    "Massa Petters jordkoja": "Lägenhetsbebyggelse",
    "Medical History Museum in Helsingborg": "Övrigt",
    "Mobergsstenen": "Minnesmärke",
    "Museilinjen": "Övrigt",
    "Myggsten": "Naturminne",
    "Möllevångstorget": "Övrigt",
    "Njutfallet (Kvarnbäcksfallet)": "Naturminne",
    "Norderport (Northern Gate)": "Stadsbefästning",
    "Norn iron works": "Metallindustri/järnbruk",
    "Nya Porfyrverket i Västäng": "Stenindustri",
    "Nyvångs Slagghög": "Bergshistorisk lämning övrig",
    "Observationsvärn nr 741": "Stridsvärn",
    "Old City Limit Stone": "Gränsmärke",
    "Optisk telegraf": "Övrigt",
    "Oscarsborg": "Fästning/skans",
    "Oscarsstone": "Minnesmärke",
    "Oscarsvärn": "Stridsvärn",
    "Oskar-Fredriksborg Fort": "Fästning/skans",
    "Oskarsvärn, Hästö": "Stridsvärn",
    "Oxebo vattensåg": "Träindustri",
    "Penåsa Ödeby": "Bytomt/gårdstomt",
    "Pershyttans kulturreservat": "Metallindustri/järnbruk",
    "Porla brunn": "Brunn/kallkälla",
    "Prekebogumman": "Naturminne",
    "Pyramiderna": "Naturminne",
    "Repslageriet Åhus": "Industri övrig",
    "Rose garden": "Park-/trädgårdsanläggning",
    "Rotensugnet": "Naturminne",
    "RRGC ”Bocken”": "Militär anläggning övrig",
    "Rutehall": "Naturminne",
    "Ryds sågverksruin": "Träindustri",
    "S:t Lars Ruin": "Kyrka/kapell",
    "S:t Pers ruin": "Kyrka/kapell",
    "Sagobygden Karins sten": "Naturminne",
    "Sagobygden Skatten i Högarör": "Röse",
    "Sagobygden Stenudden": "Övrigt",
    "Sagobygden Trollsmeden i Nockarp": "Övrigt",
    "Sagobygden Trollträdet": "Naturminne",
    "Sammilsdal": "Samlingsplats",
    "SAS flight 751 haveriplats": "Minnesmärke",
    "Segeltorps LV ställning": "Stridsvärn",
    "Sikhjälma Gammelhamn": "Hamnområde",
    "Silfhytteå": "Metallindustri/järnbruk",
    "Skansahålet": "Fästning/skans",
    "Skansar i Traryds Hembygdspark": "Fästning/skans",
    "Skansen city quarters": "Övrigt",
    "Skansport": "Fästning/skans",
    "Skurverket i Jordhamn": "Stenindustri",
    "Skåne lapidarium in Sibbhult": "Övrigt",
    "Slaggvarp": "Bergshistorisk lämning övrig",
    "Slottsberget": "Övrigt",
    "Snarkstenen": "Naturminne",
    "Snarsmon": "Övrigt",
    "St. Olofs Gryta": "Naturminne",
    "St. Stephen's Church and Cemetery": "Kyrka/kapell",
    "Staffanstenen": "Minnesmärke",
    "Statue Swedenborg": "Minnesmärke",
    "Stenbro fyra valv Seglora": "Bro",
    "Stomkvarnsleden": "Övrigt",
    "Tvillingkvarnarna": "Kvarn",
    "Stenmurslandskapet i Väsmestorp": "Hägnad",
    "Stensjö by": "Bytomt/gårdstomt",
    "Stentorn": "Övrigt",
    "Stenvallen - Historisches Gehöft und Ausflugsziel": "Bytomt/gårdstomt",
    "Stierngranatska Familjegraven": "Begravningsplats",
    "Stockholmsfänikans läger": "Militär mötesplats",
    "Stor Kari Sten": "Naturminne",
    "Stor sten": "Naturminne",
    "Stora Helvetet": "Naturminne",
    "Stora skansen - Hill fort (Kalkuddens hill fort)": "Fornborg",
    "Stora Trollkyrkan": "Naturminne",
    "Struve Geodetic Arc - Jupukka": "Minnesmärke",
    "Styresholm": "Borg",
    "Sunnäsbruk Dam": "Dammvall",
    "Sänke hög": "Gravfält",
    "Säldebråten Fornminnesgård": "Övrigt",
    "Sågverkstrampet": "Övrigt",
    "Söderport (Southern Gate)": "Stadsbefästning",
    "Södertull": "Stadsbefästning",
    "Södervärnstornet": "Övrigt",
    "Södra Strandverket": "Fästning/skans",
    "Sörby Borg": "Borg",
    "The priest's Bath": "Naturminne",
    "The Wolfstone in Exhult": "Naturminne",
    "Tjuvakällaren": "Grotta",
    "Tollareställningen": "Stridsvärn",
    "Torgbrunnen": "Övrigt",
    "Torkels Gömma": "Grotta",
    "Torne river sauna experience / Bastu på torneälven": "Övrigt",
    "Tornvallen": "Vallanläggning",
    "Torsburgen": "Fornborg",
    "Trollhättan Water Tower": "Övrigt",
    "Trollkullahålet i Stenkumla": "Grotta",
    "Trollkäringeskogen": "Övrigt",
    "Trollkärringeberget": "Avrättningsplats",
    "Trollskogen": "Övrigt",
    "UFO Graven": "Grav övrig",
    "Vadmalsstampen": "Textilindustri",
    "Valbrets grav": "Hällristning",
    "Vallerstakällaren": "Grotta",
    "Vallgrav": "Vallanläggning",
    "Vallhagar": "Husgrund, förhistorisk/medeltida",
    "Vargkitteln": "Naturminne",
    "Vargklämman": "Grotta",
    "Vasastenen": "Minnesmärke",
    "Vattenhjulet": "Industri övrig",
    "Vattentornet Keillers park": "Övrigt",
    "Vatthammar": "Kvarn",
    "Vikingaskepp, Upplands Väsby kommun": "Övrigt",
    "Villa Lusthusporten": "Övrigt",
    "Visborg": "Slott/herresäte",
    "Viskansparken": "Park-/trädgårdsanläggning",
    "Vitemölla strövområde, Stenörens ålabod": "Fiskeläge",
    "Vitterhuset": "Övrigt",
    "Vrå Fornby": "Boplatsområde",
    "Wittrocks torn": "Övrigt",
    "Yxornas häll": "Hällristning",
    "Ålafiskaren Vitemölla": "Minnesmärke",
    "Ållebergskragens fyndplats": "Fyndplats",
    "Ålsätra Slussvaktarstuga": "Kanal",
    "Ånghammare": "Minnesmärke",
    "Ödeplats": "Militär anläggning övrig",
    "Österport (Eastern Gate)": "Stadsbefästning",
}

# Longer stems also match the end of a compound (koppargruva, väderkvarn).
# Short stems match only as their own word, so "bro" does not fire inside
# a longer name.
_CLASS_SUFFIX = [
    ("Kyrkstad", ["kyrkstad", "kyrkstaden"]),
    ("Begravningsplats", ["kyrkogård", "kyrkogården", "begravningsplats", "cemetery", "graveyard", "ödekyrkogård"]),
    ("Kyrka/kapell", ["kyrkoruin", "kyrkoruinen", "kapellruin", "kyrka", "kyrkan", "kyrkor", "kapell", "kapellet", "church", "chapel"]),
    ("Kloster", ["kloster", "klostret", "klosters"]),
    ("Runristning", ["runsten", "runstenen", "runstenar", "runristning", "runristningen", "runestone", "runestones", "runic"]),
    ("Hällristning", ["hällristning", "hällristningen", "hällristningar", "hällristningarna", "petroglyph"]),
    ("Hällmålning", ["hällmålning", "hällmålningen"]),
    ("Labyrint", ["labyrint", "labyrinten"]),
    ("Fornborg", ["fornborg", "fornborgen", "hillfort"]),
    ("Stadsvall/stadsmur", ["stadsmur", "stadsmuren", "ringmur", "ringmuren", "stadsvall", "citywall"]),
    ("Stridsvärn", ["bunker", "bunkern", "bunkrar", "värn", "värnet", "skyttevärn", "luftvärnsställning", "luftvärnstorn", "kulsprutevärn", "pjäsvärn", "ställning", "ställningen"]),
    ("Militär anläggning övrig", ["batteri", "batteriet", "battery", "kasern", "kasernen", "minstation", "minstationen"]),
    ("Fästning/skans", ["fästning", "fästningen", "fortress", "fortet", "forten", "skans", "skansen", "bastion", "bastionen", "redoubt", "fästet"]),
    ("Slott/herresäte", ["slott", "slottet", "slottsruin", "castle", "säteri", "säteriet", "herrgård", "herrgården", "manor", "palats"]),
    ("Borg", ["borg", "borgen"]),
    ("Gruvområde", ["gruva", "gruvan", "gruvor", "gruvorna", "gruvlave", "gruvmiljö", "gruvpark", "gruvbyn", "mine", "mines"]),
    ("Brott/täkt", ["stenbrott", "stenbrottet", "kalkbrott", "kalkbrottet", "quarry", "quarries", "dagbrott"]),
    ("Glasindustri", ["glasbruk", "glasbruket"]),
    ("Tegelindustri", ["tegelbruk", "tegelbruket"]),
    ("Pappersindustri", ["pappersbruk"]),
    ("Träindustri", ["sågverk", "sågverket", "sågen", "sågmölla", "sawmill", "vattensåg"]),
    ("Kalkugn", ["kalkugn", "kalkugnen", "kalkbruk", "kalkbruket", "kalkindustri"]),
    ("Kvarn", ["kvarn", "kvarnen", "kvarnar", "kvarnruin", "kvarnby", "mölla", "möllan", "molla", "windmill", "watermill", "skvaltkvarn", "väderkvarn", "väderkvarnar", "stubbamölla", "mill"]),
    ("Metallindustri/järnbruk", ["järnbruk", "masugn", "masugnen", "hytta", "hyttan", "hyttor", "lapphyttan", "smedja", "smedjan", "bruk", "bruket", "ironworks", "furnace", "ånghammare", "konsthjul", "anrikningsverk"]),
    ("Kanal", ["sluss", "slussen", "slussar", "slusstation", "kanal", "kanalen", "lock", "locks"]),
    ("Fyr", ["fyr", "fyren", "lighthouse"]),
    ("Varv/slip", ["varv", "varvet", "shipyard", "docka", "dockan"]),
    ("Hamnområde", ["hamn", "hamnen", "harbour", "harbor", "fiskeläge"]),
    ("Grotta", ["grotta", "grottan", "grottor", "grottorna", "cave", "caves"]),
    ("Minnesmärke", ["minnesmärke", "minnesmärket", "minnessten", "minnesstenen", "monument", "monumentet", "staty", "memorial"]),
    ("Park-/trädgårdsanläggning", ["trädgård", "trädgården", "garden"]),
    ("Fäbod", ["fäbod", "fäbodar", "fäbodarna", "sätern"]),
    ("Lägenhetsbebyggelse", ["torp", "torpet", "torpen", "backstuga", "backstugan", "soldattorp", "soldattorpet"]),
    ("Källa med tradition", ["källa", "källan", "offerkälla", "kallkälla", "spring"]),
    ("Avrättningsplats", ["avrättningsplats", "galgbacke", "galgbacken", "galgberget", "gallows"]),
    ("Gravfält", ["gravfält", "gravfältet"]),
    ("Hög", ["gravhög", "kungshög", "kungshögen", "storhög", "hög", "högen", "mound", "barrow"]),
    ("Röse", ["röse", "röset", "rösen", "rösena", "cairn", "gravröse"]),
    ("Stenkrets/stenrad", ["skeppssättning", "skeppsättning", "domarring", "domarringen", "stenkrets", "stenring", "stensättning"]),
    ("Stenkammargrav", ["dös", "dösen"]),
    ("Bro", ["bro", "bron", "bridge", "stenvalvbro", "valvbro", "brohus"]),
    ("Fartygs-/båtlämning", ["vrak", "vraket", "skeppsvrak", "wreck"]),
    ("Kolningsanläggning", ["kolmila", "kolmilan", "mila"]),
    ("Naturminne", ["jättegryta", "jättegrytan", "jättegrytor", "jättegrytorna"]),
    ("Offerplats", ["offerlund", "offerlunden", "offerplats"]),
    ("Slagfält", ["slaget", "slagfält"]),
    ("Stadsbefästning", ["porten", "port"]),
    ("Gjuteri", ["gjuteri", "gjuteriet"]),
    ("Hägnad", ["muren", "stenmur", "stenmuren"]),
    ("Boplatsområde", ["boplats", "boplatsen", "fornby"]),
]


def google_class(title):
    """The register class this place belongs with, or a class opened for it.

    The title is the evidence. A Wikipedia title is not: several of these
    were matched to a different article.
    """
    got = CLASS_BY_TITLE.get(title)
    if got:
        return got
    tokens = re.findall(r"[a-z0-9åäö]+", title.lower())
    joined = " ".join(tokens)
    phrases = (
        ("Fornborg", ("hill fort", "hillfort")),
        ("Stadsvall/stadsmur", ("town wall", "city wall")),
        ("Träindustri", ("saw mill",)),
        ("Runristning", ("rune stone", "runic inscription", "runic stone")),
        ("Hög", ("burial mound",)),
        ("Gravfält", ("grave field",)),
        ("Stenkrets/stenrad", ("stone ship", "viking ship")),
        ("Militär anläggning övrig", ("coastal artillery", "artillery battery", "powder magazine", "fire-control", "fire control")),
        ("Metallindustri/järnbruk", ("iron works",)),
    )
    for cls, words in phrases:
        if any(p in joined for p in words):
            return cls
    for cls, suffixes in _CLASS_SUFFIX:
        for tok in tokens:
            for suf in suffixes:
                if tok == suf or (len(suf) >= 5 and tok.endswith(suf)):
                    return cls
    return None


def apply_classes():
    """Write a class onto every Google place.

    The jsonl is what a later sites rebuild reads. The cluster is what the
    score reads today. The register class lives on the site, so both are set.
    """
    import families
    records = load_records()
    missing = []
    counts = {}
    for record in records:
        cls = google_class(record["title"])
        if not cls or cls not in families.FAMILY:
            missing.append((record["title"], cls))
            continue
        record["class_sv"] = cls
        counts[cls] = counts.get(cls, 0) + 1
    if missing:
        for title, cls in missing:
            print(f"  no class: {title!r} -> {cls}")
        raise SystemExit(f"{len(missing)} places have no class")
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(tmp, OUT)

    work = sqlite3.connect(paths.WORK, timeout=60)
    places = sqlite3.connect(paths.PLACES, timeout=60)
    try:
        for record in records:
            cls = record["class_sv"]
            mix = f"{cls}×1"
            work.execute(
                "UPDATE sites SET class_sv=? WHERE uuid=?",
                (cls, record["uuid"]))
            work.execute(
                """UPDATE clusters
                      SET dominant_class=?, n_classes=1, class_mix=?
                    WHERE cluster_id=?""",
                (cls, mix, record["cluster_id"]))
            work.execute(
                """UPDATE signals
                      SET dominant_class=?,
                          class_blacklisted=?,
                          class_soft_blacklisted=?
                    WHERE cluster_id=?""",
                (cls,
                 int(cls in families.CLASS_BLACKLIST),
                 int(cls in families.CLASS_SOFT_BLACKLIST),
                 record["cluster_id"]))
            places.execute(
                """UPDATE features
                      SET class_sv=?, family=?, class_mix=?, n_classes=1
                    WHERE cluster_id=?""",
                (cls, families.FAMILY[cls], mix, record["cluster_id"]))
        work.commit()
        places.commit()
    finally:
        work.close()
        places.close()
    print(f"{len(records)} places classed, {len(counts)} classes")
    for cls, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4}  {cls}")


def ensure_stored(conn):
    """Put the jsonl rows back into sites, clusters and site_clusters.

    Inserts only. A coordinate already stored is left where it is, which
    is what keeps the jitter from being drawn again.
    """
    rows = load_records()
    n = 0
    for r in rows:
        before = conn.total_changes
        store_one(conn, r)
        if conn.total_changes > before:
            n += 1
    return n


def store_one(conn, r):
    conn.execute(
        """INSERT OR IGNORE INTO sites
             (uuid, title, lon, lat, has_point, geom_types,
              centroid_e, centroid_n, beskrivning, class_sv)
           VALUES (?,?,?,?,1,'point',?,?,?,?)""",
        (r["uuid"], r["title"], r["lon"], r["lat"],
         r["centroid_e"], r["centroid_n"], r.get("comment") or None,
         r.get("class_sv") or google_class(r["title"])),
    )
    cls = r.get("class_sv") or google_class(r["title"])
    conn.execute(
        """INSERT OR IGNORE INTO clusters
             (cluster_id, method, n_sites, rep_uuid, n_classes,
              dominant_class, class_mix, name,
              has_name, centroid_e, centroid_n, lon, lat, spread_m,
              any_polygon, any_visible, geom_types, best_description,
              best_description_len, all_boilerplate, any_measurements)
           VALUES (?,?,1,?,1,?,?,?,1,?,?,?,?,0,0,0,'point',?,?,0,0)""",
        (r["cluster_id"], "google", r["uuid"], cls,
         f"{cls}×1" if cls else None, r["title"],
         r["centroid_e"], r["centroid_n"], r["lon"], r["lat"],
         r.get("comment") or None, len(r.get("comment") or "")),
    )
    conn.execute(
        "INSERT OR IGNORE INTO site_clusters (uuid, cluster_id) VALUES (?,?)",
        (r["uuid"], r["cluster_id"]),
    )
    conn.commit()


def sources_one(out, r):
    import build_sources
    cid = r["cluster_id"]
    uid = r["uuid"]
    comment = (r.get("comment") or "").strip()
    if comment:
        build_sources.add(
            out, cid, "investigation", comment, uuid=uid, lang="sv",
            title=r["title"], publisher="Fornkoll")
    wiki = r.get("wikipedia")
    if wiki and wiki.get("extract"):
        build_sources.add(
            out, cid, "wikipedia", wiki["extract"], uuid=uid,
            lang=wiki.get("lang"), title=wiki.get("title"),
            publisher=f"Wikipedia ({wiki.get('lang')})",
            licence=BYSA[0], licence_url=BYSA[1], url=wiki.get("url"),
            lines=True)
    for page in r.get("web") or []:
        if page.get("url") and page.get("body"):
            build_sources.add(
                out, cid, "web_page", page["body"], uuid=uid,
                title=page.get("title"), url=page["url"],
                publisher=page.get("title"))


def insert_sources(out):
    """Investigation, Wikipedia and the linked pages. Returns wiki row shas."""
    import build_sources
    keep = set()
    n = 0
    for r in load_records():
        cid = r["cluster_id"]
        uid = r["uuid"]
        comment = (r.get("comment") or "").strip()
        if comment:
            n += build_sources.add(
                out, cid, "investigation", comment, uuid=uid, lang="sv",
                title=r["title"], publisher="Fornkoll")
        wiki = r.get("wikipedia")
        if wiki and wiki.get("extract"):
            n += build_sources.add(
                out, cid, "wikipedia", wiki["extract"], uuid=uid,
                lang=wiki.get("lang"), title=wiki.get("title"),
                publisher=f"Wikipedia ({wiki.get('lang')})",
                licence=BYSA[0], licence_url=BYSA[1], url=wiki.get("url"),
                lines=True)
            clean = build_sources.keep_lines(wiki["extract"])
            keep.add(build_sources.row_sha(
                cid, "wikipedia", wiki.get("lang"), wiki.get("url"), clean))
        for page in r.get("web") or []:
            if not page.get("url") or not page.get("body"):
                continue
            n += build_sources.add(
                out, cid, "web_page", page["body"], uuid=uid,
                title=page.get("title"), url=page["url"],
                publisher=page.get("title"))
    print(f"  google:      {n:,} sources offered for {len(load_records()):,} places")
    return keep


def neon(sql, params):
    url = database_url()
    endpoint = f"https://{urllib.parse.urlparse(url).hostname}/sql"
    body = json.dumps({"query": sql, "params": params}).encode()
    req = urllib.request.Request(endpoint, data=body, headers={
        "Content-Type": "application/json",
        "Neon-Connection-String": url,
    })
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read()).get("rows") or []
        except Exception as exc:
            last = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(str(last)[:300])


def publish_one(record, shards):
    uid = record["uuid"]
    title = record["title"][:200]
    neon(
        """INSERT INTO fl_title_overrides (place_uuid, title, set_by)
           VALUES ($1, $2, $3)
           ON CONFLICT (place_uuid) DO NOTHING""",
        [uid, title, ADDED_BY],
    )
    sources = []
    comment = (record.get("comment") or "").strip()
    if comment:
        sources.append(("investigation", "sv", title, comment,
                        "Fornkoll", None, None, None))
    wiki = record.get("wikipedia")
    if wiki and wiki.get("extract"):
        sources.append(("wikipedia", wiki.get("lang"), wiki.get("title"),
                        wiki["extract"], f"Wikipedia ({wiki.get('lang')})",
                        BYSA[0], BYSA[1], wiki.get("url")))
    for page in record.get("web") or []:
        if page.get("url") and page.get("body"):
            sources.append(("web_page", None, page.get("title"), page["body"],
                            page.get("title"), None, None, page["url"]))
    if sources:
        values = []
        params = []
        for kind, lang, stitle, body, publisher, lic, lic_url, url in sources:
            base = len(params)
            values.append(
                "(" + ",".join(f"${base + k}" for k in range(1, 11)) + ")"
            )
            params.extend([uid, kind, lang, stitle, body, publisher, lic,
                           lic_url, url, ADDED_BY])
        neon(
            f"""INSERT INTO fl_sources_added
                  (place_uuid, kind, lang, title, body, publisher,
                   licence, licence_url, url, added_by)
                SELECT v.place_uuid, v.kind, v.lang, v.title, v.body,
                       v.publisher, v.licence, v.licence_url, v.url, v.added_by
                  FROM (VALUES {",".join(values)})
                    AS v(place_uuid, kind, lang, title, body, publisher,
                         licence, licence_url, url, added_by)
                 WHERE NOT EXISTS (
                   SELECT 1 FROM fl_sources_added s
                    WHERE s.place_uuid = v.place_uuid AND s.kind = v.kind
                      AND COALESCE(s.url, '') = COALESCE(v.url, '')
                      AND s.removed_at IS NULL)""",
            params,
        )
    photos = [p for p in record.get("photos") or []
              if p.get("file") and p.get("thumb")]
    for start in range(0, len(photos), 15):
        chunk = photos[start:start + 15]
        values = []
        params = []
        for photo in chunk:
            base = len(params)
            values.append(
                "(" + ",".join(f"${base + k}" for k in range(1, 14)) + ")"
            )
            params.extend([
                uid, photo["source"], photo["file"], photo["thumb"],
                photo.get("page"), photo.get("author"), photo.get("licence"),
                photo.get("licence_url"), photo.get("image_url"),
                photo.get("width"), photo.get("height"),
                photo.get("distance_m"), ADDED_BY,
            ])
        neon(
            f"""INSERT INTO fl_photos_added
                  (place_uuid, source, file, thumb, page, author, licence,
                   licence_url, image_url, width, height, distance_m, added_by)
                VALUES {",".join(values)}
                ON CONFLICT (place_uuid, source, file) DO NOTHING""",
            params,
        )
    # The importer keeps these files in memory and flushes them. Writing
    # one here at the same time would be thrown away by that flush.
    if shards is not None:
        shard_put(shards, record)


THUMB = re.compile(
    r"/commons/thumb/([0-9a-f]/[0-9a-f]{2})/([^/]+)/\d+px-", re.I)


def shard_put(shards, record):
    uid = record["uuid"]
    key = uid[:2].lower()
    if key not in shards:
        path = os.path.join(DESC_DIR, key + ".json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                shards[key] = json.load(f)
        else:
            shards[key] = {}
        shards.setdefault("_dirty", set())
    images = []
    for photo in (record.get("photos") or [])[:8]:
        thumb = photo.get("thumb") or ""
        m = THUMB.search(thumb)
        item = {
            "by": photo.get("author"),
            "lic": photo.get("licence"),
            "page": photo.get("page"),
        }
        if photo.get("licence_url"):
            item["licurl"] = photo["licence_url"]
        if m:
            item["f"] = m.group(2)
            item["h"] = m.group(1)
            item["w"] = 800
        else:
            item["f"] = photo["file"]
            item["src"] = thumb
        images.append({k: v for k, v in item.items() if v})
    card = {"title": record["title"]}
    if record.get("comment"):
        card["content"] = record["comment"]
    if images:
        card["images"] = images
    shards[key][uid] = card
    shards["_dirty"].add(key)


def shard_flush(shards):
    dirty = shards.get("_dirty") or set()
    for key in dirty:
        path = os.path.join(DESC_DIR, key + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(shards[key], f, ensure_ascii=False, separators=(",", ": "))
    dirty.clear()


def publish_stored(records=None):
    """Admin rows and description cards for records already on disk."""
    records = records if records is not None else load_records()
    shards = {}
    work = sqlite3.connect(paths.WORK)
    places = sqlite3.connect(paths.PLACES)
    try:
        ensure_stored(work)
        insert_sources(places)
        places.commit()
        for i, record in enumerate(records, 1):
            publish_one(record, shards)
            if i % 20 == 0:
                shard_flush(shards)
                print(f"  published {i}/{len(records)}", flush=True)
        shard_flush(shards)
    finally:
        work.close()
        places.close()
    from build_places import write_place_coords
    write_place_coords()


def agent_rows(only=None):
    """What the parallel checks wrote. One row per place id, later file wins."""
    found = {}
    directory = os.path.join(paths.DATA, "google_verify")
    if not os.path.isdir(directory):
        return []
    for name in sorted(os.listdir(directory)):
        if only and name != only:
            continue
        if not (name.startswith("out_") and name.endswith(".jsonl")):
            continue
        with open(os.path.join(directory, name), encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    found[row["placeId"]] = row
    return list(found.values())


def article_generic(title):
    words = [t for t in fold(title).split() if t not in STOP and len(t) >= 3]
    return len(words) <= 1 and (not words or words[0] in CLASS)


def wiki_body(lang, title):
    """The article, not the lead. References and link lists are cut off."""
    page_title, _, anchor = (title or "").partition("#")
    j = get(f"https://{lang}.wikipedia.org/w/api.php", {
        "action": "query", "format": "json", "formatversion": 2,
        "redirects": 1, "prop": "extracts", "explaintext": 1,
        "exsectionformat": "wiki",
        "titles": page_title.replace("_", " "),
    })
    time.sleep(DELAY)
    if not j or j.get("__error"):
        return None
    page = ((j.get("query") or {}).get("pages") or [None])[0]
    if not page or page.get("missing"):
        return None
    text = page.get("extract") or ""
    body = section_of(text, anchor) if anchor else cut_tail(text)
    body = (body or "").strip()
    return body or None


def fetch_extract(lang, title):
    j = get(f"https://{lang}.wikipedia.org/w/api.php", {
        "action": "query", "format": "json", "formatversion": 2,
        "redirects": 1, "prop": "extracts", "explaintext": 1,
        "exsectionformat": "wiki",
        "titles": title,
    })
    time.sleep(DELAY)
    if not j or j.get("__error"):
        return None
    page = ((j.get("query") or {}).get("pages") or [None])[0]
    if not page or page.get("missing"):
        return None
    extract = cut_tail((page.get("extract") or "").strip())
    resolved = page.get("title") or title
    if not extract or article_generic(resolved):
        return None
    return resolved, extract


def merge_verified(only=None):
    """Add the pages and photographs the parallel checks actually found.

    Does not rewrite google_places.jsonl: the importer is appending to it.
    The admin reads Neon, and the source rows go into places.sqlite.
    """
    by_id = {}
    with open(CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_id[row["placeId"]] = row
    have_url = {}
    have_file = {}
    for record in load_records():
        urls = have_url.setdefault(record["place_id"], set())
        files = have_file.setdefault(record["place_id"], set())
        wiki = record.get("wikipedia")
        if wiki and wiki.get("url"):
            urls.add(wiki["url"])
        for page in record.get("web") or []:
            if page.get("url"):
                urls.add(page["url"])
        for photo in record.get("photos") or []:
            if photo.get("file"):
                files.add(photo["file"])
    n_wiki = n_web = n_photo = 0
    places = sqlite3.connect(paths.PLACES, timeout=60)
    try:
        for row in agent_rows(only):
            src = by_id.get(row.get("placeId"))
            if not src:
                continue
            uid = place_uuid(row["placeId"])
            cid = "google:" + row["placeId"]
            title = (src.get("title") or "").strip()
            urls = have_url.setdefault(row["placeId"], set())
            files = have_file.setdefault(row["placeId"], set())
            wiki = row.get("wikipedia") or None
            if wiki and wiki.get("title") and wiki.get("url"):
                host = urllib.parse.urlparse(wiki["url"]).hostname or ""
                if host.endswith("wikipedia.org") and wiki["url"] not in urls:
                    fetched = fetch_extract(wiki.get("lang") or "sv", wiki["title"])
                    if fetched:
                        resolved, extract = fetched
                        url = f"https://{wiki.get('lang') or 'sv'}.wikipedia.org/wiki/{urllib.parse.quote(resolved.replace(' ', '_'))}"
                        if url not in urls:
                            sources_one(places, {
                                "cluster_id": cid, "uuid": uid, "title": title,
                                "comment": "", "web": [],
                                "wikipedia": {
                                    "lang": wiki.get("lang") or "sv",
                                    "title": resolved, "url": url,
                                    "extract": extract,
                                },
                            })
                            neon(
                                """INSERT INTO fl_title_overrides
                                     (place_uuid, title, set_by)
                                   VALUES ($1, $2, $3)
                                   ON CONFLICT (place_uuid) DO NOTHING""",
                                [uid, title[:200], ADDED_BY],
                            )
                            neon(
                                """INSERT INTO fl_sources_added
                                     (place_uuid, kind, lang, title, body,
                                      publisher, licence, licence_url, url,
                                      added_by)
                                   SELECT $1, 'wikipedia', $2, $3, $4, $5, $6,
                                          $7, $8, $9
                                    WHERE NOT EXISTS (
                                      SELECT 1 FROM fl_sources_added s
                                       WHERE s.place_uuid = $1
                                         AND s.kind = 'wikipedia'
                                         AND s.url = $8
                                         AND s.removed_at IS NULL)""",
                                [uid, wiki.get("lang") or "sv", resolved,
                                 extract, f"Wikipedia ({wiki.get('lang') or 'sv'})",
                                 BYSA[0], BYSA[1], url, ADDED_BY],
                            )
                            urls.add(url)
                            n_wiki += 1
                            print(f"  wiki  {title} -> {resolved}", flush=True)
            note = (row.get("note") or "").strip()
            for page in row.get("other_sources") or []:
                url = page.get("url") or ""
                if not url.startswith("http") or url in urls:
                    continue
                host = (urllib.parse.urlparse(url).hostname or "").lower()
                if any(s in host for s in SKIP_HOST):
                    continue
                body = note or f"Sida om {title}."
                sources_one(places, {
                    "cluster_id": cid, "uuid": uid, "title": title,
                    "comment": "", "wikipedia": None,
                    "web": [{"title": page.get("title") or link_title(url),
                             "url": url, "body": body}],
                })
                neon(
                    """INSERT INTO fl_sources_added
                         (place_uuid, kind, lang, title, body, publisher, url,
                          added_by)
                       SELECT $1, 'web_page', NULL, $2, $3, $2, $4, $5
                        WHERE NOT EXISTS (
                          SELECT 1 FROM fl_sources_added s
                           WHERE s.place_uuid = $1 AND s.kind = 'web_page'
                             AND s.url = $4 AND s.removed_at IS NULL)""",
                    [uid, (page.get("title") or link_title(url))[:180], body,
                     url, ADDED_BY],
                )
                urls.add(url)
                n_web += 1
            places.commit()
            wanted = []
            for file in row.get("photos") or []:
                if isinstance(file, str) and file.startswith("File:") and file not in files:
                    wanted.append(file)
                    files.add(file)
            infos = imageinfo(wanted) if wanted else {}
            photos = []
            for file in wanted:
                info = infos.get(file)
                if not info:
                    continue
                item = photo_row(file, info, "hand", None)
                if item and item.get("thumb"):
                    photos.append(item)
            if photos:
                publish_one(
                    {"uuid": uid, "title": title, "comment": "",
                     "wikipedia": None, "web": [], "photos": photos},
                    None,
                )
                n_photo += len(photos)
        places.commit()
    finally:
        places.close()
    print(f"merged {n_wiki} wikipedia, {n_web} other pages, {n_photo} photos",
          flush=True)


def page_prose(url):
    """The readable text of a page, the same cut the county crawl uses.

    A PDF goes through pdftotext. Anything else is the HTML main text, with
    the navigation and the footer left out. None when the page has no prose.
    """
    import subprocess
    import tempfile
    from crawl_lansstyrelsen import UA, page_text
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = resp.read(2_000_000)
            ctype = (resp.headers.get("Content-Type") or "").lower()
    except Exception:
        return None
    is_pdf = data[:5] == b"%PDF-" or "pdf" in ctype or url.lower().split("?")[0].endswith(".pdf")
    if is_pdf:
        with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
            tmp.write(data)
            tmp.flush()
            try:
                out = subprocess.run(
                    ["pdftotext", "-q", "-enc", "UTF-8", tmp.name, "-"],
                    capture_output=True, timeout=60, check=False)
            except (OSError, subprocess.TimeoutExpired):
                return None
        text = out.stdout.decode("utf-8", "replace")
        lines = [" ".join(line.split()) for line in text.splitlines()]
        lines = [line for line in lines if len(line) >= 25]
        return "\n".join(lines).strip() or None
    html = data.decode("utf-8", "replace")
    text, _credit = page_text(html)
    return text.strip() or None


def fill_web_bodies():
    """Replace the one-line web sources on the Google places with the page.

    The import stored a pointer ('Länkad från Wikipedia…', or the agent's
    note). The page itself was never fetched. Same rule as the county
    visitor pages: the prose, not the chrome, and only when it is actually
    longer than the sentence already stored.
    """
    import build_sources
    places = sqlite3.connect(f"file:{paths.PLACES}?mode=ro", uri=True)
    rows = places.execute("""
        SELECT source_id, cluster_id, uuid, title, url, text
          FROM sources
         WHERE kind = 'web_page' AND usable = 1
           AND cluster_id LIKE 'google:%' AND url IS NOT NULL
    """).fetchall()
    places.close()
    urls = sorted({url for _, _, _, _, url, _ in rows})
    print(f"{len(rows)} web sources, {len(urls)} pages", flush=True)
    prose = {}
    for i, url in enumerate(urls, 1):
        prose[url] = page_prose(url)
        time.sleep(0.3)
        if i % 25 == 0 or i == len(urls):
            got = sum(1 for v in prose.values() if v)
            print(f"  fetched {i}/{len(urls)}, {got} with text", flush=True)

    grown = []
    skipped = 0
    for source_id, cid, uid, title, url, text in rows:
        body = prose.get(url)
        if not body:
            skipped += 1
            continue
        clean = build_sources.keep_lines(body)
        old = build_sources.keep_lines(text or "")
        if len(clean) < 400 or len(clean) <= len(old) + 200:
            skipped += 1
            continue
        sha = build_sources.row_sha(cid, "web_page", None, url, clean)
        grown.append((source_id, cid, uid, title, url, clean, sha))

    neon_n = 0
    for _, _, uid, _, url, clean, _ in grown:
        found = neon(
            """UPDATE fl_sources_added SET body = $1
                WHERE place_uuid = $2 AND kind = 'web_page'
                  AND removed_at IS NULL AND url = $3
                RETURNING place_uuid""",
            [clean, uid, url],
        )
        if found:
            neon_n += len(found)
        else:
            print(f"  ! not in the remote database: {url}", flush=True)

    by_url = {}
    for _, _, uid, _, url, clean, _ in grown:
        by_url.setdefault(uid, {})[url] = clean
    records = []
    jsonl_n = 0
    with open(OUT, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            pages = by_url.get(record.get("uuid")) or {}
            for page in record.get("web") or []:
                clean = pages.get(page.get("url"))
                if clean and page.get("body") != clean:
                    page["body"] = clean
                    jsonl_n += 1
            records.append(record)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(tmp, OUT)

    sqlite_n = 0
    for attempt in range(40):
        db = sqlite3.connect(paths.PLACES, timeout=30)
        try:
            db.execute("BEGIN IMMEDIATE")
            for source_id, cid, uid, title, url, clean, sha in grown:
                clash = db.execute(
                    "SELECT source_id FROM sources WHERE row_sha = ? AND source_id <> ?",
                    (sha, source_id)).fetchone()
                if clash:
                    continue
                db.execute(
                    "UPDATE sources SET text = ?, row_sha = ? WHERE source_id = ?",
                    (clean, sha, source_id))
                sqlite_n += 1
            db.commit()
            break
        except sqlite3.OperationalError as exc:
            db.rollback()
            sqlite_n = 0
            print(f"  places.sqlite busy ({exc}); retry {attempt + 1}", flush=True)
            time.sleep(3)
        finally:
            db.close()
    else:
        raise RuntimeError("places.sqlite stayed locked")

    print(f"pages replaced: {len(grown)} longer, {skipped} left as they were",
          flush=True)
    print(f"remote {neon_n}, jsonl {jsonl_n}, local sources {sqlite_n}", flush=True)


# A place can have two Swedish articles attached. The readership is one
# article, the one about the place. The other, where it happened, is a
# town, a person, or a different site, and its reads would decide the stars.
ONE_ARTICLE = {
    "google:ChIJ1eM3lwOTREYR51kG7OQyFy4": "Dalslands kanal",
    "google:ChIJ23cGcJfzT0YRTwObKGmSKRg": "Mölndals Kvarnby",
    "google:ChIJ5fl-WSJrVEYRdwuZL3_y0-Y": "Haväng och Vitemölla strandbackar",
    "google:ChIJB7OaGkoyUkYRZ77QED7fctc": "Rosenträdgården",
    "google:ChIJI_w4wla6X0YR7wFVa5a8YCI": "Sankt Olofs kyrkoruin",
    "google:ChIJL-e1URVCX0YRErBvdPvnnY0": "AB Karta & Oaxens Kalkbruk",
    "google:ChIJPwD9TZPLZkYRLqAQNWOY-iE": "Oscarsborg, Söderhamn",
    "google:ChIJPzhwCgUfWEYRZ0DVdImh6wU": "Stensjö, Oskarshamns kommun",
    "google:ChIJTSl_CwBnWUYRbWaWfEKPGiw": "Bergs slussar",
    "google:ChIJcenUqNWu90YRP87GN19vR8k": "Sankt Lars kyrkoruin, Visby",
    "google:ChIJg-_i7faLXUYRw-qMz41QrGQ": "Bispbergs gruva",
    "google:ChIJiX72CwAXRUYRJxFgk7XijLU": "Essljungs gruva",
    "google:ChIJn1QcZuHoXUYRUtAWg6Nyebs": "Lapphyttan",
    "google:ChIJnzt9m-sT90YRF0Adi0f-VCI": "Torsburgen (fornborg)",
    "google:ChIJr64yGY8zUkYRgiwNJRD6HZk": "Attachéväska R.W.",
    "google:ChIJwbERRphzU0YRYysqNmhmjfk": "Vikingaborgen i Trelleborg",
}


def fill_wiki_views():
    """Trailing-year Wikipedia reads for the Google places.

    The register crawl stores these on its own articles. These places were
    never in that crawl, so the star rule, which reads `wiki_views_12m`,
    saw zero for every one of them. The rows go into wiki_articles under
    the place uuid: the next signals build sums that table. One article
    per language. Where two were attached, ONE_ARTICLE says which.
    """
    from crawl_wikimedia import DELAY, get, month_range
    places = sqlite3.connect(f"file:{paths.PLACES}?mode=ro", uri=True)
    rows = places.execute("""
        SELECT DISTINCT cluster_id, uuid, lang, title
          FROM sources
         WHERE kind = 'wikipedia' AND usable = 1
           AND cluster_id LIKE 'google:%'
           AND title IS NOT NULL AND lang IS NOT NULL
    """).fetchall()
    places.close()
    start, end, d0, d1 = month_range()
    print(f"{len(rows)} articles, {d0.isoformat()} .. {d1.isoformat()}",
          flush=True)
    by_title = {}
    for cid, uid, lang, title in rows:
        page = title.partition("#")[0].replace("_", " ").strip()
        by_title.setdefault((lang, page), []).append((cid, uid, title))
    wm = sqlite3.connect(paths.WIKIMEDIA, timeout=60)
    work = sqlite3.connect(paths.WORK, timeout=60)
    fetched = {}
    try:
        for i, ((lang, page), owners) in enumerate(sorted(by_title.items()), 1):
            art = urllib.parse.quote(page.replace(" ", "_"), safe="")
            j = get("https://wikimedia.org/api/rest_v1/metrics/pageviews/"
                    f"per-article/{lang}.wikipedia/all-access/user/{art}/monthly/"
                    f"{start}/{end}")
            time.sleep(DELAY)
            views = 0
            if j and j.get("__error"):
                views = None
                print(f"  ! {page}: {j['__error']}", flush=True)
            elif j:
                views = sum(x.get("views", 0) for x in j.get("items", []))
            fetched[(lang, page)] = views
            if i % 50 == 0 or i == len(by_title):
                got = sum(1 for v in fetched.values() if v is not None)
                print(f"  {i}/{len(by_title)} fetched, {got} with a number",
                      flush=True)
        # One row per place and language. Two Swedish articles is two
        # subjects; the reads of the other one do not belong to this place.
        chosen = {}
        for (lang, page), views in fetched.items():
            if views is None:
                continue
            for cid, uid, title in by_title[(lang, page)]:
                want = ONE_ARTICLE.get(cid)
                if want is not None and lang == "sv" and page != want:
                    continue
                prev = chosen.get((uid, lang))
                if prev is None or (want is not None and page == want):
                    chosen[(uid, lang)] = (cid, page, views)
        for (uid, lang), (cid, page, views) in chosen.items():
            wm.execute("""
                INSERT INTO wiki_articles
                  (uuid, lang, title, views_12m, views_from, views_to,
                   fetched_at)
                VALUES (?,?,?,?,?,?,datetime('now'))
                ON CONFLICT(uuid, lang) DO UPDATE SET
                  title=excluded.title,
                  views_12m=excluded.views_12m,
                  views_from=excluded.views_from,
                  views_to=excluded.views_to,
                  fetched_at=excluded.fetched_at
            """, (uid, lang, page, views, d0.isoformat(), d1.isoformat()))
        wm.commit()
        # Sum of languages, one place. Same rule as build_signals.wiki_views.
        totals = {}
        for cid, page, views in chosen.values():
            totals[cid] = totals.get(cid, 0) + views
        for cid, views in totals.items():
            work.execute(
                "UPDATE signals SET wiki_views_12m=? WHERE cluster_id=?",
                (views, cid))
        work.commit()
    finally:
        wm.close()
        work.close()
    nums = [v for v in fetched.values() if v is not None]
    nums.sort()
    def pct(p):
        return nums[int((len(nums) - 1) * p)] if nums else 0
    print(f"views: {len(nums)} articles, "
          f"median {pct(0.5):,}  p90 {pct(0.9):,}  max {nums[-1] if nums else 0:,}",
          flush=True)
    print(f"  >=500: {sum(v >= 500 for v in nums)}   "
          f">=3000: {sum(v >= 3000 for v in nums)}", flush=True)
    print(f"signals updated for {len(totals)} places", flush=True)


def fill_wiki_bodies():
    """The Wikipedia source on each Google place becomes the whole article.

    The import stored the lead. The register crawl already keeps the article
    and cuts it at the references; these places were never in that crawl.
    """
    import build_sources
    places = sqlite3.connect(f"file:{paths.PLACES}?mode=ro", uri=True)
    rows = places.execute("""
        SELECT source_id, cluster_id, uuid, lang, title, url, text
          FROM sources
         WHERE kind = 'wikipedia' AND usable = 1
           AND cluster_id LIKE 'google:%'
    """).fetchall()
    places.close()
    keys = sorted({((lang or "sv"), title)
                   for _, _, _, lang, title, _, _ in rows if title})
    print(f"{len(rows)} wikipedia sources, {len(keys)} articles", flush=True)
    bodies = {}
    for i, (lang, title) in enumerate(keys, 1):
        bodies[(lang, title)] = wiki_body(lang, title)
        if i % 25 == 0 or i == len(keys):
            got = sum(1 for v in bodies.values() if v)
            print(f"  fetched {i}/{len(keys)}, {got} with text", flush=True)

    grown = []
    skipped = 0
    for source_id, cid, uid, lang, title, url, text in rows:
        body = bodies.get(((lang or "sv"), title))
        if not body:
            skipped += 1
            print(f"  ! no article: {title}", flush=True)
            continue
        clean = build_sources.keep_lines(body)
        old = build_sources.keep_lines(text or "")
        if len(clean) <= len(old):
            skipped += 1
            continue
        sha = build_sources.row_sha(cid, "wikipedia", lang, url, clean)
        grown.append((source_id, cid, uid, lang, title, url, clean, sha))

    neon_n = 0
    for _, _, uid, _, title, url, clean, _ in grown:
        found = neon(
            """UPDATE fl_sources_added SET body = $1
                WHERE place_uuid = $2 AND kind = 'wikipedia'
                  AND removed_at IS NULL
                  AND COALESCE(url, '') = COALESCE($3, '')
                RETURNING place_uuid""",
            [clean, uid, url],
        )
        if not found and title:
            found = neon(
                """UPDATE fl_sources_added SET body = $1
                    WHERE place_uuid = $2 AND kind = 'wikipedia'
                      AND removed_at IS NULL AND title = $3
                    RETURNING place_uuid""",
                [clean, uid, title],
            )
        if found:
            neon_n += len(found)
        else:
            print(f"  ! not in the remote database: {title}", flush=True)

    by_key = {(uid, lang, title): clean
              for _, _, uid, lang, title, _, clean, _ in grown}
    records = []
    jsonl_n = 0
    with open(OUT, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            wiki = record.get("wikipedia") or {}
            clean = by_key.get((record.get("uuid"), wiki.get("lang"), wiki.get("title")))
            if clean and wiki.get("extract") != clean:
                wiki["extract"] = clean
                record["wikipedia"] = wiki
                jsonl_n += 1
            records.append(record)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(tmp, OUT)

    sqlite_n = 0
    for attempt in range(40):
        db = sqlite3.connect(paths.PLACES, timeout=30)
        try:
            db.execute("BEGIN IMMEDIATE")
            for source_id, cid, uid, lang, title, url, clean, sha in grown:
                clash = db.execute(
                    "SELECT source_id FROM sources WHERE row_sha = ? AND source_id <> ?",
                    (sha, source_id)).fetchone()
                if clash:
                    continue
                db.execute(
                    "UPDATE sources SET text = ?, row_sha = ? WHERE source_id = ?",
                    (clean, sha, source_id))
                sqlite_n += 1
            db.commit()
            break
        except sqlite3.OperationalError as exc:
            db.rollback()
            sqlite_n = 0
            print(f"  places.sqlite busy ({exc}); retry {attempt + 1}", flush=True)
            time.sleep(3)
        finally:
            db.close()
    else:
        raise RuntimeError("places.sqlite stayed locked")

    print(f"articles replaced: {len(grown)} longer, {skipped} left as they were",
          flush=True)
    print(f"remote {neon_n}, jsonl {jsonl_n}, local sources {sqlite_n}", flush=True)


def main():
    if "--bodies" in sys.argv:
        fill_wiki_bodies()
        return
    if "--views" in sys.argv:
        fill_wiki_views()
        return
    if "--classes" in sys.argv:
        apply_classes()
        return
    if "--web-bodies" in sys.argv:
        fill_web_bodies()
        return
    if "--merge" in sys.argv:
        only = None
        if "--only" in sys.argv:
            only = sys.argv[sys.argv.index("--only") + 1]
        merge_verified(only)
        return
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    if "--publish" in sys.argv:
        publish_stored()
        return
    have = done_ids()
    todo = [r for r in candidates() if r["placeId"] not in have]
    if limit is not None:
        todo = todo[:limit]
    print(f"{len(todo):,} places to add ({len(have):,} already stored)",
          flush=True)
    shards = {}
    work = sqlite3.connect(paths.WORK, timeout=60)
    places = sqlite3.connect(paths.PLACES, timeout=60)
    fresh = []
    try:
        for i, row in enumerate(todo, 1):
            try:
                record = research(row)
            except Exception as exc:
                print(f"  ! {row.get('title')}: {exc}", flush=True)
                continue
            with open(OUT, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            store_one(work, record)
            sources_one(places, record)
            places.commit()
            try:
                publish_one(record, shards)
            except Exception as exc:
                print(f"  ! publish {record['title']}: {exc}", flush=True)
            fresh.append(record)
            wiki = "wiki" if record.get("wikipedia") else "no-wiki"
            print(f"  {i}/{len(todo)}  {record['title']}  "
                  f"{len(record['photos'])} photos  {wiki}  "
                  f"{len(record['web'])} pages", flush=True)
            if i % 10 == 0:
                shard_flush(shards)
        shard_flush(shards)
    finally:
        work.close()
        places.close()
    if fresh and limit is None:
        from build_places import write_place_coords
        write_place_coords()
    elif fresh:
        print("  (coords file left for the full run)", flush=True)


if __name__ == "__main__":
    main()
