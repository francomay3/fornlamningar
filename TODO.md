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

**Revisada el 2026-09-16 — sólo usuarios logueados escriben en el servidor.**
El uuid sigue siendo el autor y la cuenta sigue heredándolo, y todo lo local
(puntuar para uno mismo, visitas, `Mina besökta platser`) sigue funcionando
sin cuenta. Lo que cambia es que **nada se publica** sin que el uuid esté
linkeado a una cuenta: el POST de eventos exige el link. Motivo: un uuid
anónimo se mintea infinitas veces, así que ni el rate limit por autor ni la
regla de "dos observaciones coincidentes" de la sección 7 valían nada. Una
cuenta de Google cuesta mintear y se puede banear. Lástima la idea original;
era linda. Ver el item de implementación más abajo.

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

### Hallazgos del review de 2026-09-16 sobre el sync

- [ ] **Race en el GET que pierde un evento para siempre.** En
      `app/api/fornlamningar/events/route.ts` el GET hace dos queries sin
      transacción: primero `SELECT ... FROM fl_events WHERE seq > since`, y
      después `SELECT v FROM fl_event_seq`. Si la primera vuelve vacía (la
      ventana sólo tenía eventos propios) y **entre las dos** otro autor
      commitea el evento N, el cursor salta a N y ese evento no lo lee este
      teléfono nunca. Es exactamente el caso que el contador existía para
      impedir.
      **Fix, fácil:** invertir el orden. Leer `v` *primero*, después los
      eventos. Así el cursor nunca puede adelantarse a algo que no se leyó:
      si hay filas, el cursor es la última fila; si no hay, es el `v` leído
      *antes* de mirar, y cualquier evento posterior queda `> cursor`. Es
      mover dos líneas; no hace falta transacción ni `FOR SHARE`.
- [ ] **El feed es global, y una instalación nueva rehace toda la historia.**
      Cada teléfono baja todos los eventos de todos los usuarios desde
      `seq=0` y los aplica uno por uno a SQLite. Hoy son cientos de filas.
      Con mil usuarios activos durante tres años son millones, y el primer
      arranque de alguien nuevo se vuelve minutos de sync — el problema que
      Franco describió el 16: no quiero que la instalación número mil baje y
      aplique tres años de cambios en el primer run.
      **Lo que sale de eso:** el log de eventos es el formato correcto para
      *mover* cambios, no para *inicializar* un teléfono. Un teléfono nuevo
      tiene que arrancar de un **snapshot** (los agregados por lugar:
      promedio, conteo, cartel, advertencia) y sincronizar sólo los eventos
      posteriores al `seq` del snapshot. Es el mismo argumento que la
      sección 12 hace para los lugares, y la misma solución: el backend
      publica un snapshot por generación, y la app baja snapshot + delta. Ver
      la sección 11, que ahora junta las dos cosas. No urgente: mientras el
      log tenga miles de filas es gratis. Sí hay que **no** construir nada que
      dependa de que cada teléfono tenga el log completo (por ejemplo, calcular
      la advertencia por moda en el cliente sobre eventos crudos ya es eso).
- [ ] **El uuid anónimo no limita nada.** Cualquiera puede mintear uuids sin
      tope, así que el rate limit por autor es decorativo (queda el de IP) y
      una sola persona con dos `Glöm mig` son "dos observaciones coincidentes"
      para la advertencia de la sección 7. Franco preguntó si el uuid debería
      emitirlo el backend. **No ayuda:** un endpoint que emite uuids se lo
      pide N veces igual; sólo cambia quién genera el número. Las opciones
      reales son tres:
      1. **Exigir cuenta para publicar.** Google One Tap es un toque, la app
         no está publicada, y Firebase Auth ya está hecho. Lo local sigue
         andando sin cuenta (puntuás para vos), pero nada se postea sin
         `account`. Una cuenta de Google es cara de mintear en masa, y se
         puede banear.
      2. Anónimo puede publicar, pero los **agregados que ven los demás**
         (promedio, advertencia) sólo cuentan autores con cuenta linkeada.
         Es más código y una regla que nadie va a entender desde afuera.
      3. Play Integrity / device attestation. Es la herramienta para esto,
         pero requiere Play Store y es un proyecto aparte.
      **Mi recomendación es la 1.** Es la única que además resuelve la
      moderación de comentarios y fotos, que ya la pedía, y el costo es un
      toque de Google en la primera contribución. Lo que se pierde es la
      decisión de la sección 2 de que "el uuid anónimo es el usuario real",
      que se mantiene *localmente*: el uuid sigue siendo el autor, la cuenta
      sigue heredándolo; lo único que cambia es que el POST exige que el
      uuid esté linkeado. **Decidido por Franco el 2026-09-16: opción 1.**
- [ ] **Implementar "sólo logueados escriben".** Cuatro cambios, en este orden
      para que nada quede a medias:
      1. **Servidor, `events/route.ts` POST:** después de validar el header,
         `SELECT account FROM fl_account_devices WHERE device = $1`. Si no
         hay fila → `403 { error: 'sign in to publish' }`. `ANONYMOUS_KINDS`
         y `ACCOUNT_KINDS` se funden en una sola lista `KINDS`; la distinción
         ya no existe. El GET **no** cambia: leer sigue siendo anónimo, porque
         el mapa tiene que mostrar los promedios a todos.
      2. **Servidor, `author/route.ts` DELETE:** también exige link, por
         simetría; si no hay nada publicado no hay nada que borrar, pero el
         tombstone de `Glöm mig` no debe poder escribirlo un uuid suelto.
      3. **App, `sync.ts` `flush()`:** un 403 de este tipo **no** es un fallo
         del payload: las filas se quedan en el `outbox` con `attempts` sin
         subir, y se reintentan cuando haya cuenta. Distinguirlo del 403 de
         kind por el campo `error`.
      4. **App, UI:** la primera vez que alguien puntúa sin cuenta, el sheet
         guarda localmente y muestra una línea debajo de las estrellas:
         `Sparat på den här telefonen. Logga in för att dela` con el botón de
         login inline. No es un modal ni un bloqueo: la estrella ya está
         puesta. El menú `Konto` ya tiene el flujo; es reusarlo.
      Probar: puntuar sin cuenta → fila local, outbox pendiente, 403 en el
      flush, sin `attempts`; loguearse → link → el siguiente flush publica.

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

### Agregado en el review de 2026-09-16

- [ ] **Sacar el EXIF antes de subir.** Una foto de cámara lleva la posición
      GPS, la fecha, y el modelo de teléfono adentro del JPEG. La posición es
      casi la del sitio, pero la fecha y hora dicen *cuándo* estuvo la persona
      ahí, y el resto identifica el dispositivo. El resize de
      `expo-image-manipulator` ya lo descarta al reencodear; verificar que es
      así en las dos plataformas y no confiar en que lo hace. Si el server lo
      hace también al pasar a webp, mejor: dos capas
