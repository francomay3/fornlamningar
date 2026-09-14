# TODO

Lo que acordamos hacer, con las decisiones ya tomadas y las que faltan. Un
item se borra de acá cuando está en `main`, no cuando funciona en mi máquina.

Tres proyectos grandes, en el orden en que conviene hacerlos: el glosario no
necesita backend, el login sí, y las fotos necesitan el login para saber de
quién es cada foto.

---

## 1. Glosario de tipos de lämning (sin backend)

**Qué es:** cada `lämningstyp` (dös, gångrift, fornborg, hällkista, ...) tiene
un artículo propio: qué es, de qué época, en qué se diferencia de sus vecinos,
un ejemplo famoso, y una imagen. En el texto de un sitio, la palabra aparece
como link; al tocarla se abre un modal con el artículo.

**Decisión tomada — el modal gana sobre el aside.** Un aside fijo debajo de la
descripción repite lo mismo en los 40.000 gravfält y no tiene lugar para los
sitios con tres tipos mezclados (`class_mix` ya existe justamente porque la
identidad de un lugar es un conjunto). El modal aparece sólo si al lector le
interesa, y aguanta que un artículo linkee a otro.

**Navegación:** pila de artículos. "Atrás" vuelve al anterior, atrás en el
primero cierra; la cruz arriba a la derecha cierra de una. Es la misma pila
que el botón físico de Android, así que hay que engancharlo también.

### Datos

Tabla `glossary` en `places.sqlite`, exportada al bundle igual que
`descriptions.db`:

| columna | para qué |
|---|---|
| `term_id` | `dos`, `gangrift`, ... la clave estable |
| `lang` | `sv` (canónico), `en` después |
| `term` | la palabra como se muestra ("dös") |
| `body_md` | el artículo, Markdown |
| `image_file` | nombre del webp en el bundle |
| `image_credit` | autor + licencia + url, obligatorio |
| `updated_at` | igual que todo lo demás |

Dos textkeys por artículo como dijiste: `term` y `body_md`. El `term` no va en
`sv.json` porque no es copy del chrome — es contenido, y el chrome se mantiene
a mano mientras esto lo genera el pipeline.

### El matching es offline, no en runtime

Esta es la única parte donde te discuto el approach obvio. Buscar "dös" con un
regex sobre la prosa en el teléfono se rompe con el sueco: `dös`, `dösen`,
`dösar`, `dösarna`, y `hällkista` contiene `kista` que es otro artículo. Peor:
un falso positivo lo ve el usuario y yo no me entero nunca.

Así que el pipeline anota la descripción **cuando la genera**, y guarda el
texto con marcas explícitas (`[dös](gloss:dos)`). Se matchea una vez, offline,
donde puedo contar cuántos linkeó y leer los raros. El renderer del teléfono
sólo dibuja lo que ya está marcado.

### Imágenes: bundle, no hotlink

Preguntaste si pueden venir directo de Wikipedia. Técnicamente sí, Commons no
lo bloquea, pero:

- una imagen que se baja por red no existe sin señal, y la app es para andar
  en el campo sin datos;
- hotlinkear a Commons está explícitamente desaconsejado por ellos.

Son ~120 tipos, uno por tipo: a 1024px de ancho en webp son ~40 KB cada una,
~5 MB en total sobre los 48 MB que ya pesa el APK. Van al bundle.

Licencia: cada archivo de Commons tiene la suya (CC0, CC BY, CC BY-SA). Todas
sirven para lo nuestro — es gratis y no comercial — pero **todas menos CC0
exigen atribución**, así que `image_credit` no es opcional y se muestra en el
artículo. `wikimedia.sqlite` ya guarda autor y licencia por archivo, es de
ahí.

### Renderer de Markdown

Hace falta uno, y conviene escribirlo (~80 líneas) en vez de traer
`react-native-markdown-display`: el único elemento que de verdad necesito es
el link `gloss:` que empuja la pila, y eso en una librería se hace
overrideando su renderer igual. Soporta: párrafos, `##`, `**`, `*`, y links.
Nada más. Es la misma decisión que `src/i18n/index.ts` ya documenta sobre no
traer i18next.

### Tareas

- [ ] `glossary.py` en el pipeline: los ~120 tipos con más sitios, artículo
      generado desde Wikipedia sv + el registro, revisado a mano
- [ ] bajar y convertir las imágenes a webp 1024px, con crédito
- [ ] anotar las descripciones con `[palabra](gloss:id)` al generarlas
- [ ] exportar `glossary` al bundle + `assetVersion.ts`
- [ ] renderer de md mínimo
- [ ] `GlossaryModal` con pila, botón atrás de Android enganchado
- [ ] estilo del link: color primary + subrayado (lo que pediste)

---

## 2. Cuentas y sincronización (proyecto largo)

**Decisión tomada — el uuid anónimo es el usuario real.** Se genera la
primera vez que abre la app; puntajes, comentarios y fotos se guardan con ese
uuid sin pedir nada. El login sólo sirve para que el uuid sobreviva a un
cambio de teléfono: al registrarse, la cuenta **hereda** el uuid.

