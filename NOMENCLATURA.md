# Nomenclatura

Cómo se llaman las cosas en este proyecto, para hablar el mismo idioma.

La regla general: **los nombres del código son en inglés, la conversación es
en castellano, y los términos suecos no se traducen.** `fornlämning` no es
"ruina" ni "yacimiento"; es lo que el registro sueco llama fornlämning y
traducirlo pierde precisión. Lo mismo con las clases (`Gravfält`, `Hög`,
`Runristning`): son etiquetas de un vocabulario controlado, no descripciones.

---

## 1. Las tres cosas que más se confunden

Esta sección sola resuelve la mayoría de los malentendidos.

### site — un renglón del registro

Un **site** es una fila de la tabla `sites`, o sea **un objeto del registro
de Riksantikvarieämbetet (RAÄ)**. Tiene un `uuid`, una clase (`class_sv`),
una coordenada, y una descripción escrita por un arqueólogo.

Un site NO es necesariamente algo que se pueda visitar: puede ser una capa de
asentamiento invisible bajo un campo, o un límite administrativo.

En castellano le digo **"sitio"** o **"objeto del registro"**. Nunca "punto",
porque punto ya significa otra cosa (§4).

### cluster — un lugar

Un **cluster** es un grupo de sites que **un visitante experimenta como un
solo lugar**. Es la unidad de todo lo que sigue: el score, la descripción, el
pin del mapa, el sheet.

Vive en la tabla `clusters` y su clave es `cluster_id`, con dos formas:

    raa:1444:Fjärås 81     varios sites que comparten un raa_group
    one:<uuid>             un site solo, que no se agrupó con nadie

Esa segunda forma es el 85,7% de los clusters. **Un cluster de un solo site
es lo normal, no la excepción** — es un detalle que cambia qué arreglos son
posibles (ver §6).

En castellano le digo **"cluster"** o **"lugar"**. Los uso como sinónimos.

### feature — un lugar, ya listo para mostrar

Una **feature** es una fila de `places.sqlite`, o sea **un cluster después de
que se le juntó todo**: el texto generado, las imágenes, las fuentes, el
score, la clase que muestra.

La diferencia con cluster es de etapa, no de contenido: cluster es la unidad
mientras se calcula, feature es la unidad cuando ya está armada. Si digo
"feature" estoy hablando del producto; si digo "cluster" estoy hablando del
cálculo.

Cuidado: **OSM también usa la palabra "feature"** para cualquier cosa
mapeada. Cuando hable de OSM voy a decir "feature de OSM" explícitamente.

---

## 2. Identificadores

| nombre | ejemplo | qué es |
|---|---|---|
| `uuid` | `3c977c02-00e7-…` | clave de un **site** en RAÄ. La clave real. |
| `cluster_id` | `raa:1444:Fjärås 81` | clave de un **cluster**. Derivada, nuestra. |
| `raa_number` | `Kungälv 9:1` | el número clásico: parroquia, lämning, objeto. |
| `raa_group` | `Kungälv 9` | el `raa_number` sin el objeto. Es lo que agrupa. |
| `lamningsnummer` | `L1969:5779` | el identificador nuevo de RAÄ. |
| `qid` | `Q1408860` | el item de Wikidata. |
| `P1260` | `raa/lamning/<uuid>` | la propiedad de Wikidata que enlaza con RAÄ. |

Sobre `P1260`: tiene **varios vocabularios** y ahí estuvo el bug de Bohus.
`raa/lamning/<uuid>` es el moderno; `raa/fmi/<14 dígitos>` es el viejo (FMIS)
y es posicional — `10` + parroquia(4) + lämning(4) + objeto(4). `raa/bbr/…`
es el registro de edificios, que es otro registro y no lo usamos.

---

## 3. Clases y familias

**`class_sv`** es la clase que RAÄ le pone al site, en sueco y de un
vocabulario cerrado: `Gravfält`, `Hög`, `Runristning`, `Stensättning`,
`Vägmärke`… Hay 153 en uso. **Nunca la traduzco** cuando hablo de datos.

**`family`** es nuestra agrupación de esas 153 clases en 11 baldes, definida
en `families.py`. Es lo que el filtro de la app muestra y lo que el
exportador usa para ralear:

    graves · rockart · forts · religious · settlement · farming
    industry · hunting · maritime · transport · misc

