#!/usr/bin/env python3
"""
Parse monument dimensions out of RAA's Swedish description text.

96.7% of descriptions state measurements, and size is the thing that separates a
real monument from a technicality: an 18 m x 2 m rose is worth a detour, a
1.3 m stone with one 35 cm groove is not — yet both are the same `class_sv`.

Two traps the patterns must avoid:

  * STONE size, not monument size:
        "...talrika, synliga stenar, 0.3-0.6 m st..."
    The kerb stones of a grave are always sub-metre; reading them as the
    monument's extent makes every cairn look tiny.
  * DISTANCE to a neighbouring site:
        "Ca 65 m S 20° O om L1967:1934"
    A bearing like `m S 20° O om` or `m NÖ om` is a direction, not a size, and
    would otherwise register as a 65 m monument.

Strategy: the monument's own dimensions are stated first, so parse the leading
clause and stop at the first stone/pit enumeration. Then take the largest
surviving horizontal measure plus the height.
"""

import re

# 1,5 / 1.5 / 15
NUM = r"\d+(?:[.,]\d+)?"

# Bearings: "65 m S 20° O om", "12 m NÖ om", "5 m N om"
BEARING = re.compile(
    rf"{NUM}\s*m\s*(?:[NSÖVO]{{1,3}}|[NSÖVO]\s*\d+\s*(?:°|cg|gr))\s*(?:[oO]m)?",
    re.I)

# Where the text stops describing the monument and starts describing its parts.
# Deliberately only PLURAL / collective terms: singular "stenblock" or "block"
# is frequently the monument itself (a boulder bearing cup marks), and cutting
# there loses its size. "skålgrop" is likewise part of a monument NAME
# ("Skålgropsförekomst..."), so it must not trigger a cut either.
CUT = re.compile(
    r"\b(?:stenar(?:na)?|kantkedj|fyllning|packning|klumpar|"
    r"gropar|stenpackning)\b", re.I)

RE_DIAM = re.compile(rf"({NUM})\s*m\s*(?:i\s*)?diam|"
                     rf"({NUM})\s*m\s*i\s*diameter", re.I)
RE_RECT = re.compile(rf"({NUM})\s*[xX]\s*({NUM})\s*m", re.I)
# "Gravfalt 240 x 45-135 m" -- a range for the second side. Without this the
# whole rectangle fails to match and the parser falls back to the size of an
# INDIVIDUAL mound mentioned later ("16 m diam"), so a 240 m grave field was
# being recorded as 16 m. 14,896 descriptions use this form.
RE_RECT_RANGE = re.compile(
    rf"({NUM})\s*[xX]\s*({NUM})\s*-\s*({NUM})\s*m", re.I)
# "0.3-0.6 m h" / "5-8 m diam": take the upper bound.
RE_DIAM_RANGE = re.compile(
    rf"({NUM})\s*-\s*({NUM})\s*m\s*(?:i\s*)?diam", re.I)
RE_HIGH_RANGE = re.compile(
    rf"({NUM})\s*-\s*({NUM})\s*m\s*(?:h\b|hög|höjd)", re.I)
RE_HIGH = re.compile(rf"({NUM})\s*m\s*(?:h\b|hög|höjd)", re.I)
RE_LONG = re.compile(rf"({NUM})\s*m\s*(?:l\b|lång|längd)", re.I)
RE_SIZE = re.compile(rf"({NUM})\s*m\s*st\b", re.I)


# Largest plausible horizontal extent. Grave fields genuinely reach several
# hundred metres -- Li gravfalt at Fjaras Bracka is "ca 500x125 m" with ~160
# monuments -- and an earlier 500 m ceiling silently rejected it, because the
# guard read `a < 500`. Height is capped much lower: nothing here is 100 m tall.
MAX_HORIZ = 2000.0
MAX_VERT = 100.0


def _f(x):
    return float(x.replace(",", ".")) if x else None


