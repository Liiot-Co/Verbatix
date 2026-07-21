# Todo: Secuencia de rondas + homologación obligatoria + fix de reanudación

## Task 1: Endpoint/lógica para calcular el siguiente `round_number` esperado

**Description:** Función `next_round_number(db, project_id) -> int` en `repositories.py` (o cerca de las queries de rounds existentes): devuelve `max(round_number) + 1` si el proyecto tiene rondas, o `1` si no tiene ninguna. Se expone vía el `GET /projects/{id}/codebook-sources`-style endpoint existente o uno nuevo `GET /projects/{id}/next-round-number` — a definir según lo que sea más simple de integrar en el wizard sin duplicar la carga de `GET /projects/{id}` (que ya trae `rounds`, desde donde el frontend hoy calcula esto con `nextRoundNumber()` en `frontend/src/lib/projectTree.ts`).

**Acceptance criteria:**
- [ ] Proyecto sin rondas → función devuelve 1
- [ ] Proyecto con rondas 1, 2 → función devuelve 3
- [ ] Proyecto con solo una ronda 5 (creada como primera) → función devuelve 6

**Verification:**
- [ ] Tests pasan: `pytest backend/tests/ -v -k next_round_number`
- [ ] Manual: confirmar cálculo contra datos reales de un proyecto con 2+ rondas

**Dependencies:** None

**Files likely touched:**
- `backend/app/repositories.py`
- `backend/app/routers/projects.py` (si se decide exponer como endpoint nuevo) o `backend/app/routers/studios.py`

**Estimated scope:** S

---

## Task 2: `POST /projects/{id}/rounds` valida secuencia de `round_number`

**Description:** Si el proyecto ya tiene al menos una ronda, `round_number` del payload debe ser exactamente `next_round_number(project_id)`; si no coincide, HTTP 400 con mensaje claro ("El número de ronda debe ser N, siguiente a la última existente"). Si el proyecto no tiene ninguna ronda, no se aplica ninguna restricción (se acepta cualquier número, incluida una "ronda 5" inicial).

**Acceptance criteria:**
- [ ] Proyecto sin rondas: crear ronda con `round_number=5` funciona sin error
- [ ] Proyecto con ronda 1 existente: crear ronda con `round_number=3` falla con 400
- [ ] Proyecto con ronda 1 existente: crear ronda con `round_number=2` funciona

**Verification:**
- [ ] Tests pasan: `pytest backend/tests/ -v -k round_sequence`
- [ ] Manual: reproducir los 3 casos de aceptación contra la API real

**Dependencies:** Task 1

**Files likely touched:**
- `backend/app/routers/studios.py` (`create_round`)
- `backend/tests/test_req07.py` o nuevo `backend/tests/test_round_sequence.py`

**Estimated scope:** S

---

## Task 3: `POST /rounds/{id}/subprojects` rechaza `scratch`/`inherited_round` si no es la primera ronda

**Description:** Antes de crear los subproyectos, determinar si la ronda es "la primera del proyecto" (mismo criterio que Task 1/2: es la única ronda existente al momento de su creación, o equivalentemente `round_number == 1` dado que la secuencia ya lo garantiza salvo el caso especial de primera ronda con número arbitrario). Si NO es la primera, cualquier `catalog_origins[coding_type].origin` distinto de `imported_client_catalog` debe rechazarse con HTTP 400 ("Las rondas posteriores a la primera solo permiten homologar el libro de códigos").

**Acceptance criteria:**
- [ ] Ronda 1 de un proyecto: `scratch` y `imported_client_catalog` se aceptan; `inherited_round` se acepta si hay fuente válida (comportamiento actual sin cambios)
- [ ] Ronda 2+ de un proyecto: `scratch` rechazado con 400; `inherited_round` rechazado con 400; `imported_client_catalog` se acepta

**Verification:**
- [ ] Tests pasan: `pytest backend/tests/ -v -k homolog`
- [ ] Manual: reproducir los 2 casos contra la API real

**Dependencies:** Task 2

**Files likely touched:**
- `backend/app/routers/studios.py` (`create_round_subprojects`, `_validate_catalog_origins`)
- `backend/tests/test_req07.py` o nuevo archivo

**Estimated scope:** M

---

