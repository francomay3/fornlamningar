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

import json
import os
import re

import paths

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
    # "Lista över fornborgar i Uppland#Sollentuna kommun" names a list, not
    # the place.
    if "(" in t or "#" in t:
        return False
    return not (SIGNUM.match(t) or SHORT_SIGNUM.match(t))


_NAME_OVERRIDES = None


def name_overrides(path=None):
    """cluster_id -> the name a person set, ahead of every rule.

    Same shape as a dragged pin. The register and the Wikipedia title are
    what the rules would print; a row here replaces that and nothing else.
    Written by hand. A cluster_id that no longer exists is reported by the
    clustering pass and does not rename some other place.
    """
    global _NAME_OVERRIDES
    path = path or os.path.join(paths.DATA, "name_overrides.jsonl")
    if _NAME_OVERRIDES is not None and path == os.path.join(paths.DATA, "name_overrides.jsonl"):
        return _NAME_OVERRIDES
    out = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                row = json.loads(line)
                cid, name = row.get("cluster_id"), (row.get("name") or "").strip()
                if cid and name:
                    out[cid] = name
    if path == os.path.join(paths.DATA, "name_overrides.jsonl"):
        _NAME_OVERRIDES = out
    return out


def title_overrides(path=None):
    """place uuid -> the title typed on the admin page.

    franco-may writes src/data/title_overrides.jsonl, and that file is the
    whole list: a uuid missing from it keeps whatever the rules would
    print. A hand-written name_overrides row still applies when this file
    has nothing for that place. When both name the same cluster, the typed
    title wins, because it is the later edit.
    """
    path = path or os.path.join(paths.DATA, "title_overrides.jsonl")
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            row = json.loads(line)
            uuid, title = row.get("place_uuid"), (row.get("title") or "").strip()
            if uuid and title:
                out[uuid] = title
    return out


def resolve_title(wiki_title=None, register_name=None, cluster_id=None):
    """The place's name, or None if nothing names it.

    Returns (title, source) so a caller can record WHY -- worth having,
    because the next person to look at a wrong title needs to know whether
    to fix the guard or the register.
    """
    forced = name_overrides().get(cluster_id) if cluster_id else None
    if forced:
        return forced, "override"
    if usable_wiki_title(wiki_title):
        return wiki_title.strip(), "wikipedia"
    if register_name and register_name.strip():
        return register_name.strip(), "register"
    return None, None
