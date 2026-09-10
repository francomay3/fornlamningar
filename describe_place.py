#!/usr/bin/env python3
"""
Turn one RAA register entry into a couple of sentences a visitor would read.

The register is written by surveyors for other surveyors, in Swedish, to the
centimetre: "Stensattning, rund, 7 m diam och 0,3 m h. Overtorvad med i ytan
enstaka synliga stenar, 0,2-0,4 m st. Bevaxt med en tall." That is the right
text for an archaeologist and the wrong text for someone deciding whether to
walk twenty minutes off a road. This rewrites it.

What it does NOT do is add anything. The single biggest risk here is a model
that knows a lot about Bronze Age Scandinavia deciding to tell you about it:
dating, ritual purpose, "the people who built this believed...". None of that
is in the source, none of it is verifiable, and on a map of 10,000 places a
plausible invention is worse than a dull fact. So: temperature 0, a schema
enforced by Ollama, an explicit instruction to use only what is present, and
afterwards a check that every number in the output can be traced back to the
input.

Reads:  src/data/sites.sqlite   (read-only)
Writes: nothing -- this is the single-place generator. build_descriptions.py
        is the batch runner that persists.

Usage:
    python3 describe_place.py --lamning L1968:8656
    python3 describe_place.py --top 5 --model qwen3:8b
    python3 describe_place.py --top 3 --compare qwen3:8b,gemma3:4b
"""

import argparse
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request

DB = "src/data/sites.sqlite"
HOST = "http://localhost:11434"
DEFAULT_MODEL = "gemma3:12b"
# Translation is the easy pass, so it does not need the big model.
TRANSLATE_MODEL = "gemma3:12b"

# Bump when the prompt changes in a way that should invalidate stored output.
PROMPT_VERSION = 8

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "content": {"type": "string"},
    },
    "required": ["title", "content"],
}

SYSTEM = """\
You rewrite entries from the Swedish national heritage register for a map app \
that helps people visit archaeological sites.

Write in SWEDISH. The source is Swedish and so is your answer. You are not \
translating anything -- you are turning field-survey shorthand into plain \
Swedish that an ordinary person would read before walking out to the place.

Hard rules:
- Use ONLY facts present in the input. Do not add dating, cultural period, \
purpose, ritual meaning or historical context, and nothing you happen to know \
about this type of site. Age in particular: never state or hint at one. It is \
added separately from a reviewed table.
- Do not romanticise. Banned: mystisk, uråldrig, helig, majestätisk, tidlös, \
vittnar om, viskar, stått i århundraden.
- Do not mention the register, the survey, surveyors, inspection dates or \
damage classifications. Never repeat its internal pointers: no "se \
referensmaterial", "se bokbeskrivning", "se inskannat", "för mer information", \
no cross-references to other lamningar. If the input is mostly a pointer to \
somewhere else, ignore the pointer and describe what little is left.
- MEASUREMENTS BELONG SOMEWHERE ELSE, and this is the rule you are most \
likely to break, so check your answer against it before replying. The app shows the size as separate \
subtext, so do not put dimensions in your prose. The one exception is when \
the size IS what makes the place notable -- a 35-metre stone ship, an \
unusually tall mound, a wall you can still walk along. Then one number \
earns its place. A dolmen does not need to open with how many metres across \
it is; a skeppssättning does.
- Never give a relative measurement: how far up a face a carving begins, how \
thick a wall is, how far away another site is, how big the individual stones \
are.
- Do NOT list an inventory. If the input enumerates components ("1 borggård, \
4 vallar, 2 husgrunder, 1 brunn"), compress it the way a person speaking \
would: "vallar, två husgrunder och en brunn".
- Write out the survey's abbreviations: "2,9 m h" is "2,9 meter hög", NÖ is \
nordost, SV is sydväst, "st" is stora, "diam" is i diameter, "l" is lång, \
"br" is bred, "tj" is tjock. If you are not certain of a direction, leave it \
out.
- "X, rest av" means the REMAINS of an X -- damaged, partly gone. It does not \
mean anything is standing upright. "Rest sten" (two words, no comma) is a \
standing stone. Do not confuse them, and never change what kind of site it \
is: a hällkista stays a hällkista, it does not become a stenkrets.
- Counts must be exact. If the input says 85 remains of which 31 are mounds, \
do not write "85 högar".
- You have 45 words and the input has more. Keep the SPECIFIC and drop the \
generic: a folk name, the wording of an inscription, cup marks, a shelter \
built over it, an old map that names it, a tree growing out of it. Those are \
worth more to a reader than a dimension.
- Plain Swedish. No exclamation marks. Do not open with "Detta är" or \
"Lämningen utgörs av".
- If the input has no real content beyond a generic disclaimer, return an \
empty string for content.

title, in two cases:
- If the "name" field is not null, the title is EXACTLY that name and nothing \
else. Do not add the type, a colon, a description or a place.
      name "Anundshög"  ->  WRONG "Gravfält med skeppssättningar, Anundshög, \
Västerås"   RIGHT "Anundshög"
      name "Rökstenen"  ->  WRONG "Rökstenen: Runristning med lönnskrift"   \
RIGHT "Rökstenen"
- If "name" is null, the title is WHAT the place is plus ONE detail that tells \
it apart from others of the same kind, taken from the source: "Gravfält med \
85 gravar", "Runsten med otolkade runor", "Röse med plundringsgrop". One \
detail, not two -- and only if the source gives you one. Where the record \
says no more than "se skannat dokument", the bare type is the whole title. \
Never invent a count or a feature to fill the slot.
Never name a parish, village, municipality or county, in either case, not \
even after a comma -- the map already shows where the place is, and "Gravhög \
i Fjärås" tells the reader nothing that "Gravhög" does not. Never invent a \
poetic name. Under 45 characters.

content: 1 to 3 sentences, at most 45 words."""

