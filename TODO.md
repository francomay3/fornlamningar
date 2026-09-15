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
- [x] Firebase Auth: Google + mail, herencia del uuid. Google probado en el
      teléfono y anda
- [x] verificación del token **sin `firebase-admin`**: `jose` contra el JWKS
      de Google, con `iss` **y** `aud` clavados al proyecto — todos los
      proyectos de Firebase los firma la misma clave, así que verificar la
      firma sola acepta el token de cualquier otro proyecto
- [x] dos teléfonos en la misma cuenta: `fl_account_devices`, el autor sigue
      siendo el dispositivo y la agrupación pasa al leer. Probado: los dos
      dispositivos salen con un solo pseudónimo
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
- [ ] **separar tres cosas que yo había mezclado en una.** El "gating por
      GPS" que propuse sonaba a que había que estar parado en el lugar para
      poder puntuar, y eso rompe el caso normal: uno vuelve a casa a la noche
      y ahí puntúa y sube las fotos.
      1. **permiso** para puntuar, comentar y subir fotos: *nunca* se gatea.
         Desde donde sea, cuando sea.
      2. **el prompt** que aparece solo: sí por GPS (~200 m), pero eso es
         sobre *cuándo preguntar*, no sobre quién puede contestar. No tiene
         sentido interrumpirte con "¿la encontraste?" en el subte.
      3. **el peso del negativo** para la advertencia: ahí sí hace falta saber
         si la persona estuvo, y es el único lugar donde importa
- [ ] para (3) **no hace falta guardar un rastro de posiciones.** Hace falta
      un `visit` por lugar — una fila con `uuid` y fecha, no una posición por
      segundo. Se escribe sólo con la app abierta y la posición ya en
      pantalla, o sea con la ubicación que el mapa ya tiene: sin background
      task, que ya estaba descartado por batería. La superficie de privacidad
      es "los lugares que visitaste" y no "todos los lugares donde estuviste"
- [ ] el `visit` ya existe como stub en los dos lados (`EventKind` en
      `contributions.ts`, `ANONYMOUS_KINDS` en el route handler) y nadie lo
      escribe ni tiene tabla. Implementarlo cierra esto y además habilita
      `Mina besökta platser`, que es una feature por sí sola y es el ground
      truth que queremos
- [ ] límite honesto del `visit`: si pasaste con el teléfono en el bolsillo y
      la app cerrada, no hay visita. Por eso el permiso no puede depender de
      él — sin `visit` puntuás igual, lo único que no hacés es sumar a la
      advertencia de "acá no hay nada"
- [ ] la advertencia se decide por **moda, no por promedio**. Tres 1★ y un 5★
      dan promedio 2,0, que no es ni advertencia ni recomendación: es un
      número tibio que no le sirve a nadie. La regla va sobre el conteo de
      1★ verificados
- [ ] la pregunta es **`Hittade du lämningen?`**, no "¿existe?". La distinción
      no es cosmética: "existe" es una pregunta sobre el registro, y un sueco
      contesta "obvio, está en Fornsök". Lo que no sabemos es si una persona
      normal puede llegar y encontrarlo — a veces son piedras indistinguibles
      de cualquier otra piedra y además semienterradas, y para un turista eso
      es igual a que no exista. El registro dice `Bekräftad i fält` porque un
      inventariador con coordenadas la encontró en 1987; no es la misma
      pregunta. Ver la sección 5
- [ ] **el negativo necesita su propia forma de mostrarse, no sólo su valor.**
      Un `1,0 · 3 betyg` al lado del nombre se lee como "lugar malo"; lo que
      le ahorra el viaje al próximo visitante es
      `Flera besökare hittade inget här`. Va arriba, en lugar del promedio,
      cuando la mayoría de los puntajes son de 1★. Es el caso donde la app
      tiene que estar dispuesta a decirte que no vayas
- [x] revisado: **el registro no sabe si hay algo que ver**, así que el
      prompt no se puede reemplazar con datos. `antikvarisk bedömning` es
      99,5% `Fornlämning` y `Borttagen` no existe en nuestros datos. Ver la
      sección 5, que salió de esta revisión
- [x] **el `me` del GET normaliza los eventos propios.** El servidor excluye
      los del dispositivo que llama pero no los de los otros dispositivos de
      la misma cuenta, así que un puntaje hecho en el segundo teléfono llegaba
      con el pseudónimo de la persona mientras el del primero seguía local con
      su id de dispositivo: dos autores, una persona, contada dos veces en
      cada promedio. Se reescribe el autor al aplicar, que es el lugar más
      chico posible — todo lo de abajo ya agrupa por autor
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

### El prompt de contribución (decidido 2026-09-15)

- [ ] `visit` **automático a 50 m**, aunque el usuario sólo haya pasado
      caminando. Es por cluster y no por sitio, así que un gravfält de 160
      tumbas cuenta una vez
