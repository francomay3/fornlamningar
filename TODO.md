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

**Dónde vive:** en el repo de la app, `fornlamningar-app/wiki/sv/*.md`. El
wiki no toca ninguna descripción generada, así que no es dato del pipeline.
El matching pasa al renderizar y existe una sola vez, en TS.

### Formato

```
triggers: dös, dösen, dösar, dösarna
deny_before: meter, m, cm

# Dös
En dös är den äldsta typen av [stenkammargrav](wiki:stenkammargrav) ...

![Havängsdösen](img:dos.webp)
*Foto: Sven Rosborn, CC BY-SA 3.0*
```

Sin distinción de tipos de artículo: una clase del registro, un subtipo, un
período y un término técnico son todos lo mismo. Las imágenes van en el body,
así que un artículo tiene cero, una o tres, y el crédito va al lado de la foto.

`deny_before` cancela el match si esa palabra viene justo antes. Existe porque
`hög` es a la vez el túmulo y el adjetivo "alto": de 3.044 apariciones de
`hög` pelado, unas 500 eran "2,5 meter hög".

### Hecho

- [x] `wiki.py` → descartado. El matcher en Python y en TS son dos copias de
      la misma regla, que es el bug de las cinco copias otra vez
- [x] `scripts/build-wiki.mjs` — enumera los md (Metro no puede listar un
      directorio en runtime) y valida: link a artículo inexistente, dos
      artículos peleando un trigger, `img:` sin archivo
- [x] `src/wiki/match.ts` — triggers, alias más largo primero, límites de
      palabra suecos sin lookbehind ni `\p{...}` (Hermes)
- [x] `src/wiki/markdown.ts` — el renderer mínimo
- [x] `src/ui/WikiText.tsx` — el componente, usado tanto para la descripción
      del sitio como para los párrafos del artículo. Esa identidad es lo que
      lo hace un wiki
- [x] `src/ui/WikiModal.tsx` — una sola ventana, pila de artículos, atrás
      camina lo que el lector leyó, atrás en el primero cierra
- [x] 24 artículos, cruzados entre sí. **79,3% de las 8.821 descripciones
      recibe al menos un link**

- [x] **21 imágenes** de Commons en `wiki/img/`, webp 1024px, 3,1 MB. Bajadas
      con su atribución sacada de la API de Commons, no escrita a mano
- [x] `WikiImage` con `caption` + `credit`. El crédito es prop **requerida**:
      un campo opcional es un campo vacío en el artículo veinte a las once de
      la noche. Lo valida el build, no un abogado
- [x] los 24 artículos verificados contra Wikipedia sv y reescritos con
      estructura de turismo (`## Att se på plats`, `## Kända exempel`,
      `## Visste du?`). Correcciones de datación en dos tercios de ellos
- [x] verlo en el teléfono, instalado y andando

- [x] siete artículos que no son tipos de lämning: `att_lasa_registret`,
      `landhojningen`, `allemansratten`, `fornlamning`, `brandgrav`,
      `runformel`, `stenmaterial`. **31 artículos, 83,6% de las
      descripciones con al menos un link** (era 79,3%)

### Falta

- [ ] `fangstgrop` no recibe links de ningún otro artículo
- [ ] artículos de clases, medidos por alcance sobre los 129.075 lugares:
      `vägmärke` (7,4% — el hueco más grande), `hägnad` (4,4%),
      `bytomt` (4,1%), `lägenhetsbebyggelse` (4,0%), `blästbruk` (4,0%),
      `färdväg`/hålväg (3,1%), `husgrund` (2,5%), `fäbod`+`kåta`+`viste`
      (1,8%, presencia sami), `tomtning` (0,8%). Un solo artículo para el
      grupo industrial (`hyttområde`, `gruvområde`, `kalkugn`, `kvarn`,
      `dammvall`, ~3%) y uno para `källa`/`naturföremål med tradition` (1%,
      folclore)
- [ ] más artículos: `stenmur`, `hägnad`, `kolningsanläggning`,
      `blästbrukslämning`, `fossil åker`, `bytomt`, `mittgrop`, `övertorvad`
- [ ] el wiki en inglés, cuando haya inglés

---

## 2. Cuentas y sincronización (proyecto largo)

**Decisión tomada — el uuid anónimo es el usuario real.** Se genera la
primera vez que abre la app; puntajes, comentarios y fotos se guardan con ese
uuid sin pedir nada. El login sólo sirve para que el uuid sobreviva a un
cambio de teléfono: al registrarse, la cuenta **hereda** el uuid.

**Mi recomendación sobre el método:** Google, Apple (obligatorio si algún día
hay iOS) y mail. Sobre el mail hay una confusión que conviene aclarar:

- **Google Sign-In no da usuario/password.** Da cuentas de Google y nada más.
  Lo que estás pensando es *Firebase Auth*, que es otra cosa: ahí sí tenés
  email+password, y el hashing y el reset los hace Google.
