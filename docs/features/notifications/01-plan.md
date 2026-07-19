# Notificaciones + bandeja de entrada — PLAN

> Insumo: [`00-contexto.md`](00-contexto.md) (panorama verificado 2026-07-18).
> Este documento es el **plan** de implementación. El prompt de ejecución vive
> en [`02-prompt.md`](02-prompt.md).
>
> Todo lo de aquí está verificado contra el código actual (rutas y líneas
> citadas leídas, no asumidas). Principios rectores: seguir el flujo existente,
> tocar la BD solo si es necesario (y justificarlo), código limpio y
> desacoplado, y rendimiento consciente de hilos/async — sin romper nada.

---

## 1. Alcance

Tres eventos in-app (ninguno por correo), más dos requisitos nuevos que pidió
el usuario y que el contexto no cubría:

| # | Evento | Destinatario base | Extra |
|---|---|---|---|
| 1 | Admin asigna proyecto | El usuario asignado | — |
| 2 | Subproyecto listo para auditar | Supervisores del proyecto | **Fallback: si no hay supervisor → admins** |
| 3 | Supervisor aprueba la auditoría de la ronda | Todos los admins | Una sola vez por ronda |

**Nuevos requisitos del usuario:**
- **Recordatorio a las 4 h:** si una notificación sigue sin leerse, se vuelve a
  "empujar" (re-suena + sube el badge), con tope para no acosar.
- **Bandeja de entrada completa** (página `/notifications`), no solo el dropdown.
- **Sonido agradable** (no irritante) basado en la psicología de WhatsApp/IG/FB.
- **Push visual creativo**: toast animado con iconos, sin romper el toast actual.

---

## 2. Decisiones de arquitectura (con el porqué)

### 2.1 Entrega — long polling, refinado a `async` + threadpool

Se mantiene la decisión del contexto (§0.4): **long polling** con espera en el
servidor. Refinamiento obligatorio que el contexto no fijaba:

- El endpoint es **`async def`** y hace cada chequeo de BD con
  `starlette.concurrency.run_in_threadpool(...)`. SQLAlchemy es **síncrono**:
  llamarlo directo dentro de un `async def` **bloquea el event loop** y con él
  todas las demás peticiones del worker. `run_in_threadpool` mueve el chequeo a
  un hilo y deja el loop libre para atender el resto.
- La espera entre chequeos es `await asyncio.sleep(~1s)` — **nunca**
  `time.sleep` (congelaría el worker) ni un `Session` abierto durante la espera.
- **Sesión corta por chequeo:** abrir `SessionLocal()`, medir, cerrar. Con ~50
  usuarios en long poll, mantener 50 conexiones abiertas agotaría el pool
  (`pool_size=5 + max_overflow=10 = 15` por worker, ver
  `backend/app/core/database.py:10`). Abriendo/cerrando por chequeo, en un
  instante dado solo unos pocos usuarios están "mid-check" → holgado.
- Timeout de servidor **~25 s**, cómodo bajo el `proxy_read_timeout` default de
  nginx (60 s, `frontend/nginx.conf`) — no hay que tocar nginx.

### 2.2 Recordatorio 4 h — barrido idempotente en hilo daemon

El proyecto **ya tiene** un patrón de trabajo en segundo plano basado en hilos:
`backend/app/core/scheduler.py` (pool de hilos daemon arrancado en el `lifespan`
de `main.py:20`). El recordatorio **replica ese estilo** en un módulo nuevo
`backend/app/core/reminders.py`, arrancado/parado junto al scheduler.

**El problema de los 2 workers y por qué NO necesitamos leader-election:**
`docker-compose.prod.yml` corre `uvicorn --workers 2`. Un hilo de barrido
correría en **ambos** workers. En vez de un advisory lock / elección de líder
(infra que 3 eventos raros no justifican — principio "solo lo necesario"), el
barrido es un **UPDATE atómico y guardado**, idempotente entre workers:

```sql
update notifications
set last_reminded_at = now(), reminder_count = reminder_count + 1
where is_read = false
  and reminder_count < :max_reminders            -- tope (p.ej. 3)
  and now() - greatest(created_at, coalesce(last_reminded_at, created_at))
        >= interval '4 hours'
returning id, user_id;
```

Si el worker A ejecuta el UPDATE, mueve `last_reminded_at` a `now()`; cuando el
worker B lo ejecuta ~ε después, esas filas ya fallan el predicado de intervalo →
0 filas. Y si corren a la vez, el **row-lock de Postgres** los serializa y el
segundo re-evalúa el `WHERE` contra la versión ya actualizada → tampoco las
toca. Resultado: **recordatorio exactamente una vez**, sin coordinación. El hilo
duerme con `threading.Event.wait(timeout)` para que `stop()` sea inmediato.

