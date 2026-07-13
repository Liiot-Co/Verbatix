# Auditoría — Plan de Implementación + Prompt

> **Qué es este archivo.** Un solo documento con tres partes:
> **(0) Panorama** del estado actual observado, **(1) Plan** de la feature de
> auditoría y **(2) Prompt de implementación** (autónomo y *adaptativo*: obliga a
> leer el código real antes de escribir nada).
>
> **Regla rectora.** Nada en este documento debe tomarse como verdad congelada.
> El panorama refleja lo que existía al redactarlo (2026-07-12). Cuando la feature
> se implemente, partes del sistema habrán cambiado (p. ej. `audit_percentage` se
> mueve de `studio` a `rounds`, el Centro de Resolución puede haber evolucionado,
> el dashboard puede empezar a existir). **El implementador SIEMPRE verifica el
> estado real primero** — ver Parte 2.

---

## PARTE 0 — PANORAMA (estado observado, verificar antes de usar)

### 0.1 El flujo de negocio, punta a punta

```
Proyecto ─▶ Ronda ─▶ Estudio ─▶ subir Excel ─▶ importar ─▶ PROCESAR (motor)
                                                               │
   brands: fuzzy (catálogo) + LLM sobre el residuo            │
   reasons: LLM structured output                             ▼
                                                    status: preliminary_ready
                                                               │
                    ┌──────────────────────────────────────────┘
                    ▼
        CENTRO DE RESOLUCIÓN  (el analista acepta/descarta anomalías,
        una decisión por mention_group, se propaga a sus verbatims)
                    │  cuando no quedan grupos pendientes (summary.can_close)
                    ▼
   ┌────────────────────────────────────────────────────────────┐
   │  ◀── AQUÍ ENTRA LA NUEVA FEATURE: AUDITORÍA ──▶            │
   │  Se habilita el botón "Auditar". El usuario elige:          │
   │   · Ir al Dashboard  (aún no existe; futuro)                │
   │   · Auditar          (revisar una muestra % de lo codificado)│
   └────────────────────────────────────────────────────────────┘
                    │
                    ▼
        (futuro) Dashboard: muestra "Auditado" o "Sin auditar"
                    │
                    ▼
        nets_review ─▶ ready_to_export ─▶ export
```

### 0.2 Hallazgo central: **el schema ya anticipa la auditoría**

`backend/db/migrations/001_schema_v5.sql` (§6 "AUDITORÍA") ya define TODAS las
tablas que la feature necesita. **No hay que inventar el modelo de datos, hay que
cablearlo.** Verificar que sigan así antes de implementar:

| Tabla | Rol | Columnas clave |
|---|---|---|
| `audit_sessions` | Una sesión de auditoría por estudio/run | `target_percentage`, `total_items`, `reviewed_items`, `target_met`, `status ∈ (pending,in_progress,approved)`, `approved_by/at`, `processing_run_id` |
| `audit_code_reviews` | Progreso **por código** (el "grupo de códigos" que pide el usuario) | `code_id`, `items_count`, `corrections_count`, `status ∈ (pending,approved,with_corrections)`, `reviewer_id`, único `(audit_session_id, code_id)` |
| `audit_items` | Un verbatim muestreado dentro de un código | `verbatim_id`, `codes_snapshot jsonb`, `status ∈ (pending,correct,reassigned)`, `comment`, `reviewer_id`, único `(audit_code_review_id, verbatim_id)` |
| `audit_logs` | Bitácora append-only (ya la usa Resolución vía `log_action`) | `entity_name`, `entity_id`, `action`, `old_value/new_value jsonb` |

Además, ya existentes y relevantes:

- `studio.status` **ya incluye** `'audit_pending'` y `'audit_approved'` en su CHECK.
- `verbatim_codes.source` **ya incluye** `'audit_correction'` (la corrección de
  auditoría se registra como una asignación con ese `source`).
- `studio.audit_percentage numeric(5,2) default 10` y
  `processing_runs.audit_percentage` ya existen. **El usuario pidió mover el % de
  auditoría de `studio` a `rounds`** (aún no hecho — ver 0.4).