## Task 4: Ajustar mensajes de error para que el frontend distinga el caso "no es la primera ronda"

**Description:** El error 400 de Task 3 debe traer un código/detalle distinguible (no solo texto libre) para que el wizard pueda, por ejemplo, redirigir automáticamente a la sección de homologación en vez de solo mostrar un toast genérico. Revisar el patrón ya usado en otros 400 del router (¿usan `detail` como string plano o como dict con `code`?) y ser consistente.

**Acceptance criteria:**
- [ ] El error de Task 3 es identificable por el frontend sin parsear el string del mensaje

**Verification:**
- [ ] Tests pasan (incluye verificar el shape del error)

**Dependencies:** Task 3

**Files likely touched:**
- `backend/app/routers/studios.py`
- `frontend/src/api/client.ts` (si hace falta tipar el error)

**Estimated scope:** S

---

## Checkpoint: Backend secuencia + homologación
- [ ] `pytest backend/tests/ -v` pasa completo
- [ ] Manual: los 5 casos de aceptación de Tasks 1-4 verificados contra la API real
- [ ] Revisión con el usuario antes de continuar

---

## Task 5: Función centralizada `round_setup_incomplete(db, round_id)`

**Description:** Nueva función en `repositories.py` que determina si una ronda tiene configuración incompleta, cubriendo TODOS los puntos de falla posibles del wizard (confirmado por el usuario: "cualquier paso debe considerarse"):
- Sin ningún subproyecto creado (`subprojects` vacío para esa ronda).
- Con subproyectos, pero al menos uno con `codebook.origin = 'imported_client_catalog'` y `codebook.status != 'approved'` (homologación pendiente de confirmar/aprobar).
- Cualquier archivo importado (`imported_files`) cuyo `dataset_snapshot.status` no llegó a `'ready'` Y la ronda sigue en estado `created`/`files_uploaded` sin haber llegado a `preliminary_ready` o posterior — es decir, se subió el archivo pero el proceso de import/configuración no se cerró.
- Reutilizar/envolver la lógica ya existente en `round_processing_blockers` donde aplique, para no duplicar reglas — pero `round_setup_incomplete` es más amplio: cubre el caso "nunca se intentó importar nada todavía" que `round_processing_blockers` no contempla (esa función asume que ya hay contenido cargado).

**Acceptance criteria:**
- [ ] Ronda recién creada sin subproyectos → `True` (incompleta)
- [ ] Ronda con subproyectos, catálogo homologado pendiente de aprobar → `True`
- [ ] Ronda con subproyectos, catálogo aprobado, archivo importado y ronda en `preliminary_ready`+ → `False` (completa)
- [ ] Ronda con subproyectos scratch (sin homologación) y archivo aún no importado → `True` (incompleta: falta terminar de importar)

**Verification:**
- [ ] Tests pasan: `pytest backend/tests/ -v -k setup_incomplete`

**Dependencies:** None (independiente de Tasks 1-4)

**Files likely touched:**
- `backend/app/repositories.py`
- `backend/tests/test_round_setup_incomplete.py` (nuevo)

**Estimated scope:** M

---

## Task 6: Bloquear `scheduler.submit` si `round_setup_incomplete` es true

**Description:** Revisar TODOS los call-sites de `scheduler.submit` en `backend/app/routers/studios.py` (conocidos hoy: `import_file`, `resolve_import_flag` vía `_maybe_queue_after_review`, `bulk_resolve_profile_flags` vía el mismo helper, `resolve_all_profile_for_file` vía el mismo helper, y cualquier otro que aparezca al hacer `grep scheduler.submit`) y anteponer el chequeo de `round_setup_incomplete`. Si la ronda tiene configuración incompleta, no se dispara el motor y el `processing_status` de la respuesta refleja el bloqueo (ej. `"blocked_on_setup"` como nuevo valor, o reutilizar uno existente si aplica semánticamente).

**Acceptance criteria:**
- [ ] Ninguno de los call-sites de `scheduler.submit` dispara el motor cuando `round_setup_incomplete(db, round_id)` es `True`
- [ ] `grep -rn "scheduler.submit" backend/app/routers/studios.py` confirma que todos los call-sites pasaron por el chequeo (ver checklist en el propio PR/commit)

