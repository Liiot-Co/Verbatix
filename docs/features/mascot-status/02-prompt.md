# Mascota interactiva + estado de presencia — PROMPT DE IMPLEMENTACIÓN

> Pégale esto a quien vaya a implementar (o a un agente). Es autónomo, pero
> apóyate en [`00-contexto.md`](00-contexto.md) y [`01-plan.md`](01-plan.md)
> para el porqué. Rutas y líneas verificadas contra el código el 2026-07-19.

---

## Rol y objetivo

Implementa en Verbatix la **mascota interactiva con estado de presencia**: el
robot "W" vive en el sidebar y en el dashboard, con ojos animados (parpadeo +
pupilas que siguen el cursor); al hacer clic se abre un selector con 5 estados
ilustrados (Disponible, Almorzando, En el baño, En break, En reunión); el
estado elegido cambia el arte de la mascota y queda visible para los admins en
`/team` con "desde hace X min". Cada cambio queda registrado en un log
append-only que alimentará la futura feature de tiempos.

**Herramienta de animación: framer-motion@12 (ya instalada) + SVG en capas.
NO uses Rive ni agregues dependencias** — los SVG son trazados planos y el
render queda aislado en un componente para poder migrar a Rive después.

## Principios innegociables

1. **Sigue el flujo y estilo existentes.** Python snake_case + SQL explícito
   con `text()` en `repositories.py`; TS estricto sin `any`, componentes
   PascalCase; Tailwind con tokens `p-*`.
2. **BD: solo lo especificado abajo.** Migración aditiva e idempotente. No
   toques `session_status`/`last_activity_at` (REQ-16, otra feature).
3. **Cero dependencias nuevas.** framer-motion, zustand, lucide-react y
   `lib/sound.ts` cubren todo.
4. **No romper:** toasts (`showToast`), long-poll de notificaciones
   (`useNotificationPoll`, `routers/notifications.py`), flujo de
   aprobación/asignación de admin, menú de cuenta del sidebar.
5. **Sin código muerto:** los SVG se MUEVEN de `img/` a
   `frontend/src/assets/mascot/`; `img/` se elimina.
6. **Frontend con bun** (`bun`/`bunx`, nunca npm).
7. **`prefers-reduced-motion` se respeta siempre** (hook `useReducedMotion`
   de framer-motion): sin float, sin parpadeo, sin seguimiento de cursor;
   solo transiciones de opacidad simples.

---

## Backend

### 1. Migración `backend/db/migrations/005_user_presence.sql`
Aditiva e idempotente, con encabezado auto-documentado al estilo de
`003_notifications_reminders.sql`:

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

Refleja ambas columnas en `User` (`backend/app/models.py:22`) y crea el modelo
`UserStatusEvent` (docstring: insumo de la feature de tiempos, hermano de
`TimeTrackingEvent`/REQ-15 en `models.py:541`). Sin `CHECK` sobre `status`.

### 2. `repositories.py` (SQL con `text()`, sin commit — commitea el router)
- `set_user_presence(db, user_id, status)` → si `status` == actual, retorna
  `None` sin escribir (no-op). Si cambia: (a) `update users set
  presence_status=:s, presence_changed_at=now() where id=:id returning
  presence_changed_at`; (b) `update user_status_events set ended_at=now()
  where user_id=:id and ended_at is null`; (c) `insert into
  user_status_events (user_id, status) values (...)`. Retorna el timestamp.
- `reset_user_presence_on_login(db, user_id)` → mismo mecanismo hacia
  `'disponible'` (no-op si ya lo está).

### 3. Router nuevo `backend/app/routers/presence.py`
- Prefijo `/api/v1/presence`, tag `presence`, mismo estilo que
  `routers/notifications.py`.
- Constante `PRESENCE_STATUSES = {"disponible", "almorzando", "en_el_bano",
  "en_break", "en_reunion"}`.
- `PUT /me` (auth `current_user`): body Pydantic `{status: str}`; si no está
  en el catálogo → 422. Responde `{"status": ..., "changed_at": ...}`
  (`changed_at` actual si fue no-op). Commit en el router.
- Registra el router en `backend/app/main.py` junto a los existentes.

### 4. Integraciones puntuales
- `GET /admin/users` (`backend/app/routers/admin.py:83`): añade
  `u.presence_status, u.presence_changed_at` al SELECT (ya agrupa por `u.id`).
- `GET /auth/me` (`backend/app/routers/auth.py:128-147`): incluye ambos
  campos en el SELECT y en la respuesta.
- Login exitoso (en `auth.py`, tras validar credenciales y antes del commit de
  la sesión): llama `reset_user_presence_on_login`. Razón: un "Almorzando" de
  ayer es ruido hoy; el login es el punto fiable de reset (el logout puede no
  ocurrir).

