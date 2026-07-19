# Mascota interactiva + estado de presencia — PLAN

> Insumo: [`00-contexto.md`](00-contexto.md) (panorama verificado 2026-07-19).
> El prompt de ejecución vive en [`02-prompt.md`](02-prompt.md).
>
> Principios rectores (mismos de notifications): seguir el flujo existente,
> BD solo lo necesario (justificado), código limpio y desacoplado, cero
> dependencias nuevas, sin romper nada, y **experiencia de usuario primero**.

---

## 1. Alcance

| # | Pieza | Descripción |
|---|---|---|
| 1 | Mascota interactiva | Robot "W" en el sidebar (sección usuario) y grande en el dashboard; ojos animados (parpadeo + pupilas siguen el cursor), flotación idle, squash al clic |
| 2 | Selector de estado | Clic en la mascota → popover con 5 estados ilustrados; selección optimista con sonido y toast de error/revert |
| 3 | Estado visible para admins | `TeamAdminPage` muestra chip de estado + "desde hace X min" por usuario, con refresco periódico |
| 4 | Historial de estados | Log append-only `user_status_events` → insumo directo de la futura feature de tiempos (REQ-15) |

**Fuera de alcance (v2):** auto-expiración de estados, recordatorio "sigues en
break?", presencia en tiempo real vía long-poll (el panel admin refresca cada
30 s y basta), animación de las 4 escenas secundarias más allá de entrada/idle.

---

## 2. Decisiones de arquitectura (con el porqué)

### 2.1 Herramienta de animación — framer-motion, no Rive

Decidido en contexto §2. Resumen: los SVG son trazados planos (los ojos no son
capas), Rive exige autoría manual en su editor GUI (paso no automatizable) y
una dependencia nueva que framer-motion ya cubre. La cara navy plana
(`#1F1E2D`) permite **ojos procedurales superpuestos** con más expresividad
(seguir el cursor) que un timeline pre-horneado.

**Cláusula de reversibilidad:** todo el render vive en
`components/mascot/MascotAvatar.tsx`; la lógica de estado (catálogo, store,
API) no sabe cómo se dibuja. Migrar a Rive = reemplazar un componente (anexo A).

### 2.2 Modelo de datos — estado actual en `users` + log de eventos

Dos columnas nuevas en `users` (el panel admin necesita leer el estado actual
de N usuarios en una sola query, sin agregación):

- `presence_status text not null default 'disponible'`
- `presence_changed_at timestamptz` — habilita el "desde hace 12 min" y da
  contexto de staleness sin necesitar auto-expiración.

Tabla nueva `user_status_events` (id, user_id FK cascade, status, started_at,
ended_at nullable) — **justificación de tocar BD:** la feature de tiempos que
el usuario ya anunció necesita duraciones por estado, y las duraciones son
**irrecuperables retroactivamente** si no se registran desde ahora. Es
append-only y barata; no crear ahora significa perder los datos del período
intermedio. Cierre del evento anterior (set `ended_at`) + inserción del nuevo
en la misma transacción que el UPDATE de `users`.

`session_status`/`last_activity_at` (REQ-16, sin cablear) **no se tocan**: son
presencia de conexión; esto es estado declarado. Conviven.

### 2.3 Entrega al admin — polling simple, no long-poll

El long-poll de notificaciones existe para eventos que deben "sonar" al
instante. El estado de presencia en un panel de gestión tolera latencia de
segundos: `TeamAdminPage` refresca cada **30 s** mientras está montada (y al
recuperar foco de la pestaña). Cero infraestructura nueva, cero presión sobre
el pool de conexiones. Si algún día se quiere en vivo, la señal puede viajar en
el snapshot del stream existente (`notifications.py:26-32`) — anotado, no hecho.

### 2.4 Semántica del estado

- Catálogo cerrado (validado en backend): `disponible` (default), `almorzando`,
  `en_el_bano`, `en_break`, `en_reunion`. String plano, sin enum de BD, para
  poder añadir estados sin migración (mismo criterio que `notifications.type`).
- **Reset al hacer login:** un "Almorzando" de ayer a las 13:00 es ruido hoy.
  En el login exitoso se cierra el evento abierto y se vuelve a `disponible`.
  En el logout NO se toca (el token puede expirar sin pasar por logout; el
  reset en login es el punto fiable).
- Elegir el estado ya activo = no-op (sin evento duplicado, sin UPDATE).

---

## 3. Backend

### 3.1 Migración `backend/db/migrations/005_user_presence.sql`
Aditiva e idempotente, encabezado auto-documentado estilo 003:

```sql
alter table users
  add column if not exists presence_status text not null default 'disponible',
  add column if not exists presence_changed_at timestamptz;

create table if not exists user_status_events (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references users(id) on delete cascade,
  status     text not null,
  started_at timestamptz not null default now(),
  ended_at   timestamptz
);
create index if not exists user_status_events_user_started_idx
  on user_status_events (user_id, started_at desc);
```

### 3.2 Modelos (`models.py`)
Columnas en `User` + clase `UserStatusEvent` (docstring: "insumo de la feature
de tiempos, hermano de TimeTrackingEvent/REQ-15").

### 3.3 `repositories.py` (SQL explícito, `text()`)
- `set_user_presence(db, user_id, status) -> datetime | None` — si el estado no
  cambia, retorna None sin escribir; si cambia: UPDATE `users`, UPDATE del
  evento abierto (`ended_at = now() where user_id = :id and ended_at is null`),
  INSERT del nuevo. Sin commit (lo hace el router, patrón del proyecto).
- `reset_user_presence_on_login(db, user_id)` — mismo mecanismo, a `disponible`.

### 3.4 Router `app/routers/presence.py` (`/api/v1/presence`)
- `PUT /me` body `{"status": "..."}` → 422 si no está en el catálogo
  (constante `PRESENCE_STATUSES` en el router); responde
  `{status, changed_at}`. Auth: `current_user`.
- Registrar el router en `main.py` junto a los demás.
- `GET /api/v1/admin/users` (`admin.py:83`): añadir
  `u.presence_status, u.presence_changed_at` al SELECT — el panel ya consume
  ese endpoint; no se crea uno paralelo.
- `/me` de auth (`auth.py:128`): incluir ambos campos en la respuesta.
- Login (`auth.py`, tras validar credenciales): `reset_user_presence_on_login`.

### 3.5 Tests (`backend/tests/`)
SQLite/StaticPool como los existentes: set válido → 200 + evento abierto único;
estado inválido → 422; mismo estado dos veces → un solo evento; cambio →
evento anterior con `ended_at`; login resetea a `disponible`; admin/users
incluye los campos.

---

## 4. Frontend

### 4.1 Assets
Mover `img/*.svg` → `frontend/src/assets/mascot/` con nombres semánticos:
`hello.svg`, `lunch.svg`, `bathroom.svg`, `break.svg`, `meeting.svg`.
Eliminar `img/` (regla: sin código muerto). Import como URL de Vite.

### 4.2 `lib/presence.ts` — catálogo único FE
```ts
export type PresenceStatus = "disponible" | "almorzando" | "en_el_bano" | "en_break" | "en_reunion";
export const PRESENCE_CATALOG: Record<PresenceStatus, { label; icon; art; tint }>
```
Labels de las imágenes: Disponible / Almorzando / En el baño / En break /
En reunión. Iconos lucide ya instalados: `Smile`, `Utensils`, `Droplet`,
`Coffee`, `Users`.

### 4.3 `components/mascot/MascotAvatar.tsx` — el corazón visual
Props: `status`, `size` (`sm` sidebar ~40 px, `lg` dashboard ~180 px),
`interactive`. Estructura en capas sobre un contenedor relativo:

1. **Arte base** del estado activo — `AnimatePresence mode="popLayout"`:
   sale con `scale: 0.92, opacity: 0`, entra con spring
   (`stiffness ~380, damping ~26`) — el "pop" agradable.
2. **Capa de ojos** (solo estado `disponible`, donde la mascota mira al
   frente): parche `#1F1E2D` sobre la zona ocular + dos ojos SVG (elipse
   blanca + pupila navy) posicionados en % del viewBox (calibrar contra
   `hello.svg`, ojos ≈ centro-cara).
   - **Parpadeo**: `scaleY 1→0.08→1` (~120 ms), intervalo aleatorio 2.5–6 s,
     10 % doble parpadeo. Timer con cleanup.
   - **Pupilas siguen el cursor**: listener `pointermove` en `window`
     (throttle rAF), desplazamiento máx. ~6 % del ojo hacia el cursor, con
     spring suave (`useSpring`). Sin cursor cerca (> ~400 px) → deriva idle
     lenta (mirar alrededor cada ~4 s).
3. **Idle float**: `y: [0, -3, 0]` 4 s ease-in-out infinito (solo `lg`).
4. **Interacción**: `whileHover={{ scale: 1.04, rotate: 1.5 }}` + ojos
   ligeramente más abiertos; `whileTap={{ scale: 0.94 }}` (squash).
5. **`prefers-reduced-motion`** (hook `useReducedMotion` de framer-motion):
   sin float, sin seguimiento, sin parpadeo; solo crossfade simple.

Es un `<button>` con `aria-label="Cambiar estado — actualmente {label}"`.

### 4.4 `components/mascot/StatusPicker.tsx`
Popover anclado (mismo patrón `NotificationsPanel` + cierre clic-fuera de
`AppShell.tsx:72-79`). Grid de 5 tarjetas: mini-arte + chip con icono y label
(replicando el chip lila de las ilustraciones). Entrada en stagger
(`staggerChildren: 0.04`, springs). Estado actual con anillo `p-accent`.
Selección → optimista en store + `PUT /presence/me` + `playTick()`; error →
revert + `showToast(..., "error")`. Navegable por teclado (roving focus, Esc).

### 4.5 Estado y API
- `api/types.ts`: `UserProfile` += `presence_status: PresenceStatus`,
  `presence_changed_at: string | null`; `AdminUser` lo hereda.
- `api/client.ts`: `setPresence(status)`.
- `useVerbatixStore`: acción `setPresenceLocal(status)` que actualiza
  `user.presence_status` (+ persistencia en `verbatix:user` ya existente).

### 4.6 Montaje
- **Sidebar** (`AppShell.tsx:184-199`): el avatar de inicial se reemplaza por
  `MascotAvatar size="sm"` con **dot de estado** (color del catálogo) en la
  esquina; clic abre `StatusPicker` (el menú de cuenta se mantiene en el
  chevron/email). Colapsado: solo mascota + dot, `title` con el label.
- **Dashboard** (`ProjectDashboard.tsx:122`, junto al header "Proyectos"):
  `MascotAvatar size="lg"` como saludo — la pieza de deleite donde los ojos y
  la flotación lucen. Mismo clic → picker.
- **Descubribilidad**: hasta el primer uso (flag
  `localStorage verbatix:mascot-hint`), anillo `pulse-ring` (ya existe en
  `index.css:215`) + tooltip "Haz clic para definir tu estado".

### 4.7 Panel admin (`TeamAdminPage.tsx`)
- En cada fila (`:45`): chip `{icono} {label} · hace X min` (tint del
  catálogo; `disponible` en tono neutro). Helper `timeAgo` corto en el propio
  archivo o `lib/presence.ts`.
- Refresco: `setInterval` 30 s mientras la página está montada + refetch en
  `visibilitychange` a visible. Cleanup al desmontar.

---

## 5. Fases de implementación

| Fase | Contenido | Verificación |
|---|---|---|
| F1 | Migración 005 + modelos + repos + router presence + reset en login + campos en `/me` y `admin/users` | `pytest backend/tests/ -v` |
| F2 | Assets movidos + `lib/presence.ts` + tipos/cliente FE | `bunx tsc --noEmit` |
| F3 | `MascotAvatar` (capas, ojos, parpadeo, cursor, reduced-motion) | visual en dev |
| F4 | `StatusPicker` + store + montaje en AppShell y Dashboard | flujo completo usuario |
| F5 | Chips + polling en `TeamAdminPage` | flujo admin (2 sesiones) |
| F6 | Pulido: sonido, hint de descubribilidad, a11y, lint/typecheck final | checklist DoD del prompt |

---

## 6. Puente a la feature de tiempos (futura)

`user_status_events` ya deja listo: duración por estado = `ended_at - started_at`
(evento abierto = estado vigente). Cruce con `TimeTrackingEvent` (REQ-15,
`models.py:541`) por `user_id` + ventana temporal → "en el proyecto X estuvo
3 h, de las cuales 40 min en break". No se implementa nada de eso ahora; solo
se garantiza que los datos existan.

---

## Anexo A — Ruta Rive (opcional, futura)

Si más adelante se quiere fisicalidad de rig (cabeza que gira, brazos):
1. Rediseñar la mascota por capas en Figma (o limpiar los SVG) — los trazados
   planos actuales no sirven como rig.
2. En el editor de Rive: rig + state machine con inputs `state` (enum),
   `hover`/`tap` (triggers), `pointerX/Y` (numbers) para los ojos.
3. `bun add @rive-app/react-canvas` y reimplementar **solo**
   `MascotAvatar.tsx` con `useRive`/`useStateMachineInput`, mismas props.
Nada más cambia: catálogo, store, API y panel admin quedan intactos.