- Con eso aclarado, **agregalo**: el email es un toggle en la consola y no
  escribo una línea de cripto. Mi objeción era a hacerlo a mano, no a tenerlo.
- Entre email+password y magic link, prefiero magic link — no hay password que
  perder ni pantalla de reset que mantener — pero es preferencia, no argumento.

**En Suecia:** lo omnipresente es BankID, y no nos sirve. Es identidad legal,
requiere contrato con un banco y una empresa detrás, y para una app gratis de
tumbas es pedirle el documento a alguien para que puntúe un gravfält. Para
apps de consumo lo normal ahí es exactamente lo mismo que en el resto:
Google, Apple, mail.

**Decisión: Firebase Auth**, porque es el que conocés. Google + mail ahora,
Apple cuando haya iOS.

**Por ahora Android solo.** Hoy el login sale $0: Firebase Auth con Google y
mail es gratis y sin tope de usuarios, y Google Play son $25 una única vez.
Nada de esto es anual.

iOS queda como algo para pedirle a Kungsbacka — la cuota de Apple son
$99/año por cuenta (apps ilimitadas, no por app), y Apple la exime para
entidades sin fines de lucro y públicas en Suecia, lo cual aplica a un
municipio y no a una persona. Mismo razonamiento para el hosting y el
mantenimiento del backend. No es un blocker de nada: es una conversación para
cuando el demo web ya esté mostrado.

Apple sí está soportado como provider de Firebase Auth, igual que Google, mail,
Facebook y varios más. Dos cosas para cuando llegue el momento: necesita una
cuenta de Apple Developer paga (~$99/año), y Apple **exige** su login en
cualquier app de iOS que ofrezca login de terceros. O sea que el día que haya
iOS no es opcional, pero hasta entonces no cuesta nada no tenerlo.

**Firebase Auth con Postgres en `franco-may` conviven sin drama:** Firebase
sólo emite el token. El route handler lo verifica con `firebase-admin` y usa
el uid de Firebase como clave del usuario en nuestra tabla; los eventos siguen
guardándose contra nuestro uuid, que es el que hereda la cuenta. No hace falta
Firestore ni nada más del stack de Firebase.

### Sync: tu diseño está bien, con una corrección

Lo que describiste es un log de eventos append-only, y es el modelo correcto
para esto. Cada cambio local se aplica a la DB local **y** se postea:

```
POST /api/events   { uuid, kind, raa_id, payload, client_ts }
GET  /api/events?since=<seq>&exclude=<uuid>
```

**Las fotos no entran en el sync.** El log de eventos mueve puntajes y
comentarios, que son bytes. Las fotos viven siempre en la nube y se piden por
sitio cuando abrís el sheet — si cada teléfono se bajara las fotos de todos,
la DB local crece sin techo y la app se vuelve impresentable. Lo que sí puede
viajar en el log es que *existe* una foto (url + crédito); el archivo, nunca.

**La otra corrección:** no pagines por timestamp. El reloj del teléfono es del
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

- [x] uuid local con `expo-crypto` (no `Math.random()`: es el token que
      identifica a un autor en un endpoint que acepta escrituras anónimas).
      Vive en `contributions.db`, no en `AsyncStorage`, porque el id y las filas que
      lo referencian tienen que borrarse o sobrevivir juntos
- [x] **`contributions.db`, una base separada de `descriptions.db`** — esa se borra y
      se reemplaza cada vez que cambia `ASSET_VERSION`, así que un puntaje
      guardado ahí desaparecería en el próximo export sin un solo error
- [x] tablas `ratings`, `comments`, `photos` (sólo metadata) como log de
      eventos, no como filas mutables
- [x] `outbox` con `attempts`, para que un payload venenoso no bloquee para
      siempre lo que tiene detrás
- [x] `POST`/`GET /api/fornlamningar/events` en `franco-may` + Neon
- [x] el número de secuencia sale de una **fila contador dentro de la misma
      transacción**, no de `bigserial`. Probado contra Postgres real con dos
      transacciones concurrentes: con `bigserial` se pierde un evento para
      siempre, con el contador cero
- [x] el uuid viaja en el header `X-Author-Id`, nunca en la URL — un secreto
      en un query string queda en los logs del servidor y de cada proxy
- [x] rate limiting **en Postgres**, no en memoria: en serverless cada
      instancia tiene su propio Map
- [x] el salt para hashear IPs se genera solo en la base; no hay variable de
      entorno que administrar ni que olvidarse de copiar
- [x] escalonamiento: anónimo puede puntuar, marcar favoritos y visitados;
      comentarios y fotos devuelven 403 hasta que haya cuentas
- [x] sync al abrir la app y al volver al frente. Sin background task: la app
      se abre cuando alguien está por visitar un lugar, que es justo cuando
      los datos frescos importan