- [ ] **Licencia de las fotos de usuarios.** Hoy el crédito es
      `user:<uuid>`, pero no hay ningún lugar donde la persona acepte bajo qué
      licencia publica. Sin eso la app no puede mostrar la foto a otros con
      seguridad, y mucho menos reusarla. Una línea en el primer flujo de
      cámara ("Tu foto se publica bajo CC BY 4.0") guardada como evento o
      como fila en `settings`, una sola vez. Es la misma pregunta que ya se
      contestó para las fotos de Commons, desde el otro lado
- [ ] la moderación que falta decidir es la misma para **comentarios**, que
      ya están en `ACCOUNT_KINDS`. Decidir una vez para las dos
- [ ] la URL firmada tiene que fijar **tamaño máximo y content-type** en la
      firma (S3 lo permite), no sólo el path: si no, "sube directo a R2" es
      "sube lo que quieras a R2"

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
- [x] **`generation_sources` ya no está vacía** (hecho 2026-09-16, 12.446
      filas). `load_sources` saca el `source_id` de cada fila, `payload` lo
      quita del `model_input` y lo devuelve aparte en `source_ids`, y el loop
      de generación lo escribe en cuanto la descripción se commitea. El id
      **no** entra al payload a propósito: `source_hash` es un hash de lo que
      vio el modelo, y meter un id ahí habría hecho que los 9.181 lugares
      reportaran "mis fuentes cambiaron" y se encolaran para regenerar.
      Verificado: las 150 filas v3 re-hashean exactamente a lo guardado
  - [x] `--backfill-sources` estableció 8.842 de las 9.199 existentes, en dos
        niveles, y la columna nueva `basis` dice cuál:
        **`hash`** (148, probadas: reconstruir el payload da el `source_hash`
        guardado), **`register-only`** (8.694, escritas antes de que el
        commit `3b99dfb` cableara el corpus, así que por construcción vieron
        un solo campo), y **ausentes** (357, posteriores a ese día y sin
        `payload_version`: no las decide ni el hash ni la fecha, así que no
        reciben nada en vez de una adivinanza — regenerarlas es lo que lo
        arregla)
  - [x] **corrección al número de arriba**: no son 1.061 descripciones
        saliendo de Wikipedia. **1.401 lugares tienen una fuente de Wikipedia
        en el corpus, pero sólo 6 descripciones del archivo fueron escritas
        de una** — las otras 8.694 probadamente no. Así que la obligación de
        CC BY-SA hoy son 6 lugares, y pasa a ~1.401 después de la
        regeneración. Era mucho menos urgente de lo que parecía, y lo que lo
        vuelve urgente es la regeneración, no el tiempo
  - [ ] `features.uses_wikipedia` lo va a levantar `build_places` la próxima
        vez que corra (daría 6 hoy). **No** se escribió desde
        `build_descriptions`: esa columna alimenta el score, y escribirla
        desde fuera de su etapa es la clase de acoplamiento que se rompe solo
  - [ ] falta la otra mitad: **exportarla y mostrarla en el sheet** (pedido
        2026-09-16). Ver el item de abajo, que tiene el diseño
  - [ ] ojo con `rm places.sqlite`: los `source_id` son autoincrementales y
        `build_sources` los preserva sólo porque inserta con `INSERT OR
        IGNORE` sobre una tabla que no dropea. Borrar el archivo reasigna los
        ids y deja `generation_sources` apuntando a otras filas. Si algún día
        hay que rehacer el corpus de cero, hay que rehacer también el backfill
- [ ] **una línea de atribución en el sheet, debajo del texto generado**
      (pedido 2026-09-16). Ahora que `generation_sources` tiene datos se
      puede derivar, y el diseño lo decide un número: **sólo 26 de los 8.842
      lugares atribuidos tienen algo más que el registro.** Las licencias
      declaradas de lo que atribuye hoy son `CC0 1.0` en 8.842 lugares
      (el registro de RAÄ), `CC BY-SA 4.0` en 6 y `unresolved` en 7
  - [ ] **entonces la línea no va en todos los lugares.** Una línea idéntica
        repetida en 8.816 fichas no es atribución, es ruido que la gente
        aprende a no leer — y encima el crédito a RAÄ ya está en `Om appen` y
        el sheet ya linkea a Fornsök. La versión útil: la línea aparece
        **sólo cuando hay algo más que el registro**, y dice qué: "Bygger
        också på Wikipedia (CC BY-SA 4.0)" con el link a la fuente. Hoy son
        26 fichas; después de la regeneración, ~1.401
  - [ ] lo que hay que mover para que exista: `build_tiles.py` tiene que leer
        `generation_sources` JOIN `sources` y meter en el shard, por lugar,
        los `publisher`/`licence`/`licence_url`/`url` **distintos** de las
        fuentes no-registro. Es una columna más en `descriptions.<lang>.db`
        (JSON, como `size` y `period`), no una tabla nueva
  - [ ] **un lugar sin filas es "no lo sabemos", no "no tiene fuentes".** Son
        las 357 que el backfill no pudo establecer. No puede mostrar una
        línea que afirme nada; lo correcto es no mostrar nada, que es lo mismo
        que hace un lugar que sólo usa el registro — y por eso los dos casos
        conviven sin que haya que explicarlos
  - [ ] `basis` permite además no publicar lo no probado: si alguna vez se
        quiere ser estricto, la línea se deriva sólo de `basis IN ('payload',
        'hash')`. Hoy no cambia nada, porque las 26 salen todas de ahí
  - [ ] el `unresolved` de 7 lugares es la decisión que ya está tomada y
        escrita en `build_sources.py`: se usa, se atribuye con publisher y
        url, y si alguien pide que se baje, se baja. La línea del sheet es
        **la que hace posible esa promesa**, así que esos 7 son justamente
        los que más la necesitan
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

### `Glöm mig` no olvida en los otros teléfonos (review 2026-09-16)

**El bug.** `DELETE /api/fornlamningar/author` hace
`DELETE FROM fl_events WHERE author = $1`. Pero el log es append-only *para
los lectores*: todo teléfono que ya sincronizó tiene esas filas replicadas en
su `contributions.db` y su cursor está más adelante. Borrar en el servidor no
les manda nada, así que **los puntajes de la persona olvidada siguen en el
promedio de todos los demás para siempre**. El propio
`scripts/fornlamningar-events.sql` dice que una retractación es un evento; el
endpoint de borrado se saltó su propia regla. Para el derecho de borrado esto
es peor que no tener el botón: parece que borró y no borró.

**El fix: el borrado es un evento, y el borrado físico viene después.**

- [ ] **Servidor, `author/route.ts`.** Dentro de **una** transacción (`tx()`),
      en este orden:
      1. Tomar el número de secuencia igual que hace el POST de eventos
         (`UPDATE fl_event_seq SET v = v + 1 ... RETURNING v`).
      2. Insertar en `fl_events` una fila con `kind = 'author_erased'`,
         `author = <el que pide>`, `place_uuid = '*'` (no hay lugar; el CHECK
         no existe, pero poner un marcador explícito es mejor que un string
         vacío), `payload = '{}'`, y el `seq` obtenido.
      3. `DELETE FROM fl_events WHERE author = $1 AND kind <> 'author_erased'`.
      4. `DELETE FROM fl_account_devices WHERE device = $1`.
      El tombstone se queda: es la única fila de ese autor que sobrevive y no
      contiene nada más que el pseudónimo, que ya era público. Contar el
      `rowCount` del paso 3 para la respuesta, como ahora.
