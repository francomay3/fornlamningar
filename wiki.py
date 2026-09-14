"""The wiki: articles as files, and the one function that links prose to them.

An article is a Markdown file with a few frontmatter keys. It is a file and
not a database row because the body is prose someone has to read and edit,
and because the trigger list needs Swedish inflections chosen by eye -- both
of those want a diff, and a diff wants a file.

    wiki/sv/dos.md

        triggers: dös, dösen, dösar, dösarna

        # Dös
        En dös är den äldsta formen av ...

        ![Dösen i Havängsdösen](img:dos.webp)
        *Foto: Sven Rosborn, CC BY-SA 3.0*

Images are written in the body and not declared in the frontmatter, because
an article has zero, one or three of them and the credit belongs beside the
picture rather than in a column of its own. `img:` resolves to a file bundled
with the app: an article has to be readable in a field with no signal, which
a remote URL is not.

There is deliberately no distinction between kinds of article. `dos` is a
subtype, `stenkammargrav` is a register class, `bronsaldern` is a period, and
`kantkedja` is a piece of jargon; all four are one article with a body and a
trigger list. The first draft of this had a `kind` column and it earned
nothing -- nothing in the app or the matcher ever asked.

`deny_before` cancels a match when one of its words is the word immediately
before the trigger. It exists because `hög` is both a burial mound and the
adjective "tall": of 3,044 bare `hög` in the corpus, about half are
"2,5 meter hög". Dropping the bare form instead would have cost the single
most common opening sentence there is -- "En hög, 12 meter i diameter".

TRIGGERS ARE NOT THE TITLE. A reader meets "dösen" in a sentence, never
"Dös", so matching the title alone would link almost nothing. Swedish
inflects and compounds, so the list is written out by hand rather than
stemmed: a stemmer that turns `hällkista` into `kista` is worse than no
matching at all, because the wrong article looks authoritative.
"""

import os
import re

WIKI_DIR = "wiki"
DEFAULT_LANG = "sv"

# Keys a file may declare. Anything else is a typo and should be loud.
KEYS = {"triggers", "title", "deny_before"}


class Article:
    __slots__ = ("id", "lang", "title", "triggers", "deny_before", "body",
                 "path")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def __repr__(self):
        return f"<Article {self.lang}/{self.id} {len(self.triggers)} triggers>"


def parse(text, path=""):
    """Split `key: value` frontmatter from the Markdown body.

    The frontmatter ends at the first blank line. No `---` fences: they buy
    nothing here and every file would open with a line of punctuation.
    """
    lines = text.splitlines()
    meta, i = {}, 0
    while i < len(lines) and lines[i].strip():
        line = lines[i]
        if ":" not in line:
            raise ValueError(f"{path}: frontmatter line without a colon: {line!r}")
        key, _, value = line.partition(":")
        key = key.strip()
        if key not in KEYS:
            raise ValueError(f"{path}: unknown frontmatter key {key!r}")
        meta[key] = value.strip()
        i += 1
    body = "\n".join(lines[i:]).strip()
    if not body:
        raise ValueError(f"{path}: no body")
    return meta, body