### 2.3 Señal de sonido — un solo valor que cubre "nuevo" y "recordatorio"

En vez de reproducir el sonido "cuando sube el conteo de no-leídas" (que no
capta los recordatorios, porque un recordatorio no cambia el conteo), el stream
devuelve una **señal monótona**:

```
signal = max( greatest(created_at, coalesce(last_reminded_at, created_at)) )
         entre las no-leídas del usuario           → epoch en ms (bigint)
```

- Notificación nueva → `created_at` es el nuevo máximo → señal sube.
- Recordatorio → `last_reminded_at` pasa a ser el máximo → señal sube.

El cliente guarda la última señal y **suena solo cuando la señal aumenta**. Esto
evita filas duplicadas para los recordatorios (bandeja limpia, almacenamiento
acotado, escalable) y unifica ambos casos en un único mecanismo de cliente.

---

## 3. Cambios de esquema — sí, mínimos y justificados

La tabla `notifications` **ya existe** (`002_schema_v9.sql:205-215`, modelo en
`models.py:522`). Para 0.1 base **no hace falta ninguna tabla ni columna nueva**.
Los dos requisitos nuevos (recordatorio + señal) sí necesitan estado que **no se
puede derivar** de las columnas actuales:

| Columna nueva | Tipo | Por qué es necesaria |
|---|---|---|
| `last_reminded_at` | `timestamptz null` | Sin ella no se puede saber cuándo se re-empujó por última vez → no se puede espaciar los recordatorios 4 h ni construir la señal de sonido sin duplicar filas. |
| `reminder_count` | `smallint not null default 0` | Tope de recordatorios (no acosar indefinidamente). Sin ella el barrido re-empujaría cada 4 h para siempre. |

Índice parcial para que el barrido no escanee toda la tabla:
```sql
create index if not exists notifications_unread_created_idx
  on notifications (created_at) where is_read = false;
```

**Entrega del cambio:** archivo nuevo `backend/db/migrations/003_notifications_reminders.sql`,
**aditivo e idempotente** (`alter table ... add column if not exists`), siguiendo
el patrón auto-documentado de `002_schema_v9.sql` (nunca editar una migración ya
aplicada). Postgres corre `docker-entrypoint-initdb.d` en orden solo sobre un
data-dir vacío (`docker-compose.yml:14`); para BD existentes se aplica a mano.
Actualizar además el modelo `Notification` en `models.py`. **No** se agrega
`CHECK` sobre `type` (se valida por código con `Literal`, como fijó §0.2).

---

## 4. Backend

### 4.1 Catálogo de tipos (validado por código, no por esquema)
```python
NotificationType = Literal["project_assigned", "ready_for_audit", "audit_approved"]
```
`related_entity_id` se interpreta según `type` (§0.2): `project_assigned` → id de
proyecto; `ready_for_audit` / `audit_approved` → id de ronda.

### 4.2 Capa de datos — `repositories.py` (SQL explícito con `text()`)
- `create_notifications(db, user_ids, type, title, body, related_entity_id)` —
  **inserción masiva en una sola sentencia** (`insert ... select unnest(:uids::uuid[])`),
  no un `for` de INSERTs. Deduplica `user_ids` (set) y descarta lista vacía.
- `list_notifications(db, user_id, limit, offset, only_unread)` — página para
  dropdown e inbox.
- `notification_stream_state(db, user_id)` → `(unread_count, signal)` en **una**
  query (`count(*) filter (...)` + `max(greatest(...))`).
- `notification_preview(db, user_id)` — la no-leída más reciente (para el toast).
- `mark_notification_read(db, user_id, id)` / `mark_all_notifications_read(db, user_id)`
  — siempre con `user_id` en el `WHERE` (un usuario no marca lo ajeno).
- `sweep_reminders(db, max_reminders)` — el UPDATE de §2.2.

Helpers de destinatarios (desacoplan la resolución de audiencia de los triggers):
- `project_supervisor_ids(db, project_id)` — join `assignments` activo +
  `user_roles.role_code = 'supervisor'`.
- `global_admin_ids(db)` — `select user_id from user_roles where role_code='admin'`.

### 4.3 Servicio de emisión — `app/services/notifications.py` (nuevo, desacoplado)
Una única función `emit(db, *, type, title, body, related_entity_id, user_ids)`
que valida el tipo, deduplica y delega en `create_notifications`. Los triggers
llaman **solo** a esta función: no conocen SQL ni cómo se resuelve la audiencia.

