"""Decide one place with a local Ollama model instead of the Cursor agent.

    review/.venv/bin/python review/local.py <dir> [--model qwen3.6:35b-a3b]

Two calls per place. First the model looks at the photographs, twelve at a
time and large, and says what each one shows. A sheet of 48 at once is too
small for it: it called a photograph of the stone a drawing. Then it reads
the dossier, the pages and those descriptions, with no image, and writes the
same decision.json the agent writes. apply.py does the rest.

It cannot search further. Thinking is off: with it on, one place had not
finished in fifteen minutes.
"""

import base64
import io
import json
import os
import sys
import time
import urllib.request

from PIL import Image, ImageDraw, ImageFont

OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
MODEL = os.environ.get("FL_LOCAL_MODEL", "qwen3.6:35b-a3b")
PAGE_CHARS = 3500
BATCH = 12
GRID_COLS = 4
GRID_CELL = 400

LOOK = """\
Sitio: {name} ({kind}), {town}.
Registro: {register}

La imagen tiene {count} fotos, cada una con su etiqueta en amarillo arriba a la izquierda: {labels}.
Para cada etiqueta decí qué muestra la foto. Mirá cada celda por separado.
- muestra: qué se ve, corto, en español
- tipo: foto (una fotografía del lugar o del objeto), detalle (una fotografía de cerca de una parte),
  dibujo, mapa, documento (ficha, página escaneada, texto), cartel
- color: true si es a color, false si es blanco y negro o sepia
- nitidez: 1 borrosa o pixelada, 5 muy nítida
- objeto: 1 el objeto no se ve o está lejísimo, 5 el objeto llena la foto y se ve claro
- linda: 1 fea, 5 muy linda
- regla: true si hay una regla, una escala o una tablilla de medir en la foto
- de_este_sitio: si, no, o dudoso. "no" solo si se ve que es otro lugar u otro objeto.
"""

DECIDE = """\
Revisás un sitio del registro sueco de fornlämningar para un mapa. Todo lo que se sabe está abajo,
y al final, lo que muestra cada foto.

Fotos. `prioritize` son las que se ven primero. Elegí de las candidatas hasta seis, las mejores, para que junto
con las ya priorizadas se vea el sitio bien y desde ángulos distintos: que el objeto se vea y llene la foto,
a color, nítidas, lindas. Mirá lo que muestra cada una: de dos que muestran lo mismo, una sola, y que no sean
todas detalles. Un mapa, un plano o un cartel solo si no hay nada mejor. Si las ya priorizadas alcanzan, ninguna.

Fuentes. Solo si la única fuente es la del registro. Una página bajada que habla de este mismo sitio
(no de otro con el mismo nombre, no de la zona en general) va en `add_sources` con su número.
Una fuente agregada (con added_id) que habla de otro sitio va en `remove_sources` con ese id.

Título. Si el título es de otro sitio y el registro describe este objeto, `title` es el nombre de este objeto. Si no, null.

Estado. Si no hay data o no alcanza para decidir qué es, `aside` true. `uninteresting` true solo si es
definitivamente no interesante, que es raro.

Flag. null salvo que el administrador tenga que mirar esto ya: fuentes que se contradicen, no se sabe qué objeto es,
duda de si hay algo que ver. No encontrar fotos, skipear fotos, corregir el título o que el registro
tenga varios textos no son flag. En español y corto.

`note`: una línea, qué hiciste.
"""


