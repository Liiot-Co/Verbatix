# Implementation Plan: Secuencia de rondas + homologación obligatoria + fix de reanudación

## Overview
Hoy `POST /projects/{id}/rounds` acepta cualquier `round_number` sin validar nada, y el origen del libro de códigos (`scratch` / `inherited_round` / `imported_client_catalog`) se elige libremente sin relación con si existen rondas previas. Esto permite crear una "ronda 5" con libro `scratch` sin que exista ninguna ronda anterior en el proyecto, lo cual no tiene sentido de negocio: el libro de códigos de una ronda que no es la primera del proyecto vive en un sistema externo (otra app), nunca se crea desde cero ni se hereda del histórico interno.

Además, existe un bug de UX/datos: si el wizard de creación de ronda se abandona a medio camino (por ejemplo, se sube el archivo pero nunca se confirma el origen del libro de códigos, o se homologa un catálogo pero nunca se aprueba), al volver a esa ronda el usuario cae directo al Centro de Resolución/Procesamiento en vez de continuar la configuración pendiente — y en el peor caso el motor (`scheduler.submit`) puede haber arrancado sin que la configuración esté completa.

Este plan resuelve las 3 piezas, confirmadas con el usuario:

1. **Secuencia de `round_number` por proyecto (Estudio):** la siguiente ronda que se crea debe ser exactamente `max(round_number existentes en el proyecto) + 1`. Si el proyecto no tiene ninguna ronda todavía, se permite crear la primera con cualquier número (incluida una "ronda 5" inicial) sin bloqueo — la restricción solo aplica cuando ya existe al menos una ronda previa.
2. **Origen del libro de códigos condicionado al número de ronda:**
   - `round_number == 1` (o "es la primera ronda del proyecto"): se permite `scratch` o `imported_client_catalog`. Nunca `inherited_round` (no hay nada que heredar).
   - `round_number != 1`: **únicamente** se permite `imported_client_catalog` (homologar libro externo). Se bloquean `scratch` e `inherited_round` — el libro de códigos de rondas no-primeras siempre viene de un sistema externo, nunca se crea ni se hereda del histórico de la app.
3. **Fix de reanudación de ronda incompleta:** cualquier ronda cuya configuración no llegó a completarse — en cualquier paso: sin subproyectos creados, con subproyectos pero catálogo de homologación (`imported_client_catalog`) sin confirmar/aprobar, o cualquier otro estado intermedio detectable — debe (a) redirigir de vuelta al wizard de configuración en vez de al Centro de Resolución/Procesamiento al reabrir la ronda, y (b) mostrar un chip visible "Configuración incompleta" en la card de esa ronda dentro de `ProjectDetail.tsx`. El motor nunca debe arrancar (`scheduler.submit`) mientras la ronda esté en este estado, sin importar en qué paso quedó exactamente.

