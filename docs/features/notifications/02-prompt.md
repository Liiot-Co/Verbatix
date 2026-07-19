# Notificaciones + bandeja de entrada — PROMPT DE IMPLEMENTACIÓN

> Pégale esto a quien vaya a implementar (o a un agente). Es autónomo, pero
> apóyate en [`00-contexto.md`](00-contexto.md) y [`01-plan.md`](01-plan.md)
> para el detalle y el porqué. Todas las rutas/líneas ya están verificadas
> contra el código.

---

## Rol y objetivo
Implementa la función de **notificaciones in-app + bandeja de entrada** de
Verbatix: 3 eventos, recordatorio a las 4 h, campana con badge, dropdown, página
de bandeja completa, push animado y un sonido agradable. Debe integrarse con el
flujo y el stack actuales **sin romper nada**.

## Principios innegociables
1. **Sigue el flujo y el estilo existentes.** Python snake_case + SQL explícito
   con `text()` en `repositories.py`; TS/React con tipos estrictos (nada de
   `any`), PascalCase en componentes; Tailwind con tokens `p-*`.
2. **BD: solo lo necesario, y justifícalo.** La tabla `notifications` ya existe
   (`002_schema_v9.sql:205-215`, modelo `models.py:522`). Añade **solo** dos
   columnas y un índice (ver abajo) porque el recordatorio y la señal de sonido
   necesitan estado no derivable. Nada más.
3. **Código limpio y desacoplado.** Store de notificaciones aparte; servicio de
   emisión aislado; triggers "delgados"; canal de push propio. Nada acoplado al
   núcleo de auth/navegación.
4. **Rendimiento consciente de hilos/async** (ver sección Backend).
5. **Sin dependencias nuevas** — todo lo necesario ya está instalado.
6. **No romper lo existente:** no edites migraciones aplicadas, ni
   `ToastStack`/`showToast`, ni `playSuccess`/`playTick`, ni la lógica de
   asignación/auditoría (solo **añade** la emisión tras el commit).

---

## Backend

### 1. Migración `backend/db/migrations/003_notifications_reminders.sql`
Aditiva e idempotente, mismo encabezado auto-documentado que `002_schema_v9.sql`:
```sql
alter table notifications
  add column if not exists last_reminded_at timestamptz,
  add column if not exists reminder_count   smallint not null default 0;
create index if not exists notifications_unread_created_idx
  on notifications (created_at) where is_read = false;
```
Refleja las dos columnas en el modelo `Notification` (`models.py`). **No** agregues
`CHECK` sobre `type`.

### 2. `repositories.py` (SQL explícito con `text()`)
- `create_notifications(db, user_ids, type, title, body, related_entity_id)` —
  **un** `insert ... select unnest(:uids::uuid[])` (no bucle). Deduplica y
  descarta lista vacía.
- `list_notifications(db, user_id, limit, offset, only_unread)`.
- `notification_stream_state(db, user_id) -> (unread_count, signal)` en una query:
  `count(*) filter (where not is_read)` y
  `max(greatest(created_at, coalesce(last_reminded_at, created_at))) filter (where not is_read)`
  como epoch-ms `bigint` (0 si no hay).
- `notification_preview(db, user_id)` — la no-leída más reciente.
- `mark_notification_read(db, user_id, id)` y `mark_all_notifications_read(db, user_id)`
  — siempre con `user_id` en el `WHERE`.
- `sweep_reminders(db, max_reminders) -> list[row]` — el UPDATE guardado del plan §2.2.
- `project_supervisor_ids(db, project_id)` — `assignments` activo (`status='active'
  and revoked_at is null`) join `user_roles.role_code='supervisor'`.
- `global_admin_ids(db)` — `user_roles.role_code='admin'`.

### 3. `app/services/notifications.py` (nuevo)
`emit(db, *, type, title, body, related_entity_id, user_ids)`: valida `type`
contra `Literal["project_assigned","ready_for_audit","audit_approved"]`,
deduplica, delega en `create_notifications`. Los triggers solo llaman aquí.

