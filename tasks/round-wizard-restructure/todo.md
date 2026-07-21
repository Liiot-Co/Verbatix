# Todo: Reorganización del wizard de creación de ronda

## Task 1: `POST /rounds/{id}/subprojects` crea subprojects post-ronda

**Description:** Nuevo endpoint que recibe `catalog_origins` (u origen equivalente) para una ronda ya creada y ejecuta la misma lógica de creación de subprojects que hoy corre inline dentro de `create_round`.

**Acceptance criteria:**
- [ ] Llamar al endpoint con una ronda existente crea los subprojects esperados según `catalog_origins`
- [ ] Llamar dos veces no duplica subprojects (idempotente o rechaza si ya existen)

**Verification:**
- [ ] Tests pasan: `pytest backend/tests/ -v -k subprojects`
- [ ] Manual: crear ronda vacía por API, luego POST a `/rounds/{id}/subprojects`, verificar subprojects en DB

**Dependencies:** None

**Files likely touched:**
- `backend/app/routers/studios.py`
- `backend/app/repositories.py`

**Estimated scope:** S

---

## Task 2: `create_round` ya no crea subprojects inline

**Description:** Quitar la creación inline de subprojects de `create_round`; la ronda nace solo con nombre/número/umbral/auditoría.

**Acceptance criteria:**
- [ ] `create_round` ya no recibe/usa `catalog_origins` para crear subprojects
- [ ] Ronda creada queda en estado válido sin subprojects hasta que se llame al endpoint de Task 1

**Verification:**
- [ ] Tests pasan: `pytest backend/tests/ -v`
- [ ] Manual: crear ronda por API, confirmar que no aparecen subprojects hasta el paso 2

**Dependencies:** Task 1

**Files likely touched:**
- `backend/app/routers/studios.py`
- `backend/tests/test_req08_req04.py`
- `backend/tests/test_coding_scope.py`

**Estimated scope:** S

---

## Checkpoint: Backend subprojects
- [ ] `pytest backend/tests/ -v` pasa completo
- [ ] Crear ronda vacía + agregar subprojects reproduce el mismo estado final que antes
- [ ] Revisión con el usuario antes de continuar

---

## Task 3: Endpoint explícito de comparación de perfil

**Description:** Extraer el cruce de perfil (por Respondent ID) de `importFile()` a un endpoint separado que corre sobre verbatims ya importados, disparado explícitamente desde el frontend después de seleccionar campos.

**Acceptance criteria:**
- [ ] `importFile()` deja de ejecutar el cruce de perfil automáticamente
- [ ] Nuevo endpoint corre el cruce sobre datos ya importados y devuelve los mismos flags/resultados que antes

**Verification:**
- [ ] Tests pasan: `pytest backend/tests/ -v -k perfil`
- [ ] Manual: importar archivo sin perfil, confirmar que no bloquea; luego correr el endpoint de perfil por separado

**Dependencies:** None (independiente de Phase 1)

**Files likely touched:**
- `backend/app/pipeline/orchestrator.py` (o donde viva el import actual)
- `backend/app/routers/studios.py`

**Estimated scope:** M

---

## Task 4: Ajustar duplicados por Respondent ID

**Description:** Mover el chequeo de duplicados (P3) junto con el cruce de perfil del Task 3, ya que ambos usan Respondent ID. Pendiente confirmar con usuario antes de implementar (ver Open Question en plan.md).

**Acceptance criteria:**
- [ ] Duplicados se detectan en el mismo paso que perfil (una sola pasada sobre Respondent ID)
- [ ] Flujo "continuar sin perfil" sigue permitiendo detectar duplicados si el usuario decide revisarlos después

**Verification:**
- [ ] Tests pasan: `pytest backend/tests/ -v -k duplicat`
- [ ] Manual: importar archivo con Respondent ID duplicados, confirmar que se reportan en el paso correcto

**Dependencies:** Task 3, confirmación de Open Question

**Files likely touched:**
- `backend/app/pipeline/orchestrator.py`

**Estimated scope:** S

---

## Checkpoint: Backend perfil
- [ ] `pytest backend/tests/ -v` pasa completo
- [ ] Import de verbatims funciona sin perfil (flujo "continuar sin perfil")
- [ ] Revisión con el usuario antes de continuar

---

## Task 5: Modal de creación de proyecto en `ProjectDashboard.tsx`

**Description:** Agregar un modal para crear proyecto directamente desde el dashboard, sin pasar por el wizard.