- [x] probado de punta a punta contra producción: 401 sin header, 200 vacío,
      POST, visible para otro autor, excluido para el propio, 403 en
      comentario, 400 en 6 estrellas, idempotente al reenviar
- [ ] Firebase Auth: Google + mail, herencia del uuid
- [ ] verificación del token con `firebase-admin` en el route handler
- [ ] qué pasa si dos teléfonos heredan a la misma cuenta (decidir: merge)
- [x] UI: sección `Betygsätt platsen` con cinco estrellas que responden a
      tap y a drag, más el promedio de la comunidad en el header del sheet
- [x] **la escala tiene nombre en cada paso** — `Inget att se`, `Knappt
      synligt`, `Värt ett stopp`, `Värt en omväg`, `Värt en resa`. Los tres
      de arriba son la escalera de Michelin (parada / desvío / viaje), que es
      el vocabulario que se inventó para esta pregunta exacta. La etiqueta
      sigue al dedo mientras arrastrás
- [x] existe / visible / visitable / interesante son **un solo eje**: si
      alguna es negativa no vale la pena ir, así que es una sola pregunta con
      un solo control, y nombrar el fondo de la escala (`Inget att se`) es lo
      que reemplaza a un botón aparte de "acá no hay nada"
- [x] el promedio de visitantes **reemplaza** al score del modelo en cuanto
      hay un puntaje, no se promedia con él. Mezclarlos da un número que no
      se puede explicar: el modelo mide cuánta documentación tiene el lugar,
      la estrella mide si valió la pena ir, y los primeros cuatro puntajes
      reales ya no coinciden (5★ en una Stenkammargrav que el modelo puntúa
      1,95). Cualquier media de los dos escondía justo ese desacuerdo
- [x] se muestra la media cruda **más la cantidad** (`1,0 · 1 betyg`), no una
      media achicada hacia un prior. El puntaje más valioso de esta app es el
      de la persona que manejó hasta ahí y encontró un campo arado; subirle
      ese 1 a 3,25 entierra la única advertencia que tiene el lugar. El
      achicamiento va en el **ranking**, donde los puntajes compiten entre
      sí, no en el display
- [ ] usar la media achicada para ordenar el mapa (prior = media global de
      usuarios, m ≈ 3), para que un 5 solo no le gane a un 4,6 muy visitado
- [ ] prompt de contribución cuando un lugar no tiene ningún aporte y la
      única fuente es Raä, **con gating por GPS** (~200 m): así cada respuesta
      viene de alguien parado ahí y no de alguien adivinando desde el sillón,
      que además es el vector de vandalismo obvio mientras no haya cuentas.
      Va *después* de la descripción, no tapándola
- [ ] antes de diseñar ese prompt: revisar si el export trae `antikvarisk
      bedömning`. `Uppgift om` ya significa "reportado pero no confirmado en
      el terreno" y `Borttagen` significa "ya no está" — no tiene sentido
      preguntarle a la gente lo que el registro ya dice
- [ ] agregados derivados en `places` (`n_betyg`, media, "no hay nada")
      recalculados desde el log, nunca escritos a mano: misma relación que
      las descripciones con el pipeline
- [ ] moderación antes de que "acá no hay nada" sea visible: mínimo 2–3
      observaciones coincidentes y una forma de apagar a un autor
- [ ] ojo con el sesgo de selección al entrenar con esto: sólo vamos a tener
      etiquetas de lugares donde alguien fue, y la gente va a donde la app
      los manda. El modelo se confirma a sí mismo si no mostramos a propósito
      algunos lugares de score bajo

**Nota para debuggear desde esta máquina:** el puerto 5432 está bloqueado
(acepta el TCP y lo resetea al mandar el saludo de Postgres, lo que se lee
como ECONNRESET y parece una base caída). No es la VPN, probado con ella
apagada. Para migraciones usar `node scripts/apply-fl-schema.cjs`, que va por
el endpoint HTTP de Neon en el 443.

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

**Compresión: partida, y tenías razón en mover el webp al backend.**
`expo-image-manipulator` exporta webp sólo en Android, así que si el webp lo
hace el server hay un solo código para las dos plataformas y una sola calidad
de salida. Pero el resize **sí** va en el teléfono: una foto de cámara son
~4000px y 4 MB, y subir eso con una barra de señal en el medio del campo es
donde la subida falla. Entonces:

- teléfono: resize a 1080p (lado largo) + JPEG q85 → ~250 KB. El resize
  funciona en las dos plataformas.
- server: JPEG → webp al guardarlo en R2, y ahí también el thumbnail del
  carousel.

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
- [ ] cámara + galería, resize a 1080p + JPEG q85 en el teléfono
- [ ] conversión a webp + thumbnail en el backend
- [ ] R2 + endpoint de URL firmada
- [ ] decidir moderación
- [ ] metadata de fotos en el log de eventos; los archivos nunca

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