EXAMPLES = [
    ({"class": "Runristning", "name": None, "location": "Stala, Orust",
      "source": "Runsten, gnejs, 2,9 m h, 0,7 m br (NÖ-SV) och 0,3 m tj. "
                "Runhöjd 10-12 cm. Ristningen vetter mot SV och börjar 0,94 m "
                "från basen. Runradens längd är 0,84 m. Runorna är ifyllda med "
                "färg, de är ej tolkade.",
      "size": "length/diameter 2.9 m"},
     {"title": "Runsten med otolkade runor",
      "content": "En runsten av gnejs. Runorna vetter mot sydväst och är "
                 "ifyllda med färg, men de är ännu inte tolkade."}),
    ({"class": "Stenkrets/stenrad", "name": "Ales stenar",
      "location": "Valleberga, Ystad",
      "source": "Skeppssättning, 67 m l (NV-SÖ) och 19 m br, bestående av 59 "
                "resta stenar, 0,5-2,5 m h. Stävstenarna är högst. Belägen på "
                "krön av brant klint mot havet.",
      "size": "length/diameter 67 m"},
     {"title": "Ales stenar",
      "content": "En skeppssättning av 59 resta stenar, 67 meter lång, med de "
                 "högsta stenarna i stävarna. Den ligger på krönet av en brant "
                 "klint mot havet."}),
]

