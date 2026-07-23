# Correcciones UX — Ronda / Resolución / Auditoría

## Problem Statement
¿Cómo cerramos las brechas entre el flujo esperado (wizard → clasificación → resolución → auditoría) y el comportamiento actual, sin rediseñar lo que ya funciona?

## Recommended Direction
Seis fixes independientes y acotados, agrupables en 3 lotes por área de código:

**Lote 1 — Wizard (bug puro)**
- **A.** `handleContinueToReview` en `CreationWizard.tsx:1250` ignora `withProfile` y siempre hace `goToStep("review")`. Fix: si `withProfile === true`, navegar a `"profile"` en vez de `"review"`.

**Lote 2 — Centro de resolución**
- **B.** El sidebar actual se mantiene sin cambios estructurales. Al expandir un ítem del sidebar, se renderiza la tabla interactiva inline como panel de detalle (no ruta nueva, no tab).
- **C.** En esa tabla, las menciones marcadas como "especiales" se ordenan siempre al final (comparator de sort, no filtro).

**Lote 3 — Auditoría**
- **D.** Vista de auditoría: agregar columnas `respondedId`/`realId`, eliminar columna "qué se hizo".
- **E.** El link/botón "ir a auditoría" queda oculto (no solo deshabilitado) hasta que el 100% de las menciones de la ronda actual estén clasificadas.
- **F.** Cuando el conteo no alcanza el mínimo para una nueva mención, se dispara un toast/banner informativo (no bloqueante) cuyo mensaje varía según el tipo de codificación (`brands`, `dau`, etc. — mismo enum que ya usa `CODING_LABELS`).

## Key Assumptions to Validate
- [ ] "Especial" ya existe como flag/campo en el modelo de mención que llega a la tabla del centro de resolución (no hay que inventarlo) — verificar en `repositories.py`/`models.py`.
- [ ] El endpoint de auditoría expone `respondedId`/`realId` en el payload actual, o requiere un cambio de serializer — verificar antes de tocar frontend.
- [ ] "100% clasificado" tiene ya una fuente de verdad (ej. contador de pendientes por ronda) reutilizable para el gate E, en vez de calcularlo ad-hoc en el frontend.

## MVP Scope
Los 6 ítems tal como están descritos arriba. Cada uno es un diff chico y aislado — no requiere entregarse junto.

## Not Doing (and Why)
- Ruta separada para la tabla "detallada" — el usuario confirmó que va inline al expandir, no como pantalla nueva.
- Modal bloqueante en F — el usuario pidió explícitamente no bloqueante.
- Gate de auditoría a nivel proyecto completo — se limita a la ronda actual, confirmado por el usuario.
- Rediseño visual del sidebar o de la tabla — fuera de alcance, esto es reordenamiento/composición, no un rediseño de UI.

## Open Questions
- Para D: ¿"qué se hizo" se elimina también del backend/export, o solo de la tabla en pantalla?
- Para F: ¿el umbral mínimo por tipo de codificación ya existe en backend (`expectedMaxMentions`/`mentionsDecision` en `roundControls`, visto en `CreationWizard.tsx`) o hay que definirlo nuevo para el centro de resolución?
