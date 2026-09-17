# TODO

Lo que falta hacer. **Un item se borra de acá cuando está en `main`**, no
cuando funciona en mi máquina — y se borra de verdad: el registro de lo hecho
sale del `git log`, y el razonamiento de cada cosa construida vive en el
comentario del archivo que la implementa, que es un mejor lugar porque no
puede desfasarse de él. Lo único que sobrevive a estar hecho son las
decisiones y los hallazgos que no se leen en un solo lugar del código, y ésos
están al final, en *Decisiones tomadas*.

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

- [ ] `Grov skada` (987) es la señal más débil de las tres: dañado de
      gravedad todavía puede ser perfectamente visitable — un röse excavado
      se sigue viendo. Candidato a label negativa con peso bajo, no a
      exclusión, y hay que decidirlo aparte
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

- [ ] lo que **no** se reparó es el servidor: el duplicado local que la
      migración descartó ya estaba posteado, así que el log tiene dos visitas
      de un autor para un lugar en un día. Hoy no le molesta a nadie, pero es
      la razón por la que contar visitas, cuando llegue, tiene que deduplicar
      al leer y no confiar en la regla del cliente
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
  - **hecho**: una base por idioma, `descriptions.<lang>.db`, y cada
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
**Hecho 2026-09-16** (`87cbec1` en franco-may, deployado; `1f602b5` en la app).
Una diferencia con el plan de abajo: los tres pasos van en **una** transacción
y no en statements independientes. El argumento viejo era que un borrado a
medias es mejor que uno rechazado, y eso vale mientras todos los pasos sean
borrados; deja de valer en el momento en que uno es una **publicación**.

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

- [ ] el 1★ verificado usa `visited` (GPS). Un visitante **declarado** que
      puntúa 1★ no cuenta para la advertencia. Decidir si la presencia
      declarada alcanza, ahora que el gate la pide
- [ ] los skips **se miden**: una pregunta que todos saltean es una pregunta
      mal escrita, y eso sólo se ve si el skip se cuenta. Empieza como tabla
      local; sincronizarlo necesita un `kind` nuevo en el servidor
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

### Decidido el 2026-09-17: el picker queda para despues, y el reporte es texto

Se construyo y se revirtio, y el motivo vale mas que el codigo. `fl_places` en
Postgres (163.701 filas, 49 MB) y `POST /places/near` tenian **un solo
lector**: la lista de "cual de estos estas viendo". Franco dejo la feature para
mas adelante, y mientras tanto **agregar un sitio manda lo que la persona
escriba mas la posicion, y lo lee un humano**. Con este trafico eso es mas
barato que cualquier otra cosa.

Y estaba en el lugar equivocado igual. El picker corre cuando alguien esta
parado en un campo sin senal, que es exactamente donde un endpoint no tiene
respuesta. Medido, para cuando vuelva: el registro entero no excluido como
SQLite local son **9,9 MB de archivo — 4,0 MB comprimido en el APK sin el
blurb, 12,0 MB con el**. O sea que la version offline de esto cuesta ~7% del
APK y ninguna base de datos. Franco ya lo habia autorizado: "podria aceptar
que esten todas en el build, si eso simplifica algo, pero no mostrarlas
todas".

Lo que deja en claro, y aplica a las secciones 11 y 12: **Postgres se queda con
el log de cambios y nada mas** — escritores concurrentes, orden garantizado,
append. Los datos derivados y masivos son archivos versionados en el CDN, como
los tiles ya son. Un snapshot es un archivo, y un archivo no necesita base.

No quedo nada de infraestructura: se probo un Postgres local en Docker y se
saco el mismo dia. El telefono habla con `https://franco-may.com` — la URL
esta escrita en `src/data/endpoint.ts` — asi que nada de lo que Franco hace
habria llegado nunca a un contenedor, y probar contra produccion es la unica
forma de probar lo que va a pasar de verdad. **Todo contra produccion.**

Lo que hace falta cuando se retome, en vez de la lista de arriba:

- [ ] `nearby.db` local (4 MB) en vez de un endpoint, para que el picker
      funcione sin senal
- [ ] el `verified` sigue yendo por `fl_events`, que es el camino correcto y
      ya existe

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