- [ ] **Servidor, `events/route.ts`.** Agregar `'author_erased'` a los kinds
      que el GET sirve (hoy sirve todo lo que hay, así que sale solo), y al
      `payloadSchemas` con `z.object({}).loose()` para que un cliente que lo
      mande por error reciba 400 igual que cualquier kind que no está en
      `ANONYMOUS_KINDS`. **No** agregarlo a `ANONYMOUS_KINDS`: sólo el
      servidor lo escribe.
- [ ] **App, `remote.ts` → `applyRemote`.** Un caso nuevo: si
      `e.kind === 'author_erased'`, ejecutar
      `DELETE FROM ratings/visits/signs/presence/comments/photos WHERE
      author = e.author` en la misma transacción que aplica el lote. `e.author`
      llega ya como pseudónimo, que es exactamente la clave con la que están
      guardadas las filas remotas. Después el cursor avanza como siempre.
- [ ] **App, `sync.ts` → `forgetMe`.** No cambia: sigue llamando al DELETE
      primero. Lo único nuevo es que la respuesta del servidor ahora es
      verdad.
- [ ] **Migrar lo ya borrado.** Los borrados hechos antes de este fix no
      tienen tombstone y no se pueden reconstruir (el autor ya no está).
      Como la app no está publicada y los únicos teléfonos son los de Franco,
      alcanza con reinstalar. Anotarlo acá para no buscarlo después.
- [ ] Probar como se probó lo demás: teléfono A puntúa, B sincroniza y ve el
      promedio, A hace `Glöm mig`, B sincroniza y el promedio desaparece.

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

### Comentarios del review de 2026-09-16

De acuerdo con el planteo, con una corrección: **dos de los cuatro ejemplos
motivadores son bugs, no cosas para loguear**. Loguearlos los haría visibles;
arreglarlos los hace desaparecer. Van acá como items propios porque el
logging es un proyecto y estos son tardes.

- [ ] **Bug: el `outbox` abandona filas para siempre y no lo dice.** En
      `sync.ts` `flush()` marca el lote entero como fallido ante cualquier
      4xx; `attempts` sube; a los 10, `pending()` (`contributions.ts:~1240`,
      `WHERE attempts < 10`) las deja de ver. Nadie las borra, nadie las
      muestra, y la persona cree que su puntaje está publicado.
      **Fix:** (1) un 4xx **no** es un fallo del lote: el servidor devuelve
      `event_id` en el 400 de payload y `kind` en el 403/400 de kind, así que
      marcar sólo esa fila y reintentar el resto en la siguiente vuelta;
      (2) una fila que llega a 10 intentos pasa a un estado terminal visible
      (`dead = 1`) y el menú muestra un contador "N contribuciones no se
      pudieron enviar" con un botón de reintentar que resetea `attempts`;
      (3) un 5xx o error de red no suma `attempts` — sólo los 4xx, porque
      sólo esos son culpa del payload. Recién con eso hecho, el log de la
      sección 8 recibe "fila muerta" como warning.
- [ ] **Bug: los singletons de base se envenenan.** `open()` en
      `contributions.ts` y `openFor()` en `descriptions.ts` cachean la
      promesa para siempre. Si `migrate` o el `PRAGMA` tiran una vez (disco
      lleno, una migración a medias en un teléfono viejo), **todo** lo que
      toca la base rechaza hasta reiniciar la app, sin mensaje. `pointsData.ts`
      ya lo hace bien: `cache.catch(() => { cache = null })`. Copiar ese patrón
      en los otros dos.
- [ ] **Bug: las migraciones 4 y 5 hacen `BEGIN … COMMIT` dentro de un
      `execAsync`.** Si una sentencia falla a mitad, expo-sqlite deja la
      transacción abierta en esa conexión y `user_version` no sube; el próximo
      arranque reintenta la misma migración con `visits_local` ya creada y
      `visits` ya borrada. Usar `withTransactionAsync` (que hace rollback
      solo) y escribir cada paso idempotente (`CREATE TABLE IF NOT EXISTS`,
      `DROP TABLE IF EXISTS`). Es lo que tiene que estar sano **antes** de que
      haya un teléfono que no sea el de Franco, porque una migración rota es
      irrecuperable a distancia.
- [ ] `remote.ts` abre una **segunda conexión** a `contributions.db` con
      `openDatabaseAsync` directo, saltándose el singleton, WAL y migrate.
      Funciona porque `pull()` casualmente llama a `getAuthorId()` antes.
      Importar `open()` y listo.
- [ ] `visit_day` se calcula en **hora local** para las visitas propias y en
      **UTC** para las remotas (`remote.ts` aplica `date(server_ts)`). La misma
      persona en dos teléfonos se dedup con dos calendarios distintos. El
      servidor no sabe la zona; mandar `visit_day` dentro del payload desde el
      teléfono y usar eso al aplicar.
- [ ] `refreshReminder()` pide el permiso de notificaciones **al pasar a
      background**. Android descarta o muestra el diálogo al volver sin
      contexto. Pedirlo sólo desde el switch de `Påminnelser`, que ya lo hace,
      y en `refreshReminder` sólo programar si el permiso *ya* está.

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

### El flujo que Franco describió (2026-09-16), y lo que implica

**Mantener apretado en el mapa → menú → "Agregar sitio".** La app le pide al
backend los lugares del **registro completo** más cercanos a ese punto (no
los 10.000 del mapa: justamente los que no están), se los muestra
simplificados — tipo, distancia, la primera línea de la descripción — y la
persona elige cuál es el que tiene delante. Al elegir, ese lugar queda
**verificado**: alguien estuvo ahí y lo encontró. En la siguiente
regeneración entra al top 10k, se le genera descripción y traducción, y
aparece en el mapa de todos.

Es mejor que "agregar un sitio libre" por tres razones, y conviene dejarlas
escritas:

- el 95% de las veces lo que la persona ve **ya está en el registro**, sólo
  que el score lo dejó afuera. Esto convierte un falso negativo en una
  etiqueta positiva con un toque, sin inventar entidades ni necesitar uuid
  propio del cliente
- la verificación es **la label que más falta**: alguien fue y lo encontró
  sin que la app lo mandara, así que no tiene el sesgo de selección de la
  sección 2. Entra a `labels` con `source='user_verified'`
- el caso "no está en el registro" queda como **último item de la lista**
  ("ninguno de estos"), que es el flujo original de reporte libre, y se
  vuelve raro en vez de ser el default

Lo que hace falta para eso:

- [ ] **el backend tiene que tener los 129k clusters con posición y tipo.**
      Hoy no tiene ninguno: Postgres sólo tiene `fl_events`. Es la misma
      necesidad que la sección 11 (snapshots servidos desde el backend) y la
      sección 12 (el conjunto de lugares como dato del servidor): una tabla
      `fl_places(cluster_id, lon, lat, family, class_sv, title, score)` que
      el pipeline **sube** en cada generación. Con PostGIS o con un índice
      sobre `(lon, lat)` redondeados alcanza para "los 10 más cercanos"
