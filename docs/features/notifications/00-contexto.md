# Notificaciones + bandeja de entrada — Contexto (para armar plan y prompt)

> Este documento NO es el plan ni el prompt de implementación — es el panorama
> verificado contra el código + las decisiones tomadas en la conversación de
> investigación previa (2026-07-18). Sirve de insumo para escribir después
> `01-plan-y-prompt.md`, siguiendo el mismo formato que
> `docs/features/audit/00-plan-y-prompt.md` (PARTE 0 panorama / PARTE 1 plan /
> PARTE 2 prompt autónomo).

## 0.1 Alcance — los 3 eventos, ni uno más

Solo estas tres notificaciones, todas in-app, ninguna por correo:

1. **Admin asigna un proyecto a un usuario** → notifica al usuario asignado.
2. **Codificador termina y el subproyecto queda listo para auditar** → notifica
   a los supervisores del proyecto.
3. **Supervisor aprueba la auditoría completa de una ronda** → notifica a los
   admins.

Sonido: **el mismo sonido para los tres eventos**, no solo para el de
asignación. Se dispara cuando el conteo de no-leídas *sube* respecto al valor
anterior conocido por el cliente — nunca en cada respuesta del polling, o
sonaría en loop mientras haya algo sin leer.

## 0.2 Estado observado del código (verificado, no asumido)

- **La tabla ya existe.** `backend/db/migrations/002_schema_v9.sql:205-215`
  crea `notifications` (`id, user_id, type, title, body, related_entity_id,
  is_read, created_at`, índice en `(user_id, is_read)`), comentada como
  `REQ-11: notificaciones de asignación`. Modelo SQLAlchemy en
  `backend/app/models.py:522`. **No hay repos, router ni UI que la usen
  todavía.** No se necesita ninguna tabla nueva para lo descrito en 0.1.
- **`related_entity_id` no tiene columna de tipo asociada.** El frontend debe
  inferir si apunta a un proyecto o a una ronda a partir del valor de `type`
  (p. ej. `project_assigned` → id de proyecto; `ready_for_audit` /
  `audit_approved` → id de ronda). Válido mientras cada `type` apunte a un
  solo tipo de entidad.
- **`type` no tiene `CHECK` constraint** (a diferencia de `flag_type` o
  `status` en la misma migración). Se deja así; validar el catálogo de
  valores a nivel de código (`Literal`/enum en Python), no en el esquema.
- **CLAUDE.md está desactualizado sobre auth.** Dice Supabase/JWKS; el código
  real usa sesiones opacas locales (`backend/app/core/auth.py`,
  tabla `auth_sessions`, header `Authorization: Bearer <token>` validado
  contra la BD en cada request — no hay JWT, no hay Supabase en ningún punto
  del stack). Esto importa porque descarta Supabase Realtime como opción y
  porque el mecanismo de entrega elegido (ver 0.4) tiene que seguir
  funcionando con auth por header, no por cookie.
- **Deploy:** `docker-compose.prod.yml` corre
  `uvicorn app.main:app --workers 2`. Cualquier estado en memoria (conexiones
  WebSocket/SSE abiertas) vive en un solo worker y es invisible para el otro
  — no aplica a polling ni a long polling, que consultan la BD directamente
  en cada request.
- **`frontend/nginx.conf`** hace `proxy_pass http://backend:8001` en
  `location /api/` **sin `proxy_read_timeout` propio** → usa el default de
  nginx (60s). Un long poll con espera máxima de ~25s cabe con margen.
- **Patrón de "vivo" ya existente en el frontend:** `setInterval` a pelo, sin
  librería de fetching (no hay `react-query`/`SWR`/`axios`, solo `fetch`
  envuelto en `frontend/src/api/client.ts` + Zustand en
  `frontend/src/store/useVerbatixStore.ts`). Ejemplos:
  `frontend/src/components/UnifiedStudioView.tsx:144-149` (cada 8s mientras
  autoProcessing) y `frontend/src/components/AuditView.tsx:178-184` (mientras
  espera que el codificador termine).