- [x] **`run_pipeline.sh` no construye el producto.** Corre stages 1–6 pero
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
- [x] **`describe_place.load_sources` devuelve `[]` en silencio si
      `places.sqlite` no existe**, y hashea ese payload degradado como válido.
      Tiene que fallar. Con el runner arreglado el archivo siempre está, pero
      un `sys.exit("places.sqlite missing: run build_sources.py first")` es
      lo que convierte un dato silenciosamente peor en un error
- [x] **`generated.sqlite` en LFS con WAL abierto.** El fix propuesto acá
      (checkpoint al salir) era innecesario: medido, el `close()` de sqlite3
      ya trunca el WAL y borra el archivo. Lo que deja un WAL huérfano es una
      salida que nunca llega al `close()` — un SIGKILL, la laptop que se
      duerme — y ahí no corre código nuestro. Asi que el fix es **avisar**:
      `build_descriptions.py --status` reporta un `-wal` no vacío antes de
      abrir la base, porque abrirla es lo que lo reabsorbe. Verificado
      matando un writer con SIGKILL: 5.191.232 bytes reportados y 20.000
      filas recuperadas
- [ ] **archivos muertos en `src/data/`** — *bloqueado: el clasificador de
      permisos no me deja borrar archivos. Es un comando de una linea, esta
      en el mensaje del 2026-09-17.* De bases que ya no existen:
      `sites.sqlite-wal` (48 MB) y `-shm`, `descriptions.sqlite-wal`/`-shm`,
      `ksamsok_raw.sqlite-wal`/`-shm`. Y la tabla `scores_old` en
      `work.sqlite` (245.860 filas, nada la lee). Borrar. No hay nada que
      recuperar: un WAL sin su base principal es basura
- [x] **`dims.py:202` abre `src/data/sites.sqlite`**, que no existe. Usar
      `paths.WORK`. Nueve docstrings más nombran `sites.sqlite`,
      `ksamsok_raw.sqlite`, `fornlamningar_full.gpkg` o `descriptions.sqlite`
      (`build_sites.py`, `build_clusters.py`, `build_labels.py`,
      `build_signals.py`, `build_scores.py`, `build_descriptions.py`,
      `describe_place.py`, `build_tiles.py`). Buscar y reemplazar por los
      nombres de `paths.py`
- [x] `paths.TILES` y `paths.APP_DATA` **no los usa nadie**; `build_tiles.py`
      duplica la ruta como `DEFAULT_OUT`. Usar `paths` o borrarlos
- [x] `run_pipeline.sh` nunca pasa `--keep-geojson`, pero `sync-assets.sh`
      de la app **exige** `tiles_input.geojsonl`. Una corrida limpia borra el
      archivo que el build de la app necesita. Que el runner lo pase siempre
- [x] **`dominant_class` con dos reglas.** `build_clusters.py` elige el
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
- [x] **`places.sqlite` pesa 815 MB sin motivo.** El UNIQUE de `sources`
      incluye `text` entero, así que el índice (297 MB) es más grande que la
      tabla (244 MB). **Fix:** columna `text_sha TEXT` (sha1 del texto) y
      `UNIQUE (cluster_id, kind, lang, url, text_sha)`. Baja a ~500 MB.
      Después `VACUUM`, que nunca se corrió. Ver también la nota sobre qué es
      `places.sqlite` más abajo.
      **Hecho 2026-09-17: 781 MB → 476 MB**, con un `row_sha` de las cinco
      columnas juntas en vez de una por columna — el índice pasó de 298 MB a
      16 MB. Y deduplica **más** que el viejo: en SQLite un NULL nunca es
      igual a otro NULL, así que el `UNIQUE` anterior dejaba pasar 2.564
      filas duplicadas con `url` NULL, que iban al modelo dos veces.
      Migrado en el lugar para no perder `first_seen_at`
- [x] `build_places.py` y `build_sources.py` hacen `INSERT OR REPLACE` /
      `INSERT OR IGNORE` y **nunca borran**: un cluster que desaparece de
      `work` queda en `places.sqlite` para siempre, y un texto del registro
      que RAÄ corrigió queda al lado del nuevo y los dos van al modelo. Con
      los ids estables de la sección 12, agregar un `DELETE ... WHERE
      cluster_id NOT IN (SELECT cluster_id FROM work.clusters)` al final de
      cada uno