- [ ] **no hornear los 50 m en los datos.** Guardar `distance_m` *y*
      `accuracy_m` en el evento y que el umbral sea una constante del código:
      bajo copa de bosque la precisión en Android anda entre 10 y 30 m, a
      veces peor, así que 50 va a dar falsos positivos y negativos y el
      número se va a querer ajustar. Con las dos columnas se ajusta sin
      perder las visitas ya guardadas
- [ ] el prompt automático en el lugar **sólo si el sitio no tiene ni fotos
      ni puntuaciones**. Si ya tiene, no molestar ahí
- [ ] si ya tenía, el pedido se guarda para más tarde en una **notificación
      local** — `expo-notifications`, programada en el teléfono. **No push:**
      sin FCM, sin tokens, sin backend y sin costo. Una por día como máximo, y
      sólo si hay algo que preguntar
- [ ] si visitó varios lugares en un día, preguntar **sólo por el que menos
      fotos y puntuaciones tenga**. El cliente puede ordenarlos porque la
      metadata de fotos y los ratings se sincronizan (los archivos no)
- [ ] `Mina besökta platser` como pantalla, que sale gratis de tener `visit`

### Los carteles

El registro sabe el estado del cartel en **105 lugares de 251.014** — el
0,04% — y la antikvarie de Kungsbacka ya confirmó que el dato no existe en
ninguna fuente. Así que esto es, por lejos, el dato más original que puede
producir la app, y no es cosmético: responde "¿voy a entender qué estoy
mirando cuando llegue?".

- [ ] **el cartel no es un prompt aparte, es una etiqueta en la foto.** Un
      chip `Skylt` por foto dentro del flujo que el usuario ya está usando:
      un toque, ninguna pantalla nueva, y queda el dato estructurado en vez
      de tener que adivinar cuál de las fotos es el cartel. Eso es lo "no
      intrusivo"
- [ ] **"ya tiene fotos" no debe tapar el pedido del cartel.** Son
      necesidades distintas: cinco fotos del paisaje y ninguna del cartel es
      el caso normal. Si comparten la condición, el dato que más nos
      interesa es el único que no vamos a juntar
- [ ] **`Fanns det någon skylt?` Ja/Nej** en el mismo prompt. La ausencia de
      una foto etiquetada no es lo mismo que "no hay cartel", y con el
      registro sabiendo el 0,04% el negativo vale tanto como el positivo
- [ ] eso alimenta `sign_status` / `has_or_doesnt_need_sign`, que ya existen
      en `places.features` y están en `None` para 250.911 de 251.014


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

## 5. Los campos de estado del registro (hallazgo, 2026-09-15)

**Corrección de lo que dije el 14:** `antikvarisk bedömning` **no** sirve para
saber si un lugar existe. Es 99,5% `Fornlämning` (310.440 de 311.844) y el
valor `Borttagen` no aparece ni una vez en nuestros datos — es prácticamente
una constante. Tampoco `aktualitetsstatus`, que es `Bekräftad i fält` en
311.457 de 311.844.

O sea: **el registro no responde "hay algo que ver"**, y eso refuerza el
prompt de contribución en vez de reemplazarlo. "Bekräftad i fält" quiere
decir que un inventariador lo verificó, a veces hace cuarenta años; no dice
nada de lo que encuentra un visitante hoy. Y `skadestatus` es `Okänd` en el
72% de los sitios, que es una declaración sobre cuánto no sabe el registro.

Pero mirando los campos vecinos aparecieron dos cosas que sí sirven. Los
cuatro campos se ingieren en `build_sites.py:199` y **nunca se vuelven a
leer**: no filtran, no son señal, no son label.

### Tareas

- [x] **274 lugares que el propio registro dio de baja están en la app.**
      `Utgår på grund av felregistrering` (116) y `Överförd till annan
      lämning` (158) van a `excluded_hard`: no son lugares, son erratas, y por
      eso acá el veto sí se justifica — el registro no está diciendo que el
      lugar sea aburrido, está diciendo que la ficha no es un lugar. Sólo
      donde **todos** los sitios del cluster están dados de baja: 205 de los
      230 clusters, y 25 quedan porque también tienen sitios vivos. 74 de esos
      205 estaban llegando a la app
- [x] **138 etiquetas negativas.** `Förstörd` (peso 0,9) y `Uppgift om
      lämning, ej bekräftad i fält` (peso 0,6), con `source='register'`, misma
      regla de todo-o-nada por cluster y nunca contra un positivo existente.
      El ratio pasa de **1:832 a 1:61**. El AUC se mueve 0,8113 → 0,8119, y
      eso es el resultado honesto: el set positivo está definido por
      documentación, así que la métrica es ciega justo a lo que estos
      negativos arreglan
- [ ] `Grov skada` (987) es la señal más débil de las tres: dañado de
      gravedad todavía puede ser perfectamente visitable — un röse excavado
      se sigue viendo. Candidato a label negativa con peso bajo, no a
      exclusión, y hay que decidirlo aparte
- [x] los negativos del registro y los de los usuarios (sección 2) apuntan al
      mismo target — "valió la pena ir" — así que conviene que entren por el
      mismo camino y con un `source` distinto en `labels`, que la tabla ya
      tiene justo para esto