## 0.3 Los 3 disparadores — punto exacto en el código

| Evento | Dónde | Detalle a respetar |
|---|---|---|
| Admin asigna proyecto | `backend/app/routers/assignments.py:24` función `create_assignment` | Tras el `db.commit()`, notificar a `payload.user_id`. Único destinatario, caso simple. |
| Codificador listo para auditar | `backend/app/pipeline/audit.py:149` dentro de `start_audit_session`, en la llamada `set_round_status(db, round_id, "audit_pending")` | No es un botón "terminé" explícito: se dispara cuando alguien con capacidad `audit.view` abre la vista de auditoría y `_round_audit_readiness` ya dio `ready=True`. Destinatarios: supervisores con fila activa en `assignments` para ese proyecto (join `assignments` + `user_roles` donde `role_code='supervisor'`). |
| Supervisor aprueba auditoría | `backend/app/pipeline/audit.py:335` dentro de `approve_session`, en la llamada `set_round_status(db, ctx["round_id"], "audit_approved")` | **Cuidado:** `set_round_status` (`backend/app/repositories.py:1235`) solo aplica el cambio a `audit_approved` cuando **todos** los subproyectos de la ronda ya están aprobados. Hay que comparar el status de la ronda antes/después de la llamada (o usar un `UPDATE ... RETURNING`) para notificar una sola vez por ronda, no una vez por subproyecto/tipo de codificación. Destinatarios: todos los usuarios con `role_code='admin'` (rol global, no ligado a `assignments` — un admin ve todo vía el bypass de `is_admin` en `visible_project_ids`, `backend/app/core/access.py:59`). |

## 0.4 Mecanismo de entrega elegido: long polling

Se evaluaron y descartaron, en orden, por ser desproporcionados al tamaño real
del problema (~50 usuarios, 3 tipos de evento de baja frecuencia, ninguno
requiere sub-segundo):

- **Novu / Pusher / Ably / OneSignal** — infraestructura nueva (servicio
  aparte con su propia BD, o SaaS de pago) para un problema de 3 eventos
  internos. Descartado.
- **WebSocket nativo** — bidireccional cuando solo se necesita
  servidor→cliente; el frontend tendría que implementar reconexión a mano;
  mismo problema de fan-out entre los 2 workers que SSE, sin ninguna ventaja
  a cambio. Descartado para esta función (sí tendría sentido a futuro para
  presencia en vivo sobre `users.session_status`, que hoy es pull).
- **SSE (`fastapi.sse.EventSourceResponse`, nativo desde FastAPI 0.135;
  el repo ya tiene 0.139)** — el cliente nativo `EventSource` del navegador
  **no admite headers personalizados**, así que no puede mandar
  `Authorization: Bearer <token>` como hace el resto de la app. Usarlo
  implicaría token en query string (se filtra en logs/proxies) o una
  librería cliente adicional. Descartado por fricción con el modelo de auth
  actual, no por rendimiento.
- **SSE/long-poll "real" con Postgres `LISTEN`/`NOTIFY`** — resuelve el
  fan-out entre los 2 workers de forma elegante y sin Redis, pero es más
  infraestructura (conexión de escucha persistente por worker, reconexión)
  de la que 3 eventos raros justifican hoy. Queda como posible fase 2 si el
  volumen de eventos crece mucho.
- **Short polling (cliente pregunta cada 5s con `setInterval`)** — funciona,
  pero para el evento de asignación (que lleva sonido) da hasta 5s de retraso
  perceptible, y genera más tráfico total que la alternativa elegida (~10
  req/s vs ~2 req/s a 50 usuarios) porque la mayoría de las respuestas son
  "no hay nada nuevo".

**Elegido: long polling con loop interno de espera en el servidor (sin
`LISTEN`/`NOTIFY`).** El endpoint mantiene la petición abierta revisando la
BD cada ~1s hasta encontrar algo nuevo o hasta un timeout de ~25s, y entonces
responde; el cliente vuelve a mandar la petición de inmediato. Es HTTP
normal (compatible con el auth por header tal cual está), no necesita
infraestructura nueva, y para eventos tan poco frecuentes genera menos
tráfico total que el short polling a la vez que da latencia cercana a 1s —
justo lo que pide el requisito de sonido.