- [ ] `build_labels.py` joinea `hand_labels.csv` por `lamningsnummer`, que
      **no es único** en `sites`. Una etiqueta puede abrirse en varios uuids
      y `n_hand` cuenta el abanico. Joinear por uuid, o dedup por cluster
- [x] `build_signals.py` y `build_scores.py` tienen `print()` en castellano
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

## 14. El rescate por proximidad mide urbanidad, no mérito (hallazgo 2026-09-16)

Salió de una pregunta de Franco: "hay muchos kulturlager en los tiles, ¿no
deberían estar excluidos como clase?". La clase se llama **`Stadslager`** (107
en el export; algunos títulos generados dicen "Kulturlager", que es la palabra
del modelo para lo mismo).

### Lo que la clase es, medido

Por el lenguaje del propio registro, de los 107 en el export:

| | |
|---|---|
| sólo lenguaje de excavación (`påträffats`, `undersökning`, `under markytan`) | **55** |
| ni una cosa ni la otra (vago) | 29 |
| algo visible (`husgrund`, `ruin`, `stengata`, `kullersten`) | 19 |
| sin texto | 4 |

Así que ~80% es ruido: "Kulturlager med sot, tegel och keramik har
påträffats, och en kritpipa daterades till 1620-40" no es un lugar para
visitar, es el informe de una excavación.

- [ ] **pero la clase no es homogénea**, y ahí está el problema con excluirla
      de una: `Sala gruvby` es Stadslager y tiene "över 200 bebyggelselämningar"
      con husgrunder, härdar y brunnar. Es un pueblo minero abandonado, o sea
      exactamente un lugar para ir a caminar

### Y excluirla no alcanzaría, por el motivo equivocado

`build_scores` ya fundió las dos listas en **una** regla: excluido por clase,
**rescatado por evidencia del sitio** (`has_name`, `sitelinks`, `has_image`,
una página de länsstyrelsen sobre él, o estar a ≤500 m de una). Así que Sala
gruvby sobreviviría por su nombre — bien. Pero:

- [ ] de los 126 clusters Stadslager, **72 se rescatarían y 54 de esos 72 es
      por `dist_to_board_m <= 500`**. Y esa condición está **confundida** para
      esta clase: el 45% de los Stadslager están a ≤500 m de una recomendación
      de länsstyrelsen, contra el **5,4% de todos los clusters** — 8× más.
      Mediana 606 m contra 2.936 m. No es mérito: un stadslager **es** el
      centro de una ciudad, y ahí es donde länsstyrelsen pone sus
      recomendaciones (una iglesia, una ruina, un museo). `Boplats`, que ya
      está excluida, está en el 5,0%: el sesgo es de las clases urbanas

### El hallazgo que importa, que no es de esta clase

- [ ] **2.845 clusters de clase excluida están en el export sólo porque hay
      otra cosa a menos de 500 m** — casi tantos como los 2.895 rescatados por
      evidencia real. Los peores: **1.193 `Stensättning`** y **841 `Boplats`**
- [ ] **la versión exacta de esa condición ya existe**: 3.263 clusters tienen
      una página de länsstyrelsen **sobre ellos** (`labels` con
      `source='county'`), y eso ya es una condición de rescate aparte. De los
      8.294 que están a ≤500 m de una, sólo 288 tienen además la propia: o sea
      que el radio de 500 m aporta **8.006 casos en los que el board estaba
      hablando de otra cosa**
- [ ] el comentario que justifica la condición dice que una recomendación de
      länsstyrelsen "es la única de estas que es un humano diciendo *vayan
      acá*". Eso es cierto de la página propia y **falso** de la proximidad:
      estar a 400 m de un cartel sobre una iglesia no es nadie diciendo nada
      sobre el boplats invisible de al lado

### Propuesta, en orden de importancia