**Acceptance criteria:**
- [ ] Botón "Nuevo proyecto" abre modal con formulario mínimo (nombre + campos requeridos actuales)
- [ ] Crear proyecto desde el modal navega o refresca la lista igual que el flujo anterior

**Verification:**
- [ ] `bunx tsc --noEmit` sin errores
- [ ] Manual: crear proyecto desde el modal, confirmar que aparece en el dashboard

**Dependencies:** None

**Files likely touched:**
- `frontend/src/components/ProjectDashboard.tsx`

**Estimated scope:** S

---

## Task 6: Fusionar `AddLoadView.tsx` en `CreationWizard.tsx`

**Description:** Unificar ambos componentes en un solo wizard, eliminando el paso "Proyecto" (ya cubierto por Task 5) y el deep-link `?projectId=` sigue saltando directo al primer paso de ronda.

**Acceptance criteria:**
- [x] Un solo componente maneja todo el flujo de ronda, sin duplicar lógica entre los dos archivos originales
- [x] `?projectId=` sigue funcionando (salta directo a "Archivo + Ronda")

**Verification:**
- [x] `bunx tsc --noEmit` sin errores
- [ ] Manual: entrar por deep-link y por dashboard, confirmar mismo comportamiento

**Dependencies:** Task 5

**Files likely touched:**
- `frontend/src/components/CreationWizard.tsx`
- `frontend/src/components/AddLoadView.tsx` (eliminado tras fusión)

**Estimated scope:** L

---

## Task 7: Reordenar pasos del wizard

**Description:** Implementar la secuencia: (1) Archivo+Ronda, (2) Libro de códigos, (3) Campos, (4) Perfil (opcional), (5) Revisar perfil (opcional), (6) Resumen+Confirmar. Botón "Atrás" habilitado en todos los pasos.

**Acceptance criteria:**
- [x] Los 6 pasos aparecen en el orden correcto y son navegables hacia atrás
- [x] El gate de confirmación (umbral/auditoría) vive en el paso de resumen, no antes

**Verification:**
- [x] `bunx tsc --noEmit` sin errores
- [ ] Manual: recorrer los 6 pasos de punta a punta, ida y vuelta

**Dependencies:** Task 6

**Files likely touched:**
- `frontend/src/components/CreationWizard.tsx`

**Estimated scope:** M

---

## Task 8: Botones "Continuar sin perfil" / "Comparar perfil"

**Description:** Al final del paso de campos, mostrar dos botones que ramifican el flujo: saltar directo a resumen, o ir al paso de perfil (que llama al endpoint de Task 3).

**Acceptance criteria:**
- [x] "Continuar sin perfil" salta directo al paso de resumen
- [x] "Comparar perfil" llama al nuevo endpoint y avanza a "Revisar perfil"

**Verification:**
- [ ] Manual: probar ambas ramas end-to-end contra el backend real

**Dependencies:** Task 3, Task 7

**Files likely touched:**
- `frontend/src/components/CreationWizard.tsx`
- `frontend/src/api/` (cliente del nuevo endpoint)

**Estimated scope:** S

---

## Task 9: `localStorage` para recordar configuración

**Description:** Guardar último umbral, auditoría, alcance y origen del libro de códigos usados; prellenar en los pasos correspondientes sin forzar el valor (el usuario siempre puede editar).

**Acceptance criteria:**
- [x] Config previa se prellena automáticamente en una nueva ronda
- [x] Editar y guardar una nueva config actualiza lo guardado en `localStorage` para la próxima vez

**Verification:**
- [ ] Manual: crear dos rondas seguidas, confirmar que la segunda prellena con los valores de la primera

**Dependencies:** Task 7

**Files likely touched:**
- `frontend/src/components/CreationWizard.tsx`

**Estimated scope:** S

---

## Checkpoint: Frontend completo
- [x] `bunx tsc --noEmit` sin errores
- [ ] `bun run lint` sin errores (bloqueado: `@eslint/js` no resuelve en este entorno — falla igual en `developer` sin mis cambios, ver nota abajo)
- [ ] Flujo manual completo probado en navegador: crear proyecto → crear ronda → importar → libro de códigos → campos → (con y sin perfil) → resumen
- [ ] Revisión final con el usuario

**Nota de bloqueo:** `bun run lint` falla con `Cannot find package '@eslint/js'` tanto en el estado limpio de `developer` como con estos cambios aplicados — es un problema de entorno (paquete no instalado/resuelto), no algo introducido por Tasks 6-9. No se pudo verificar lint hasta que se resuelva la instalación de dependencias.