TRANSLATE_SYSTEM = """\
Translate a short Swedish text about an archaeological site into English.

This is the easy half of the job: the Swedish you are given has already been \
simplified, so translate it and change nothing else. Do not shorten, expand, \
re-order, improve or add. Same facts, same number of sentences, same register.

Swedish heritage terms: gravfält = grave field; hög = burial mound; röse = \
cairn; stensättning = stone setting; stenkammargrav and gånggrift = passage \
grave; hällkista = stone cist; täckhäll = capstone; hällristning = rock \
carving; hällmålning = rock painting; runsten = runestone; skålgrop = cup \
mark; fornborg = hillfort; borg = castle; förborg = outer bailey; vall = \
rampart; vallgrav = moat; borggård = courtyard; husgrund = house foundation; \
kantkedja = kerb; skeppssättning = stone ship setting; stävsten = prow stone; \
domarring = judge ring; bytomt = village site; fäbod = summer farm; hytta = \
blast furnace; blästplats = bloomery; kolningsanläggning = charcoal burning \
site; fångstgrop = pitfall trap; tomtning = hut foundation; skärvstenshög = \
mound of fire-cracked stone; övertorvad = turfed over; betesmark = pasture; \
hällmark = bare rock; morän = moraine; krön = crest; klint = cliff.

treudd = three-pointed stone setting; hällkista = stone cist; klapperstensfält \
= field of beach cobbles; rest sten = standing stone; röjningsröse = clearance \
cairn; offerkast = offering cairn.

More class names, all of which have come out wrong: färdväg = old road (NOT \
"journey"); hägnadsmur and hägnad = enclosure wall (a field boundary, NOT \
defensive); klosterruin = monastery ruins; kloster = monastery; skans = \
redoubt; spärranordning = underwater barrier; milstolpe = milestone; \
fästning = fortress; bro = bridge; kyrkogård = churchyard; kapell = chapel; \
kolerakyrkogård = cholera cemetery; slagfält = battlefield; \
avrättningsplats = execution site; minnesmärke = memorial; \
gruvhål = mine shaft; lämning = remains.

Compass words: nordost = north-east, sydväst = south-west, sydost = \
south-east, nordväst = north-west, öster = east, väster = west.

Capitalise titles as a sentence, not as a headline: only the first word and \
proper names take a capital. "Fornborg med glaspärlstillverkning" becomes \
"Hillfort with glass bead production", never "Hillfort with Glass Bead \
Production".

Leave Swedish PLACE NAMES and site names exactly as they are. "Äggastenarna" \
stays "Äggastenarna", not "the Egg Stones"; "Ales stenar" stays "Ales stenar". \
Translating a name makes it impossible to find the place on a sign or a map."""


def payload(conn, cluster_id):
    """Everything the model is allowed to know about a place."""
    r = conn.execute("""
        SELECT c.cluster_id, c.name, c.dominant_class, c.n_sites, c.n_classes,
               c.class_mix, c.parish, c.municipality, c.county, c.province,
               c.spread_m, c.best_description, c.all_boilerplate,
               s.uuid, s.lamningsnummer, s.dim_len_m, s.dim_height_m,
               s.dim_area_m2, s.terrang
          FROM clusters c
          LEFT JOIN sites s ON s.uuid = (
               SELECT s2.uuid FROM site_clusters x JOIN sites s2 ON s2.uuid = x.uuid
                WHERE x.cluster_id = c.cluster_id
                ORDER BY s2.description_len DESC, s2.uuid LIMIT 1)
         WHERE c.cluster_id = ?""", (cluster_id,)).fetchone()
    if r is None:
        return None

    place = " ".join(x for x in (r["parish"], r["municipality"]) if x)
    dims = []
    if r["dim_len_m"]:
        dims.append(f"length/diameter {r['dim_len_m']:g} m")
    if r["dim_height_m"]:
        dims.append(f"height {r['dim_height_m']:g} m")
    out = {
        "class": r["dominant_class"],
        "name": r["name"],
        "location": f"{place}, {r['county']}" if r["county"] else place,
        "source": " ".join((r["best_description"] or "").split()),
    }
    if (r["n_sites"] or 1) > 1:
        out["group"] = (f"{r['n_sites']} recorded remains within "
                        f"{round(r['spread_m'] or 0)} m: {r['class_mix']}")
    if dims:
        out["size"] = ", ".join(dims)
    if r["terrang"]:
        out["surroundings"] = " ".join(r["terrang"].split())
    return {"cluster_id": r["cluster_id"], "uuid": r["uuid"],
            "lamning": r["lamningsnummer"], "boilerplate": r["all_boilerplate"],
            "model_input": out}


def messages(model_input):
    msgs = [{"role": "system", "content": SYSTEM}]
    for inp, out in EXAMPLES:
        msgs.append({"role": "user", "content": json.dumps(inp, ensure_ascii=False)})
        msgs.append({"role": "assistant", "content": json.dumps(out, ensure_ascii=False)})
    msgs.append({"role": "user",
                 "content": json.dumps(model_input, ensure_ascii=False)})
    return msgs