def _json(work, name, default):
    path = os.path.join(work, name)
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _chat(model, content, images, fmt, timeout):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": content, "images": images}],
        "format": fmt,
        "stream": False,
        "think": False,
        "keep_alive": "30m",
        "options": {"temperature": 0.2, "num_ctx": 32768},
    }
    req = urllib.request.Request(f"{OLLAMA}/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        out = json.load(res)
    return json.loads((out.get("message") or {}).get("content") or "{}"), out


def _grid(work, labels):
    rows = (len(labels) + GRID_COLS - 1) // GRID_COLS
    sheet = Image.new("RGB", (GRID_COLS * GRID_CELL, rows * GRID_CELL), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 40)
    except OSError:
        font = ImageFont.load_default()
    for i, label in enumerate(labels):
        x, y = (i % GRID_COLS) * GRID_CELL, (i // GRID_COLS) * GRID_CELL
        path = os.path.join(work, "thumbs", f"{label}.jpg")
        if os.path.exists(path):
            img = Image.open(path).convert("RGB")
            scale = min((GRID_CELL - 8) / img.width, (GRID_CELL - 8) / img.height)
            img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                             Image.LANCZOS)
            sheet.paste(img, (x + (GRID_CELL - img.width) // 2, y + (GRID_CELL - img.height) // 2))
        box = draw.textbbox((x + 8, y + 8), label, font=font)
        draw.rectangle((box[0] - 5, box[1] - 5, box[2] + 5, box[3] + 5), fill="black")
        draw.text((x + 8, y + 8), label, fill="yellow", font=font)
        draw.rectangle((x, y, x + GRID_CELL - 1, y + GRID_CELL - 1), outline="gray", width=3)
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def look(work, model, timeout):
    """{label: description} for every thumbnail the dossier saved.

    Kept in seen.json. The dossier empties the folder, so it is never stale.
    """
    cached = _json(work, "seen.json", None)
    if cached is not None:
        return cached
    place = _json(work, "place.json", {})
    photos = _json(work, "photos.json", {})
    officials = _json(work, "official.json", [])
    labels = [str(n) for n in sorted(int(k) for k in photos)]
    labels += [f"O{o['o']}" for o in officials]
    labels = [l for l in labels if os.path.exists(os.path.join(work, "thumbs", f"{l}.jpg"))]
    register = next((t.get("body") or "" for t in place.get("texts") or []
                     if t.get("kind") == "register"), "") or place.get("content") or ""
    seen = {}
    for i in range(0, len(labels), BATCH):
        batch = labels[i:i + BATCH]
        fmt = {"type": "object", "properties": {"fotos": {
            "type": "array", "minItems": len(batch), "maxItems": len(batch),
            "items": {"type": "object", "properties": {
                "etiqueta": {"type": "string", "enum": batch},
                "muestra": {"type": "string"},
                "tipo": {"type": "string",
                         "enum": ["foto", "detalle", "dibujo", "mapa", "documento", "cartel"]},
                "color": {"type": "boolean"},
                "nitidez": {"type": "integer", "minimum": 1, "maximum": 5},
                "objeto": {"type": "integer", "minimum": 1, "maximum": 5},
                "linda": {"type": "integer", "minimum": 1, "maximum": 5},
                "regla": {"type": "boolean"},
                "de_este_sitio": {"type": "string", "enum": ["si", "no", "dudoso"]},
            }, "required": ["etiqueta", "muestra", "tipo", "color", "nitidez", "objeto",
                            "linda", "regla", "de_este_sitio"]}}}, "required": ["fotos"]}
        prompt = LOOK.format(name=place.get("title") or "", kind=place.get("_kind") or "",
                             town=place.get("municipality") or "", register=register[:1200],
                             count=len(batch), labels=", ".join(batch))
        got, _ = _chat(model, prompt, [_grid(work, batch)], fmt, timeout)
        for f in got.get("fotos") or []:
            if f.get("etiqueta") in batch:
                seen[f.pop("etiqueta")] = f
    with open(os.path.join(work, "seen.json"), "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False)
    return seen


def score(f, size=None):
    s = 2 * f["objeto"] + f["nitidez"] + f["linda"] + (2 if f["color"] else 0)
    s += 1 if f["tipo"] == "foto" else 0
    if size and max(size) < 1000:
        s -= 2
    return s


def schema(candidates, pages, added_ids):
    """Only the fields this dossier can fill, and only numbers that exist.

    A field for official photos on a place that has none is an invitation
    to list O1 to O48. Skips are not asked: asked, the model skipped every
    photograph it did not prioritize.
    """
    props = {}
    if candidates:
        props["prioritize"] = {"type": "array", "maxItems": 6,
                               "items": {"type": "integer", "enum": candidates}}
    if pages:
        props["add_sources"] = {"type": "array",
                                "items": {"type": "integer", "enum": pages}}
    if added_ids:
        props["remove_sources"] = {"type": "array",
                                   "items": {"type": "integer", "enum": added_ids}}
    props.update({
        "title": {"type": ["string", "null"]},
        "aside": {"type": "boolean"},
        "uninteresting": {"type": "boolean"},
        "flag": {"type": ["string", "null"]},
        "note": {"type": "string"},
    })
    return {"type": "object", "properties": props, "required": list(props)}


def _describe(label, f, star, size):
    size_s = f" · original {size[0]}×{size[1]}" if size else ""
    return (f"{label}{star}: {f['muestra']} · {f['tipo']} · "
            f"{'color' if f['color'] else 'blanco y negro'} · nitidez {f['nitidez']} · "
            f"objeto {f['objeto']} · linda {f['linda']}{size_s} · puntaje {score(f, size)}")


def message(work, seen, candidates, skip, officials_in):
    with open(os.path.join(work, "dossier.md"), encoding="utf-8") as f:
        parts = [DECIDE, "\n# Dossier\n", f.read()]
    for p in _json(work, "pages.json", []):
        with open(os.path.join(work, f"page{p['n']}.txt"), encoding="utf-8") as f:
            text = f.read()
        if len(text) > PAGE_CHARS:
            text = text[:PAGE_CHARS] + " …"
        parts.append(f"\n# Página {p['n']}: {p['title']} · {p['url']}\n{text}")
    photos = _json(work, "photos.json", {})
    sizes = _json(work, "sizes.json", {})
    if not seen:
        parts.append("\n# Fotos\n(No hay fotos.)")
    starred = [l for l in seen if photos.get(l, {}).get("prioritized")]
    if starred:
        parts.append("\n# Ya priorizadas")
        parts += [_describe(l, seen[l], "*", sizes.get(l)) for l in starred]
    if candidates:
        parts.append("\n# Candidatas para `prioritize`, de mayor a menor puntaje")
        parts += [_describe(str(n), seen[str(n)], "", sizes.get(str(n))) for n in candidates]
    if skip:
        parts.append(f"\n(Ya se skipean, no son de este sitio o son documentos: {', '.join(map(str, skip))}.)")
    if officials_in:
        parts.append(f"(Ya se agregan las fotos oficiales {', '.join(officials_in)}.)")
    return "\n".join(parts)


def _respelling(old, new):
    import difflib
    a, b = (old or "").casefold(), (new or "").casefold()
    return not a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.7


def decide(work, model=MODEL, timeout=900):
    t0 = time.time()
    seen = look(work, model, timeout)
    t1 = time.time()
    photos = _json(work, "photos.json", {})
    sizes = _json(work, "sizes.json", {})
    pages = [p["n"] for p in _json(work, "pages.json", [])]
    place = _json(work, "place.json", {})
    added = [t["added_id"] for t in place.get("texts") or [] if t.get("added_id")]

    skip, candidates, officials_in = [], [], []
    for label, f in seen.items():
        if label.startswith("O"):
            if f["de_este_sitio"] == "si" and f["tipo"] != "documento":
                officials_in.append(label)
            continue
        if f["de_este_sitio"] == "no" or f["tipo"] == "documento":
            skip.append(int(label))
        elif not photos.get(label, {}).get("prioritized") and not f.get("regla"):
            candidates.append(int(label))
    candidates.sort(key=lambda n: -score(seen[str(n)], sizes.get(str(n))))
    candidates = candidates[:16]

    d, out = _chat(model, message(work, seen, candidates, skip, officials_in), [],
                   schema(candidates, pages, added), timeout)
    d["skip"] = skip
    d["add_official"] = officials_in
    d["add_sources"] = [{"page": n} for n in d.get("add_sources") or []]
    if d.get("title") and _respelling(place.get("title"), d["title"]):
        d["title_dropped"] = d.pop("title")
    d["seen"] = seen
    with open(os.path.join(work, "decision.json"), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    return {
        "seconds": round(time.time() - t0, 1),
        "look_s": round(t1 - t0, 1),
        "decide_s": round(time.time() - t1, 1),
        "decide_prompt_tokens": out.get("prompt_eval_count"),
        "decision": d,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("local.py <dir> [--model M]")
    model = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else MODEL
    print(json.dumps(decide(sys.argv[1], model), ensure_ascii=False, indent=1))
