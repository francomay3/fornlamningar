"""What a place is called, decided in one place.

There were two columns, `name` and `title`, and they read as synonyms while
holding different things: `name` was the folk name out of the register and
`title` was a phrase the model wrote. Nobody could reason about which should
win -- which is why the map spent weeks showing "Gravfält med 160
fornlämningar" for a stone that people have called Frodestenen for
centuries.

So: one question, one answer. `title` is the place's name. The model's phrase
is `generated_heading` and it is a fallback, named for what it is.

THE PRIORITY, and the measurement behind it:

  1. The Swedish Wikipedia article title, unless it is a catalogue
     identifier. Where the two disagree it is usually because the register
     named an OBJECT and Wikipedia named the PLACE -- "Frodestenen" is the
     standing stone, "Li gravfält" is the grave field it stands in, and a
     visitor is going to the field. Same shape in "Bredarör" ->
     "Kungagraven i Kivik" and "Kyrkebacken" -> "Gudahagen".

  2. The register's folk name.

  3. Nothing. The caller falls back to the generated heading, then the class.

THE GUARD IS NOT OPTIONAL. 1,055 of 1,660 Swedish articles -- 64% -- are
titled "<landskap> runinskrifter N", because that is sv.wikipedia's policy
for runestones. Without the guard, promoting Wikipedia would rename
Jarlabankes bro, one of the best known runic monuments in Sweden, to
"Upplands runinskrifter 165". The pattern is syntactic and applied by policy,
so it is safe to match; a parenthetical disambiguator (7 titles) is
Wikipedia's plumbing rather than part of a name, so it goes too.
"""

import re

# "Upplands runinskrifter 165", "Närkes runinskrifter 34". Written as one
# alternation of landskap names rather than a loose r"runinskrifter \d+"
# match, so an article legitimately titled after an inscription -- if one
# ever exists -- is not swept up with them.
SIGNUM = re.compile(
    r"^(Upplands|Södermanlands|Östergötlands|Västergötlands|Smålands"
    r"|Gotlands|Ölands|Skånes|Hallands|Bohusläns|Dalarnas|Närkes"
    r"|Värmlands|Gästriklands|Hälsinglands|Medelpads|Jämtlands"
    r"|Ångermanlands|Norrbottens|Västerbottens|Västmanlands|Blekinges"
    r"|Dalslands|Lapplands|Härjedalens) runinskrifter\s+\d+", re.I)

# "U 165", "Sö 279" -- the short signum, in case a title uses it directly.
SHORT_SIGNUM = re.compile(r"^(U|Sö|Ög|Vg|Sm|G|Öl|DR|Vs|Nä|Hs|M|J|Br|Gs)"
                          r"\s?\d+[A-Za-z]?$")


def usable_wiki_title(title):
    """Is this Wikipedia title a NAME, or a catalogue entry wearing one?"""
    if not title or not title.strip():
        return False
    t = title.strip()
    if "(" in t:
        return False
    return not (SIGNUM.match(t) or SHORT_SIGNUM.match(t))


def resolve_title(wiki_title=None, register_name=None):
    """The place's name, or None if nothing names it.

    Returns (title, source) so a caller can record WHY -- worth having,
    because the next person to look at a wrong title needs to know whether
    to fix the guard or the register.
    """
    if usable_wiki_title(wiki_title):
        return wiki_title.strip(), "wikipedia"
    if register_name and register_name.strip():
        return register_name.strip(), "register"
    return None, None