**Verification:**
- [ ] Tests pasan: `pytest backend/tests/ -v`
- [ ] Manual: forzar un import con ronda sin subproyectos (vía API directa) y confirmar que el motor no arranca

**Dependencies:** Task 5

**Files likely touched:**
- `backend/app/routers/studios.py`

**Estimated scope:** M

---

## Task 7: Exponer configuración incompleta en `GET /projects/{id}`

**Description:** Agregar un campo `setup_incomplete: boolean` a cada ronda en la respuesta de `get_project` (`backend/app/routers/projects.py`), calculado con la misma lógica de `round_setup_incomplete` (Task 5), para que el frontend pinte el chip sin hacer una llamada extra por ronda.

**Acceptance criteria:**
- [ ] `GET /projects/{id}` incluye `setup_incomplete` en cada objeto de `rounds`
- [ ] El valor coincide con lo que devolvería `round_setup_incomplete` para esa ronda

**Verification:**
- [ ] Tests pasan: `pytest backend/tests/ -v -k get_project`

**Dependencies:** Task 5

**Files likely touched:**
- `backend/app/routers/projects.py`
- `frontend/src/api/types.ts` (`RoundSummary` — nuevo campo opcional)

**Estimated scope:** S

---

## Checkpoint: Backend reanudación
- [ ] `pytest backend/tests/ -v` pasa completo
- [ ] Manual: abandonar wizard en cada uno de los 3 puntos de falla, confirmar que el motor no arranca y que `setup_incomplete` refleja el estado correcto
- [ ] Revisión con el usuario antes de continuar

---

## Task 8: Wizard bloquea el input de número de ronda

**Description:** En `CreationWizard.tsx`, cuando el proyecto ya tiene rondas (`project.rounds.length > 0`), el campo "Número de ronda" se muestra bloqueado (readOnly/disabled) mostrando directamente el valor de `nextRoundNumber(project.rounds)` (ya existe esta función en `frontend/src/lib/projectTree.ts`) — nunca editable en ese caso. Si el proyecto no tiene rondas, el campo sigue editable (para permitir crear una "ronda 5" inicial).

**Acceptance criteria:**
- [ ] Proyecto con rondas existentes: input de número de ronda no editable, muestra `max+1`
- [ ] Proyecto sin rondas: input editable, cualquier valor aceptado

**Verification:**
- [ ] `bunx tsc --noEmit` sin errores
- [ ] Manual: ambos casos verificados en el wizard

**Dependencies:** Task 2 (backend ya valida, esto es solo UX)

**Files likely touched:**
- `frontend/src/components/CreationWizard.tsx`

**Estimated scope:** S

---

## Task 9: Wizard oculta selector de origen inválido cuando no es la primera ronda

**Description:** En el paso "Configuración" del wizard, si el proyecto ya tiene rondas (no es la primera), ocultar por completo el radiogroup de origen del libro (`scratch` / `inherited_round` / `imported_client_catalog`) y mostrar directamente la sección de homologación (subir libro del cliente), sin selector — coherente con la decisión de UX ya tomada ("quitar de la UI, para quitar ruido visual"). Si es la primera ronda del proyecto, se mantiene el comportamiento actual (selector completo con las 3 opciones, sin `inherited_round` disponible salvo que ya existan libros oficiales — comportamiento sin cambios ahí).

**Acceptance criteria:**
- [ ] Proyecto con rondas existentes: paso "Configuración" muestra directo la sección de homologación, sin radiogroup de origen
- [ ] Proyecto sin rondas (primera ronda): comportamiento actual sin cambios (selector con scratch/homologar visibles)

**Verification:**
- [ ] `bunx tsc --noEmit` sin errores
- [ ] Manual: ambos casos verificados en el wizard

**Dependencies:** Task 8

**Files likely touched:**
- `frontend/src/components/CreationWizard.tsx`

**Estimated scope:** M

---

## Checkpoint: Frontend wizard
- [ ] `bunx tsc --noEmit` sin errores
- [ ] Manual: crear ronda 2+ en un proyecto con ronda previa, confirmar número bloqueado y único flujo de homologación visible
- [ ] Revisión con el usuario antes de continuar

---

## Task 10: Chip "Configuración incompleta" en la card de la ronda

