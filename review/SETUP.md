# Cómo se corre

No hay que crear un agente en Cursor. El manager arranca uno por sitio con el comando `agent` y le manda `prompt.md` ya rellenado: el sitio, el trabajo y las herramientas. Ese texto es todo lo que el agente recibe. No lee el `AGENTS.md` del pipeline. El workspace del proceso es una carpeta vacía en `/tmp`, afuera del repo. `agent -p` pide un login propio (`agent login` o `CURSOR_API_KEY`); la sesión del IDE no le alcanza.

## Antes de spawnear

1. Desplegar franco-may. La columna `by_agent` ya está en Neon. El código que la escribe está en el repo local. Hasta que ese código esté en franco-may.com, un verify del agente se grabaría como si lo hubieras firmado vos. El prompt, si eso pasa, lo deshace y se detiene. Mejor no llegar ahí.

2. `FL_AGENT_TOKEN`, el mismo valor en Vercel y en esta máquina. El server lo lee de su entorno y lo compara con el `Authorization: Bearer` que manda el agente. El manager lo toma del entorno o de `franco-may/.env.local`. No es el login de Franco. La producción que está en el aire todavía lee la fila vieja de la base. Cuando se despliegue este código, la variable tiene que estar puesta en Vercel antes, o los agentes dejan de entrar.

## Qué hace el manager

`python3 review/manager.py` lee `GET /places` y arma la cola.

Queda afuera un sitio que ya tiene `verified_at`, o `uninteresting`, o `aside`. También queda afuera uno que este script ya entregó y todavía no terminó (`review/inflight.json`, dos horas).

Lo que queda se reparte en cuatro carriles, de a uno, para que un carril no se coma a los otros:

| carril | qué es | orden |
|---|---|---|
| `bare` | score, cero fotos, y el tipo no está en la lista de vacíos | score alto primero |
| `drawer` | score, hay fotos, ninguna priorizada | score alto primero |
| `empty` | `Fyndplats`, `Fornlämningsliknande lämning`, `Fornlämningsliknande bildning`, `Övrigt` | score bajo primero |
| `rest` | el resto de lo abierto | score alto primero |

Un tipo de la lista de vacíos con score y cero fotos cae en `empty`. Si ese mismo tipo tiene fotos sin priorizar y score, cae en `drawer`: el trabajo es mirar el cajón. La lista está en `EMPTY_KINDS` al tope de `manager.py`.

```
python3 review/manager.py              # imprime 12, no arranca nadie
python3 review/manager.py --spawn 1    # uno, para leer el log
python3 review/manager.py --spawn 4    # cuatro a la vez
```

El log queda en `review/logs/<uuid>.log`. `--force` está puesto a propósito: sin eso, cada pedido se queda esperando un clic y los procesos se traban. El sandbox va apagado para que pueda llegar a franco-may.com.

Cuando el proceso termina, el manager saca el uuid de `inflight.json`. Si el agente cerró bien, el próximo dry-run ya no lo muestra, porque la lista viene de Neon. Si murió a la mitad, el sitio sigue abierto y vuelve a entrar después de las dos horas, o antes si se borra esa línea del json.

## Para corregir el trabajo

Lo que hay que leer es `prompt.md`. El manager reemplaza el nombre, el tipo, el uuid y la URL de la API.

Cosas que están decididas en el código y se pueden mover:

- `uninteresting` de un agente entrena el modelo, igual que uno tuyo. `verify` con `by_agent` no entrena. Entra al entrenamiento el día que lo firmás vos en el admin, que borra la marca de agente.
- Los 15 sitios que ya estaban en `fl_compare_aside` no se entregan.
- El manager no reserva el sitio en Neon. La reserva es el json local. Dos managers a la vez en dos máquinas se pueden pisar. Uno solo en esta máquina, no.