- [x] **sacado `dist_to_board_m <= 500` como condición de rescate** (hecho
      2026-09-16, `e6fa057`). Removido y **no** achicado, que era la otra
      opción: a 50 m todavía rescata 76 clusters, y ésos son justamente los
      que el condado distinguió de su vecino, así que un radio chico estaría
      contradiciendo al juicio al que la condición existe para deferir —
      además de dejar una constante que nadie puede justificar después.
      Ningún radio es defendible, así que no hay radio.
  - [x] el argumento que lo decide es interno: `build_clusters` agrupa por
        **grupo RAÄ y no por proximidad**, porque *"grouping by proximity is
        us guessing"* — su pase espacial se eliminó después de medir que
        encadenaba 535 sitios en seis kilómetros. El spread medio de un
        cluster es 45 m. Dos clusters a 300 m son dos monumentos que **el
        condado separó**
  - [x] la distancia al board **sigue** siendo feature del modelo
        (`board_le_200`, `board_le_1km`, `log_board`), que es su lugar
        correcto: ahí el modelo la pesa contra todo lo demás en vez de ser un
        override
  - [x] medido: AUC **sin cambios** en 0,8119 — que es el chequeo de sanidad
        y no un resultado, porque el rescate no es feature y no podía
        moverlo. El pool de candidatos baja de 128.951 a **126.210** (se van
        2.741), y de los 10.000 pines del export instalado se irían
        exactamente **100**: 65 Stensättning, 8 Boplats, 7 Fångstgrop y 6
        Gränsbestämt område. **Todos sin nombre** — lo que tenía nombre se
        rescató por tenerlo. Seis son de la clase de límites administrativos
        que Franco tocó una vez esperando Li gravfält
- [x] **`Stadslager` excluido** (hecho 2026-09-16, `cc0cfe8`), pero **no** con
      `CLASS_BLACKLIST`: ahí el rescate lo habría salvado por `has_name`, y
      para esta clase el nombre es **el del pueblo de encima** (Trelleborg,
      Varberg, Landskrona, "Ängelholms medeltida stad" — los 22). Se hizo con
      un `CLASS_BURIED` nuevo, cuyo único rescate es el propio campo del
      registro `placering = 'Synlig ovan mark'`. Sobre estos 126 clusters ese
      campo los separa **3 / 123**, y los tres son los destinos de verdad:
      Sala gruvby, Kungahälla/Klosterkullen y Brätte. Se fueron 104 de los
      107 pines
  - [x] aplicado en `build_scores` y no como columna nueva de `signals`, así
        que agregar una clase a la lista **no** pide re-correr la etapa 4
  - [x] **el agujero que destapó**: al sacar 204 pines de ruido subieron
        otros desde abajo del corte y `Gränsbestämt område` pasó de 6 a 10 —
        la clase de límites administrativos. Estaba en `CLASS_BLACKLIST`,
        donde el rescate tampoco sirve: `has_name` es el nombre de lo
        delimitado ("Sala silvergruva", "Nydala Kloster") y `any_visible` es
        1 en **los 71**, porque lo visible es el monumento y no el límite.
        Movido a un `CLASS_NOT_A_PLACE` nuevo, excluido sin rescate al lado
        de `struck`: 70 de los 71 tienen otro monumento a menos de 500 m, o
        sea que el pin duplica uno que ya existe
  - [x] **exportado, y el export no costó nada**: de los 2.912 lugares del
        nuevo top 10.000 sin descripción generada, **cero** muestran hoy
        prosa generada. Los 2.200 que tienen texto muestran el texto crudo
        del registro ("Kyrkoruin.") y lo siguen mostrando. Entran 458,
        se van 204
- [ ] ojo: `CLASS_BLACKLIST` la leen `build_clusters` (etapa 2) y
      `build_signals` (etapa 4), así que esto pide **re-correr etapas 2→5**, y
      eso cambia qué lugares están en el export. No es gratis en tiempo ni
      neutral en datos: hay que decidirlo sabiendo que mueve el conjunto de
      10.000
- [ ] **medir antes de creerse el resultado**: el AUC y el ratio de labels, y
      cuántos de los 2.845 tenían de verdad algo que ver. Es el mismo cuidado
      que se tuvo con las 138 etiquetas negativas del registro

---

## Decisiones tomadas, que no viven en ningún archivo

Lo de acá NO es trabajo pendiente: son las decisiones y los hallazgos de datos
que hay que conocer para no volver a discutirlos, y que no se leen en un solo
lugar del código. **El registro de lo construido se saca del `git log`, no de
acá** — el razonamiento de cada cosa hecha está en el comentario del archivo
que la implementa, que es un mejor lugar porque no puede desfasarse de él.

**El puntaje**