**Description:** En `ProjectDetail.tsx`, dentro del render de cada ronda en la lista, si `round.setup_incomplete` es `true` (nuevo campo de Task 7), mostrar un chip visible (ej. badge naranja/warning) con texto "Configuración incompleta" junto al nombre de la ronda.

**Acceptance criteria:**
- [ ] Ronda con `setup_incomplete: true` muestra el chip en su card
- [ ] Ronda con `setup_incomplete: false` no muestra el chip

**Verification:**
- [ ] `bunx tsc --noEmit` sin errores
- [ ] Manual: confirmar el chip aparece/desaparece según el estado real de la ronda

**Dependencies:** Task 7

**Files likely touched:**
- `frontend/src/components/ProjectDetail.tsx`
- `frontend/src/api/types.ts`

**Estimated scope:** S

---

## Task 11: Click en ronda incompleta navega al wizard en modo reanudación

**Description:** En `ProjectDetail.tsx`, si `round.setup_incomplete` es `true`, el `target` de la card debe ser `/wizard?projectId={projectId}&roundId={round.id}` en vez de `roundPhasePath(round.id, round.status)` (que hoy lleva a `/rounds/{id}` o `/rounds/{id}/report`). Esto requiere que el wizard soporte un nuevo modo "reanudar ronda existente pero incompleta", distinto del modo actual "agregar carga a ronda ya configurada" (`isAddLoadMode`, que asume subproyectos ya creados).

**Acceptance criteria:**
- [ ] Click en una ronda con `setup_incomplete: true` navega a `/wizard?projectId=&roundId=`, no a `/rounds/{id}`
- [ ] Click en una ronda con `setup_incomplete: false` mantiene el comportamiento actual

**Verification:**
- [ ] `bunx tsc --noEmit` sin errores
- [ ] Manual: verificar la navegación en ambos casos

**Dependencies:** Task 10, Task 12 (el wizard debe soportar el modo antes de enrutar hacia él)

**Files likely touched:**
- `frontend/src/components/ProjectDetail.tsx`

**Estimated scope:** S

---

## Task 12: Wizard soporta modo reanudación de ronda incompleta

**Description:** Nuevo modo del wizard (distinto de "ronda nueva" y de "agregar carga"): cuando entra con `?projectId=&roundId=` y la ronda existe pero está incompleta, el wizard debe:
- Cargar el estado ya persistido de la ronda (nombre, número, threshold, audit, subproyectos si existen, archivo ya subido si existe).
- Determinar el paso de entrada según el mismo criterio de `round_setup_incomplete` (Task 5): sin subproyectos → paso "Configuración" (con los datos de ronda ya prellenados, foco en elegir/completar origen del libro); con subproyectos pero homologación pendiente → paso "Configuración", sección de homologación abierta directo; archivo subido pero import sin cerrar → paso "Datos".
- Nunca debe re-crear la ronda ni duplicar subproyectos ya existentes — debe detectar y reusar lo que ya existe (similar a como hoy `ensureRound()` ya evita re-crear si `round` está seteado, pero ahora inicializado desde el fetch de la ronda existente en vez de desde cero).

**Acceptance criteria:**
- [ ] Reanudar una ronda sin subproyectos entra directo al paso Configuración con los datos ya guardados prellenados
- [ ] Reanudar una ronda con homologación pendiente entra al paso Configuración con la sección de homologación ya expandida
- [ ] Reanudar una ronda con archivo subido pero sin importar entra al paso Datos
- [ ] En ningún caso se duplican subproyectos ni se crea una ronda nueva

**Verification:**
- [ ] `bunx tsc --noEmit` sin errores
- [ ] Manual: los 3 casos de entrada verificados end-to-end contra el backend real

**Dependencies:** Task 5 (criterio de incompletitud), Task 9

**Files likely touched:**
- `frontend/src/components/CreationWizard.tsx`
- `frontend/src/api/client.ts` (si hace falta un endpoint para traer el estado detallado de la ronda a reanudar)

**Estimated scope:** L

---

## Checkpoint: Frontend completo
- [ ] `bunx tsc --noEmit` sin errores
- [ ] `bun run build` sin errores
- [ ] Manual end-to-end: abandonar wizard en cada uno de los 3 puntos de falla posibles, volver al proyecto, confirmar chip visible y reanudación al paso correcto en los 3 casos
- [ ] Revisión final con el usuario