- `processing_runs.random_seed` existe → permite **muestreo reproducible**.

### 0.3 Patrones del código a respetar (no reinventar)

**Backend** (`backend/app/`)
- Es un **servicio de procesamiento** con acceso a datos por **SQL explícito**
  (`text()`) en `repositories.py`. **No hay ORM vivo** (el de `models.py` es dead
  code). El Centro de Resolución es el molde exacto a imitar:
  - Router `routers/resolution.py` bajo `prefix="/api/v1"`, deps
    `current_user` + `get_db`.
  - Orquestación transaccional en `pipeline/resolution.py` (`resolve_group`):
    valida, muta, `log_action(...)`, `db.commit()`, devuelve dict serializable.
  - Concurrencia con **optimistic locking**: `expected_status` → `409 Conflict`
    (`ResolutionConflict`), idempotencia si ya está resuelto.
  - Errores mapeados a HTTP: `LookupError→404`, `ValueError→400`,
    `BelowThresholdError→422`, conflicto→409.
- Cómo se unen verbatim↔código↔grupo (base de la tabla de auditoría):
  `verbatim_codes (is_active) → verbatims (mention_group_id) → codes`. Ver
  `repositories.get_group_detail` y `process._process_brands`.
- Tareas largas: se encolan como background task y el front hace *polling* de
  `GET /studios/{id}` (ver `_process_studio_task`, `status: processing`).

**Frontend** (`frontend/src/`, **bun**, no npm)
- Rutas en `App.tsx` (`/studios/:studioId/resolution` es el vecino directo).
- API client tipado en `api/client.ts` + tipos en `api/types.ts` (sin `any`).
- Design system por tokens Tailwind: `card`, `input`, `btn-primary`, `btn-ghost`,
  `badge-{success,warning,error,pending,auto}`, `kbd-hint`, colores `p-text`,
  `p-text-muted`, `p-text-faint`, `p-accent`, `p-surface`, `p-border`,
  `p-bg-subtle`, `p-success/warning/error`. **Reusar, no crear nuevos.**
- Motion con `framer-motion`, íconos `lucide-react`, toasts vía
  `useVerbatixStore().showToast`, `Breadcrumb`, atajos de teclado con
  `registerShortcuts()/useKeyboardShortcuts()`, feedback sonoro opcional.
- El Centro de Resolución (`ResolutionCenter.tsx` + `ResolutionSidebar.tsx`) es la
  **referencia de UX**: cola a la izquierda, panel de trabajo a la derecha,
  navegación por teclado, remoción optimista con rollback, "todo resuelto" state.
- `StudioSummaryCards.tsx` es donde hoy vive el CTA "Pendiente → Centro de
  Resolución"; el CTA "Auditar" nace como hermano de ese.

### 0.4 La única migración pendiente que toca a esta feature

El usuario dijo: *"el % de auditoría ahora está en el estudio pero se moverá a la
ronda"*. Hoy: `studio.audit_percentage` + input en el **paso Estudio** del
`CreationWizard.tsx` (`sAudit`, enviado en `createStudio`). El destino: la ronda
lo posee. Esto **es parte del alcance** (ver 1.3). El prompt debe verificar si ya
se movió antes de tocarlo.

---

## PARTE 1 — PLAN

### 1.1 Objetivo y alcance

**Objetivo.** Que el analista pueda **auditar** una muestra (definida por el % de
auditoría de la ronda) de lo que el motor + la resolución codificaron: revisar,
**por código**, los verbatims que cayeron en él; confirmarlos, **reasignarlos**,
**editarlos** o **eliminarlos**; y dejar constancia auditada de qué se hizo. Al
terminar, el estudio queda marcado como **auditado** (visible luego en el
dashboard); si no se audita, queda **sin auditar**.

**En alcance**
1. Migración `audit_percentage` de `studio` → `rounds` (+ ajuste de wizard y lectura).
2. Backend: sesión de auditoría (crear/reanudar), muestreo reproducible por código,
   endpoints de lectura y de revisión (confirmar/reasignar/editar/eliminar),
   aprobación final, y exposición del **estado de auditoría** del estudio.