def generate(model_input, model=DEFAULT_MODEL, host=HOST, timeout=180):
    body = {
        "model": model,
        "messages": messages(model_input),
        "stream": False,
        "format": SCHEMA,
        # Nothing here benefits from sampling. We want the same input to give
        # the same output, so a rerun is a no-op and a bad output is
        # reproducible while we fix the prompt.
        "options": {"temperature": 0, "num_predict": 400},
        # Reasoning models burn seconds thinking about a paraphrase and
        # sometimes leak the reasoning into the JSON. Ignored by models that
        # have no thinking mode.
        "think": False,
    }
    req = urllib.request.Request(
        f"{host}/api/chat", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    elapsed = time.time() - t0
    text = data.get("message", {}).get("content", "")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None, elapsed, f"unparseable JSON: {text[:200]}"
    title = " ".join(str(parsed.get("title") or "").split())
    content = " ".join(str(parsed.get("content") or "").split())
    return {"title": title, "content": content}, elapsed, None


def translate(sv, model=None, host=HOST, timeout=180):
    """Second pass: the simplified Swedish into English.

    Split from generation on purpose. Doing both at once meant every
    translation slip landed in the only text we had -- "O" read as west
    instead of east, taeckhaellar as "covered cairns", Borg as "hillfort".
    All of our errors were translation errors and none were simplification
    errors, so the two jobs are now separate: the hard one (jargon into plain
    language) runs against the source, and the easy one runs against clean
    text and can be redone with a better model without touching it.
    """
    body = {
        "model": model or TRANSLATE_MODEL,
        "messages": [
            {"role": "system", "content": TRANSLATE_SYSTEM},
            {"role": "user", "content": json.dumps(
                {"title": sv["title"], "content": sv["content"]},
                ensure_ascii=False)},
        ],
        "stream": False,
        "format": SCHEMA,
        "options": {"temperature": 0, "num_predict": 400},
        "think": False,
    }
    req = urllib.request.Request(
        f"{host}/api/chat", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    elapsed = time.time() - t0
    try:
        parsed = json.loads(data.get("message", {}).get("content", ""))
    except json.JSONDecodeError:
        return None, elapsed, "unparseable JSON"
    return ({"title": " ".join(str(parsed.get("title") or "").split()),
             "content": " ".join(str(parsed.get("content") or "").split())},
            elapsed, None)


RETITLE_SYSTEM = """\
Give a short Swedish title to an archaeological site. Reply with JSON: \
{"title": "..."}.

You are given the register fields plus "already_written", the finished plain \
Swedish description of this place. The distinguishing detail is in there \
-- use it.

Two cases:
- If "name" is not null, the title is EXACTLY that name and nothing else. No \
type, no colon, no description, no place.
      name "Rökstenen"  ->  WRONG "Rökstenen: Runristning med lönnskrift"   \
RIGHT "Rökstenen"
- If "name" is null, the title is WHAT the place is plus ONE detail from \
"already_written" that tells it apart from others of the same kind. Prefer a \
detail over the bare type, which merely repeats the class the reader is \
already shown -- but ONLY if the description actually contains one. Some \
records say no more than "se skannat dokument"; for those the bare type is \
the correct and complete answer. Never supply a detail the description does \
not give you. A made-up count is far worse than a dull title.
      WRONG "Fornborg"        RIGHT "Fornborg med spår av glaspärlstillverkning"
      WRONG "Klosterruiner"   RIGHT "Klosterruiner med hägnadsmur och tre dammar"
      WRONG "Gravfält"        RIGHT "Gravfält med skeppssättningar och runsten"

Where "already_written" describes something other than the "class" field, \
trust "already_written" -- the class is the commonest type in a mixed group \
and is sometimes not what the place is really about.

Never name a parish, village, municipality or county, not even after a comma: \
the map already shows where the place is. Never invent a poetic name. Plain \
Swedish, under 50 characters."""

TITLE_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
}


def retitle(model_input, content_sv, model=DEFAULT_MODEL, host=HOST,
            timeout=120):
    """Rewrite only the title, leaving the approved body text alone.

    The title rule changed after 253 descriptions had already been written and
    reviewed: they were coming out as "Gravfalt i Fjaras", naming the parish,
    which the map already shows and which made every title of a given class
    interchangeable. Regenerating everything would have thrown away body text
    that was read and approved, so this asks for a title only -- and shows the
    model the finished Swedish body, which is where the distinguishing detail
    already is.
    """
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": RETITLE_SYSTEM},
            {"role": "user", "content": json.dumps(
                {**model_input, "already_written": content_sv},
                ensure_ascii=False)},
        ],
        "stream": False,
        "format": TITLE_SCHEMA,
        "options": {"temperature": 0, "num_predict": 80},
        "think": False,
    }
    req = urllib.request.Request(
        f"{host}/api/chat", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    elapsed = time.time() - t0
    try:
        parsed = json.loads(data.get("message", {}).get("content", ""))
    except json.JSONDecodeError:
        return None, elapsed, "unparseable JSON"
    return " ".join(str(parsed.get("title") or "").split()), elapsed, None


def translate_title(title_sv, model=None, host=HOST, timeout=120):
    """The English title for a Swedish one, on its own."""
    body = {
        "model": model or TRANSLATE_MODEL,
        "messages": [
            {"role": "system", "content": TRANSLATE_SYSTEM},
            {"role": "user",
             "content": json.dumps({"title": title_sv}, ensure_ascii=False)},
        ],
        "stream": False,
        "format": TITLE_SCHEMA,
        "options": {"temperature": 0, "num_predict": 80},
        "think": False,
    }
    req = urllib.request.Request(
        f"{host}/api/chat", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    elapsed = time.time() - t0
    try:
        parsed = json.loads(data.get("message", {}).get("content", ""))
    except json.JSONDecodeError:
        return None, elapsed, "unparseable JSON"
    return " ".join(str(parsed.get("title") or "").split()), elapsed, None


# --- output checks ---------------------------------------------------------
BANNED = re.compile(
    r"\b(mysterious|ancient|sacred|majestic|timeless|shrouded|whisper\w*|"
    r"testament|silent witness|bygone|time-worn|awe-inspiring|enigmatic|"
    r"spiritual|mystical|legendary|"
    r"mystisk\w*|uråldrig\w*|helig\w*|majestätisk\w*|tidlös\w*|"
    r"vittnar om|viskar|sägenomsusad\w*)\b", re.I)
NUM = re.compile(r"\d+(?:[.,]\d+)?")
# Straight, curly and Swedish quotes, plus the guillemets the register uses.
QUOTED = re.compile(r"['\"\u2018\u2019\u201c\u201d\u201e\u00ab\u00bb]"
                    r"[^'\"\u2018\u2019\u201c\u201d\u201e\u00ab\u00bb]*"
                    r"['\"\u2018\u2019\u201c\u201d\u201e\u00ab\u00bb]")


def _numbers(text):
    return [float(m.group().replace(",", ".")) for m in NUM.finditer(text or "")]


def check(result, model_input):
    """Cheap, mechanical hallucination checks. Flags, never rejects.

    The number check is the useful one: it is the only class of invention we
    can catch automatically. A number in the output that is nowhere near any
    number in the input means the model produced a measurement, a year or a
    count out of thin air. Rounding is allowed for -- 7,2 becoming "about 7"
    is exactly what we asked for -- so a source number within 15%, or whose
    rounded value matches, counts as support.
    """
    flags = []
    src = " ".join(str(v) for v in model_input.values())
    src_nums = _numbers(src)
    # Accept a source number, the same number rounded, or the same number in
    # the other unit -- the source writes "0,84 m" and a metre-to-centimetre
    # rewrite to "84 cm" is correct, not invented. Without this the check
    # cried wolf on exactly the conversions we asked the model to make.
    candidates = [c for s in src_nums for c in (s, s * 100, s / 100)]
    # Two-digit years, as the register writes them: "vid inv -81" is 1981, and
    # a model that expands it has read the source correctly rather than made a
    # number up. Only 1900-1999, because that is the abbreviation surveyors
    # used; a bare "-05" is far more likely a range than 1905.
    candidates += [1900 + s for s in src_nums if 0 <= s <= 99]
    for n in _numbers(result["content"]) + _numbers(result["title"]):
        if any(abs(n - s) <= max(0.15 * max(abs(s), 1e-9), 0.05)
               or round(n) == round(s) for s in candidates):
            continue
        flags.append(f"number:{n:g}")
    # Quoted spans are exempt. The register transcribes what a stone actually
    # says, and an inscription reading "Ty platsen ar helig" or "den heliga
    # Sancta Maria" is a quotation, not the model reaching for reverence. Both
    # were flagged and both were correct, and a flagged row ships raw Swedish
    # instead -- so this check was throwing away good descriptions.
    prose = QUOTED.sub(" ", result["content"]) + " " + result["title"]
    if BANNED.search(prose):
        flags.append("purple:" + ",".join(
            sorted({m.group(0).lower() for m in BANNED.finditer(
                prose)})))
    words = len(result["content"].split())
    if words > 80:
        flags.append(f"long:{words}w")
    if len(result["title"]) > 50:
        flags.append(f"title:{len(result['title'])}c")
    if result["content"] and result["content"].lower().startswith("this is"):
        flags.append("thisis")
    # Not an error, just the rule the model breaks most. Measured rather than
    # argued about: the size is shown as subtext anyway, so a duplicated
    # dimension is a blemish, not a falsehood. Worth knowing the rate.
    if re.search(r"\d+(?:[.,]\d+)?\s*(?:m|meter|metres|meters|cm)\b",
                 result["content"], re.I):
        flags.append("dim-in-prose")
    return flags


def top_clusters(conn, n):
    return [r["cluster_id"] for r in conn.execute("""
        SELECT c.cluster_id FROM clusters c
          JOIN scores sc ON sc.cluster_id = c.cluster_id
         WHERE c.lon IS NOT NULL AND sc.excluded_hard = 0 AND sc.excluded_soft = 0
         ORDER BY sc.score_intrinsic DESC LIMIT ?""", (n,))]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=DB)
    p.add_argument("--host", default=HOST)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--compare", help="comma-separated models to run side by side")
    p.add_argument("--cluster-id")
    p.add_argument("--lamning", help="e.g. L1968:8656")
    p.add_argument("--top", type=int, help="the N best-scoring places")
    p.add_argument("--show-input", action="store_true")
    a = p.parse_args()

    conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    ids = []
    if a.cluster_id:
        ids = [a.cluster_id]
    elif a.lamning:
        row = conn.execute("""
            SELECT sc.cluster_id FROM sites s JOIN site_clusters sc ON sc.uuid = s.uuid
             WHERE s.lamningsnummer = ?""", (a.lamning,)).fetchone()
        if not row:
            sys.exit(f"no cluster for {a.lamning}")
        ids = [row["cluster_id"]]
    elif a.top:
        ids = top_clusters(conn, a.top)
    else:
        sys.exit("pass --cluster-id, --lamning or --top")

    models = a.compare.split(",") if a.compare else [a.model]
    stats = {m: [0.0, 0, 0] for m in models}   # seconds, calls, flagged

    for cid in ids:
        pl = payload(conn, cid)
        if pl is None:
            print(f"!! {cid}: not found")
            continue
        print("=" * 78)
        print(f"{pl['lamning'] or cid}  |  {pl['model_input']['class']}  |  "
              f"{pl['model_input']['location']}")
        if a.show_input:
            print(json.dumps(pl["model_input"], ensure_ascii=False, indent=2))
        else:
            src = pl["model_input"]["source"]
            print(f"  SOURCE: {src[:220]}{'...' if len(src) > 220 else ''}")
        for m in models:
            res, elapsed, err = generate(pl["model_input"], m, a.host)
            stats[m][0] += elapsed
            stats[m][1] += 1
            if err:
                print(f"  [{m}] ERROR {err}")
                continue
            flags = check(res, pl["model_input"])
            if flags:
                stats[m][2] += 1
            print(f"  [{m}] {elapsed:.1f}s{'  FLAGS ' + ' '.join(flags) if flags else ''}")
            print(f"     title:   {res['title']}")
            print(f"     content: {res['content'] or '(empty)'}")

    print("=" * 78)
    for m, (secs, n, flagged) in stats.items():
        if n:
            print(f"{m}: {secs/n:.1f}s per place, {flagged}/{n} flagged")


if __name__ == "__main__":
    main()
