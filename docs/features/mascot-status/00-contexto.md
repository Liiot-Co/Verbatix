# Mascota interactiva + estado de presencia — CONTEXTO

> Panorama verificado el 2026-07-19 contra el código actual (rutas y líneas
> leídas, no asumidas). Insumo para [`01-plan.md`](01-plan.md) y
> [`02-prompt.md`](02-prompt.md).

---

## 0. Qué se quiere

La mascota de Verbatix (robot naranja con la "W") vive en la app como imagen
**accionable y animada**: al hacer clic, el usuario define su **estado de
presencia** (Almorzando, En el baño, En break, En reunión, o Disponible). La
mascota cambia de arte según el estado, y los **admins ven el estado de cada
persona** desde el panel de equipo. Los ojos y micro-detalles deben estar
animados (parpadeo, seguimiento del cursor) para una experiencia agradable.

Además, el historial de estados alimentará una **futura feature de tiempos**
(cuánto se demora un usuario en un proyecto y en qué estado está) — pariente
directo del `TimeTrackingEvent` que ya existe para REQ-15.

---

## 1. Los assets (`img/`, sin trackear en git)

5 SVG vectorizados por ChatGPT, todos `viewBox` ~1254×1254, **planos**:
paths auto-trazados sin grupos ni IDs semánticos (`id="Layer_1"` único):

| Archivo | Escena | Chip en la imagen | Paths |
|---|---|---|---|
| `ChatGPT … 02_28_02 p.m. (1).svg` | Robot saludando (pose inicial) | — | 48 |
| `ChatGPT … 02_09_16 p.m..svg` | Comiendo sándwich + lonchera | "Almorzando" | 190 |
| `ChatGPT … 02_18_13 p.m..svg` | Cepillándose los dientes | "En el baño" | 78 |
| `ChatGPT … 02_23_46 p.m..svg` | Café en puff | "En break" | 88 |
| `imagen1.svg` | En laptop con globo "…" | "En reunión" | 63 |

Colores dominantes (muestreados del SVG base): cara **#1F1E2D** (navy plano),
cuerpo **#FE5902** (naranja), acentos **#9678F4** (violeta). Calzan con los
tokens del design system: `--p-accent` violeta (h 292) y `--p-accent-mid`
naranja (h 40) en `frontend/src/index.css:37-38`.

**Implicación clave:** al ser trazados planos, los ojos NO son elementos
separables. Pero la cara es un navy plano y uniforme → se puede **cubrir la
zona de ojos con un parche navy y dibujar ojos procedurales encima** (elipses
SVG blancas + pupilas), lo que habilita parpadeo y seguimiento de cursor sin
tocar el arte trazado.

---

## 2. Evaluación de herramienta: Rive vs. stack actual

### Rive (pedido inicial)
- Editor + formato `.riv` + runtime (`@rive-app/react-canvas`). Excelente para
  mascotas con state machines (estilo Duolingo).
- **Contras decisivos para ESTE caso:**
  1. El `.riv` **solo se autora en el editor GUI de Rive** — un agente/código
     no puede producirlo. El plan quedaría bloqueado en un paso manual.
  2. La importación de SVG a Rive funciona bien con SVG por capas (p.ej.
     pegado desde Figma); nuestros 5 archivos son trazados planos de 48–190
     paths sin nombres → limpieza manual pesada por escena en el editor.
  3. Dependencia nueva (runtime ~100 KB + canvas) — regla de CLAUDE.md: no
     agregar dependencias si el stack existente cubre la necesidad.

### framer-motion + capas SVG (recomendado)
- `framer-motion@12` **ya está instalado** (`frontend/package.json`), y ya se
  usa en `AppShell.tsx` (springs, `AnimatePresence`, `whileHover/whileTap`).
- Cubre todo lo pedido: crossfade entre estados, squash-and-stretch al clic,
  flotación idle, y — con el truco del parche navy — **ojos procedurales**
  con parpadeo aleatorio y pupilas que siguen el cursor (más control que un
  timeline pre-horneado de Rive).