3. Frontend: ruta y vista de Auditoría, CTA habilitado tras la resolución, tabla
   por código con los verbatims, acciones de editar/eliminar, progreso hacia el %,
   e indicador de estado (auditado / sin auditar) reutilizable por el dashboard.
4. Todos los casos borde de 1.7.

**Fuera de alcance** (no implementar, sí dejar los *hooks*)
- El Dashboard en sí (futuro) — solo exponer el estado que consumirá.
- Exportación / nets.
- Re-muestreo automático tras reproceso del motor (sí: invalidar/avisar).

### 1.2 Modelo de dominio de la auditoría

**El `target_percentage` es GLOBAL sobre todo lo codificado, no por código.** Es la
fracción del **total de lo que se hizo** (lo que irá al Excel) que el analista va a
revisar: 6% → se audita el 6% de todo lo codificado; 100% → se audita el 100%. La
tabla se **presenta agrupada por código** ("los verbatims donde cayeron"), pero el
tamaño de la muestra sale de la población total, no de cada código por separado.

Una **sesión** de auditoría (`audit_sessions`) por estudio, anclada al último
`processing_run`. Al iniciarla se materializa la muestra en dos pasos:

1. **Población** = todos los verbatims codificados que irán al Excel
   (`verbatims` con al menos un `verbatim_codes.is_active`). Es "lo que se hizo".
   (Si negocio quiere excluir el código de descarte/sistema, se hace con un flag;
   por defecto se incluye porque también es parte de lo hecho.)
2. **Muestra global** = `ceil(total_población * target_percentage/100)` verbatims,
   elegidos de forma **reproducible** (ver 1.4) sobre TODA la población de una vez.
   Cada verbatim muestreado se guarda como `audit_items` con `codes_snapshot` =
   foto de los códigos que tenía al muestrear (para mostrar "qué se hizo" y auditar
   cambios).

Los `audit_code_reviews` son la **capa de agrupación/presentación**: tras elegir la
muestra global, se agrupan los items por su código y se crea un `audit_code_reviews`
por cada código que tenga ≥1 item muestreado (con `items_count` = cuántos cayeron
ahí). Un código con 0 items en la muestra simplemente no aparece — es esperado y
correcto con muestreo global (un código chico puede no salir sorteado con 6%).

- `total_items` = tamaño de la muestra global; `reviewed_items` avanza a medida que
  el analista revisa; `target_met` = `reviewed_items >= total_items`.

Esto satisface literalmente el pedido: *"si se pone 6% se muestra el 6%, si se pone
100% se muestra el 100% de lo hecho"* y *"revisar grupos de códigos con los
verbatims donde cayeron: la respuesta, el verbatim, el código"*.

### 1.3 Migración: `audit_percentage` a la ronda

Nueva migración `backend/db/migrations/003_*.sql` (verificar el siguiente número
libre):
- `alter table rounds add column audit_percentage numeric(5,2) not null default 10;`
- Backfill desde el estudio si aplica (por ronda, tomar el del estudio existente).
- **Decisión de compatibilidad:** mantener `studio.audit_percentage` por ahora
  (no romper el motor / `processing_runs`), pero la **fuente de verdad para la
  sesión de auditoría pasa a ser la ronda**. La sesión lee
  `coalesce(rounds.audit_percentage, studio.audit_percentage)` para tolerar datos
  viejos. Retirar la columna del estudio queda como limpieza posterior (nota en el
  doc, no en esta entrega, para no romper `process.py`).
- Wizard: mover el input "% de auditoría" del **paso Estudio** al **paso Ronda**;
  `createRound` pasa a aceptar `audit_percentage`; `createStudio` deja de enviarlo
  (o lo hereda de la ronda). Verificar el orden real de creación en el wizard antes
  de mover.

### 1.4 Muestreo (GLOBAL, reproducible, con reglas claras)

