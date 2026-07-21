# Implementation Plan: Reorganización del wizard de creación de ronda

## Overview
Reordenar el flujo de creación de proyecto/ronda según la encuesta UX (`docs/verbatix-ux-survey_2026-07-20T21-41-23-877Z.json`): el proyecto se crea desde un modal en `ProjectDashboard`, y el wizard de ronda pasa a 6 pasos (archivo+ronda → libro de códigos → campos → perfil opcional → revisar perfil opcional → resumen). Los subprojects se crean después de la ronda, no en el mismo request. La comparación de perfil se separa del import de verbatims para poder correr después de seleccionar campos, no empaquetada dentro de `importFile()`.

## Architecture Decisions
- Backend: `create_round` deja de crear `catalog_origins`/subprojects inline; nuevo endpoint `POST /rounds/{id}/subprojects` los crea en un paso 2.
- Backend: se separa el import de verbatims del cruce de perfil. `importFile()` deja de correr el cruce de perfil como parte del mismo commit; el cruce se dispara con un endpoint explícito, después de que el usuario confirma los campos seleccionados.
- Frontend: `AddLoadView.tsx` se fusiona dentro de `CreationWizard.tsx`; se elimina el paso "Proyecto" del wizard (ya se crea antes, en el modal del dashboard).
- Frontend: preferencias de configuración (umbral, auditoría, alcance, origen de libro de códigos) se guardan en `localStorage`, prellenan el formulario pero nunca fuerzan un valor — el usuario siempre puede editar.
- El gate de confirmación (umbral/auditoría) se mueve al paso de resumen final, con botón "Atrás" habilitado en todos los pasos.

## Task List

### Phase 1: Backend — subprojects diferidos
- [ ] Task 1: `POST /rounds/{id}/subprojects` crea subprojects post-ronda
- [ ] Task 2: `create_round` ya no crea subprojects inline

### Checkpoint: Backend subprojects
- [ ] `pytest backend/tests/ -v` pasa completo
- [ ] Crear ronda vacía + agregar subprojects reproduce el mismo estado final que antes

### Phase 2: Backend — separar cruce de perfil del import
- [ ] Task 3: Endpoint explícito de comparación de perfil, desacoplado de `importFile()`
- [ ] Task 4: Ajustar duplicados por Respondent ID (ver Open Questions)

### Checkpoint: Backend perfil
- [ ] `pytest backend/tests/ -v` pasa completo
- [ ] Import de verbatims funciona sin perfil (flujo "continuar sin perfil")

### Phase 3: Frontend — modal de proyecto en dashboard
- [x] Task 5: Modal de creación de proyecto en `ProjectDashboard.tsx`

### Phase 4: Frontend — fusión y reordenamiento del wizard
- [x] Task 6: Fusionar `AddLoadView.tsx` en `CreationWizard.tsx`, quitar paso "Proyecto"
- [x] Task 7: Reordenar pasos: archivo+ronda → libro de códigos → campos → perfil (opcional) → revisar perfil (opcional) → resumen
- [x] Task 8: Botones "Continuar sin perfil" / "Comparar perfil" al final del paso de campos
- [x] Task 9: `localStorage` para recordar config (umbral, auditoría, alcance, origen libro)

### Checkpoint: Frontend completo
- [x] `bunx tsc --noEmit` sin errores
- [ ] `bun run lint` sin errores (bloqueado por entorno: `@eslint/js` no resuelve, ver todo.md)
- [ ] Flujo manual completo probado en navegador: crear proyecto → crear ronda → importar → libro de códigos → campos → (con y sin perfil) → resumen

## Risks and Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| Tests existentes asumen subprojects creados junto con la ronda | Alto | Actualizar `test_req08_req04.py`, `test_coding_scope.py` y afines en Phase 1 antes de tocar frontend |
| Separar perfil del import puede romper el flujo de duplicados (P3), que hoy comparte el mismo endpoint | Medio | Resolver Open Question antes de Task 3-4 |
| Fusionar dos componentes grandes (`CreationWizard` + `AddLoadView`) puede introducir regresiones de estado entre pasos | Medio | Probar manualmente cada paso tras Task 6-7 antes de seguir |

## Open Questions
- Los duplicados por Respondent ID repetido (hoy parte de `importFile()`), ¿se quedan en el paso de campos o se mueven junto con el cruce de perfil en el paso 4/5? Recomendación: moverlos junto con perfil, ya que ambos usan Respondent ID y evita partir la lógica de cruce en dos lados. Pendiente de confirmación del usuario.