**Regla de aislamiento de fallos:** la emisión ocurre **después** del
`db.commit()` del núcleo (asignar / auditar) y va envuelta en `try/except` con
log. Una notificación es no-crítica: **jamás** debe revertir ni romper la acción
que la disparó.

### 4.4 Router — `app/routers/notifications.py` (nuevo, registrar en `main.py`)
Prefijo `/api/v1/notifications`, todos con `Depends(current_user)`:
- `GET /stream?since_signal=<int>` — **long poll** `async` (§2.1). Responde
  `{ unread_count, signal, preview }` en cuanto `signal > since_signal` o al
  timeout. `preview` = la no-leída más reciente (o `null`).
- `GET ?limit=&offset=&only_unread=` — lista paginada (dropdown + inbox).
- `GET /unread-count` — conteo inmediato para sembrar el badge al montar.
- `POST /{id}/read` · `POST /read-all` — marcar leído.

### 4.5 Los 3 disparadores (edge cases incluidos)

**Evento 1 — asignación** · `routers/assignments.py:46`, tras `db.commit()`:
```
emit(type="project_assigned", user_ids=[payload.user_id],
     related_entity_id=project_id, ...)   # omitir si el destinatario == actor
```

**Evento 2 — listo para auditar** · `pipeline/audit.py:149`
(`start_audit_session`, alrededor de `set_round_status(db, round_id, "audit_pending")`):
- `start_audit_session` es **reanudable**: se ejecuta cada vez que alguien con
  `audit.view` abre la vista y `_round_audit_readiness` da `ready=True`. Para **no
  notificar en cada apertura**, leer el status de la ronda **antes** de la
  llamada y emitir solo si `status_previo != 'audit_pending'` (primera transición).
- Destinatarios: `project_supervisor_ids(project_id)`; **si vacío →
  `global_admin_ids()`** (fallback pedido por el usuario). Deduplicar (un admin
  que además sea supervisor no recibe dos) y excluir al actor.

**Evento 3 — auditoría aprobada** · `pipeline/audit.py:335`
(`approve_session`, alrededor de `set_round_status(db, ctx["round_id"], "audit_approved")`):
- `set_round_status` (`repositories.py:1235`) **solo** mueve la ronda a
  `audit_approved` cuando **todos** los subproyectos están aprobados. Para
  notificar **una sola vez por ronda** (no por subproyecto): leer status
  **antes**, llamar, releer **después**, y emitir solo si
  `previo != 'audit_approved' and posterior == 'audit_approved'`.
- Destinatarios: `global_admin_ids()` (rol global; el admin ve todo vía el bypass
  `is_admin` de `access.py:62`). Confirma decisión abierta §0.7-2 (todos los
  admins, no solo `projects.created_by`).

---

## 5. Frontend

Sin dependencias nuevas: `framer-motion`, `lucide-react`, `zustand` y
`react-router-dom` ya están (`package.json`). El sonido reutiliza el sintetizador
Web Audio existente — cero assets binarios.

### 5.1 Estado — `store/useNotificationStore.ts` (nuevo, desacoplado)
Store Zustand **separado** del `useVerbatixStore` para no acoplar notificaciones
al núcleo de auth/navegación:
```
unread: number
signal: number
muted: boolean            // persistido en localStorage 'verbatix:notif-muted'
items: Notification[]     // caché del dropdown
toasts: NotifToast[]      // canal de push propio (no toca el ToastStack genérico)
setStreamState / setItems / pushToast / dismissToast / toggleMuted
```

### 5.2 Motor de long poll — `hooks/useNotificationPoll.ts` (nuevo)
Montado **una vez** en `AppShell` (arranca con `user` presente, para en logout):
- Bucle: `fetch('/notifications/stream?since_signal=<signal>')` con
  `AbortController`; al resolver actualiza el store y **re-dispara de inmediato**.
  En fallo de red, backoff corto (3–5 s) y reintenta.
- **Semilla sin sonido:** en el primer response fija `signal` **sin** sonar
  (evita sonar al entrar). En incrementos posteriores: `playNotification()` (si
  `!muted`, con rate-limit ~2 s) + refresca la lista + `pushToast(preview)`.
- **StrictMode:** guardar un `ref` para no duplicar el bucle en el doble-montaje
  de desarrollo; `abort()` en cleanup/unmount/logout.
- Sembrar el badge al montar con `GET /unread-count` (no esperar al primer stream).