---

## 4. La brújula en el marcador de posición (hecho 2026-09-15)

El punto azul debería mostrar **hacia dónde apunta el teléfono**, para poder
pararse en el campo y barrer con el teléfono hasta encontrar en qué dirección
caminar.

**El hallazgo que importa: el `heading` que ya trae la librería es el
equivocado.** `<UserLocation heading />` es una sola palabra y funciona, pero
`@maplibre/maplibre-react-native` lo alimenta con `coords.heading`, que su
propio tipo documenta como *"direction in which the device is traveling"* —
el rumbo del GPS sobre el suelo, no la brújula. Parado y quieto eso es `null`
o el último valor pegado, así que la flecha no se mueve o miente; y caminando
te dice para dónde **vas**, que es justo lo que ya sabés. Lo que se necesita
es el magnetómetro.

`expo-location` ya está instalado y expone `watchHeadingAsync`, con
`trueHeading` y `magHeading`. Así que no hay dependencia nueva.

### Tareas

- [x] hook `useCompassHeading()` sobre `watchHeadingAsync`
- [x] usar `trueHeading`, no `magHeading`: la declinación magnética en Suecia
      es de unos 5–8° al este, y a 100 m de distancia 6° son ~10 m de error
      lateral — suficiente para pasar de largo un röse en el bosque.
      `trueHeading` necesita permiso de ubicación, que ya lo tenemos
- [x] **suavizado obligatorio.** El magnetómetro crudo tiembla varios grados
      por segundo; un cono que salta se ve roto. Filtro pasabajos sobre el
      seno y el coseno del ángulo, **nunca sobre los grados** — promediar 359°
      y 1° da 180°, o sea exactamente al revés
- [x] el cono como capa propia al lado de `<UserLocation />`, no como
      `children`: los children reemplazan el puck entero y habría que
      redibujarlo. Mismo patrón que `ProvisionalLocation.tsx`, que ya dibuja
      su punto con `GeoJSONSource` + `Layer`
- [x] posición viva para esa capa: `UserLocation` la tiene adentro y no la
      expone, así que hace falta un `watchPositionAsync` propio
- [x] `icon-rotation-alignment: "map"` para que el cono gire con el mapa
      cuando la brújula del mapa no está al norte
- [x] icono propio (una cuña con degradado, como el de iOS). No importar el
      `heading.png` de `node_modules`
- [x] qué hacer cuando el sensor no está calibrado: `accuracy` bajo en
      Android es común y el rumbo puede estar 30° equivocado. Mejor ocultar
      el cono que mostrar uno que miente en el bosque
- [x] apagar la suscripción cuando la app no está al frente; el magnetómetro
      a 60 Hz come batería, y esto es una app que se usa lejos de un enchufe

---

## 6. El menú de la app (arriba a la izquierda)

**La regla de los rincones, que ya está implementada:** *abajo* es actuar
sobre el mapa (dónde estoy, dónde está el norte, qué se muestra) y *arriba* es
actuar sobre la app. Los rincones de abajo son los únicos que el pulgar
alcanza caminando con el teléfono en una mano, así que son para lo que se toca
todo el tiempo.

El menú existe porque hay **cinco cosas inconexas de nivel-app**. Con dos
sería el cajón de sastre contra el que advierte el comentario de `Fab.tsx`.
Los cuatro que faltan ya están en el menú **deshabilitados con `Kommer
snart`**, que es un compromiso imposible de olvidar y además le dice al
usuario que la app tiene una forma.

### Tareas

- [x] `Konto` — login con Google y mail, logout, crear cuenta
- [x] **`Mina besökta platser`** — una fila por **lugar**, no por visita, con
      la fecha y un contador de días. Y es también una lista de pendientes:
      cada fila dice si la puntuaste, y tocarla abre el sheet con las
      estrellas. Sin eso es un diario, y un diario no le pide nada a nadie
- [x] `visit_day` ahora es el día **local**, y las filas viejas se repararon
      desde `created_at` (que sí es un timestamp UTC completo). Migración por
      rebuild de la tabla, porque un UPDATE puede violar el índice único:
      01:00 y 14:00 del mismo día sueco son dos días UTC distintos y uno
      local. Probado contra sqlite3 real con `TZ=Europe/Stockholm`
- [ ] lo que **no** se reparó es el servidor: el duplicado local que la
      migración descartó ya estaba posteado, así que el log tiene dos visitas
      de un autor para un lugar en un día. Hoy no le molesta a nadie, pero es
      la razón por la que contar visitas, cuando llegue, tiene que deduplicar
      al leer y no confiar en la regla del cliente
- [x] **`Påminnelser`** on/off — apagarlo **desprograma** la notificación de
      esta noche, no sólo deja de programar las próximas; prenderlo pide el
      permiso ahí mismo y el switch guarda el estado que *logró*, no el que
      se pidió, porque el sistema puede negarse. `settings` key-value en
      `contributions.db`, schema 3