- **Un solo tamaño, global:** `n = ceil(total_población * pct/100)` sobre TODA la
  población de verbatims codificados (no un `n` por código). Con `pct == 100` la
  muestra es la población completa; con `pct == 0` la muestra es vacía (auditoría
  trivialmente satisfecha, ver 1.7). **No** se aplica "mínimo 1 por código": con un
  % bajo, los códigos chicos pueden quedar con 0 items, que es el comportamiento
  correcto de un muestreo global.
- **Selección determinista:** ordenar TODA la población por `hash(verbatim_id ||
  seed)` y tomar los primeros `n`, con `seed = processing_runs.random_seed`
  (persistir uno si es NULL). Nada de aleatoriedad no reproducible. Reabrir la
  sesión no re-muestrea ni pierde progreso (idempotencia).
- Tras elegir la muestra, **agrupar por código** para materializar los
  `audit_code_reviews` (capa de presentación, ver 1.2).

### 1.5 Ciclo de vida y transiciones de estado

```
preliminary_ready ──(resolución completa, can_close)──▶ [CTA "Auditar" habilitado]
        │                                                        │
        │  usuario NO audita → sigue al dashboard                │ usuario inicia auditoría
        │  (estudio: "sin auditar")                              ▼
        │                                            studio.status = 'audit_pending'
        │                                            audit_session.status = 'in_progress'
        │                                                        │
        │                              revisa items (confirmar / reasignar / editar / eliminar)
        │                                                        │  target_met && aprueba
        ▼                                                        ▼
   (futuro dashboard lee el estado)              studio.status = 'audit_approved'
                                                 audit_session.status = 'approved'
```

- **Habilitación del CTA:** solo cuando la resolución está completa
  (`resolution/summary.can_close == true`). Antes, el CTA se muestra deshabilitado
  con tooltip ("Resolvé las anomalías pendientes primero").
- **"Auditar" es opcional:** el usuario puede saltar al dashboard. El estado de
  auditoría (`not_started`) se expone igual.
- **Aprobación** exige `target_met` (o `audit_percentage == 0`). Al aprobar, cada
  `audit_code_review` sin ítems reasignados → `approved`; con reasignaciones →
  `with_corrections`.

### 1.6 Diseño técnico

#### Backend — nuevo router `routers/audit.py` + orquestador `pipeline/audit.py`

Endpoints (todos bajo `/api/v1`, con `current_user`), imitando el estilo de
`resolution.py`:

| Método + ruta | Propósito |
|---|---|
| `POST /studios/{id}/audit/session` | Crear **o reanudar** (idempotente) la sesión; materializa muestra; setea `audit_pending`. Devuelve resumen. |
| `GET  /studios/{id}/audit/session` | Resumen: `target_percentage`, `total_items`, `reviewed_items`, `progress_pct`, `target_met`, `status`, contadores por estado. |
| `GET  /studios/{id}/audit/codes` | Lista de `audit_code_reviews`: código (número/label/net), `items_count`, `reviewed`, `corrections_count`, `status`. |
| `GET  /audit-code-reviews/{id}/items` | Items del código: verbatim (original + normalizado), `codes_snapshot`, códigos actuales, `status`, `comment`. Paginado. |
| `POST /audit-items/{id}/review` | Acción: `correct` \| `reassign(code_ids / new_code)` \| `remove`. Escribe `verbatim_codes` (`source='audit_correction'`) o desactiva; actualiza item + contadores + `audit_logs`; `expected_status` opcional (409). |
| `PATCH /audit-items/{id}` | Editar `comment` / `status` sin cambiar códigos. |
| `DELETE /audit-items/{id}` | **Eliminar**: desactiva la(s) asignación(es) del verbatim (queda sin código → `coding_status='needs_review'`), item `status='reassigned'` con nota, `corrections_count++`, log. Reversible vía log. |
| `POST /studios/{id}/audit/approve` | Finaliza (requiere `target_met`); `audit_approved`. |

- Repos nuevos en `repositories.py` (SQL explícito): `create_or_get_audit_session`,
  `sample_audit_items`, `get_audit_summary`, `list_audit_code_reviews`,
  `list_audit_items`, `review_audit_item`, `remove_audit_item`,
  `approve_audit_session`. Reusar `create_code`, `log_action`,
  `_current_codebook_id`, `list_studio_codes`.