Las dos cosas tienen que ser la misma unidad: si se ralea por familia y se
filtra por otra cosa, el mapa queda con agujeros.

**`class_mix`** es lo que un cluster realmente contiene: `"Hög×3;
Stensättning×2"`. Existe porque un cluster es un lugar pero no es *una* cosa.

---

## 4. Score, estrellas y puntos

**`score_intrinsic`** — el score que **no usa ninguna feature derivada de
documentación**. Puede encontrar lugares de los que nadie escribió.

**`score_full`** — el mismo modelo, más el crédito por estar documentado.
Es el que se publica hoy.

Los dos son **log-odds**, no probabilidades. Van de −13 a +32 y no están
acotados. Un score de 13 no es "13 sobre 20"; es la escala logarítmica de una
regresión logística. Si digo "subió de 0,87 a 13,49" eso es un salto enorme,
no un 13%.

**`stars`** (0–5) es el **percentil** del score dentro de lo exportado. Es lo
único que ve el usuario. Dos lugares con estrellas iguales pueden tener
scores muy distintos.

**"puesto" / "rank"** es la posición en el orden por `score_full`. Lo uso
cuando quiero decir algo concreto: "puesto 355 de 123.267" es más informativo
que un score.

**"punto"** — cuidado, esta la uso para tres cosas y trato de calificarla
siempre:

- **pin** = el marcador en el mapa. Un pin = un cluster.
- **punto de OSM** = un nodo de OpenStreetMap.
- **coordenada** = un par lon/lat suelto.

Si escribo "punto" sin calificar, casi siempre quiero decir **pin**.

**"nodo"** — sólo lo uso para OSM, donde es un término técnico: OSM tiene
**nodos** (un punto), **ways** (una línea o el contorno de un área) y
**relaciones**. Cuando dije "no hay ningún nodo `tourism=information`" quise
decir exactamente eso: puede haber un *área* y no la habría visto. De hecho
en Li gravfält pasó eso. **Si digo "nodo" siempre es OSM, nunca nuestro.**

---

## 5. Las bases de datos y sus niveles

Los niveles ya están definidos en `paths.py` y dicen **de dónde saca su
autoridad cada archivo**, que es lo único que hace falta saber para
contestar "¿lo puedo borrar?".

| nivel | archivo | contenido | ¿se puede borrar? |
|---|---|---|---|
| RAW | `raa_export.gpkg` | el export de RAÄ | no sin re-bajarlo (183 MB) |
| RAW | `raa_api.sqlite` | 311.845 respuestas de la API | no, son 4 h de crawl |
| RAW | `lansstyrelsen.sqlite` | planes y PDFs de los länsstyrelser | no |
| RAW | `wikimedia.sqlite` | fotos y artículos | re-bajable |
| RAW | `contributions.sqlite` | **tus comentarios y visitas** | **NUNCA. Y nunca a git.** |
| EXPENSIVE | `generated.sqlite` | texto del modelo | sí, pero son horas |
| WORK | `work.sqlite` | sites, clusters, signals, scores | sí, se rehace en minutos |
| PRODUCT | `places.sqlite` | **el producto**: una fila por lugar | derivado |
| PAYLOAD | shards, tiles, `descriptions.*.db` | lo que baja el teléfono | siempre |

Tablas por base:

    work.sqlite         sites · clusters · site_clusters · signals · scores
                        · labels · wikidata
    places.sqlite       features · feature_sites · sources · images
                        · generation_sources
    generated.sqlite    ai_descriptions · failures
    contributions.sqlite events · sync

---

## 6. Signals, features (de modelo), labels

Acá hay una colisión de palabras que conviene tener clara.

**`signals`** es una tabla: **una medición cruda por cluster**, nunca un
puntaje ni un peso. `dist_to_board_m` es una distancia en metros. Es cruda a
propósito, para poder re-puntuar sin re-derivar nada.

**"feature"** en sentido de modelo estadístico es **una entrada del
clasificador**, derivada de una signal: `board_le_200` es la feature
booleana "hay un cartel a 200 m o menos".

    signal   = la medición          dist_to_board_m = 187.3
    feature  = lo que el modelo lee board_le_200 = true

Sí, "feature" significa dos cosas (§1 y ésta). Trato de decir **"feature del
modelo"** cuando hablo de la segunda, y **"feature"** a secas para la fila
de `places.sqlite`.

**`labels`** es lo que el modelo trata de **predecir**, no lo que lee. Ésta
es la distinción que más cuesta y la más importante:

> Una label es un objetivo de entrenamiento, no una entrada. Puntuar un lugar
> le enseña al modelo *globalmente*; no le sube el score *a ese lugar*.

Por eso tus visitas están como **feature** (`visited`) y tus estrellas como
**label**. Si una cosa fuera las dos, el ajuste aprendería "la presencia
predice la presencia" y el score dejaría de significar nada.

---

## 7. Las tres capas del proyecto

| repo | qué es | remote |
|---|---|---|
| `fornlamningar` | el pipeline de datos, en Python | `github.com/francomay3/fornlamningar` |
| `fornlamningar-app` | la app, Expo/React Native | **no tiene remote** |
| `franco-may` | el mapa web y el backend de sync | `github.com/francomay3/franco-may` |

**"el pipeline"** = las 13 etapas de `run_pipeline.sh`.
**"una etapa"** (stage) = una de ellas, y se nombran por nombre y no por
número, porque los números ya se corrieron una vez.

    parse · cluster · join · labels · sources · signals · score
    places · descriptions · translate · tiles · assets · release

**"generación"** (generation) tiene dos sentidos y los distingo así:
- **"generar descripciones"** = correr el modelo local sobre los textos.
- **"la generación 4"** = una versión numerada de los archivos publicados,
  el contador en `src/data/generation`. Cuando diga esto último voy a decir
  siempre "la generación N", con número.

**"release"** = el directorio inmutable con los 6 archivos versionados y su
manifest. Los archivos nunca se pisan: un teléfono a mitad de descarga se
llevaría un SQLite cortado entre dos versiones.

---

## 8. Cosas del mapa y de la app

| término | qué es |
|---|---|
| **basemap** | el mapa de fondo (estilo liberty, recoloreado al tema) |
| **style** | el JSON de MapLibre: `basemap-style.json` y `-dark.json` |
| **glyph** | los PNG chiquitos de los iconos. Hay dos juegos, claro y oscuro |
| **shard** | un pedazo del corpus de descripciones, partido para bajarlo |
| **tile** | un mosaico vectorial. Los usa el mapa web, no la app |
| **paleta / token** | los colores con nombre de rol en `theme.ts` |
| `paper` `ink` `accent` | roles, no colores. Significan lo mismo en claro y oscuro |
| **sheet** | el panel que sube desde abajo |
| **thinning** | ralear pines por zoom, por familia |

---

## 9. Glosario sueco

Lo que no traduzco, con lo que quiere decir.

| sueco | qué es |
|---|---|
| **fornlämning** | un resto antiguo protegido por ley. La unidad del registro |
| **lämning** | resto, en general. Más amplio que fornlämning |
| **Riksantikvarieämbetet (RAÄ)** | la autoridad nacional de patrimonio |
| **Fornsök** | el buscador público de RAÄ |
| **FMIS** | el sistema viejo de RAÄ. Sobrevive en los ids `raa/fmi/…` |
| **länsstyrelse** (pl. *-lser*) | el gobierno del län. Publican planes de cuidado |
| **län** | provincia / condado |
| **socken** / **församling** | parroquia. Es la unidad del `raa_number` |
| **gravfält** | campo de tumbas |
| **hög** | túmulo |
| **röse** | túmulo de piedra |
| **stensättning** | sepultura de piedra plana. La clase más común |
| **runristning / runsten** | inscripción rúnica / piedra rúnica |
| **hällristning** | arte rupestre |
| **domarring** | círculo de piedras (lit. "anillo de jueces") |
| **fornborg** | castro / fuerte de altura |
| **skylt** | cartel |
| **naturum** | centro de visitantes de un área natural |

---

## 10. Cómo pedir las cosas

Frases que van a significar exactamente una cosa:

- *"el score de X"* → `score_full` de ese cluster.
- *"el puesto de X"* → su rank por `score_full`.
- *"las estrellas"* → el percentil que ve el usuario.
- *"correr el pipeline"* → todo, incluidas descripciones y traducciones.
- *"correr desde tiles"* → `./run_pipeline.sh --from tiles`.
- *"el export"* → los 6.000 mejores clusters, lo que ve la app.
- *"un cartel"* → un cartel físico en el campo.
- *"un board de OSM"* → `tourism=information` + `information=board` en OSM.
  Las dos cosas son distintas y el segundo casi nunca existe.