### 4. `app/routers/notifications.py` (nuevo) + registrar en `main.py`
Prefijo `/api/v1/notifications`, todos con `Depends(current_user)`:
- **`GET /stream?since_signal=<int>`** — `async def`. Bucle hasta ~25 s:
  cada ~1 s calcula `(unread, signal)` con
  `await run_in_threadpool(...)` usando una **`SessionLocal()` efímera** (abrir/
  cerrar por chequeo, no un `Session` sostenido; `asyncio.sleep`, no `time.sleep`).
  Responde `{unread_count, signal, preview}` en cuanto `signal > since_signal`, o
  al timeout con el estado actual.
- `GET ?limit=&offset=&only_unread=` — lista.
- `GET /unread-count` — conteo inmediato (sembrar badge).
- `POST /{id}/read` · `POST /read-all`.

### 5. Triggers (solo **añadir** emisión tras el commit del núcleo, en `try/except`+log)
- **`routers/assignments.py:46`** (tras `db.commit()` en `create_assignment`):
  `emit(type="project_assigned", user_ids=[payload.user_id],
  related_entity_id=project_id, ...)`. Omite si el destinatario es el actor.
- **`pipeline/audit.py:149`** (`start_audit_session`, junto a
  `set_round_status(db, round_id, "audit_pending")`): lee el status de la ronda
  **antes**; emite `ready_for_audit` **solo si** el status previo no era ya
  `audit_pending` (evita re-notificar en cada apertura de la vista).
  Destinatarios = `project_supervisor_ids(project_id)`; **si vacío →
  `global_admin_ids()`**. Deduplica y excluye al actor. `related_entity_id = round_id`.
- **`pipeline/audit.py:335`** (`approve_session`, junto a
  `set_round_status(db, ctx["round_id"], "audit_approved")`): lee status
  **antes**, llama, **relee después**; emite `audit_approved` a `global_admin_ids()`
  **solo si** `previo != 'audit_approved' and posterior == 'audit_approved'` (una
  vez por ronda). `related_entity_id = round_id`.

### 6. Recordatorio `app/core/reminders.py` (nuevo) + `lifespan` de `main.py`
Hilo daemon al estilo de `core/scheduler.py`; arráncalo/páralo junto a
`scheduler.start()/stop()`. Cada ~60 s (`threading.Event.wait(timeout)` para
parada limpia) ejecuta `sweep_reminders` en una sesión corta propia. **No** uses
advisory lock: el UPDATE atómico guardado ya es idempotente entre los 2 workers
(plan §2.2). Parámetros por config: intervalo, `max_reminders` (default 3),
ventana 4 h.

---

## Frontend (bun; sin deps nuevas)

### 7. `api/types.ts` + `api/client.ts`
Tipos `Notification`, `NotificationPreview`, `NotificationStream`,
`NotificationList`. Funciones con el patrón `request<T>()`:
`streamNotifications(sinceSignal, signal?: AbortSignal)`, `getNotifications`,
`getUnreadCount`, `markNotificationRead`, `markAllNotificationsRead`.

### 8. `store/useNotificationStore.ts` (nuevo, Zustand separado)
`unread`, `signal`, `muted` (persistido `verbatix:notif-muted`), `items`,
`toasts` (canal propio), y acciones `setStreamState/setItems/pushToast/
dismissToast/toggleMuted`.

### 9. `hooks/useNotificationPoll.ts` (nuevo) — montar una vez en `AppShell`
Arranca con `user` presente, para en logout. Bucle `fetch` del `/stream` con
`AbortController` que **re-dispara de inmediato**; backoff 3–5 s en fallo de red.
**Semilla sin sonido** en el primer response; en incrementos de `signal`:
`playNotification()` (si `!muted`, rate-limit ~2 s) + refresca lista +
`pushToast(preview)`. Guarda un `ref` anti-doble-montaje de StrictMode; `abort()`
en cleanup. Siembra el badge al montar con `getUnreadCount()`.