- Exponer el **estado de auditoría** en `GET /studios/{id}` (bloque `audit: {
  status: 'not_started'|'in_progress'|'approved', reviewed_items, total_items,
  target_met }`) para el dashboard futuro y los badges. Verificar la forma actual
  de `get_studio` antes de extenderla.
- Reglas de integridad: reasignar a código inexistente → `create_code` (dedupe);
  la corrección escribe `verbatim_codes` con `on conflict do update set is_active`,
  respetando el índice único `(verbatim_id, code_id)`; toda mutación en una sola
  transacción + `log_action` antes del `commit`.

#### Frontend

- **Ruta** en `App.tsx`: `/studios/:studioId/audit` → `AuditView.tsx`. (Mismo
  patrón que `/resolution`.)
- **Tipos** en `api/types.ts` y **funciones** en `api/client.ts`
  (`getAuditSession`, `createAuditSession`, `getAuditCodes`, `getAuditItems`,
  `reviewAuditItem`, `patchAuditItem`, `deleteAuditItem`, `approveAudit`).
- **CTA "Auditar"** en `StudioSummaryCards.tsx` (hermano del card "Pendiente"):
  habilitado cuando `can_close`; junto a un CTA secundario "Ir al dashboard"
  (deshabilitado/placeholder, con tooltip "Próximamente"). Reflejar el estado de
  auditoría con un badge (`badge-success` "Auditado" / `badge-pending` "Sin
  auditar" / `badge-warning` "En auditoría").
- **`AuditView.tsx`** (layout tipo master-detail, coherente con Resolución):
  - Breadcrumb + header con **barra de progreso** hacia el `target_percentage` y
    badge de estado; botón "Aprobar auditoría" (habilitado si `target_met`).
  - Izquierda: **lista de códigos** (`audit_code_reviews`) con progreso por código
    y estado (pending/approved/with_corrections), seleccionable.
  - Derecha: **tabla del código seleccionado** con columnas: *Respuesta* (verbatim
    `original_text`), *Normalizado*, *Código actual*, *Qué se hizo* (estado +
    snapshot), *Comentario*, *Acciones*. "Qué verbatims cayeron en ese código" se
    resuelve mostrando el `items_count`/frecuencia del código y su muestra.
  - **Acciones por fila:** Marcar correcto · Reasignar (selector de código, reusar
    grid de códigos/estilo de `ResolutionSidebar`) · Editar (comentario) ·
    **Eliminar** (quita la asignación; confirmación ligera). Remoción/actualización
    **optimista con rollback** (patrón `applyOptimisticRemoval`).
  - **Atajos de teclado** consistentes (`registerShortcuts("audit-view", …)`):
    marcar correcto, reasignar, editar, eliminar, navegar; y `?` para el panel de
    atajos.
  - Estados vacíos: sin muestra (pct 0 / sin codificados), "todo revisado", carga
    (skeletons como en Resolución).
- **Accesibilidad/UX:** foco manejado, `aria-*` en la tabla y controles, sonido
  opcional reutilizando el helper de `ResolutionSidebar`, animaciones sutiles y
  coherentes (no nuevas primitivas visuales).

### 1.7 Casos borde (contemplar TODOS)

1. **`audit_percentage == 0`** → muestra vacía; auditoría "satisfecha" al instante;
   `approve` permitido sin items; estudio pasa a `audit_approved` marcando
   "auditado (0%)". Dejar claro en UI que no había muestra.
2. **Nada codificado** (todo descartado/anomalías) → sin `audit_code_reviews`;
   estado vacío explicativo; `approve` permitido.
3. **Resolución incompleta** → CTA deshabilitado; intentar `POST session` → 409/422
   con mensaje claro.
4. **Redondeo / códigos pequeños** → `ceil` + mínimo 1 si pct>0; documentar.
5. **Reasignar a código nuevo** → `create_code` (dedupe por label normalizado).
6. **Eliminar la última asignación de un verbatim** → verbatim queda sin código;
   `coding_status='needs_review'`; log; visible como "sin código".
7. **Idempotencia / reanudar** → reabrir la sesión no re-muestrea ni pierde
   progreso; doble-submit de una revisión es no-op.
8. **Concurrencia** → `expected_status` en revisiones → 409 con aviso (last-write
   con advertencia), igual que Resolución.
9. **Reproceso del motor tras auditar** → la sesión referencia un `processing_run`;
   si hay un run nuevo, marcar la sesión como **desactualizada** y ofrecer
   re-muestrear (no borrar la vieja silenciosamente; avisar).
10. **Ambos `coding_type`** (brands y reasons) auditables con la misma vista.
11. **Muestreo reproducible** con `random_seed` persistido.
12. **Permisos/roles** → registrar `reviewer_id`/`approved_by`; `analyst` puede
    auditar; respetar el patrón de auth existente (no añadir gating nuevo salvo que
    exista).
13. **Estudio no encontrado / sin codebook** → 404 con mensaje.
14. **% de auditoría en ronda vs estudio** → leer con `coalesce` mientras conviven.
15. **Navegación directa por URL** a `/audit` sin sesión creada → crear/redirigir
    con estado claro (no crashear).
16. **Borrado en cascada** → al borrar estudio/ronda, las tablas de auditoría caen
    por FK `on delete cascade` (verificado en schema); no dejar huérfanos.

### 1.8 Orden de implementación sugerido

1. **Migración 003** (`rounds.audit_percentage` + backfill) y ajuste de wizard/`createRound`.
2. **Backend auditoría**: repos + `pipeline/audit.py` + `routers/audit.py`, registrar router en `main.py`; extender `get_studio` con el bloque `audit`.
3. **Tests backend** (SQLite/StaticPool o FakeSession): muestreo (tamaños, mínimo 1, pct 0), idempotencia, revisión (correct/reassign/remove), aprobación con/sin target, 409 por conflicto, cascada.
4. **API client + tipos** frontend.
5. **CTA + badges** en `StudioSummaryCards` (y donde se liste el estudio).
6. **`AuditView.tsx`** + ruta + atajos + estados vacíos/carga.
7. **Verificación end-to-end** (skill `verify`/`run`): flujo completo resolución→auditar→aprobar; typecheck (`bunx tsc --noEmit`), lint (`bun run lint`), `pytest backend/tests -v`.

---

## PARTE 2 — PROMPT DE IMPLEMENTACIÓN (autónomo y adaptativo)

> Pegar este bloque como instrucción a un agente implementador. Está diseñado para
> **no asumir** que el sistema quedó como en la Parte 0: obliga a leer el estado
> real primero.

```text
Vas a implementar la feature de AUDITORÍA descrita en
docs/features/audit/00-plan-y-prompt.md (Partes 0 y 1). El plan es tu norte, pero
el código pudo cambiar desde que se escribió. NO ASUMAS: verifica el estado real
ANTES de escribir código, y adapta el plan a lo que encuentres. Si algo del plan
contradice el código actual, gana el código y lo dejas anotado.

═══ PASO 0 — LECTURA OBLIGATORIA (antes de tocar nada) ═══
Lee y confirma el estado real de:
1. Schema y migraciones: backend/db/migrations/*.sql — confirma que existan
   audit_sessions, audit_code_reviews, audit_items, audit_logs con las columnas
   del plan; que studio.status incluya 'audit_pending'/'audit_approved'; que
   verbatim_codes.source incluya 'audit_correction'; y si audit_percentage YA se
   movió a rounds o sigue en studio. Determina el siguiente número de migración libre.
2. El flujo predecesor (Resolución) COMO ESTÉ HOY: backend/app/routers/resolution.py,
   backend/app/pipeline/resolution.py, y en el front ResolutionCenter.tsx +
   ResolutionSidebar.tsx + StudioSummaryCards.tsx. Es tu molde de estilo y UX.
3. Acceso a datos: backend/app/repositories.py (patrón SQL con text(); cómo se unen
   verbatims↔verbatim_codes↔codes↔mention_groups; log_action; _current_codebook_id;
   create_code; list_studio_codes). backend/app/pipeline/process.py (cómo se asignan
   códigos y el random_seed en processing_runs).
4. Cableado: backend/app/main.py (registro de routers) y routers/studios.py
   (forma real de GET /studios/{id}, que vas a extender con el bloque `audit`).
5. Front: App.tsx (rutas), api/client.ts + api/types.ts (contratos), CreationWizard.tsx
   (dónde vive hoy el input "% de auditoría" y el orden real de creación de ronda/estudio),
   y los tokens del design system (card, input, btn-*, badge-*, kbd-hint, colores p-*).
6. CLAUDE.md (comandos, estilo, reglas: bun no npm; SQL explícito; sin `any`; sin
   dependencias nuevas sin justificar; tests con SQLite/StaticPool o FakeSession).

═══ PASO 1 — QUÉ CONSTRUIR (contrato de comportamiento) ═══
Implementa, respetando 1.2–1.7 del plan:
· Migración: rounds.audit_percentage (+ backfill), y mueve el input del % al paso
  Ronda del wizard; createRound lo acepta; la sesión de auditoría lee
  coalesce(rounds.audit_percentage, studio.audit_percentage). No rompas process.py.
· Backend (imitando resolution.py):
  - pipeline/audit.py (orquestación transaccional: muestreo reproducible con
    random_seed; ceil + mínimo 1 si pct>0; muestra vacía si pct==0) y
    routers/audit.py con los endpoints de la tabla 1.6 (crear/reanudar sesión
    idempotente, resumen, códigos, items, review correct/reassign/remove, patch,
    delete, approve). Registra el router en main.py.
  - Corrección de auditoría = verbatim_codes con source='audit_correction'
    (respeta el único (verbatim_id, code_id)); eliminar = desactiva asignación y
    deja el verbatim en 'needs_review'. log_action en cada mutación, dentro de la
    misma transacción, antes del commit.
  - Optimistic locking con expected_status → 409; idempotencia si ya revisado/aprobado.
    Errores: LookupError→404, ValueError→400, conflicto→409, precondición→422.
  - Extiende GET /studios/{id} con audit: { status, reviewed_items, total_items,
    target_met } para el dashboard futuro y los badges.
· Frontend:
  - Ruta /studios/:studioId/audit → AuditView.tsx. Tipos + funciones en
    api/types.ts / api/client.ts (sin `any`).
  - CTA "Auditar" en StudioSummaryCards (hermano de "Pendiente"), habilitado solo si
    resolution/summary.can_close; CTA secundario "Ir al dashboard" como placeholder
    deshabilitado; badge de estado (Auditado / Sin auditar / En auditoría).
  - AuditView master-detail: lista de códigos (audit_code_reviews) a la izquierda;
    a la derecha la tabla del código con columnas Respuesta / Normalizado / Código
    actual / Qué se hizo / Comentario / Acciones. Acciones: marcar correcto,
    reasignar (reusa el grid/estilo de códigos de ResolutionSidebar), editar
    comentario, ELIMINAR. Actualización optimista con rollback. Barra de progreso
    hacia el %, botón Aprobar (activo si target_met). Atajos de teclado
    (registerShortcuts("audit-view", …)) coherentes con Resolución. Estados
    vacíos/carga con skeletons.

═══ PASO 2 — CASOS BORDE ═══
Cubre TODOS los de 1.7 (pct 0, nada codificado, resolución incompleta, redondeo,
reasignar a código nuevo, eliminar última asignación, idempotencia/reanudar,
concurrencia, reproceso posterior, ambos coding_type, roles, sin codebook, % en
ronda vs estudio, deep-link sin sesión, cascada de borrado).

═══ PASO 3 — CALIDAD Y ESTILO (no negociable) ═══
· Reusa el design system y los patrones existentes; NO inventes primitivas ni
  agregues dependencias sin justificar contra el stack actual.
· Python snake_case + type hints + SQL por text() en repositories; TS/React
  PascalCase/camelCase, strict, sin `any`; Tailwind + @layer components.
· Sin dead code: si mueves el % de auditoría, limpia lo que quede huérfano.
· Comenta como el código vecino (densidad y estilo del Centro de Resolución),
  en español, explicando el PORQUÉ de las decisiones no obvias.

═══ PASO 4 — VERIFICACIÓN (obligatoria antes de decir "listo") ═══
· Tests backend nuevos (SQLite/StaticPool o FakeSession, nunca DB real): muestreo
  (tamaños, mínimo 1, pct 0), idempotencia de la sesión, review
  (correct/reassign/remove), approve con y sin target_met, 409 por conflicto,
  cascada de borrado. Corre: pytest backend/tests/ -v
· Front: cd frontend && bunx tsc --noEmit && bun run lint && bun run build
· Ejercita el flujo real end-to-end (skill verify/run): resolución completa →
  Auditar → revisar/reasignar/editar/eliminar → aprobar → estado "auditado";
  y el camino "no auditar" → estado "sin auditar". Reporta resultados reales
  (si algo falla, dilo con el output). No declares terminado sin observar el flujo.

Entrega un resumen de: qué verificaste en el PASO 0 y qué difería del plan, qué
migración number usaste, endpoints y componentes creados, casos borde cubiertos, y
salida de tests/typecheck/lint/verify.
```

---

### Notas para el autor del plan (no van al implementador)
- El schema ya trae toda la auditoría; el riesgo está en el **cableado y el
  muestreo reproducible**, no en el modelo.
- La decisión de compatibilidad de `audit_percentage` (coalesce ronda/estudio) evita
  romper `process.py`/`processing_runs`; retirar la columna del estudio es limpieza
  posterior.
- Punto de decisión abierto para validar con negocio: si el % se muestrea **por
  código** (elegido, encaja con `audit_code_reviews`) o **global** sobre todos los
  verbatims. El plan asume por-código porque el schema y el pedido lo favorecen.

---

## REGISTRO DE IMPLEMENTACIÓN (2026-07-13)

Qué difería del plan al implementar (ganó el código):

1. **La migración 1.3 ya estaba hecha.** `003_round_level_thresholds.sql` ya había
   movido `audit_percentage` (y `min_mentions_threshold`) de `studio` a `rounds`,
   dropeando la columna del estudio; el wizard ya pedía el % en el paso Ronda y
   `createRound` ya lo aceptaba. No hubo migración nueva ni `coalesce`: la sesión
   lee `rounds.audit_percentage` directo.
2. **`processing_runs.random_seed` existía pero el motor nunca lo seteaba.** La
   sesión de auditoría genera y persiste uno al muestrear si está NULL.
3. **Los tests del repo usan FakeSession + patch** (no SQLite/StaticPool);
   `tests/test_audit.py` sigue ese molde (33 tests).
4. **No existe script `lint`** en `frontend/package.json` (CLAUDE.md lo menciona);
   la verificación fue `tsc -b && vite build` dentro del contenedor.
5. **Items multi-código:** un verbatim muestreado se cuelga de su código primario
   (`output_index=1`) para que `total_items` == tamaño de la muestra; el
   `codes_snapshot` conserva todos sus códigos.
6. Muestreo **global** (decisión del punto abierto): `ceil(población · pct/100)`
   ordenando por `sha256(verbatim_id:seed)` — reproducible y monótono (subir el %
   solo agrega ítems, no reordena).

Entregado: `pipeline/audit.py` + `routers/audit.py` (8 endpoints), repos de
auditoría en `repositories.py`, bloque `audit` en `GET /studios/{id}`,
`AuditView.tsx` + ruta `/studios/:studioId/audit`, CTA "Auditar" + badge y
placeholder "Ir al dashboard" en `StudioSummaryCards`. Verificado e2e por API:
precondición 422, muestra 45/441 (10%), idempotencia, correct/reassign(+código
nuevo)/remove/patch, 409 por conflicto y tras aprobar, approve con gate 422,
`audit_approved`, `with_corrections`, `audit_logs` completos y
`source='audit_correction'` en la corrección.