**Mi recomendación sobre el método:** Google (y Apple si algún día hay iOS, es
obligatorio ahí). **Usuario/password no.** Traer passwords significa hashing,
reset por mail, y ser responsable de un leak — todo eso para un login que
existe nada más que para no perder tus estrellitas. Si querés una opción sin
Google, magic link por mail antes que password.

### Sync: tu diseño está bien, con una corrección

Lo que describiste es un log de eventos append-only, y es el modelo correcto
para esto. Cada cambio local se aplica a la DB local **y** se postea:

```
POST /api/events   { uuid, kind, raa_id, payload, client_ts }
GET  /api/events?since=<seq>&exclude=<uuid>
```

**La corrección:** no pagines por timestamp. El reloj del teléfono es del
usuario — mal seteado, zona horaria rara, o directamente adelantado — y con
`since=<tiempo>` te comés eventos o los repetís para siempre. El servidor le
pone un `seq` monotónico a cada evento y el cliente guarda el último `seq` que
vio. El `client_ts` se guarda igual, pero como dato, no como índice.

Lo otro: filtrar los propios eventos **en el servidor** (`exclude=uuid`), como
dudaste. Si no, el teléfono se baja todas sus propias fotos de vuelta.

**Dónde:** `franco-may` como querés. Next.js route handlers + Postgres
(Neon o Supabase, los dos tienen free tier que aguanta esto de sobra). El log
de eventos es una tabla sola.

### Tareas

- [ ] uuid local + `AsyncStorage`, antes que cualquier otra cosa de esta
      sección — todo lo demás cuelga de que exista
- [ ] tablas locales `ratings`, `comments`, `photos` con `uuid` y `ts`
- [ ] cola de salida que sobreviva a que la app se cierre sin señal
- [ ] `POST /api/events` + Postgres en `franco-may`
- [ ] `GET /api/events?since=&exclude=` con `seq` del servidor
- [ ] sync en background, una vez por día
- [ ] Google sign-in, herencia del uuid
- [ ] qué pasa si dos teléfonos heredan a la misma cuenta (decidir: merge)

---

## 3. Fotos

**Carousel:** fotos una al lado de la otra, scroll libre sin snap. Eso es un
`ScrollView` horizontal y sale bien solo.

**Visor a pantalla completa:** acá no improviso. Pinch, doble tap, swipe entre
fotos y arrastrar para cerrar, todo a 60fps, es exactamente lo que se siente
casero si lo escribo yo. `react-native-awesome-gallery` corre sobre
`reanimated` + `gesture-handler`, que ya son dependencias nuestras. Swipe
infinito (de la última a la primera) lo soporta.

**El frame de "sacá una foto"** va siempre al final del carousel, y es lo
único que se ve cuando no hay fotos — como pediste.

**Compresión: 1080p webp. Ojo con un detalle** —
`expo-image-manipulator` exporta webp **sólo en Android**. Como Android es
primero, arrancamos con webp; el día que haya iOS, ahí se cae a JPEG q80 o se
convierte en el servidor.

**Storage:** te recomiendo Cloudflare R2 antes que Firebase Storage. Misma
API (S3), y no cobra egress — que es justamente lo que te cobraría Firebase
si esto llega a andar. El teléfono pide una URL firmada a un endpoint nuestro
y sube directo; la foto nunca pasa por nuestro servidor.

**Lo que falta decidir:** moderación. Un endpoint público de subida de fotos
recibe, tarde o temprano, algo que no es una tumba. Mínimo: cada foto arranca
`pending` y no se sirve hasta que la apruebo, o se sirve y hay un botón de
reportar. Hay que elegir antes de abrirlo, no después.

**La tabla ya existe** (`images` en `places.sqlite`) con `source`, `file`,
`local_path`, `credit`, `updated_at`. Una foto de usuario es
`source='user'` y `credit='user:<uuid>'`. No hace falta tabla nueva.

### Tareas

- [ ] carousel de scroll libre en `PlaceSheet`
- [ ] frame de prompt al final, y solo cuando no hay fotos
- [ ] `react-native-awesome-gallery` para el visor
- [ ] cámara + galería, resize a 1080p, webp
- [ ] R2 + endpoint de URL firmada
- [ ] decidir moderación
- [ ] fotos de usuario dentro del sync de la sección 2

---

## Pendientes viejos, de antes de hoy

- [ ] colapsar `name` y `title` en una columna (`titles.py` ya está; falta el
      rename de schema en `build_places.py` y `build_tiles.py`)
- [ ] `build_tiles.py` leyendo de `places.sqlite`, no de `work.sqlite` +
      `generated.sqlite`. Nada lo bloquea ya
- [ ] 19,3% de las descripciones con más de una medida. Dos iteraciones del
      prompt no movieron nada; queda post-procesar la prosa o un segundo pase
- [ ] el APK instalado es de antes del cambio de clustering
- [ ] ~55% de los objetos `fornvard` no matchean con nada
- [ ] regenerar descripciones de los que entraron/salieron del top 10k
      (2.374 con texto ya afuera, 3.526 adentro sin texto)