- [ ] `GET /api/fornlamningar/places/near?lon&lat&n=10` → lista simplificada
- [ ] el evento es `kind='verified'` sobre un `cluster_id` existente, así que
      **sí** entra en `fl_events`, a diferencia del sitio libre. Con cuenta,
      como todo lo que se escribe (decisión de la sección 2)
- [ ] `build_labels.py` lee los `verified` del servidor (o de un export del
      log) como positivos con `source='user_verified'`. Es la tercera fuente
      de labels después de Wikidata y el registro, y la única que mide lo que
      queremos medir
- [ ] **un verificado entra al top 10k por regla, no por score.** Si el modelo
      lo puntuó bajo y una persona lo encontró, la persona gana; el export
      fuerza `verified` adentro del corte igual que `excluded_hard` fuerza
      afuera. Si no, el toque del usuario no cambia nada visible y la feature
      se siente rota
- [ ] la posición del pin largo se guarda en el evento (`lon`, `lat`,
      `accuracy_m`) aunque haya elegido un lugar existente: es la segunda
      posición observada de ese lugar, y con varias se puede detectar el caso
      "la posición del registro está mal" sin preguntarlo

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

## 11. Un archivo por idioma, descargado on demand (investigado 2026-09-15)

La idea: un SQLite por idioma con **todo** lo que es texto de ese idioma
—strings de la interfaz, los 31 artículos del wiki con sus triggers, y las
descripciones de los lugares— y que la app baje el idioma cuando se elige en
vez de empaquetar todos.

Factible, unos **dos días de trabajo**. Medido antes de opinar, y la medición
cambia el argumento: **el ahorro de tamaño es 2 MB sobre 56**.

### Los números del APK (56,3 MB, build de 2026-09-15)

| parte | comprimido |
|---|---|
| `lib/arm64-v8a` (MapLibre, Hermes, RN) | **31,6 MB** |
| dex (4 archivos) | 10,2 MB |
| `res` (las dos bases + imágenes del wiki + iconos) | 9,1 MB |
| `assets` (bundle JS 3,3 MB) | 3,3 MB |

Las bases **se comprimen dentro del APK**: `descriptions.sv.db` 6,21 MB →
**2,05 MB**, `descriptions.en.db` 6,00 MB → **2,06 MB**. Los otros textos son
ruido al lado: 6,8 KB de strings por idioma y 124 KB de artículos. Las 3,1 MB
de imágenes del wiki son las mismas para todos los idiomas y no se mueven.

Total del idioma como concepto: **4,1 MB de 56,3 — el 7%**.

### Por qué el ahorro real es la mitad de eso

- [ ] **el sueco tiene que venir empaquetado.** Si no, lo primero que hace
      una app recién instalada es pedir 2 MB por red, y el caso de uso es
      alguien en el campo sin señal. Así que el esquema realista no es "la
      app no tiene ningún idioma" sino "el sueco viene, los demás se bajan",
      y el ahorro hoy es exactamente el inglés: **~2 MB**

### Por qué igual vale la pena, cuando toque

- [ ] **corregir una traducción no necesita un release.** Hoy una frase mal
      traducida se arregla publicando un APK. Con el idioma como archivo
      versionado se arregla y el próximo arranque lo trae. Aplica sobre todo
      a los artículos y a las descripciones, que son lo que más va a cambiar
- [ ] **cada idioma nuevo cuesta cero en el APK.** El tercero y el cuarto son
      gratis en vez de +2 MB cada uno
- [ ] el formato de descripción más rico que está diferido (resumen + cuerpo
      Markdown) multiplica el tamaño de las descripciones. Si eso llega, esto
      pasa de lindo a necesario

### El trabajo, en orden de dificultad

- [ ] **~1 día, lo difícil: los artículos dejan de ser código.**
      `src/wiki/articles.ts` son 943 líneas generadas que van en el bundle, y
      `linkify()` se llama **durante el render** con las tablas de triggers en
      memoria. Pasarlo a SQLite convierte algo sincrónico en asíncrono. Se
      resuelve cargando strings + triggers al arrancar (~130 KB, un
      parpadeo) y dejando sólo los cuerpos en consulta por id. `useLanguage`
      ya tiene el tercer estado `ready` para esperar eso
  - [ ] lo que **no** puede moverse: el mapa de `require()` de las 23
        imágenes y sus créditos. Metro no resuelve un `require` desde una
        variable, así que `articles.ts` se parte en dos — imágenes y créditos
        generados y empaquetados, texto en la base
- [ ] **~½ día, la descarga hecha en serio.** Un manifiesto
      (`{idioma: {url, bytes, sha256, version}}`), `createDownloadResumable`
      de expo-file-system, verificar el hash antes de aceptar el archivo,
      rename atómico, y no borrar el viejo hasta que el nuevo verifique. Más
      la UI: progreso en el diálogo de idioma, cancelar, reintentar, y qué
      pasa si se elige inglés sin señal (no se puede elegir, con un mensaje
      que lo diga). `ASSET_VERSION` cubre lo empaquetado; hay que extenderlo
      a lo descargado
- [ ] **~3 h, lo fácil: un solo generador.** Hoy hay tres productores de
      texto por idioma (`check-i18n.mjs` sobre los JSON, `build-wiki.mjs`
      sobre los `.md`, y `build_tiles.py` + `sync-assets.sh` para las
      descripciones). Se unifican en un script que emite `lang.<code>.db` con
      tres tablas, conservando la validación de claves y placeholders
- [ ] **dónde se sirven, que cuesta plata y es decisión de Franco.** Vercel
      cobra egress: 2 MB por descarga contra los 100 GB del plan son unas
      50.000 descargas por mes — cómodo hoy, pero escala con el éxito. R2 no
      cobra egress y ya estaba en el plan para las fotos

### Cómo le llegan las actualizaciones a quien ya tiene la app

Si una descripción se corrige, tiene que llegar a un teléfono que ya tiene su
copia local. Medido sobre `descriptions.sv.db` (9.558 filas): el texto útil
son **3,52 MB** (368 B de descripción en promedio, 131 KB de títulos), el
archivo pesa 6,21 MB y **2,05 MB** comprimido. El resto es índice y las
columnas `size`/`period`; la columna `raw` va vacía en lo que se envía.

Un delta de filas sueltas, comprimido:

| qué cambió | delta | vs bajar todo |
|---|---|---|
| 268 títulos (la corrección de 2026-09-15) | **50 KB** | 40× más barato |
| 1.000 descripciones | 180 KB | 11× |
| 6.500 (una regeneración grande) | **1,13 MB** | todavía menos que 2,05 MB |

- [ ] **las filas viajan, el archivo no — nunca.** Incluso si cambia la tabla
      entera, mandar las filas comprimidas (1,13 MB) es más barato que mandar
      el archivo (2,05 MB): el índice y el overhead de SQLite pesan más que
      el texto. Así que el `.db` prearmado del APK existe sólo para que la
      instalación sea instantánea y offline, y todo lo demás son filas