- 100 % implementable por un agente, cero pasos manuales, cero dependencias.

**Decisión:** framer-motion + capas. La arquitectura aísla el render en un
componente (`MascotAvatar`) para que migrar a Rive después sea un swap
contenido (anexo en el plan).

---

## 3. Backend verificado

- **`User`** (`backend/app/models.py:22-46`): ya tiene `session_status`
  (`active|away|offline`, comentado REQ-16) y `last_activity_at`, definidos en
  `002_schema_v9.sql:192` pero **sin cablear** (ningún router los usa). Son
  presencia *de conexión*, distinta del estado *declarado* que pide esta
  feature — no se reutilizan ni se pisan.
- **`TimeTrackingEvent`** (`models.py:541`): eventos REQ-15 por
  proyecto/subproyecto/export (`assigned|opened|last_activity|completed|…`).
  El log de estados de esta feature es su complemento natural.
- **Migraciones**: la última es `004_notification_sender.sql`; la siguiente es
  **005**. Patrón: aditivas e idempotentes (`add column if not exists`,
  `create table/index if not exists`), encabezado auto-documentado
  (`003_notifications_reminders.sql`).
- **Long polling ya resuelto** (`app/routers/notifications.py:34-46`):
  `async def` + `run_in_threadpool` + sesión corta por chequeo + timeout 25 s.
  No hace falta replicarlo para presencia: el panel de equipo tolera un
  refresco de ~30 s (ver plan §4).
- **Admin**: `GET /api/v1/admin/users` (`app/routers/admin.py:76-100`) arma la
  lista con SQL explícito — punto natural para exponer el estado al panel.
- **`/me`** (`app/routers/auth.py:128-147`): construye `UserProfile` a mano —
  punto para devolver el estado propio al hidratar sesión.
- **Auth**: `require_admin`/capacidades vía roles; el front usa
  `can(user, "users.manage")` (`frontend/src/lib/capabilities.ts`).
- **Tests**: `pytest backend/tests/` con SQLite/StaticPool (los modelos crean
  el schema; la migración SQL es solo Postgres).

## 4. Frontend verificado

- **`AppShell.tsx`**: sidebar 220/64 px; sección usuario abajo con avatar de
  inicial (`:192`) y patrón de popover anclado ya resuelto (campana +
  `NotificationsPanel anchorRef`, `:169-183`; cierre por clic-fuera `:72-79`).
- **Store**: `useVerbatixStore` (zustand) con `user: UserProfile`, toasts;
  `useNotificationStore` separado — precedente de slice por feature.
- **Tipos**: `UserProfile`/`AdminUser` en `frontend/src/api/types.ts:288-301`;
  cliente HTTP en `api/client.ts` (`getAdminUsers`, etc.).
- **`TeamAdminPage.tsx`**: panel "Equipo y asignaciones" (ruta `/team`, gated
  por `users.manage`), filas de usuario en `:45` — ahí se muestra el estado.
- **Sonido**: `lib/sound.ts` con `playTick`/`playSuccess` (WebAudio, sin asset).
- **Sin test runner FE** (no hay vitest): la verificación es
  `bunx tsc --noEmit` + `bun run lint` + prueba manual.
- **Vite** importa SVG como URL estática; los archivos (57–192 KB) son
  aceptables sin optimizar (svgo opcional en build-time con `bunx`).

## 5. Restricciones heredadas (CLAUDE.md + patrón notifications)

1. Sin dependencias nuevas (cubierto: framer-motion, zustand, lucide, WebAudio).
2. BD: solo lo necesario y justificado; migraciones aditivas e idempotentes.
3. SQL explícito con `text()` en `repositories.py`; TS estricto sin `any`.
4. No romper: toasts, sonido, long-poll de notificaciones, flujo de admin.
5. Sin código muerto: `img/` se muda a `frontend/src/assets/mascot/` con
   nombres semánticos y `img/` desaparece.
