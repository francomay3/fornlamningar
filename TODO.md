# TODO

Lo que falta hacer. Cuando algo se hace, se borra de este archivo.
No es un lugar para documentar lo que fuimos haciendo.

## Visitas, puntajes y la advertencia

- [ ] Contar visitas deduplicando al leer: el log ya tiene dos visitas de
      un autor para un lugar en un día.
- [ ] `Glöm mig` borra sólo este dispositivo. Seguir el link y borrar el
      otro teléfono queda por decidir. (deberia mandar un payload al BE para borrar todos los comentarios y valoraciones de ese usuario)

## Idioma y atribución

- [ ] Las etiquetas del mapa siguen en sueco (`points.geojson` es uno para
      los dos idiomas). Resolver el título en la app desde la base del
      idioma.
- [ ] Línea de atribución en la ficha. `build_tiles.py` mete en el shard los publisher / licence /
      url distintos de las fuentes no-registro. Un lugar sin filas en
      `generation_sources` no muestra nada. Los `unresolved` se atribuyen
      con publisher y url.
- [ ] El párrafo de fuentes de `Om appen` está escrito a mano. Derivarlo
      de `sources.publisher` y las licencias.
- [ ] Las licencias MIT y Apache-2.0 piden el texto del aviso en el
      binario, no sólo el nombre y el id SPDX.

## Agregar y reportar sitios

- [ ] Agregar un sitio manda el texto y la posición, y lo lee un humano.
      No entra al mapa sin moderación; mientras tanto se muestra sólo a
      quien lo escribió. pienso que agregar podria ser manteniendo press en el mapa y que aparezca un menu que diga "agregar un sitio" o algo asi. y que cuando lo tocas, te abra un modal para agregar el sitio. en el poder elegir de una serie de sitios 50m a la redonda, pingueando toda la base de RAÄ... si el usuario elige "otro" o algo asi, esto queda sin id de raä, pero igual en la moderacion lo voy a temrinar solucionando.
- [ ] Reportar: no está aquí / es inaccesible / la posición no es correcta,
      más un campo libre. "La posición no es correcta" puede traer una
      coordenada. `not_found` ("no lo encontré") no es lo mismo que "no está". esto deberia poder hacerse desde el sheet quizas con tres puntitos en algun lado, o haciedno long press en el icono sobre el mapa.
- [ ] Cuando se retome el picker: `nearby.db` local (~4 MB), no un
      endpoint. El `verified` va por `fl_events`.

## Releases

- [ ] Subir el release a Google Cloud Storage. `make_release.py` congela
      el payload y no sube.
- [ ] Un número de generación monótono, compartido por lugares y
      descripciones, uno por archivo. `ASSET_VERSION` es un hash. Los
      archivos son inmutables; el manifiesto es lo único que se pisa.
      El `versionCode` del APK sale de ese número.
- [ ] Guardar con el export el `seq` del log con el que se generó.
- [ ] `generated.sqlite` a ese storage y a `.gitignore`. Decidir si se
      reescribe el historial LFS viejo o se deja de crecer y nada más.
      `raa_export.gpkg` se queda en LFS.
- [ ] Al terminar, el pipeline dice cuántos lugares del export no tienen
      descripción y con qué comando se cierran. La generación sigue siendo
      un job aparte, no una etapa del pipeline.

## Ids de cluster

- [ ] El sufijo `#idx` de un grupo partido tiene que salir del menor uuid
      de sus miembros, no del orden de un `SELECT`. `ORDER BY uuid` en el
      `SELECT` de `sites`.
- [ ] `build_descriptions.py --status` cuenta `cluster_id` de `generated`
      que no existen en `work.clusters`. Tiene que dar cero. Borrar las
      filas `sp:` que quedaron del método espacial.
- [ ] Guardar el `site_clusters` de la generación anterior. El redirect
      por intersección de miembros se construye cuando haya un rename real.

## Score

- [ ] `visited` salió de un import de Google. Re-medir el peso cuando haya
      unas cien confirmaciones de usuarios reales.
- [ ] Al validar contra las labels de contribución, excluir las features
      de visitante. El AUC de 0,9993 es la feature devolviendo la respuesta.
- [ ] Reservar ~20% de los lugares confirmados como test: `visitors_n` y
      `visitor_text` en 0 en la matriz, y usarlos sólo para validar. Las
      visitas nuevas entran al test, no al train.
- [ ] El export imprime cuántos de los 10.000 se movieron por datos de
      usuario.
- [ ] `Grov skada` (987) es candidata a label negativa con peso bajo, no
      a exclusión. Decidirlo aparte.
- [ ] ~55% de los objetos `fornvard` no matchean. Medir un match por
      contención antes de cambiar la distancia al centroide.

## Basemap

- [ ] Transform del estilo en `sync-assets.sh`, después del `curl`.
      `background` a `paper` primero: es lo que se ve offline. Agua y
      verde hacia la paleta, no más saturados.
- [ ] Los glyphs se piden por red. Sin señal los nombres salen en blanco.
      Costa, lagos y rutas sí están.
- [ ] El texto de la app no promete más offline que los puntos y las
      descripciones. El basemap de OpenFreeMap es por red.

## Datos

- [ ] `build_tiles.py` lee `places.sqlite`, no `work` + `generated`.
- [ ] Descripciones con más de una medida. El checker cuenta y no borra.
      En el prompt 10, el 61,5% trae más de una. Un pase que deje la
      primera no está escrito.

## Logs

- [ ] Warnings y errores de la app y del backend a una tabla de Postgres.
      Rate limit, tope de tamaño, el mismo warning N veces es un contador.
      Sin uuid ni texto que escribió el usuario. Cola con techo en el
      teléfono. Nivel `warn` y `error`. Una vista agrupada por mensaje,
      con conteo y última vez.