- [ ] **la forma es la que ya tiene el sync de contribuciones**: un log
      append-only y un cursor.
      `GET /api/fornlamningar/descriptions?lang=sv&since=<version>` →
      `{ version, rows, deleted }`, aplicado con `UPSERT` en **una
      transacción**, y la versión local avanza **después** del commit
- [ ] **la misma disciplina, por la misma razón**: una fila que el schema
      rechaza no puede abortar el lote, porque el cursor no avanza, el
      siguiente pull trae la misma ventana y falla igual — sync trabado para
      siempre. Ya nos pasó en producción con `signs.has_sign`
- [ ] **el dato de qué cambió ya existe**: `generated.sqlite` tiene
      `created_at`, `translated_at` y el `source_hash` con `payload_version`.
      No hay que inventar el versionado, hay que exponerlo

Las tres cosas que se rompen, y que son el trabajo real:

- [ ] **la base deja de ser un asset reemplazable y pasa a ser estado
      mutable.** Hoy se borra y se re-copia cuando cambia `ASSET_VERSION`, y
      eso es lo que la hace segura. Con deltas hay dos caminos de
      actualización que pueden pelearse, así que hace falta una regla
      explícita: **lo empaquetado es un piso** — si la base del APK es más
      nueva que la versión local, se re-copia y la cadena de deltas arranca
      de cero
- [ ] **las bajas.** Cuando se mueve el clustering hay lugares que
      desaparecen del export — ya pasó, 11 entre el export sueco y el
      inglés. El delta tiene que poder decir "este uuid ya no existe", y hay
      que decidir qué pasa con la valoración que alguien dejó ahí. Mi
      opinión: la valoración se queda, el evento es de la persona y no del
      export
- [ ] **quién sirve el endpoint.** Un archivo estático por versión no escala:
      con clientes en versiones arbitrarias son N² archivos de delta. Es un
      endpoint dinámico, y el backend ya tiene Postgres y `tx()`. Los 50 KB
      de un delta chico son irrelevantes para el egress; si algún día hay
      muchos usuarios, el escape es un snapshot completo por generación en R2

- [ ] **cuándo**: ~~no todavía~~ **decidido el 2026-09-16: se hace**, ver la
      revisión al final de esta sección. Sigue siendo cierto que trae consigo
      la sección 8: van a ser transacciones aplicándose en teléfonos que nadie
      puede ver, así que los logs van en el mismo paquete de trabajo

### La alternativa que ahorra casi todo el trabajo

- [ ] **decidir si hay Play Store antes de construir esto.** Play Asset
      Delivery hace exactamente esto sin manifiesto, sin servidor, sin
      verificación de hash y sin costo de egress: un AAB con un paquete por
      idioma y Google entrega el que corresponda on demand. Hoy no aplica
      porque se firma con el keystore de debug y el APK se distribuye a
      mano — pero si Play está en el horizonte, el mecanismo propio es
      trabajo que después se tira
- [x] ~~recomendación: no hacerlo todavía por el tamaño~~ — superada. El
      tamaño nunca fue el argumento; el argumento es el de la revisión de
      abajo, y con ese sí se hace

### Revisado el 2026-09-16: la pregunta cambió, y la respuesta también

Franco preguntó "¿por qué no hacerlo todavía?". La respuesta de arriba era
correcta para la pregunta de arriba — *ahorrar 2 MB no vale dos días*. Pero
el mismo día apareció otra pregunta, y esa sí lo justifica:

> No quiero que a los tres años de publicada, cada instalación nueva baje
> tres años de cambios y los aplique todos en el primer run. La base entera
> debería ir aplicando los cambios en el backend, y una instalación nueva
> baja una base fresca; después sólo actualizaciones.

Eso es exactamente el modelo correcto, y unifica tres cosas que este TODO
tenía separadas:

| qué | hoy | con el modelo de Franco |
|---|---|---|
| descripciones (sección 11) | en el APK, deltas por filas | snapshot por generación + deltas |
| lugares (sección 12) | en el APK, snapshot completo | el mismo snapshot |
| agregados de usuarios (sección 2) | cada teléfono rehace el log | el backend los materializa; snapshot + eventos desde su `seq` |

**El principio:** el backend es el dueño del estado actual; el log de
eventos y los deltas son cómo *viaja*, no cómo se *guarda*. Un teléfono
nuevo baja el estado, no la historia.

- [ ] **el APK lleva igual una base sueca**, por la razón de arriba: primer
      arranque offline en el campo. Pero esa base es un **piso** con número de
      generación, no la verdad. Al primer arranque con red, la app compara su
      generación con la del servidor y baja el snapshot si está atrás
- [ ] **un número de generación para todo** — lugares, descripciones por
      idioma, agregados. Sale de una corrida del pipeline. Es lo que la
      sección 12 ya pedía, extendido a los agregados
- [ ] **el snapshot es un SQLite por generación e idioma en R2**, prearmado
      por el pipeline. Los deltas (`since=<gen>`) son un endpoint dinámico
      sobre Postgres que devuelve filas. El corte entre "bajá el snapshot" y
      "aplicá deltas" lo decide el servidor: si `since` está a más de N
      generaciones, contesta `{snapshot_url}` en vez de filas. Así el cliente
      nunca aplica tres años de nada
- [ ] eso obliga a que **el pipeline suba a Postgres** en cada generación
      (`fl_places`, `fl_descriptions`), que es lo mismo que necesita el flujo
      de "agregar sitio" de la sección 9. Un `push_generation.py` al final
      de `run_pipeline.sh`
- [ ] Play Asset Delivery sigue siendo la alternativa **para el idioma**,
      pero no cubre ni los lugares ni los agregados ni las correcciones sin
      release. Con el modelo de Franco el mecanismo propio deja de ser
      "trabajo que después se tira": es el único que hace las tres cosas
- [ ] **decidido el 2026-09-16: se hace.** Es el siguiente proyecto grande.
      El orden dentro de él importa: primero los ids estables de la sección
      12 — sin eso, un snapshot nuevo huerfanea las contribuciones — y la
      decisión de cuentas de la sección 2 ya está tomada. Después el
      `push_generation.py`, después el endpoint de snapshot/delta, y la app al
      final, porque es lo único que no se puede probar sin lo anterior

---

## 12. Actualizar el conjunto de lugares (investigado 2026-09-15)

Hoy se mandan los 10.000 mejores por score. Con el tiempo va a haber lugares
que salgan (ruido que se filtró) y lugares que entren (falsos negativos), así
que el conjunto tiene que poder actualizarse en un teléfono ya instalado.

### Acá el delta es la forma equivocada, al revés que en la sección 11

`points.geojson`: 10.000 lugares, 2,48 MB en crudo, **480 KB comprimido**
(248 B por lugar). Un delta de 2.000 lugares son 100 KB — o sea que el
archivo completo ya es más chico que el delta más grande de descripciones.