### 5.3 Campana + badge — `AppShell.tsx`
No hay topbar; el shell es sidebar con el menú de usuario abajo (patrón
`menuRef`/`menuOpen`, líneas 160-203). Agregar junto a ese bloque un **botón
campana** (`Bell` de lucide) con su propio `bellRef`/`bellOpen`:
- **Badge** con el conteo; anima un "pop" (keyframe `scale`) cuando el conteo
  **sube**, y un `ring` sutil. Framer-motion, coherente con las animaciones que
  ya usa el shell.
- Al abrir despliega `NotificationsPanel`.
- Nuevo `NAV_ITEM` o enlace "Bandeja" → `/notifications` (sin capability guard:
  todo usuario autenticado tiene bandeja).

### 5.4 Dropdown — `components/NotificationsPanel.tsx` (nuevo)
Últimas ~8; icono por tipo; timestamp relativo; clic → marca leído + navega
(`project_assigned`→`/projects/:id`, `ready_for_audit`→`/rounds/:id/audit`,
`audit_approved`→`/rounds/:id/report`). Acciones "Marcar todas como leídas",
"Ver todas" → `/notifications`, y toggle de silencio (mute).

### 5.5 Bandeja completa — `components/NotificationsInbox.tsx` (nuevo)
Ruta nueva en `App.tsx` dentro del `AppShell`:
`<Route path="/notifications" element={<NotificationsInbox />} />`.
Lista paginada (limit/offset) con filtro **Todas / No leídas**, agrupada por día
(Hoy / Ayer / fecha), iconos por tipo, estado vacío cuidado, marcar-todo-leído,
y por item marcar-leído + navegar.

### 5.6 API client — `api/client.ts` + tipos en `api/types.ts`
Tipos `Notification`, `NotificationPreview`, `NotificationStream`,
`NotificationList`. Funciones con el mismo patrón `request<T>()`:
`streamNotifications(sinceSignal, signal?)` (acepta `AbortSignal`),
`getNotifications`, `getUnreadCount`, `markNotificationRead`,
`markAllNotificationsRead`.

### 5.7 Push visual — `components/NotificationToast.tsx` (nuevo, sin tocar `ToastStack`)
Canal propio (store §5.1), **no** reutiliza el toast genérico para no acoplar ni
alterar su comportamiento. Diseño (creativo pero sobrio, coherente con el design
system `p-*`):
- Chip de icono con color por tipo (`UserPlus`, `ClipboardCheck`, `ShieldCheck`).
- Título en negrita + cuerpo atenuado; entra con **spring** (misma familia que
  `ToastStack.tsx:29`: `stiffness ~350, damping ~25`), `layout` para apilar.
- Barra de progreso de auto-cierre (~5 s); clic → navega + marca leído; botón X.
- Respeta `prefers-reduced-motion` (fade simple sin desplazamiento).

---

## 6. Diseño del sonido (psicología aplicada)

Extender `frontend/src/lib/sound.ts` con `playNotification()` — sintetizado con
el helper `tone()` existente, **sin assets** (coherente con el comentario
"ponytail" del archivo). Un **único** sonido para los 3 eventos (§0.1).

```ts
export function playNotification(): void {
  const audioCtx = getContext();
  if (!audioCtx) return;
  const t = audioCtx.currentTime;
  tone(587.33, t,        0.14, 0.050, audioCtx); // D5 — fundamental cálido
  tone(880.00, t + 0.10, 0.22, 0.045, audioCtx); // A5 — quinta justa ascendente
  tone(1760.0, t + 0.10, 0.12, 0.015, audioCtx); // armónico agudo, muy tenue (brillo "campana")
}
```

**Principios (WhatsApp / Instagram / Facebook Messenger):**
- **Corto (<0.5 s):** no exige atención; se puede ignorar sin estrés → no irrita
  con repetición.
- **Ataque suave + decaimiento exponencial:** sin transitorio brusco → no dispara
  la respuesta de sobresalto (amenaza). El `tone()` actual ya hace rampa de 10 ms.
- **Intervalo consonante ascendente (quinta justa):** valencia **positiva** —
  "algo bueno llegó"; la consonancia reduce tensión frente a intervalos
  disonantes o descendentes.
- **Frecuencia media-alta pero no penetrante (~590–880 Hz):** audible sobre ruido
  de oficina sin ser estridente; el armónico a 1760 Hz da timbre de campana, no
  filo.