def parse_dims(text, head=260):
    """Return (length_m, height_m, area_m2) — None where not stated.

    `length_m` is the largest horizontal extent; `area_m2` uses the rectangle
    when given, otherwise a circle from the diameter.
    """
    if not text:
        return None, None, None
    t = " ".join(text.split())

    # Drop bearings before anything else, so distances never look like sizes.
    t = BEARING.sub(" ", t)

    # Keep only the leading clause describing the monument itself.
    head_txt = t[:head]
    m = CUT.search(head_txt)
    if m and m.start() > 20:          # keep at least the opening statement
        head_txt = head_txt[:m.start()]

    length = area = height = None

    # Ranges first: "240 x 45-135 m" must win over the plain "240 x 45" read,
    # and RE_RECT would otherwise never match this string at all.
    for mm in RE_RECT_RANGE.finditer(head_txt):
        a, lo, hi = _f(mm.group(1)), _f(mm.group(2)), _f(mm.group(3))
        if a and lo and hi and a < MAX_HORIZ and hi < MAX_HORIZ:
            length = max(length or 0, a, hi)
            # mean width for area: the upper bound alone overstates it
            area = max(area or 0, a * (lo + hi) / 2)

    for mm in RE_DIAM_RANGE.finditer(head_txt):
        hi = _f(mm.group(2))
        if hi and hi < MAX_HORIZ:
            length = max(length or 0, hi)
            area = max(area or 0, 3.14159 * (hi / 2) ** 2)

    for mm in RE_RECT.finditer(head_txt):
        a, b = _f(mm.group(1)), _f(mm.group(2))
        if a and b and a < MAX_HORIZ and b < MAX_HORIZ:
            length = max(length or 0, a, b)
            area = max(area or 0, a * b)

    for mm in RE_DIAM.finditer(head_txt):
        d = _f(mm.group(1) or mm.group(2))
        if d and d < MAX_HORIZ:
            length = max(length or 0, d)
            area = max(area or 0, 3.14159 * (d / 2) ** 2)

    for mm in RE_LONG.finditer(head_txt):
        v = _f(mm.group(1))
        if v and v < MAX_HORIZ:
            length = max(length or 0, v)

    # `N m st` is a size statement; only trust it if nothing better was found,
    # because it is also how stone sizes are written.
    if length is None:
        for mm in RE_SIZE.finditer(head_txt):
            v = _f(mm.group(1))
            if v and v < MAX_HORIZ:
                length = max(length or 0, v)

    for mm in RE_HIGH_RANGE.finditer(head_txt):
        hi = _f(mm.group(2))
        if hi and hi < MAX_VERT:
            height = max(height or 0, hi)

    for mm in RE_HIGH.finditer(head_txt):
        v = _f(mm.group(1))
        if v and v < MAX_VERT:
            height = max(height or 0, v)

    return length, height, area


if __name__ == "__main__":
    import sqlite3
    import sys
    tests = [
        ("Stensättning, 10 m diam och 0.3 m h. Övertorvad med i ytan talrika, "
         "synliga stenar, 0.3-0.6 m st, till största delen rundade.",
         "trampa: piedras 0.3-0.6 m no deben contar"),
        ("Fyrtorn, ruin. Ca 65 m S 20° O om L1967:1934, som den är identiskt "
         "lik. Ca 5 m hög, ca 4 m i diameter.",
         "trampa: 65 m es una distancia"),
        ("Svärdlipningssten/häll av granit, 1,3x1,3 m med 1 slipskåra ca 35 cm l.",
         "el que Franco marcó 0"),
        ("Röse, 18 m diam och 2 m h. Övertorvat.", "monumento grande"),
        ("Skålgropsförekomst i av frostsprängning fyrdelat stenblock, 5x5 m st "
         "och ca 1 m h", "hoyuelos: bloque de 5x5"),
    ]
    print("=== casos de prueba ===")
    for txt, why in tests:
        l, h, a = parse_dims(txt)
        print(f"  len={str(l):>6}  h={str(h):>5}  "
              f"area={str(round(a)) if a else '-':>6}  <- {why}")
    if len(sys.argv) > 1:
        c = sqlite3.connect("file:src/data/sites.sqlite?mode=ro", uri=True)
        print("\n=== sitios etiquetados a mano ===")
        for lamn, lab, b in c.execute(
                "select s.lamningsnummer, l.label, s.beskrivning from labels l "
                "join sites s on s.uuid=l.uuid where l.source='hand' "
                "order by l.label desc"):
            l, h, a = parse_dims(b)
            print(f"  {lamn:<12} lbl={lab:<4} len={str(l):>6} h={str(h):>5} "
                  f"area={(round(a) if a else None)}")