def load(lang=DEFAULT_LANG, wiki_dir=WIKI_DIR):
    """Every article for `lang`, keyed by id (the filename without .md)."""
    d = os.path.join(wiki_dir, lang)
    if not os.path.isdir(d):
        return {}
    out = {}
    for name in sorted(os.listdir(d)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(d, name)
        with open(path, encoding="utf-8") as f:
            meta, body = parse(f.read(), path)
        aid = name[:-3]
        triggers = [t.strip() for t in meta.get("triggers", "").split(",")]
        triggers = [t for t in triggers if t]
        if not triggers:
            raise ValueError(f"{path}: no triggers, so nothing would ever link here")
        title = meta.get("title")
        if not title:
            # The H1 is the title. Repeating it in frontmatter is a second
            # place to forget to update.
            m = re.match(r"#\s+(.+)", body)
            if not m:
                raise ValueError(f"{path}: no title: and no '# ' heading")
            title = m.group(1).strip()
        deny = [d.strip().lower() for d in meta.get("deny_before", "").split(",")]
        out[aid] = Article(id=aid, lang=lang, title=title, triggers=triggers,
                           deny_before=[d for d in deny if d],
                           body=body, path=path)
    _check_collisions(out)
    return out


def _check_collisions(articles):
    """Two articles claiming the same trigger is a bug, not a preference.

    Whichever one the matcher happened to reach first would win silently and
    consistently, which is the kind of wrong that survives a review.
    """
    seen = {}
    for a in articles.values():
        for t in a.triggers:
            key = t.lower()
            if key in seen and seen[key] != a.id:
                raise ValueError(
                    f"trigger {t!r} is claimed by both {seen[key]!r} and "
                    f"{a.id!r}; one of them has to give it up")
            seen[key] = a.id


def matcher(articles):
    """One compiled regex over every trigger, longest first.

    LONGEST FIRST IS THE WHOLE TRICK. Python's alternation is first-match,
    not longest-match, so with `kista` before `hällkista` the word hällkista
    matches... nothing, because of the word boundary -- but `stenkista` would
    match `kista` inside it if the boundary were weaker, and the day someone
    adds `grift` next to `gånggrift` the ordering is the only thing standing
    between a reader and a link to the wrong article.

    \\b does not work here. Python's \\b is defined on [A-Za-z0-9_], so in
    `hällkista` the boundary between `ll` and `kista`... is not a boundary,
    fine -- but `Ö` in `Öland` IS a non-word character to \\b, so `\\bland`
    would match inside `Öland`. The lookarounds below test for Swedish
    letters explicitly.
    """
    pairs = []
    for a in articles.values():
        for t in a.triggers:
            pairs.append((t, a.id))
    pairs.sort(key=lambda p: (-len(p[0]), p[0]))
    if not pairs:
        return None, {}
    body = "|".join(re.escape(t) for t, _ in pairs)
    rx = re.compile(rf"(?<![\wÀ-ɏ])({body})(?![\wÀ-ɏ])",
                    re.IGNORECASE)
    index = {t.lower(): aid for t, aid in pairs}
    deny = {a.id: set(a.deny_before)
            for a in articles.values() if a.deny_before}
    return rx, (index, deny)


PREV_WORD = re.compile(r"([\w\u00c0-\u024f]+)[^\w\u00c0-\u024f]*$")


def annotate(text, articles, rx=None, index=None, limit_per_article=1):
    """Rewrite `text`, turning the first hit of each article into a link.

    Returns (text, {article_id: hits_linked}).

    `limit_per_article=1` because a description that says "dös" four times
    does not want four underlined words; the reader needs the offer once.
    The count of hits NOT linked is still worth having, which is why the
    return value counts them rather than just listing the articles.
    """
    if rx is None:
        rx, index = matcher(articles)
    if rx is None:
        return text, {}
    index, deny = index
    used, hits = set(), {}

    def sub(m):
        word = m.group(1)
        aid = index[word.lower()]
        if aid in deny:
            prev = PREV_WORD.search(text, 0, m.start())
            if prev and prev.group(1).lower() in deny[aid]:
                return word
        hits[aid] = hits.get(aid, 0) + 1
        if hits[aid] > limit_per_article or aid in used:
            return word
        used.add(aid)
        return f"[{word}](wiki:{aid})"

    return rx.sub(sub, text), hits


LINK = re.compile(r"(?<!!)\[([^\]]+)\]\(wiki:([a-z0-9_-]+)\)")
IMAGE = re.compile(r"!\[([^\]]*)\]\(img:([^)]+)\)")
IMAGE_DIR = os.path.join(WIKI_DIR, "img")


def strip(text):
    """The prose without the links, for anything that wants plain text."""
    return LINK.sub(r"\1", text)


def check_images(articles, image_dir=IMAGE_DIR):
    """(article_id, filename) for every `img:` that has no file on disk.

    A missing image is a broken article, and the only moment it is cheap to
    notice is before the export. In the app it is a grey rectangle nobody
    reports.
    """
    missing = []
    for a in articles.values():
        for _, fn in IMAGE.findall(a.body):
            if not os.path.isfile(os.path.join(image_dir, fn)):
                missing.append((a.id, fn))
    return missing


def images(articles):
    """Every bundled filename the wiki references, for the export step."""
    return sorted({fn for a in articles.values()
                   for _, fn in IMAGE.findall(a.body)})


def check_links(text, articles):
    """Article ids referenced by `text` that do not exist.

    Bodies link to each other by hand, so this is the difference between a
    wiki and a pile of dead ends.
    """
    return sorted({aid for _, aid in LINK.findall(text) if aid not in articles})