Pero el motivo de fondo no es el tamaño. Una descripción es **local a su
fila**: función de las fuentes de ese lugar y de nada más. Un lugar no. Cada
feature lleva `score`, `stars` y `minzoom`, y los tres se calculan **sobre el
conjunto entero**:

- `score` es un percentil, así que depende de cuántos y cuáles hay
- `stars` es un bucket de ese percentil
- `minzoom` sale de la caminata greedy best-first sobre los 10.000

Agregar o quitar un lugar cambia los valores **de los otros**. Un delta
tendría que traer las filas recalculadas, que potencialmente son todas.

- [ ] **snapshot versionado, el archivo completo, 480 KB.** No deltas. Es la
      conclusión opuesta a la de las descripciones y por un motivo con
      nombre: aquello es row-local, esto se calcula en conjunto
- [ ] **se versionan juntos con las descripciones.** Los dos salen del mismo
      export; si uno se actualiza y el otro no, hay un marcador sin
      descripción o una descripción sin marcador. **Un solo número de
      generación para los dos**, no dos versiones independientes
- [ ] **un lugar que se va no se lleva los datos de la gente.** Misma regla
      que las bajas de la sección 11: la valoración, la visita y la
      respuesta son de la persona, no del export. `visitedPlaces()` cruza
      contribuciones con descripciones, así que hay que verificar que siga
      mostrando un lugar que dejó de estar en el mapa

### Decidido: no se muestran todos, a ningún zoom

Sobreviven 128.951 clusters, y mandarlos todos son 36,6 MB en crudo pero
**5,5 MB comprimido** — el mismo orden que una base de descripciones. Eso
haría que un falso negativo ya estuviera en el mapa y no hiciera falta
actualizar nada.

- [x] **descartado, y no por el tamaño**: la mayoría de esos puntos son
      ruido, y el ruido no se muestra **por más que se haga mucho zoom**.
      Decisión de Franco, 2026-09-15. El corte se queda
- [ ] tenerlos en el build sin mostrarlos **no simplifica lo suficiente**.
      Mediría: ahorraría mandar la geometría de un lugar que asciende, pero
      `score`/`stars`/`minzoom` se siguen recalculando en conjunto, así que
      la actualización existe igual — y el snapshot completo son 480 KB de
      todas formas. A cambio habría que parsear 128.951 features en el
      teléfono para descartar la mayoría. Mala relación: se paga RAM para
      abaratar una actualización que ya es barata
- [ ] lo que **sí** queda de esto: el corte en 10.000 es un número puesto a
      mano. Si un falso negativo aparece seguido, el problema no es el
      mecanismo de actualización sino el score, y ahí la respuesta es
      `build_scores.py`, no la red

### La mitad que faltaba: un lugar no sólo entra o sale, puede cambiar de id (review 2026-09-16)

Todo lo caro cuelga de `cluster_id`: las 13 horas de `generated.sqlite`, las
filas de `places.sqlite`, `lansstyrelsen.matches.cluster_id`, y **cada
puntaje, visita y respuesta de cada usuario**, en el teléfono y en Postgres.
Si el id de un lugar cambia entre dos generaciones, todo eso queda huérfano
sin un solo error. Ya pasó una vez: `generated.sqlite` tiene hoy **95
descripciones con prefijo `sp:`** del método espacial que se eliminó, y nada
las detecta.

**Franco preguntó si debería haber clusters en absoluto.** Medido antes de
opinar, sobre `work.clusters`:

| tipo de id | cuántos | estable? |
|---|---|---|
| `one:<uuid>` (sitio suelto) | 212.397 | **sí** — es el uuid del registro |
| `raa:<parish>:<group>` (grupo RAÄ) | 38.473 | **sí** — sale de datos del registro |
| `raa:<parish>:<group>#<idx>` (grupo partido por la guarda espacial) | **159** | **no** — `idx` es el orden de un `SELECT` sin `ORDER BY` |

O sea: **el 99,94% de los ids ya son estables** y el problema son 159
clusters más una limpieza única. Los clusters sí deben existir — un gravfält
de 160 tumbas es un destino, y `raa_group` es el condado diciendo "estas
fichas son un monumento", que fue la medición que mató el clustering
espacial. Lo que hay que arreglar es cómo se numeran los pedazos cuando un
grupo se parte, no la idea.

- [ ] **`#idx` determinístico.** En `build_clusters.py`, en vez de
      `roots.setdefault(root, len(roots))`, ordenar los sub-clusters por el
      **menor uuid de sus miembros** y numerarlos en ese orden. Mejor todavía:
      usar ese uuid como sufijo (`raa:1384:268#eddd2aa1`), así el id de un
      pedazo no depende ni siquiera de cuántos pedazos hay. Un sitio que se
      mueve de pedazo cambia de cluster, lo cual es correcto; los demás no se
      enteran
- [ ] **`ORDER BY uuid` en el `SELECT` de `sites`** que alimenta al
      clustering, para que ninguna otra cosa dependa del orden físico de la
      tabla
- [ ] **limpieza única:** borrar las 95 filas `sp:%` de `generated.sqlite`,
      y agregarle a `build_descriptions.py --status` un conteo de
      "`cluster_id` en `generated` que no existe en `work.clusters`". Ese
      número tiene que ser cero después de cada `run_pipeline.sh`, y si no lo
      es, es la alarma de que algo renombró clusters
- [ ] **la única fuente de inestabilidad que queda es el registro mismo**: si
      RAÄ cambia el `raa_group` o el `parish_code` de una ficha (pasa, poco),
      el cluster cambia. Para eso, el export lleva una tabla `redirects(old_id,
      new_id)` calculada comparando la generación anterior con la nueva por
      **intersección de miembros**: si el 100% de los uuids del cluster viejo
      están en un cluster nuevo, es un rename. La app aplica los redirects a
      `contributions.db` al actualizar; el servidor los aplica al leer.
      Construirlo cuando haya un caso real, no antes — pero el dato que lo
      hace posible (`site_clusters` de la generación anterior) hay que
      **guardarlo** desde ahora, y hoy se hace `DROP TABLE`
- [ ] con eso, la regla de esta sección queda completa: un lugar que **sale**
      conserva las contribuciones (ya decidido), un lugar que **cambia de id**
      las hereda por redirect, y un lugar que **entra** no tiene ninguna


---

## 13. Higiene: lo que el review de 2026-09-16 encontró desfasado

Nada de esto es diseño. Es el costo de que el proyecto haya crecido tres
capas (fuentes, lugares, traducciones, backend) mientras el runner, los docs
y algunos scripts se quedaron en la versión de hace un mes. Cada item es
chico; juntos son la diferencia entre un repo que otro agente puede tocar y
uno que no.

### Pipeline

