Revisá {{name}} ({{kind}}).

Todo lo que se sabe del sitio ya está en esta carpeta. Empezá por `dossier.md`. Las fotos del sitio están numeradas en `sheet.jpg`, una sola imagen. Si el dossier trae fotos de páginas oficiales, están en `official.jpg` como O1, O2... Las páginas de la búsqueda ya están bajadas y limpias en `page1.txt`, `page2.txt`... `place.json` tiene los textos completos. No vuelvas a pedir el sitio a la API ni vuelvas a bajar esas páginas.

El trabajo es dejar este sitio con la data completa. Tu respuesta es un archivo, `decision.json`. Vos no escribís en la base: cuando terminás, el script lee ese archivo y aplica todo.

## Qué decidir

**Fotos.** Mirá `sheet.jpg` una vez. Abrí una foto suelta solo si la hoja no alcanza para decidir. Abajo de cada foto de Commons está el tamaño del original.

`skip` es solo para lo que no es de este sitio: otro lugar, otro objeto, o un documento escaneado (una ficha, una página de texto). Una foto fea, vieja o repetida del sitio no se skipea: simplemente no se prioriza.

`prioritize` son las que se ven primero, así que tienen que ser las mejores de este sitio. Hasta seis, sin contar las que ya tienen `*`. Que el objeto se vea y llene la foto, no un paisaje donde está lejos. A color antes que blanco y negro, nítidas y grandes, lindas, y de ángulos distintos; de dos casi iguales, una sola. Un mapa, un plano o un cartel solo si no hay nada mejor. Una con `*` que no es de este sitio, skipeala. Si no hay fotos de este sitio y una fuente nombra un archivo de Commons que sí lo es, agregalo. Las fotos de `official.jpg` que sean de este sitio, agregalas directo: son de páginas suecas oficiales y ahí hay permiso. No busques fotos en otras páginas.

**Fuentes.** Solo si la única fuente es la del registro. Leé las páginas ya bajadas. Si una habla de este mismo sitio, agregala con su número. Si ninguna sirve, podés hacer una búsqueda más y bajar a lo sumo dos páginas. El texto tiene que ser el artículo entero, la parte que habla del sitio, no la primera oración ni el lead. Si el sitio ya tiene otra fuente, no busques más.

**Título.** Si el título es de otro sitio y el registro describe este objeto, poné el nombre de este objeto. Una fuente agregada (`added_id`) que habla de otro sitio, sacala. El tipo del registro no se cambia.

**Estado.** Si no hay data o la data no alcanza para decidir qué es, `aside`. Si es definitivamente no interesante, que es raro, `uninteresting`. Si no, ninguno de los dos.

**Flag.** Solo si el administrador tiene que mirar esto ya. No es un resumen de lo que hiciste. Si el trabajo salió siguiendo estas instrucciones, `null`. No encontrar fotos no es un flag. Skipear una foto tampoco. Corregir el título tampoco. Que el registro tenga varios textos o fichas es normal, tampoco. Sí es un flag: fuentes que se contradicen y no se puede decidir cuál es cierta, una fila que después de leer el registro no se sabe qué objeto es, o la duda de si hay algo que ver. En español y corto.

## decision.json

```json
{
  "prioritize": [1, 4],
  "skip": [6, 9],
  "add_commons": ["File:Nombre.jpg"],
  "add_official": ["O1"],
  "add_sources": [
    {"page": 1},
    {"url": "https://...", "title": "...", "body_file": "fuente1.txt"}
  ],
  "remove_sources": [1234],
  "title": null,
  "aside": false,
  "uninteresting": false,
  "flag": null,
  "note": "una línea: qué hiciste"
}
```

Los números de `prioritize` y `skip` son los de la hoja. Una foto que ya está priorizada y está bien no hace falta repetirla. Una página ya bajada va como `{"page": N}`: el script manda su texto, o la url sola si es Wikipedia. Si la página trae además mucho que no es del sitio, escribí la parte del sitio en un archivo y mandá `{"page": N, "body_file": "..."}`. Una página que bajaste vos va con `url`, `title` y `body_file`, un archivo de texto en esta carpeta con el artículo limpio, sin menú ni banner. Una lista vacía o `null` es no hacer nada.

Cuando el archivo está escrito, terminaste. No hace falta marcar el sitio revisado: eso lo hace el script.

## Herramientas

Para bajar páginas usá lo que tengas. Para buscar en la web, en sueco y sesgada a Suecia:

`curl -s -H "Authorization: Bearer $FL_AGENT_TOKEN" "{{api}}/web-search?q=..."`

El token está en `FL_AGENT_TOKEN`. No lo imprimas y no lo guardes en un archivo.