### 10. `lib/sound.ts` — añade `playNotification()`
Exactamente (reutiliza el `tone()` existente, sin assets):
```ts
export function playNotification(): void {
  const audioCtx = getContext();
  if (!audioCtx) return;
  const t = audioCtx.currentTime;
  tone(587.33, t,        0.14, 0.050, audioCtx); // D5
  tone(880.00, t + 0.10, 0.22, 0.045, audioCtx); // A5 (quinta justa)
  tone(1760.0, t + 0.10, 0.12, 0.015, audioCtx); // brillo tenue
}
```
Un solo sonido para los 3 eventos. Maneja el rechazo de autoplay sin romper UI.
(Fundamentos psicológicos: plan §6.)

### 11. `AppShell.tsx` — campana + badge
Junto al bloque de usuario (patrón `menuRef`/`menuOpen`, líneas 160-203) añade un
botón `Bell` con `bellRef`/`bellOpen` propios. Badge con el `unread`; anima un
"pop" (framer-motion `scale`) cuando el conteo **sube**. Abre `NotificationsPanel`.
Añade enlace "Bandeja" → `/notifications`.

### 12. `components/NotificationsPanel.tsx` (nuevo, dropdown)
Últimas ~8, icono por tipo, timestamp relativo, clic → marcar leído + navegar
(`project_assigned`→`/projects/:id`, `ready_for_audit`→`/rounds/:id/audit`,
`audit_approved`→`/rounds/:id/report`). "Marcar todas como leídas", "Ver todas" →
`/notifications`, y toggle de silencio.

### 13. `components/NotificationToast.tsx` (nuevo, canal propio — NO tocar `ToastStack`)
Chip de icono con color por tipo (`UserPlus`/`ClipboardCheck`/`ShieldCheck`),
título en negrita + cuerpo atenuado, entrada **spring** (misma familia que
`ToastStack.tsx:29`), `layout` para apilar, barra de auto-cierre (~5 s), clic →
navega + marca leído, botón X. Respeta `prefers-reduced-motion`.

### 14. `components/NotificationsInbox.tsx` (nuevo) + ruta en `App.tsx`
`<Route path="/notifications" element={<NotificationsInbox />} />` dentro del
`AppShell` (sin capability guard). Lista paginada (limit/offset), filtro **Todas /
No leídas**, agrupada por día (Hoy/Ayer/fecha), iconos por tipo, estado vacío
cuidado, marcar-todo-leído, y por item marcar-leído + navegar.

---

## Casos borde que DEBEN quedar cubiertos (ver plan §7)
Fallback a admins sin supervisor · dedup admin-que-es-supervisor · no re-notificar
al reabrir auditoría · evento 3 una sola vez por ronda · excluir al actor ·
recordatorio 4 h con tope · idempotencia del barrido entre 2 workers · autoplay
bloqueado · usuario offline (semilla sin sonido).

## Pruebas — `backend/tests/test_notifications.py` (estilo `test_audit.py`)
Repos (CRUD + audiencia + fallback + dedup); triggers (asignar=1; ready_for_audit
solo en la 1ª transición; audit_approved 1×/ronda); barrido (bump, idempotencia,
tope, no toca leídas); señal (monotonicidad). Todo con SQLite/StaticPool o
FakeSession — nunca BD real.

## Criterios de aceptación
- [ ] Los 3 eventos generan la notificación correcta a la audiencia correcta,
      con todos los casos borde de arriba.
- [ ] Recordatorio a las 4 h re-empuja (suena + badge) hasta el tope; idempotente.
- [ ] Campana con badge animado, dropdown funcional y página `/notifications`.
- [ ] Push animado con icono; sonido agradable, único, silenciable; sin romper
      `ToastStack` ni los sonidos existentes.
- [ ] `pytest backend/tests/ -v` verde (incluye `test_notifications.py`).
- [ ] `cd frontend && bunx tsc --noEmit` y `bun run lint` verdes.
- [ ] Nada de lo existente cambia de comportamiento (asignación/auditoría intactas).

## Cierre
Tras implementar, corre `graphify update .` (regla del `CLAUDE.md`).