- [x] **`Språk`** sv/en — **la mitad de la interfaz**: `src/i18n` con 130
      claves, los 31 artículos del wiki traducidos con sus propios `triggers:`
      en inglés, y `check-i18n.mjs` validando claves y placeholders
- [ ] **`Språk`, la otra mitad: las descripciones siguen en sueco** (hallazgo
      de campo 2026-09-15: "lo puse en inglés pero las descripciones siguen
      viéndose en sueco"). Es el comportamiento actual por diseño, no un bug:
      `DESCRIPTION_LANG = "sv"` en `src/data/descriptions.ts` es una constante
      porque es una propiedad **del archivo** — sólo se empaqueta el export
      sueco. Para moverla hacen falta tres cosas:
  - [ ] `content_en` para todo el país, no sólo los 150 de KB (es la tirada
        larga; hoy hay 148 traducidos)
  - [ ] `build_tiles.py --lang en` emitiendo un segundo `descriptions.db`, y
        el APK llevando los dos (+10 MB) o bajando el segundo a demanda —
        **decisión de tamaño, es de Franco**
  - [x] **hecho**: una base por idioma, `descriptions.<lang>.db`, y cada
        **fila** lleva el idioma en que realmente está — el export cae al
        sueco por fila, así que hoy 5.540 de 9.547 lugares están de verdad en
        inglés y el resto son suecos adentro del archivo inglés. El matcher
        del wiki toma el idioma de la fila, así que un lugar sin traducir
        sigue subrayando sus palabras suecas. +6 MB de APK (56,3 MB)
  - [ ] **los labels del mapa siguen en sueco**: salen de `points.geojson`,
        que es un solo archivo para los dos idiomas y lleva el título sueco.
        Duplicarlo son +2,5 MB, o el label se resuelve en la app desde la
        base del idioma (ya tiene el `title` por fila) — esto último es mejor
        y no cuesta bytes
  - [ ] faltan los ~4.000 sin traducir, y de los traducidos hay que ver
        cuántos son viejos: la cola por timestamp ya los detecta
  - [ ] `DESCRIPTION_LANG` pasa a ser función del idioma elegido y de qué
        bases hay empaquetadas. Todo lo que lo necesita ya pregunta ahí,
        incluido el matcher del wiki: los triggers se eligen por el idioma de
        la **prosa**, así que eso sale gratis
- [x] **`Om appen`** — las dos listas se **generan** de los archivos que
      describen: los 23 créditos los emite `build-wiki.mjs` de las propias
      líneas de crédito de los artículos (que ya valida que no falten), y los
      21 paquetes los emite `build-licences.mjs` del árbol instalado, leyendo
      el campo `license` de cada uno. Una pantalla de licencias es la única
      que nadie mira hasta que importa, así que una copia a mano se desfasa
      justo para el lado que duele y nada lo avisa
- [ ] **el párrafo de fuentes está escrito a mano y va a desfasarse.** Los
      créditos de las 23 fotos y los 21 paquetes se generan, pero la lista de
      fuentes de las descripciones es prosa en `sv.json`. El pipeline **sí**
      tiene el dato: `sources.publisher` por fila y el `LICENCE_MAP` de
      `crawl_lansstyrelsen.py`. Derivarlo necesita que el export lleve el
      conjunto de `kind`/publisher/licencia presentes
- [ ] **las licencias de los paquetes están como nombre + id SPDX**, que es
      práctica común pero no es lo que MIT y Apache-2.0 piden: piden que el
      **texto** del aviso viaje con el binario. La versión rigurosa empaqueta
      los `LICENSE` de `node_modules` y los muestra. Hoy la nota al pie dice
      que viajan en los paquetes, que es cierto del `.apk` pero no es lo mismo
      que mostrarlos
- [ ] **atribución por lugar en las descripciones.** La app dice en `Om
      appen` de qué fuentes salen las descripciones en general, que es la
      declaración agregada honesta, pero no dice **cuál** alimentó a cuál. De
      los 9.558 exportados, **1.061 tienen fuente de Wikipedia** (CC BY-SA
      4.0, o sea que la descripción es una adaptación y arrastra
      share-alike), 200 `county_attr`, 111 `county_plan`, 81 `county_page`,
      59 `county_programme` y 44 `county_pdf` (CC BY 4.0 / CC BY-SA 4.0)
- [ ] `generation_sources` **existe y está vacía** (0 filas), y era
      exactamente el mecanismo para que la atribución fuera calculada y no
      declarada. Llenarla es lo que hace posible la línea de crédito por
      lugar; después hay que exportarla y mostrarla en el sheet
- [ ] `ATTRIBUTION` en `src/map/constants.ts` **no lo usa nadie**, así que
      hoy el mapa no muestra ninguna atribución de OSM. Con `Om appen` está a
      dos toques, que es discutible; ponerlo en el mapa es una decisión
      visual, no técnica
- [x] **`Glöm mig`** — `_reset()` ya existe en `contributions.ts` y no tiene
      botón. Va separado por una línea y en color de acento: borrar todo lo
      que contribuiste no puede estar en la misma lista visual que cambiar el
      idioma
- [x] **`Glöm mig` tiene que abrir una ventana de advertencia antes de
      ejecutar.** Es la única acción de toda la app que no se puede deshacer
      ni reintentar: no hay copia de la que volver, y los puntajes, visitas y
      respuestas sobre carteles se van todos juntos. La advertencia tiene que
      decir *qué* se pierde, no preguntar "¿estás seguro?" — que es la
      pregunta que la gente aprende a contestar sí sin leer
- [x] **`Glöm mig` son tres cosas, no una.** Las tres, en este orden, porque
      el orden es parte del diseño:
      1. pedirle al servidor que borre por autor — **antes** de tirar el
         uuid, porque el uuid es lo único con que se puede pedir. Después de
         tirarlo los eventos publicados quedan huérfanos para siempre: nadie
         los puede volver a asociar con esa persona, ni para borrarlos
      2. **cerrar la sesión de Firebase.** `_reset()` borra la fila `device`,
         así que el `account_id` local se va, pero la sesión de Firebase
         sigue abierta y te quedás con el avatar puesto y un uuid nuevo: un
         estado incoherente
      3. borrar local. El uuid nuevo ya sale gratis de borrar la fila
         `device` — `getDeviceId()` lo genera en la siguiente llamada
- [x] **el link es el agujero, y es el argumento de verdad para (1) y (2).**
      Resuelto: la fila del link se borra con los eventos
      Si no se cierra la sesión y el uuid nuevo se vuelve a linkear a la
      misma cuenta, la cuenta sigue apuntando al dispositivo viejo, cuyos
      eventos siguen publicados. Borrar local dejando el link en el servidor
      es la peor de las tres opciones: parece que borró y no borró. O borra
      por autor, o como mínimo desvincula
- [x] **decidido: cerrar sesión NO rota el uuid.** Es tentador — te daría la
      semántica que uno espera, "ahora soy anónimo" — y es la trampa contra
      la que ya nos estrellamos una vez: partir a una persona en dos autores
      a propósito. Además rompe "¿esto lo puntué yo?", que se resuelve por
      autor, así que haría falta una tabla de uuids históricos para
      reconocernos a nosotros mismos. `Logga ut` significa "dejá de mostrar
      quién soy"; el que cambia de identidad es `Glöm mig`. Dos acciones con
      un significado nítido cada una, en vez de un logout que hace medio
      borrado
- [x] **el link sólo cubre dispositivos que alguna vez iniciaron sesión**, y
      eso es irreparable por diseño. Si puntuás en el teléfono A sin cuenta y
      después te logueás sólo en el B, lo del A queda como autor anónimo
      aparte. Lo único que puede probar que el A era tuyo es el A presentando
      su uuid, y un endpoint que te deje reclamar eventos de un uuid ajeno es
      un endpoint para robar contribuciones. La consecuencia práctica es
      chica: loguearse una vez en cada teléfono antes de jubilarlo
- [ ] **borra sólo este dispositivo**, incluso para alguien logueado con dos
      teléfonos. Se podría seguir el link y borrar el otro, y para una lectura
      estricta del derecho de borrado probablemente haya que hacerlo; no está
      hecho porque el secreto de un dispositivo destruiría datos escritos en
      otro, y un diálogo parado en un teléfono sólo puede prometer
      honestamente lo que ese teléfono hizo. El otro teléfono tiene el mismo
      botón
- [ ] el glifo del botón ya refleja si estás logueado (relleno vs contorno).
      Cuando haya avatar de Google, decidir si se usa en vez del glifo

---

## 7. La cola de preguntas (decidido 2026-09-15)

Hoy el sheet tiene dos bloques fijos: las estrellas y la pregunta del cartel.
La idea de Franco es mejor: **una pregunta a la vez**. Al contestar se va y
aparece la siguiente, y el usuario contesta cuantas quiera y para cuando
quiera.

Lo que lo hace valer no es el orden, es que **habilita condicionales**. La
foto del cartel sólo tiene sentido si contestó que hay cartel, y un bloque
fijo no puede expresar eso.

### El orden

0. **`Har du varit här?`** — el gate. Se pregunta **incluso cuando el GPS ya
   registró la visita**: 50 metros con la app abierta no es lo mismo que haber
   estado, porque podés pasar al lado de un röse por un sendero y no verlo, que
   es justo lo que esta app existe para avisar. La visita es un **candidato** y
   esto es la **confirmación**
1. **el puntaje** — la escala con nombres que ya existe. Va primero porque es
   el target del modelo y es lo único que no se puede conseguir de otra forma
2. **`Fanns det någon skylt?`** — `Ja` / `Nej` / `Osäker`
3. **la foto del cartel** — sólo si contestó `Ja`. Diseñada ahora, apagada
   hasta que exista el backend de fotos (sección 3), y no es una pregunta:
   es un botón que abre la cámara. "¿Podrías sacar una foto?" con Ja/Nej es
   raro, porque el `Ja` tiene que abrir la cámara igual

### Las decisiones

- [x] **el gate es haber estado, no estar ahí.** Lo que se rechazó en la
      sección 2 fue gatear por GPS *en el momento* — uno vuelve a casa y ahí
      puntúa — y eso sigue funcionando porque la visita quedó registrada. Lo
      único que cambia es el caso "nunca estuve acá"
- [x] **por qué el puntaje necesita el gate, y no es prolijidad.** La escala
      pregunta si valió la pena el viaje, y quien no fue sólo puede contestar
      con lo que la app le mostró: descripción, fotos, score. O sea que su
      estrella es **una función de los features que el modelo ya ve** — que es
      exactamente cómo las labels de Wikidata le enseñaron "está documentado"
      en vez de "vale la pena ir". Dejar puntuar a no-visitantes reintroduce
      ese defecto por el target
- [x] **`Nej` con visita del GPS no es una contradicción.** Es evidencia de
      que el sitio no se ve estando al lado, que es casi el negativo más
      fuerte que la app puede juntar. Por eso se guarda el par (`had_visit`) y
      no sólo la respuesta: el desacuerdo es el caso valioso
- [x] **confirmar no escribe una visita.** El que confirma un lugar que vio en
      1998 no lo visitó hoy, y fabricar una fila con la fecha de hoy pondría
      una fecha falsa en la única tabla que existe para tener fechas reales.
      `Mina besökta platser` en cambio descarta los lugares cuya última
      respuesta es `Nej`
- [x] **el que confirmó sin visita del GPS aparece con `Tidigare`** en vez de
      una fecha. El único timestamp que tenemos es cuándo nos lo dijo, que no
      es cuándo fue, y ponerlo sería una fecha inventada en la única lista
      donde la fecha es el contenido. Las con fecha primero y las sin fecha al
      final, porque la lista se lee como una cronología
- [x] **una pregunta que puede esconder a las otras tiene que dejar una
      puerta.** `Hoppa över` en el gate reemplazaba la sección entera por
      `Tack!` sin forma de volver, o sea que un toque borraba las estrellas de
      ese lugar para siempre. Y las respuestas que ya existen se muestran
      diga lo que diga el gate: esconder el propio puntaje de alguien detrás
      de una pregunta que todavía no contestó no es nuestra decisión
- [x] el costo, dicho en voz alta: esto ata el crecimiento de los datos a la
      velocidad a la que la gente camina. Se paga igual — 50 puntajes de gente
      que fue valen más que 500 de gente que leyó la descripción

- [x] **el checkbox `Jag kunde inte hitta lämningen` debajo del input de
      puntaje.** La idea de Franco, y reemplaza a la pregunta condicional que
      yo había propuesto. El diagnóstico es lo que acierta: poner una estrella
      es *publicar una opinión negativa*, y alguien que no pudo verificar nada
      no quiere opinar — quiere reportar. Son dos actos distintos. Y un escape
      a la vista, antes, saca la barrera en el momento en que existe, donde una
      aclaración condicional llega después de que la persona ya hizo lo que no
      quería hacer
- [x] **no se guarda como 1★.** Una estrella es "para nada recomendable" y
      nada más; el flag es "no pude verificar". Si el checkbox escribiera
      `stars: 1`, al volver a abrir el lugar la persona vería *una estrella
      puesta por ella* — justo la opinión que se negó a dar. Se guarda como
      respuesta propia y **cuenta como el puntaje más bajo sólo donde hace
      falta un número**: ranking, score, labels
- [x] **exclusión mutua en las dos direcciones.** Enforced en SQLite, no sólo
      en la UI: `stars` es nullable y un CHECK deja pasar exactamente una de
      las dos. Probado contra sqlite3 real: las dos puestas falla, ninguna
      puesta falla. Marcar el checkbox borra el
      puntaje además de deshabilitarlo, y tocar una estrella desmarca el
      checkbox. Si sólo se deshabilita queda un estado intermedio — tres
      estrellas apagadas y el checkbox marcado — donde nadie sabe qué se
      guardó. Es una pregunta con dos formas de contestarse, así que no puede
      tener dos respuestas a la vez
- [x] **`Inget att se` se queda.** No lo reemplaza: son los dos consejos
      distintos que queríamos separar. `Inget att se` es "la encontré y no hay
      nada que valga la pena"; el checkbox es "no pude verificar". Para el
      próximo visitante son mensajes diferentes, y son justo los dos que el
      registro no distingue
- [x] **`Osäker` es una respuesta; `Hoppa över` es la ausencia de una.** La
      respuesta del cartel es de tres valores y se guarda como texto, no como
      un tercer entero: `has_sign IN (0,1,2)` es un booleano con una mentira
      adentro. No
      pueden compartir un botón. `Osäker` es dato — la persona estuvo y no
      pudo determinarlo, y para el cartel eso vale casi tanto como un `Nej`.
      `Hoppa över` no se guarda como dato nunca: lo único que registra es "no
      me preguntes esto ahora". Si comparten un botón, el día que contemos
      respuestas vamos a estar contando silencios
- [x] **las respondidas colapsan** a una línea con `Ändra`, y las salteadas a
      una con `Svara`. Sacar las estrellas al responder habría sacado el único
      lugar donde alguien puede ver o corregir su propio puntaje, y saltear
      una vez no es una decisión para siempre
- [x] el **cartel es un hecho del sitio**, así que va al lado del período y
      el tamaño y no al lado de los botones que lo preguntan. Mayoría de la
      última respuesta por autor, con `unsure` como su propio bucket — se
      inclina al `no`, pero leerlo como `no` sería contestar por la persona, y
      todo el valor de este campo es que la respuesta viene de gente. El
      empate también es `oklart`. Siempre con el conteo, porque con el
      registro en 105 de 251.014 el reporte de un visitante es lo mejor que
      esto va a tener y el lector tiene que saber qué tan flaco es
- [x] **la advertencia por moda**, que estaba escrita y no construida. Cuenta
      un "no lo encontré" o **un 1★ de alguien a quien el GPS puso en el
      sitio**: una estrella es una opinión, y la opinión de alguien que no fue
      es justo lo que esto no puede usar, mientras que el "no lo encontré" ya
      viene gateado. Mínimo dos, porque uno no es un patrón — un solo reporte
      decidiendo lo que ven todos los demás es una mala tarde, o una persona
      con bronca. Y eso significa que un "no lo encontré" solo vuelve a
      mostrar las estrellas del modelo, que es el canje correcto
- [ ] el 1★ verificado usa `visited` (GPS). Un visitante **declarado** que
      puntúa 1★ no cuenta para la advertencia. Decidir si la presencia
      declarada alcanza, ahora que el gate la pide
- [ ] los skips **se miden**: una pregunta que todos saltean es una pregunta
      mal escrita, y eso sólo se ve si el skip se cuenta. Empieza como tabla
      local; sincronizarlo necesita un `kind` nuevo en el servidor
- [x] **la cola vive en un solo lugar.** Se usa desde el sheet y desde el
      flujo de la notificación de la noche. Dos implementaciones se
      desincronizan — es lo que ya pasó con los dos sheets abiertos a la vez y
      con el padding de la cámara
- [x] **la cola necesita un final visible.** Cuando no queda nada que
      preguntar tiene que decir algo, no desaparecer. Un bloque que se esfuma
      solo se lee como un bug, no como una tarea terminada
- [x] `SegmentedControl` (el de una fila de celdas, el del umbral de estrellas
      en los filtros) para las de sí/no, en vez de dos botones sueltos: dos
      celdas pegadas se leen como **una** pregunta con dos estados
- [x] el recordatorio de la noche considera "contestado" **sólo el puntaje**.
      Antes bastaba contestar el cartel para silenciarlo, o sea que la
      pregunta barata tapaba a la valiosa: una visita real sin puntaje, que es
      lo único que ese recordatorio existe para juntar

---

## 8. Logs de warnings y errores, en un solo lugar (pedido 2026-09-15)

**Qué es:** que la app y el backend manden sus warnings y errores al mismo
endpoint, y que ahí se guarden en una tabla de Postgres. Hoy un error en el
teléfono no existe para nadie: no hay Crashlytics, no hay Sentry, y el único
síntoma de un bug es que Franco lo vea.

El ejemplo que lo motivó: **cada vez que `t()` cae al sueco porque falta una
traducción**, eso debería quedar registrado. `check-i18n.mjs` ya rechaza el
build si faltan claves, así que ese caso concreto no debería llegar a
producción — pero el fallback existe justamente para lo que el build no
previó, y un fallback silencioso es un hueco que nadie encuentra.

### Qué más vale la pena, de lo que ya sabemos que pasa

- el fallback por artículo del wiki: leer un artículo en sueco con la app en
  inglés es lo mismo, y hoy tampoco avisa
- un `kind` que el servidor no acepta: el 4xx marca el lote entero y a los 10
  intentos las filas salen de la cola **para siempre**. Eso pasó hoy y sólo
  se vio porque lo fui a buscar
- un evento remoto descartado en `applyRemote` por no pasar la validación: es
  una contribución de alguien que se pierde en silencio
- `refreshReminder` cancelando por excepción, que hoy se come con un `catch`
- en el pipeline: los `flags` de las descripciones ya son esto, pero viven en
  la base y nadie los mira

### Decisiones que hay que tomar antes de escribir una línea

- [ ] **es un endpoint de escritura anónimo**, igual que los eventos, y por lo
      tanto tiene los mismos problemas: alguien puede llenar la tabla. Hace
      falta el rate limiting que ya existe para eventos, un tope de tamaño por
      mensaje, y probablemente **muestreo** — el mismo warning 10.000 veces es
      una fila con un contador, no 10.000 filas
- [ ] **no puede llevar datos personales.** Un stack trace es texto nuestro,
      pero un mensaje de error con el texto que el usuario escribió, o con su
      uuid de autor, convierte la tabla de logs en un lugar donde hay que
      pensar en GDPR. El uuid es además una credencial de escritura, así que
      no puede viajar ni en el payload ni en un header a un endpoint que
      guarda todo lo que recibe
- [ ] **la app es offline-first**, así que los logs necesitan cola propia como
      el `outbox`, con su propio límite: un teléfono sin señal en el campo no
      puede acumular logs sin techo, y un log perdido es aceptable de una
      manera en que un puntaje perdido no
- [ ] **qué se hace con lo que llega.** Una tabla que nadie lee es peor que no
      tenerla, porque da la sensación de que está cubierto. Mínimo: una vista
      agrupada por mensaje con conteo y última vez visto
- [ ] nivel mínimo: `warn` y `error`. Nada de `info` ni `debug` — eso es lo
      que convierte un log útil en un vertedero
- [ ] el backend ya tiene Postgres y `tx()`; la tabla puede vivir al lado de
      `fl_events` con el mismo `apply-fl-schema.cjs`

---

## 9. Contribuir y reportar sitios (pedido 2026-09-15)

Hoy el mapa es de sólo lectura sobre el registro: lo único que un visitante
puede dejar es una opinión sobre algo que ya está. Faltan las dos direcciones
contrarias — agregar lo que falta y desmentir lo que sobra.

- [ ] **agregar un sitio que no está en el mapa.** Mínimo: posición (la del
      GPS, corregible arrastrando el pin), tipo elegido de las mismas
      familias que ya usa el filtro, y una descripción libre corta. Es el
      primer caso donde el usuario **crea** una entidad y no un evento sobre
      una entidad existente, así que necesita uuid propio del cliente y una
      tabla aparte: no puede entrar en `fl_events`, que asume un `uuid` del
      registro
- [ ] **reportar un sitio, con categorías.** Las tres que pidió, y son
      suficientes para empezar: **no está aquí** / **es inaccesible** / **la
      posición no es correcta**. Una por reporte, más un campo libre opcional
- [ ] la tercera categoría y "agregar un sitio" son la misma cosa vista de dos
      lados. Si alguien dice "la posición no es correcta", lo útil es que
      pueda **marcar dónde sí está**: el reporte lleva una coordenada
      opcional, y el flujo es el mismo pin arrastrable
- [ ] `no está aquí` ya tiene un primo: el flag `not_found` de la valoración.
      **No son lo mismo** y hay que no confundirlos: `not_found` es "no lo
      encontré" (puede ser mío, puede estar tapado de maleza), el reporte es
      "no está". Lo primero es una duda, lo segundo una afirmación. Vale usar
      el conteo de `not_found` para **sugerir** el reporte al que ya lo marcó
- [ ] **nada de esto puede aparecer en el mapa sin moderación**, y la
      moderación es el mismo problema que ya bloquea las fotos: un punto
      inventado o un reporte falso sobre un sitio real son vandalismo con la
      misma cara que una contribución. Mientras no haya moderación, esto se
      guarda y se muestra **solo a quien lo escribió**
- [ ] un reporte y un sitio nuevo son afirmaciones **sobre el mundo, firmadas**
      — a diferencia de una valoración. Es el segundo candidato después de las
      fotos a exigir cuenta y no uuid anónimo. Decisión de Franco

## 10. El filtro de estrellas no son las estrellas del usuario (hallazgo 2026-09-15)

Reportado como bug: "filtrar por estrellas no toma en consideración el nuevo
puntaje de un fornlämning luego de que lo puntúes". El filtro hace lo que
dice hoy — sólo que lo que dice no es lo que se lee.

- [ ] **son dos escalas distintas con el mismo icono.** Las del filtro son
      buckets del percentil de `score` que calcula el pipeline (`stars` viene
      en el tile, ver `src/map/thinning.ts`); las de la ficha son el promedio
      de las valoraciones de la gente. El filtro no puede mirar las segundas
      hoy: son filas de `contributions.db`, y el filtro es una expresión de
      MapLibre sobre el tile — a propósito, porque así no hay que parsear
      2,3 MB en JS
- [ ] el `Beräknat automatiskt` debajo del control **existe** y claramente no
      alcanza. Lo mínimo es que el texto diga de qué son esas estrellas
- [ ] la decisión de verdad es si el filtro debería honrar las valoraciones
      reales cuando las hay. Las valoraciones son **escasísimas** (una por
      lugar, y sólo de quien pasó por ahí), así que un filtro que las mezcle
      hace desaparecer lugares buenos sin visitar. Alternativas: dejarlo como
      está con mejor rótulo; o un filtro aparte "mis lugares valorados" que no
      toque el score. **Decisión de Franco**

---

## Pendientes viejos, de antes de hoy

- [ ] `check-i18n.mjs` no detecta **claves duplicadas** en un mismo archivo.
      `sv.json` tenía `common.cancel` dos veces (mismo valor, así que no hizo
      daño); si los valores hubieran diferido, el que gana es el último y
      nada lo avisa
- [ ] el build de Android deja recursos generados viejos: al renombrar
      `descriptions.db` a `descriptions.sv.db`, el APK salió con las dos y
      6 MB de peso muerto. `assembleRelease` no limpia
      `android/app/build/generated/res/react/release/raw`
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