## Architecture Decisions
- La validación de secuencia y de origen de catálogo se hace en el **backend** (fuente de verdad), en `POST /projects/{id}/rounds` y `POST /rounds/{id}/subprojects` — nunca solo en el frontend.
- El "número de ronda esperado" (`max+1`, o `1` si no hay rondas) se expone en un endpoint ya existente o uno nuevo liviano, para que el wizard lo consuma y bloquee el input en vez de dejarlo editable (ya confirmado con el usuario: "bloquear el input").
- Para "es la primera ronda del proyecto" usamos el mismo criterio que la secuencia: si `round_number == 1`, sin importar si hay otras rondas con otros números (dado que la secuencia ya obliga a que la única forma de tener rondas con `round_number > 1` sea habiendo empezado en 1 y avanzado consecutivamente — excepto el caso especial confirmado de "primera ronda con número arbitrario, ej. 5", que también cuenta como su propia \"ronda 1\" del proyecto a efectos de origen de catálogo).
- Definición operativa de "ronda con configuración incompleta" (confirmada por el usuario: cualquier paso cuenta, sin excepciones):
  - No tiene ningún subproyecto creado (`subprojects` vacío) — nunca se llamó a `POST /rounds/{id}/subprojects`.
  - Tiene subproyectos, pero al menos uno con `codebook.origin = 'imported_client_catalog'` y `codebook.status != 'approved'` (homologación pendiente de confirmar).
  - Cualquier otro estado no cubierto arriba pero que impida procesar (se reutiliza `round_processing_blockers`/lógica equivalente ya existente en `repositories.py` para no duplicar reglas) — el criterio se centraliza en una sola función `round_setup_incomplete(...)` para que futuros pasos de configuración añadidos automáticamente entren en el chequeo sin tener que tocar cada call-site.
- El chequeo de "no arrancar el motor si la configuración está incompleta" se centraliza en el mismo punto donde ya se decide `processing_status` (import_file, resolve_import_flag, bulk_resolve, catalog-import) — no se introduce un mecanismo paralelo.
- El chip de "Configuración incompleta" se calcula en el frontend a partir de datos que ya trae `GET /projects/{id}` (lista de rounds con sus subprojects) — si hace falta el estado del codebook (`approved`/`pending`) para el segundo caso, se añade ese campo a la respuesta de `get_project` en vez de hacer N llamadas adicionales por ronda.
- Reanudación: en vez de que el chip solo informe, el click en la card de una ronda incompleta debe navegar directo a `/wizard?projectId={id}&roundId={roundId}` (nueva variante de deep-link) que reanuda el wizard en el paso correcto según lo que falte, en vez de ir a `/rounds/{id}` (UnifiedStudioView).

## Task List

### Phase 1: Backend — secuencia de `round_number` por proyecto
- [ ] Task 1: Endpoint/lógica para calcular el siguiente `round_number` esperado de un proyecto (reutilizable por wizard y por validación)
- [ ] Task 2: `POST /projects/{id}/rounds` valida que `round_number` sea exactamente el esperado (si ya existen rondas), sin bloquear la primera ronda con número arbitrario

### Checkpoint: Backend secuencia
- [ ] `pytest backend/tests/ -v` pasa completo
- [ ] Manual: crear ronda 1, luego intentar crear ronda 3 (debe fallar), crear ronda 2 (debe pasar)
- [ ] Manual: proyecto sin rondas, crear directamente "ronda 5" (debe pasar, ninguna validación de secuencia aplica)

### Phase 2: Backend — origen de catálogo condicionado al número de ronda
- [ ] Task 3: `POST /rounds/{id}/subprojects` rechaza `scratch`/`inherited_round` si la ronda no es la primera del proyecto
- [ ] Task 4: Ajustar mensajes de error / respuesta para que el frontend distinga este caso de otros 400 existentes

### Checkpoint: Backend homologación
- [ ] `pytest backend/tests/ -v` pasa completo
- [ ] Manual: ronda 1 permite scratch/homologar; ronda 2+ solo permite homologar (scratch/heredar responden 400)

### Phase 3: Backend — fix de reanudación (no arrancar motor con configuración incompleta)
- [ ] Task 5: Función centralizada `round_setup_incomplete(db, round_id)` en `repositories.py`
- [ ] Task 6: Bloquear `scheduler.submit` en todos los call-sites relevantes (`import_file`, `resolve_import_flag`, `bulk_resolve_profile_flags`, `resolve_all_profile_for_file`, `catalog-import`) si `round_setup_incomplete` es true
- [ ] Task 7: Exponer el estado de configuración incompleta en `GET /projects/{id}` (campo por ronda) para que el frontend pinte el chip sin llamadas extra

### Checkpoint: Backend reanudación
- [ ] `pytest backend/tests/ -v` pasa completo
- [ ] Manual: abandonar wizard a medio camino (sin subproyectos, y por separado con homologación sin confirmar) en ambos casos el motor no debe arrancar aunque se fuerce el import

### Phase 4: Frontend — wizard bloquea número de ronda y oculta orígenes inválidos
- [ ] Task 8: Wizard consume el `round_number` esperado y lo muestra bloqueado (no editable) cuando el proyecto ya tiene rondas
- [ ] Task 9: Wizard oculta el selector "Crear desde cero / Heredar / Homologar" y muestra directo la sección de homologación cuando la ronda no es la primera del proyecto

### Checkpoint: Frontend wizard
- [ ] `bunx tsc --noEmit` sin errores
- [ ] Manual: crear ronda 2+ en un proyecto con ronda previa — número bloqueado, único flujo visible es homologar

### Phase 5: Frontend — chip de configuración incompleta + reanudación
- [ ] Task 10: `ProjectDetail.tsx` muestra chip "Configuración incompleta" en la card de la ronda cuando corresponda
- [ ] Task 11: Click en una ronda con configuración incompleta navega al wizard en modo reanudación (`?projectId=&roundId=`) en vez de a `/rounds/{id}`
- [ ] Task 12: Wizard soporta el modo reanudación: carga el estado ya guardado de la ronda (archivo subido, subproyectos si existen, catálogo pendiente) y salta al paso correspondiente

### Checkpoint: Frontend completo
- [ ] `bunx tsc --noEmit` sin errores
- [ ] `bun run build` sin errores
- [ ] Manual end-to-end: abandonar wizard en cada uno de los 3 puntos de falla posibles (sin subproyectos / homologación sin confirmar / archivo subido sin importar), volver al proyecto, confirmar chip visible y reanudación al paso correcto en los 3 casos
- [ ] Revisión final con el usuario

## Risks and Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| Definir "primera ronda del proyecto" de forma ambigua si en el futuro se permite borrar rondas y la secuencia queda con huecos | Medio | La regla de secuencia (`max+1`) ya previene huecos hacia adelante; documentar explícitamente que `delete_round` no re-abre huecos para creación (ronda borrada no libera su número) |
| Múltiples call-sites disparan `scheduler.submit` — fácil olvidar uno al centralizar el chequeo | Alto | Enumerar explícitamente los 5 call-sites conocidos en Task 6 y verificar con `grep scheduler.submit` antes de cerrar el checkpoint |
| El wizard de reanudación (Task 12) puede requerir re-diseñar cómo se detecta "en qué paso quedó" — no existe hoy un mecanismo de eso | Alto | Reutilizar el mismo criterio de `round_setup_incomplete` (Task 5) para decidir el paso de entrada: sin subproyectos → paso "Configuración"; con subproyectos pero homologación pendiente → paso "Configuración" (sección de homologación); archivo subido sin importar → paso "Datos" |
| Cambiar `GET /projects/{id}` (Task 7) puede romper consumidores existentes del tipo `RoundSummary` si se agrega un campo mal tipado | Bajo | Campo nuevo opcional (`setup_incomplete: boolean`), no se tocan campos existentes |

## Open Questions
Ninguna pendiente — todas las decisiones de alcance fueron confirmadas por el usuario en la conversación previa a este plan.