- [ ] **`run_pipeline.sh` no construye el producto.** Corre stages 1–6 pero
      no `build_sources.py`, `build_places.py`, `crawl_lansstyrelsen.py
      --join` ni `crawl_wikimedia.py`. `places.sqlite` — "lo que estamos
      construyendo" según `paths.py` — no lo genera nada del runner. Y
      `build_labels.py` y `build_sources.py` leen `lansstyrelsen.matches.
      cluster_id`, que sólo se actualiza con el `--join` manual: un rebuild
      que mueva clusters usa un mapping viejo sin avisar.
      **Fix:** agregar al runner, después de `2:cluster`, un stage
      `crawl_lansstyrelsen.py --join` (es sólo el join, no el crawl), y
      después de `5:score` los stages `build_sources.py` y `build_places.py`.
      Los crawls (`crawl_wikimedia.py`, `crawl_lansstyrelsen.py` sin `--join`)
      quedan afuera como el de K-samsök: son RAW, se corren a mano
- [ ] **`describe_place.load_sources` devuelve `[]` en silencio si
      `places.sqlite` no existe**, y hashea ese payload degradado como válido.
      Tiene que fallar. Con el runner arreglado el archivo siempre está, pero
      un `sys.exit("places.sqlite missing: run build_sources.py first")` es
      lo que convierte un dato silenciosamente peor en un error
- [ ] **`generated.sqlite` en LFS con WAL abierto.** Está en `journal_mode=
      WAL` (`build_descriptions.open_out`), así que después de una sesión de
      generación el `-wal` tiene filas que el archivo principal no tiene, y
      `git add` commitea sólo el principal. Hoy el `-wal` (1 MB) es más nuevo
      que el `.sqlite`. **Fix fácil:** al salir de `build_descriptions.py`
      (incluido el SIGINT) ejecutar `PRAGMA wal_checkpoint(TRUNCATE)`. Y un
      check en `--status` que avise si el `-wal` tiene tamaño > 0
- [ ] **archivos muertos en `src/data/`**, de bases que ya no existen:
      `sites.sqlite-wal` (48 MB) y `-shm`, `descriptions.sqlite-wal`/`-shm`,
      `ksamsok_raw.sqlite-wal`/`-shm`. Y la tabla `scores_old` en
      `work.sqlite` (245.860 filas, nada la lee). Borrar. No hay nada que
      recuperar: un WAL sin su base principal es basura
- [ ] **`dims.py:202` abre `src/data/sites.sqlite`**, que no existe. Usar
      `paths.WORK`. Nueve docstrings más nombran `sites.sqlite`,
      `ksamsok_raw.sqlite`, `fornlamningar_full.gpkg` o `descriptions.sqlite`
      (`build_sites.py`, `build_clusters.py`, `build_labels.py`,
      `build_signals.py`, `build_scores.py`, `build_descriptions.py`,
      `describe_place.py`, `build_tiles.py`). Buscar y reemplazar por los
      nombres de `paths.py`
- [ ] `paths.TILES` y `paths.APP_DATA` **no los usa nadie**; `build_tiles.py`
      duplica la ruta como `DEFAULT_OUT`. Usar `paths` o borrarlos
- [ ] `run_pipeline.sh` nunca pasa `--keep-geojson`, pero `sync-assets.sh`
      de la app **exige** `tiles_input.geojsonl`. Una corrida limpia borra el
      archivo que el build de la app necesita. Que el runner lo pase siempre
- [ ] **`dominant_class` con dos reglas.** `build_clusters.py` elige el
      miembro representativo con `families.representative_order`; `build_
      signals.py` elige la clase con `class_significance`. `build_tiles` usa
      la primera y `build_scores` la segunda, así que el ícono del mapa y el
      score de un cluster pueden hablar de clases distintas.
      **Fix:** `build_signals.py` no calcula clase. Lee
      `clusters.dominant_class` con un JOIN y punto. Si `class_significance`
      tiene algo que `representative_order` no (peso por "importancia" además
      de por representatividad), se fusiona en `families.py`, que es el único
      lugar donde puede vivir una regla sobre clases. Una regla, un archivo
- [ ] **`clusters.name` es `MAX(s.title)`**: en un cluster de varios sitios el
      nombre popular es el que ordena último alfabéticamente. Franco preguntó
      si el título debería generarlo el modelo — **ya lo hace**: `describe_
      place` emite `{title, content}` y `ai_descriptions.title` existe. Lo que
      está mal es la *otra* columna, `name`, que es el nombre popular del
      registro y sirve de fallback y de label del mapa. **Fix:** tomar el
      `title` del **miembro representativo** (el mismo que da `uuid` y
      `dominant_class`), no el `MAX`. Y es el mismo item que "colapsar `name`
      y `title`" de abajo: una sola columna `title`, generada cuando hay
      descripción, del representativo cuando no
- [ ] **inglés a medias en las fuentes.** `sources.lang` existe pero
      `load_sources` no filtra por él, así que leads de Wikipedia en inglés
      entran a un prompt que pide sueco. Y `ai_descriptions` guarda el inglés
      como columnas `title_en`/`content_en`: un tercer idioma es una
      migración de schema y cinco scripts.
      **Fix en dos pasos, el primero hoy:** (1) `load_sources(cluster_id,
      lang)` filtra `lang IN (?, NULL)` — el sueco genera con fuentes suecas
      y sin idioma; la traducción al inglés puede recibir las inglesas como
      contexto *adicional* (nombres propios, terminología) pero no como
      fuente, porque la traducción es del texto sueco y no una regeneración.
      (2) Cuando haya tercer idioma, mover las traducciones a
      `translations(cluster_id, lang, title, content, translated_at, model,
      source_hash)` y dejar `ai_descriptions` sólo con el sueco canónico. No
      antes: hoy es un rename sin beneficio
- [ ] **`places.sqlite` pesa 815 MB sin motivo.** El UNIQUE de `sources`
      incluye `text` entero, así que el índice (297 MB) es más grande que la
      tabla (244 MB). **Fix:** columna `text_sha TEXT` (sha1 del texto) y
      `UNIQUE (cluster_id, kind, lang, url, text_sha)`. Baja a ~500 MB.
      Después `VACUUM`, que nunca se corrió. Ver también la nota sobre qué es
      `places.sqlite` más abajo
- [ ] `build_places.py` y `build_sources.py` hacen `INSERT OR REPLACE` /
      `INSERT OR IGNORE` y **nunca borran**: un cluster que desaparece de
      `work` queda en `places.sqlite` para siempre, y un texto del registro
      que RAÄ corrigió queda al lado del nuevo y los dos van al modelo. Con
      los ids estables de la sección 12, agregar un `DELETE ... WHERE
      cluster_id NOT IN (SELECT cluster_id FROM work.clusters)` al final de
      cada uno
- [ ] `build_labels.py` joinea `hand_labels.csv` por `lamningsnummer`, que
      **no es único** en `sites`. Una etiqueta puede abrirse en varios uuids
      y `n_hand` cuenta el abanico. Joinear por uuid, o dedup por cluster
- [ ] `build_signals.py` y `build_scores.py` tienen `print()` en castellano
      en medio de código en inglés. Cosmético, pero delata pegado de otra
      sesión