- existe / visible / visitable / interesante son **un solo eje**: si alguna es
  negativa no vale la pena ir, así que es una sola pregunta con un solo
  control, y nombrar el fondo de la escala (`Inget att se`) reemplaza a un
  botón aparte de "acá no hay nada"
- el promedio de visitantes **reemplaza** al score del modelo en cuanto hay un
  puntaje; no se promedia con él. El modelo mide cuánta documentación tiene el
  lugar, la estrella mide si valió la pena ir, y los primeros cuatro puntajes
  reales ya lo contradijeron
- se muestra la **media cruda** más la cantidad, sin shrinkage: el dato más
  valioso que puede tener este mapa es la única persona que manejó hasta allá
  y encontró un campo arado
- el flag "no pude encontrarlo" **no es 1★**. Una estrella es una opinión
  negativa; el flag es no haber podido opinar. Exclusión mutua por CHECK
- el recordatorio de la noche considera "contestado" **sólo el puntaje**: la
  pregunta barata (el cartel) no puede tapar a la valiosa
- **el costo, dicho en voz alta**: gatear todo detrás de "¿estuviste acá?" ata
  el crecimiento de los datos a la velocidad a la que la gente camina. Se paga
  igual — 50 puntajes de gente que fue valen más que 500 de gente que leyó la
  descripción

**Identidad**

- **cerrar sesión NO rota el uuid.** Es tentador porque daría la semántica
  esperada ("ahora soy anónimo") y es la trampa contra la que ya nos
  estrellamos una vez: partir a una persona en dos autores a propósito.
  Además rompe "¿esto lo puntué yo?", que se resuelve por autor. `Logga ut`
  significa "dejá de mostrar quién soy"; el que cambia de identidad es
  `Glöm mig`
- **publicar exige cuenta, contribuir no** (2026-09-16). Un uuid anónimo se
  mintea infinitas veces, así que ni el rate limit por autor ni "dos
  observaciones coincidentes" valían nada. Leer sigue siendo anónimo
- **comentarios y fotos siguen cerrados**, y no por falta de cuenta: no hay
  forma de bajarlos. Se abren cuando haya moderación

**Hallazgos de datos**

- **el registro no sabe si hay algo que ver**, así que el prompt no se puede
  reemplazar con datos: `antikvarisk bedömning` es 99,5% `Fornlämning` y
  `Borttagen` no existe en nuestros datos
- **274 lugares que el registro dio de baja estaban en la app.**
  `Utgår på grund av felregistrering` (116) y `Överförd till annan lämning`
  (158) → `excluded_hard`: no son lugares aburridos, son erratas. Sólo donde
  **todos** los sitios del cluster están de baja (205 de 230 clusters)
- **138 etiquetas negativas** del registro (`Förstörd` 0,9,
  `Uppgift om lämning, ej bekräftad i fält` 0,6). El ratio pasa de 1:832 a
  1:61; el AUC apenas se mueve (0,8113 → 0,8119)
- **la atribución: 1.401 lugares tienen una fuente de Wikipedia en el corpus,
  pero sólo 6 descripciones fueron escritas de una.** La obligación de CC BY-SA
  hoy son 6 lugares, y pasa a ~1.401 después de la regeneración — lo que la
  vuelve urgente es regenerar, no el paso del tiempo
- **los `source_id` son estables sólo mientras `places.sqlite` no se borre.**
  `build_sources` los preserva porque inserta con `INSERT OR IGNORE` sobre una
  tabla que no dropea; `rm` del archivo los reasigna y deja
  `generation_sources` apuntando a otras filas

**Hallazgos de review que resultaron falsos** (para no volver a reportarlos)

- `ATTRIBUTION` **sí** se usa: se renderiza en `MapScreen.tsx:561` desde el
  primer commit, así que el mapa muestra el crédito de OSM
- las migraciones **no pueden ser idempotentes** y no hace falta: dos pasos
  reconstruyen tablas leyendo la columna vieja. Lo que reemplaza a la
  idempotencia es la atomicidad
- el estado `dead` del `outbox` **no necesita columna**: `attempts >=
  MAX_ATTEMPTS` ya lo dice. Lo que faltaba no era el flag, era que alguien
  mirara
- exigir cuenta en el `DELETE` de autor **sería un bug**: dejaría a una
  persona sin cuenta sin forma de ser olvidada

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