- **Volumen moderado (gain ~0.05):** presente, no invasivo.
- **Consistencia:** el mismo sonido siempre → reconocimiento pavloviano ("es
  Verbatix") sin esfuerzo cognitivo.
- **Agencia del usuario:** toggle de silencio (mute) persistido → quien lo
  encuentre molesto lo apaga; esto previene la reactancia/habituación negativa
  que sí generan los sonidos no silenciables. Además `play()` maneja el rechazo
  de autoplay sin romper la UI (§0.5).

---

## 7. Matriz de casos borde

| Caso | Resolución |
|---|---|
| Evento 2 sin ningún supervisor | Fallback a **todos los admins** (`global_admin_ids`). |
| Admin que también es supervisor del proyecto | **Dedup** por set de `user_ids` → una sola notificación. |
| Reapertura de la vista de auditoría (evento 2 re-dispara) | Emitir solo en la **primera** transición a `audit_pending` (comparar status previo). |
| Aprobación por subproyecto (evento 3 se llama N veces) | La ronda solo pasa a `audit_approved` cuando **todos** están aprobados → comparar antes/después y emitir **una vez**. |
| El actor es también destinatario | Excluir al actor de `user_ids`. |
| No-leída >4 h | Recordatorio: re-empuja (señal sube → suena), hasta `max_reminders` (p.ej. 3). |
| 2 workers ejecutan el barrido | UPDATE atómico guardado = idempotente → exactamente un recordatorio. |
| 50 usuarios en long poll | Sesión corta por chequeo (no se retienen conexiones) → pool holgado. |
| Fallo al emitir notificación | `try/except` + log tras el commit del núcleo → nunca revierte la acción disparadora. |
| Autoplay bloqueado por el navegador | `play()` atrapa el rechazo; la UI (badge/toast) sigue funcionando. |
| Usuario offline cuando llega el evento | Sin stream abierto no suena; al volver, el badge ya trae el conteo y la semilla no re-suena. |

---

## 8. Rendimiento, hilos y concurrencia (resumen)
- **async ↔ sync:** endpoints de stream `async` + `run_in_threadpool` para el
  SQLAlchemy síncrono; jamás bloquear el event loop; `asyncio.sleep`, no
  `time.sleep`.
- **Conexiones:** sesión efímera por chequeo del long poll; el barrido usa su
  propia sesión corta por tick.
- **Escritura:** emisión con **un** INSERT masivo (`unnest`), no bucle.
- **Barrido:** UPDATE único guardado por índice parcial; sin advisory lock porque
  la atomicidad ya garantiza exactamente-una-vez.
- **Desacople:** store de notificaciones separado; servicio de emisión aislado;
  triggers "delgados" que solo llaman `emit`; canal de toast propio.

## 9. Qué NO se toca (no romper)
- No se editan migraciones ya aplicadas (`001`/`002`) — solo se agrega `003`.
- No se altera `ToastStack`/`showToast` existentes ni `playSuccess`/`playTick`.
- Los triggers solo **añaden** una emisión tras el commit existente; no cambian
  la lógica de asignación ni de auditoría.
- Sin `CHECK` sobre `type` (validación por código, §0.2).

## 10. Pruebas — `backend/tests/test_notifications.py` (estilo `test_audit.py`)
- Repos: crear/listar/contar/marcar-leído/marcar-todo; `project_supervisor_ids`,
  `global_admin_ids`; **fallback** a admins sin supervisor; dedup.
- Triggers: asignar → 1 notif; `ready_for_audit` solo en la primera transición
  (no en reaperturas); `audit_approved` una vez por ronda (no por subproyecto).
- Barrido: bump correcto de `last_reminded_at`/`reminder_count`; **idempotencia**
  (segundo barrido = 0 filas); tope `max_reminders`; no toca leídas.
- Señal: monotonicidad (nueva y recordatorio la suben; leído la baja).
- (Frontend) opcional: `bunx tsc --noEmit` + `bun run lint` verdes.

## 11. Orden de implementación sugerido
1. Migración `003` + modelo + índice parcial.
2. Repos (datos + helpers de audiencia) + servicio `emit` + tests de repos.
3. Router `notifications` (stream/list/read) + registro en `main.py`.
4. Los 3 triggers con sus edge cases + tests de triggers.
5. Barrido `reminders.py` + arranque en `lifespan` + tests de barrido.
6. Store + hook long poll + client/types.
7. Campana + badge + dropdown + toast push + `playNotification`.
8. Página de bandeja `/notifications`.
9. Verificación: `pytest`, `bunx tsc --noEmit`, `bun run lint`, prueba manual E2E.

## 12. Decisiones abiertas (§0.7) — resueltas
1. **Evento 2 sin supervisor →** fallback a **admins** (confirmado por el usuario).
2. **Evento 3 →** **todos los admins** (confirmado; rol global).