Reglas de implementación acordadas para el loop:

- Revisar la BD dentro del loop con `asyncio.sleep` (nunca `time.sleep`,
  que bloquearía el worker entero).
- **No mantener una `Session` de SQLAlchemy abierta durante toda la espera**
  — abrir/soltar en cada chequeo, para no agotar el pool de conexiones con
  varias peticiones largas concurrentes.
- El cliente re-dispara la siguiente petición inmediatamente al recibir
  cualquier respuesta (con datos nuevos o vacía por timeout), con un backoff
  corto si la petición falla por red.
- Timeout del lado servidor (~25s) queda cómodo bajo el timeout de nginx
  (60s, default, ver 0.2) — no hace falta tocar `frontend/nginx.conf`.

## 0.5 Comportamiento del sonido

- Un solo sonido, compartido por los 3 tipos de notificación.
- Se dispara en el cliente comparando el conteo de no-leídas devuelto contra
  el último conteo conocido (guardarlo en el store de Zustand): solo si
  **subió**, no en cada respuesta del long poll.
- Los navegadores bloquean `audio.play()` sin interacción previa del usuario
  en la página — no debería ser un problema real en una SPA donde el usuario
  ya hizo login e interactuó, pero el `play()` debe manejar el rechazo sin
  romper la UI si ocurre.

## 0.6 Panorama de archivos (para detallar en el plan)

**Backend**
- `backend/app/repositories.py` — nuevas funciones: `create_notification`,
  `list_notifications`, `count_unread_notifications`,
  `mark_notification_read`, `mark_all_notifications_read`, más helpers
  `project_supervisor_ids` y `global_admin_ids` (SQL explícito con `text()`,
  mismo estilo del archivo).
- `backend/app/routers/notifications.py` (nuevo) — endpoint de long polling
  para el conteo/lista, `POST /notifications/{id}/read`,
  `POST /notifications/read-all`. Registrar en `backend/app/main.py`.
- `backend/app/routers/assignments.py:24` — disparo evento 1.
- `backend/app/pipeline/audit.py:149` — disparo evento 2.
- `backend/app/pipeline/audit.py:335` — disparo evento 3 (con la comparación
  antes/después descrita en 0.3).
- `backend/tests/test_notifications.py` (nuevo) — los 3 disparadores +
  listar/marcar leído, estilo `test_audit.py`.

**Frontend**
- `frontend/src/api/types.ts` — tipos `Notification`, `NotificationList`.
- `frontend/src/api/client.ts` — funciones de long polling y de
  marcar-leído, mismo patrón `request<T>()` existente.
- `frontend/src/components/NotificationsPanel.tsx` (nuevo) — dropdown, marcar
  leído, navegación a `/projects/:id` o `/rounds/:id` según `type`.
- `frontend/src/components/AppShell.tsx` — ícono `Bell` (lucide-react, ya
  instalado) junto al menú de usuario existente (mismo patrón
  `menuRef`/`menuOpen`), badge, loop de long polling, disparo de sonido según
  0.5. Arranca con sesión activa (`user` de `useVerbatixStore`), para en
  logout.
- Asset de audio nuevo (breve, no intrusivo) en `frontend/public/` o
  `frontend/src/assets/`.

## 0.7 Decisiones que siguen abiertas — resolver antes o durante el plan

1. **Destinatarios del evento 2 sin supervisor asignado.** Si un proyecto no
   tiene ningún usuario con `role_code='supervisor'` en `assignments`, ¿cae a
   los admins como respaldo, o simplemente no se notifica a nadie?
2. **Confirmación final de que "todos los admins" es el destinatario correcto
   del evento 3**, en vez de solo `projects.created_by`. Propuesto en la
   investigación previa, no objetado, pero no confirmado explícitamente.