- [ ] **README.md y PIPELINE.md describen otro proyecto.** README dice que la
      app es Next.js en `franco-may`, lista seis stages y una base que se
      llama `sites.sqlite`. PIPELINE.md tiene un "Stage 7 — Frontend" que
      describe la web. Ninguno menciona `build_sources`, `build_places`,
      `describe_place`, `generated.sqlite`, `places.sqlite` ni la app RN.
      **Qué hacer:** README se reescribe corto — los tiers de `paths.py`, la
      tabla de stages real (con los que faltan en el runner), y un link a la
      app. PIPELINE.md **no se reescribe**: es el registro de qué se midió y
      qué hipótesis murieron, y eso sigue siendo verdad. Se le agrega arriba
      una nota "el pipeline descrito acá llega hasta `scores`; lo que viene
      después (fuentes, lugares, descripciones, app) está en README y en este
      TODO" y se borra la parte de Stage 7 que habla de la web como producto

### App

- [ ] **dos lockfiles** (`package-lock.json` y `yarn.lock`). `build-licences.
      mjs` dice "run yarn install", así que gana yarn: borrar `package-lock.
      json` y agregarlo al `.gitignore`
- [ ] **`versionCode` no existe en `app.json`**: cada prebuild sale con
      versionCode 1, y la segunda subida a Play se rechaza. Agregar
      `android.versionCode` y **subirlo en cada release** — o mejor, que
      `sync-assets.sh` lo derive del número de generación del export, así el
      APK y sus datos tienen un solo número (es lo que la sección 11 pide de
      todas formas)
- [ ] **iOS no compila** y el README dice `npx expo run:ios`. Los plugins de
      Firebase y Google Sign-In están en `app.json` pero no hay
      `GoogleService-Info.plist`. Como iOS está diferido a propósito (sección
      2), lo honesto es que el README lo diga y sacar la línea
- [ ] README dice "sin cuentas" y "`descriptions.db`, 10 MB"; AGENTS.md dice
      "sin bottom-sheet library" y "sin icon font". Las cuatro son falsas.
      Comentarios stale: `App.tsx` ("no-op hasta que endpoint.ts apunte a un
      server"), `LocateButton.tsx` ("la app no tiene gesture-handler"),
      `i18n/index.ts` y `LanguageDialog.tsx` ("las descripciones son sólo en
      sueco"). Un agente que lea eso construye la app equivocada
- [ ] el build de Android deja recursos generados viejos: al renombrar
      `descriptions.db` a `descriptions.sv.db`, el APK salió con las dos y
      6 MB de peso muerto. `assembleRelease` no limpia
      `android/app/build/generated/res/react/release/raw`
- [ ] `check-i18n.mjs` no detecta **claves duplicadas** en un mismo archivo.
      `sv.json` tenía `common.cancel` dos veces (mismo valor, así que no hizo
      daño); si los valores hubieran diferido, el que gana es el último y
      nada lo avisa
- [ ] `src/data/descriptionAssets.ts` lo genera `sync-assets.sh` y está
      trackeado; los otros cuatro generados están ignorados. Ignorarlo también
- [ ] filtros en `AsyncStorage`, idioma y recordatorios en `settings` de
      SQLite: dos stores de preferencias. Mover los filtros a `settings`

### Qué es `places.sqlite`, y si se desvía de la visión

Franco describió la visión: una tabla `places` (raa_id, posición, tipo,
cartel, si los usuarios lo encuentran…) y una tabla `sources` (raa_id,
atribución, contenido, timestamp…). **`places.sqlite` es exactamente eso**:
`features` es `places` (una fila por cluster con lon/lat, clase, familia,
título, descripción, cartel, estacionamiento, score, provenance), `sources`
es `sources` (por cluster: kind, lang, texto, autor, publisher, licencia, url,
fetched_at), más `images` y `generation_sources`. No va al build: es el tier
PRODUCT; lo que va al teléfono es el tier PAYLOAD que `build_tiles.py` emite.

Las desviaciones son dos, y ninguna es de forma:

- **`build_tiles.py` no lo lee.** Recalcula títulos, dimensiones y
  descripciones desde `work` + `generated` + `wikimedia`. Así que hoy el
  producto es un archivo que nada consume, y el export sale de tres bases
  intermedias. El pendiente "`build_tiles.py` leyendo de `places.sqlite`" de
  abajo es lo que cierra esto, y con eso `places.sqlite` pasa a ser la única
  cosa que hay que subir al backend en la sección 11
- **`sources` es en un 97% el registro copiado.** 325k de 335k filas son
  `register`, `register_parts` y `register_vegetation`: el `beskrivning` de
  RAÄ que ya está en `work.sites`, ahora con columna de licencia. Es
  defendible (una fuente es una fuente, y la licencia del registro también
  hay que declararla), pero es lo que hace que el archivo pese lo que pesa.
  Con el `text_sha` de arriba el costo baja a la mitad y deja de importar

Respuesta corta: **no es una desviación, es la visión sin terminar de
conectar.** Lo que falta es que sea la fuente del export.

---

## Pendientes viejos, de antes de hoy

Con comentarios del review de 2026-09-16 en cursiva.

- [ ] colapsar `name` y `title` en una columna (`titles.py` ya está; falta el
      rename de schema en `build_places.py` y `build_tiles.py`).
      *Subirlo: es el mismo fix que el `MAX(s.title)` de la sección 13, y con
      él desaparece la pregunta de "¿de qué miembro es este nombre?"*
- [ ] `build_tiles.py` leyendo de `places.sqlite`, no de `work.sqlite` +
      `generated.sqlite`. Nada lo bloquea ya.
      *Subirlo también: es lo que convierte a `places.sqlite` en el producto
      que `paths.py` dice que es, y es el prerequisito de subir una sola base
      al backend (sección 11). Hoy `build_tiles` es un segundo `build_places`
      con reglas propias*
- [ ] 19,3% de las descripciones con más de una medida. Dos iteraciones del
      prompt no movieron nada; queda post-procesar la prosa o un segundo pase.
      *Coincido con el post-proceso. Un modelo local de 8B no va a obedecer
      "una medida" de forma confiable, y `describe_place.check()` ya sabe
      encontrar números en la prosa: es el lugar natural para un pase que
      deje sólo la primera medida y mande el resto a `size`*
- [ ] el APK instalado es de antes del cambio de clustering.
      *Es exactamente el caso donde hoy se pierden contribuciones por uuid
      huérfano (sección 12). Antes de reinstalar, exportar `contributions.db`
      del teléfono y contar cuántas filas apuntan a `cluster_id` que ya no
      existen: es la primera medición real del problema*
- [ ] ~55% de los objetos `fornvard` no matchean con nada.
      *Probablemente muchos son polígonos grandes (áreas de fornvård) que
      contienen varios clusters; un match por contención en vez de por
      distancia al centroide podría recuperar una parte. Medir antes*
- [ ] regenerar descripciones de los que entraron/salieron del top 10k
      (2.374 con texto ya afuera, 3.526 adentro sin texto).
      *Los 2.374 de afuera no hay que tocarlos: texto ya generado es texto que
      va a servir cuando vuelvan a entrar, y borrarlo es tirar horas de
      modelo. Sólo los 3.526 de adentro. Y con el modelo de la sección 11 este
      item deja de ser un evento y pasa a ser lo que hace el pipeline en cada
      generación*