### 5. Tests `backend/tests/test_presence.py`
SQLite/StaticPool o FakeSession como los existentes — nunca BD real:
1. `PUT /presence/me` válido → 200, `users.presence_status` actualizado y un
   evento abierto (`ended_at is null`).
2. Estado fuera de catálogo → 422, sin evento.
3. Mismo estado dos veces → un solo evento (no-op).
4. Cambio de estado → evento anterior cerrado (`ended_at` seteado) + nuevo
   abierto.
5. Login → resetea a `disponible` y cierra el evento abierto.
6. `GET /admin/users` incluye `presence_status` y `presence_changed_at`.

Corre `pytest backend/tests/ -v` — **toda la suite**, no solo la nueva.

---

## Frontend

### 6. Assets
Mueve (no copies) los 5 SVG de `img/` a `frontend/src/assets/mascot/`:

| Origen (`img/`) | Destino |
|---|---|
| `ChatGPT Image 19 jul 2026, 02_28_02 p.m. (1).svg` | `hello.svg` (pose inicial, saludo) |
| `ChatGPT Image 19 jul 2026, 02_09_16 p.m..svg` | `lunch.svg` |
| `ChatGPT Image 19 jul 2026, 02_18_13 p.m..svg` | `bathroom.svg` |
| `ChatGPT Image 19 jul 2026, 02_23_46 p.m..svg` | `break.svg` |
| `imagen1.svg` | `meeting.svg` |

Elimina la carpeta `img/`. Importa como URL de Vite (`import helloUrl from
"@/assets/mascot/hello.svg"`).

### 7. `frontend/src/lib/presence.ts` — catálogo único
```ts
export type PresenceStatus =
  | "disponible" | "almorzando" | "en_el_bano" | "en_break" | "en_reunion";

export const PRESENCE_CATALOG: Record<PresenceStatus, {
  label: string;            // "Disponible", "Almorzando", "En el baño", "En break", "En reunión"
  icon: LucideIcon;         // Smile, Utensils, Droplet, Coffee, Users
  art: string;              // URL del SVG
  tint: string;             // clase tailwind para dot/chip (p.ej. text/bg con p-accent o tonos)
}>;
export const PRESENCE_ORDER: PresenceStatus[];   // disponible primero
export function presenceTimeAgo(iso: string | null): string; // "hace 12 min" corto
```

### 8. Tipos y cliente
- `api/types.ts` (`UserProfile` en `:288`): añade
  `presence_status: PresenceStatus` y `presence_changed_at: string | null`
  (importa el tipo desde `lib/presence.ts` o declara el union aquí y
  reexporta — un solo source of truth).
- `api/client.ts`: `setPresence(status: PresenceStatus): Promise<{status, changed_at}>`
  → `PUT /api/v1/presence/me`.
- `store/useVerbatixStore.ts`: acción `setPresenceLocal(status, changedAt)`
  que actualiza `user` (la persistencia en `verbatix:user` ya existe vía
  `writeStored`).

### 9. `components/mascot/MascotAvatar.tsx` — la pieza de deleite
`<motion.button>` con `aria-label` "Cambiar estado — actualmente {label}".
Props: `status: PresenceStatus`, `size: "sm" | "lg"` (~40 px / ~180 px),
`onClick`. Capas dentro de un contenedor `relative` cuadrado:

1. **Arte del estado** (`<motion.img src={art}>`) con
   `AnimatePresence mode="popLayout"` keyed por `status`: exit
   `{scale: 0.92, opacity: 0}`, enter con spring
   `{type: "spring", stiffness: 380, damping: 26}`.
2. **Ojos procedurales** — SOLO cuando `status === "disponible"` (única pose
   frontal). Sobre la zona ocular, un SVG absoluto con `viewBox` alineado al
   arte: un parche rect/ellipse de fill `#1F1E2D` (el navy plano de la cara —
   verifica el registro visual en el navegador y calibra las coordenadas en %
   contra `hello.svg`; los ojos originales son dos elipses blancas grandes en
   el centro de la cara) y encima dos ojos: elipse blanca + pupila `#1F1E2D`.
   - **Parpadeo:** `scaleY` 1→0.08→1 en ~120 ms; `setTimeout` recursivo con
     intervalo aleatorio 2.5–6 s; 10 % de las veces doble parpadeo; cleanup
     al desmontar.
   - **Pupilas siguen el cursor:** listener `pointermove` en `window` con
     throttle por `requestAnimationFrame`; desplaza cada pupila hacia el
     cursor con `useSpring` (máx. ~6 % del tamaño del ojo). Si el cursor está
     a > 400 px del centro de la mascota, deriva idle: mirar a un punto
     aleatorio cercano cada ~4 s.
   - Hover del botón → ojos `scale: 1.08` (se "iluminan").
3. **Idle float** (solo `size="lg"`): `animate={{ y: [0, -3, 0] }}`,
   `transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}`.
4. **Gestos:** `whileHover={{ scale: 1.04, rotate: 1.5 }}`,
   `whileTap={{ scale: 0.94 }}`.
5. **Dot de estado** (solo `sm`): círculo absoluto abajo-derecha con el
   `tint` del catálogo y borde `p-surface` (como un presence dot clásico).
6. **`useReducedMotion()`** → true: nada de 2–4; solo fade de opacidad.

### 10. `components/mascot/StatusPicker.tsx`
Popover anclado, mismo patrón que `NotificationsPanel` (se abre desde un ref y
se cierra por clic-fuera como en `AppShell.tsx:72-79`, y con `Escape`).
Contenido: título "¿Qué estás haciendo?", grid de 5 tarjetas en
`PRESENCE_ORDER`: mini-arte (~64 px) + chip con icono y label (replica el chip
lila redondeado de las ilustraciones: `bg-p-accent-soft`, icono violeta).
Entrada con stagger (`staggerChildren: 0.04`, springs suaves). La tarjeta del
estado actual lleva anillo `ring-2 ring-p-accent` y no re-emite. Selección:
1. Optimista: `setPresenceLocal(status, ahora)` + cerrar popover + `playTick()`
   (`lib/sound.ts:84`).
2. `await setPresence(status)`; en error → revert al estado previo +
   `showToast("No se pudo actualizar tu estado.", "error")`.
Teclado: tarjetas son botones reales, Tab/flechas navegan, Esc cierra.

### 11. Montaje
- **Sidebar** (`AppShell.tsx:184-199`): reemplaza el `<div className="avatar">`
  de inicial (`:192`) por `MascotAvatar size="sm" status={user.presence_status}`
  cuyo clic abre `StatusPicker` (nuevo ref + estado `pickerOpen`, mismo manejo
  de clic-fuera que `menuRef`/`bellRef` en `:72-79`). El menú de cuenta
  (email/logout) sigue abriéndose desde el área de email/chevron — no lo
  rompas. Colapsado: solo la mascota con dot y `title={label}`.
- **Dashboard** (`ProjectDashboard.tsx:122`, header "Proyectos"): coloca
  `MascotAvatar size="lg"` a la derecha del header (flex, no rompas el layout
  existente); mismo clic → picker anclado a él.
- **Descubribilidad:** hasta el primer cambio de estado (flag localStorage
  `verbatix:mascot-hint`), la mascota del sidebar lleva la animación
  `pulse-ring` existente (`index.css:215`) y `title="Haz clic para definir tu
  estado"`. Al primer uso, setea el flag y quita el pulso.

### 12. Panel admin (`TeamAdminPage.tsx`)
- `AdminUser` ya heredará los campos (§8). En cada fila de usuario (`:45`),
  junto al chip de `account_status`, añade el chip de presencia:
  `{icono} {label} · {presenceTimeAgo(presence_changed_at)}` con el `tint`
  del catálogo (`disponible` en tono neutro/verde suave; los demás con su
  color). Trunca elegante en pantallas chicas (`hidden sm:flex` si estorba).
- **Refresco:** `useEffect` con `setInterval` de 30 s que re-llama `load()`
  mientras la página está montada + listener `visibilitychange` que refresca
  al volver a la pestaña. Cleanup de ambos.

---

## Definition of Done

- [ ] `pytest backend/tests/ -v` en verde (suite completa, con los 6 tests nuevos).
- [ ] `cd frontend && bunx tsc --noEmit` y `bun run lint` limpios.
- [ ] Flujo usuario: clic en mascota (sidebar y dashboard) → picker → elegir
      "En break" → arte cambia con pop + tick sonoro; recargar la página →
      el estado persiste (viene de `/me`).
- [ ] Flujo admin: con otra sesión admin en `/team`, el chip muestra
      "En break · hace X min" en ≤ 30 s sin recargar.
- [ ] Re-login del usuario → vuelve a "Disponible" y el evento quedó cerrado
      en `user_status_events`.
- [ ] Ojos: parpadean a intervalos irregulares y las pupilas siguen el cursor;
      con `prefers-reduced-motion` activado, nada se mueve salvo fades.
- [ ] `img/` ya no existe; los 5 SVG viven en `frontend/src/assets/mascot/`.
- [ ] Nada roto: campana/long-poll de notificaciones, menú de cuenta,
      aprobación/asignación en `/team`, atajos de teclado.
