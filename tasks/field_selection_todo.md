# Selección de campos a clasificar + muestra — Backlog (ver detalle en tasks/field_selection_plan.md)

## Fase 1 — Foundation (backend, pure logic)

## Task 1: Helper `sample_values` para dau y excel

**Description:** Función pura que, dado un set de registros/filas ya parseados
en memoria, devuelve N (default 5) valores no vacíos y distintos para un
campo/columna dado, elegidos al azar. Una implementación en
`pipeline/ingest/dau.py` (opera sobre `list[dict[str, str]]` de
`parse_records`) y otra en `pipeline/ingest/excel.py` (opera sobre filas ya
leídas de una hoja). Sin I/O nuevo — reusa datos ya parseados, no vuelve a leer
el archivo.

**Acceptance criteria:**
- [x] `dau.sample_values(records, field, n=5)` devuelve hasta `n` valores no
      vacíos únicos de ese campo (menos si el campo tiene menos valores distintos)
- [x] `excel.sample_values(rows, column, n=5)` mismo contrato para columnas de Excel
- [x] Determinístico en tests (semilla fija o input pequeño que no requiera random real)

**Verification:**
- [x] Tests: `pytest backend/tests/test_dau.py -v`, `pytest backend/tests/test_excel_sample_values.py -v` (16 passed)
- [x] Manual: N/A (función pura)

**Dependencies:** None

**Files likely touched:**
- `backend/app/pipeline/ingest/dau.py`
- `backend/app/pipeline/ingest/excel.py`
- `backend/tests/test_dau.py` / `backend/tests/test_excel.py`

**Estimated scope:** Small (2 files + tests)

---

## Task 2: Ensamblado de metadata por campo

**Description:** Función que, para un `.dau` parseado, devuelve
`list[{field, suggested_coding_type, reason, sample_values}]` combinando
`guess_coding_type()` (ya existe) + `sample_values` (Task 1); `reason` es el
patrón que matcheó (ej. `"coincide con plantilla NBS_UNAID"`) o
`"sin patrón conocido, requiere clasificación manual"` si `guess_coding_type`
devuelve `None`. Equivalente para Excel pero con `suggested_coding_type=None`,
`reason=None` siempre (sin heurística). Vive en `pipeline/imports.py` (mismo
archivo que ya tiene `suggested_source_label` y la lógica de duplicados).

**Acceptance criteria:**
- [ ] Campo con patrón conocido (`NBS_UNAID*`, `VYK[`) → `suggested_coding_type` poblado + `reason` describe el patrón
- [ ] Campo sin patrón conocido → `suggested_coding_type=None`, `reason="sin patrón conocido..."`
- [ ] Columna de Excel → siempre `suggested_coding_type=None`, `reason=None`
- [ ] `sample_values` presente en ambos casos

**Verification:**
- [ ] Tests: nuevo `pytest backend/tests/test_imports.py -v` (o el archivo que agrupe `pipeline/imports.py`)
- [ ] Manual: N/A

**Dependencies:** Task 1

**Files likely touched:**
- `backend/app/pipeline/imports.py`
- `backend/tests/test_imports.py`

**Estimated scope:** Small (1 archivo + tests)

### Checkpoint: Foundation
- [ ] Tests unitarios de Task 1-2 en verde
- [ ] Ningún endpoint ni contrato de API tocado todavía

---

## Fase 2 — Backend wiring

## Task 3: Endpoint `preview-fields`

**Description:** `POST /rounds/{round_id}/files/{file_id}/preview-fields`
(body: `{sheet: str | None}` para Excel, ignorado para `.dau`). Parsea el
archivo ya subido (mismo storage/checksum que usa `catalog-preview`,
`studios.py:760-786`), corre la función de Task 2, devuelve
`{fields: [{field, suggested_coding_type, reason, sample_values}]}` sin
persistir nada.

**Acceptance criteria:**
- [ ] `.dau`: devuelve un item por `question_key` no-infraestructura, con sugerencia cuando aplica
- [ ] Excel: devuelve un item por columna de la hoja indicada, sin sugerencia
- [ ] No inserta filas ni crea `Question`/`Subproject` — idempotente, se puede llamar N veces
- [ ] 404/400 apropiados si `file_id` no existe o `sheet` no existe en el archivo

**Verification:**
- [ ] Tests: `pytest backend/tests/test_studios_routes.py -v -k preview_fields` (o archivo equivalente de rutas)
- [ ] Manual: `curl` contra un `.dau` y un `.xlsx` de prueba, verificar shape de respuesta

**Dependencies:** Task 2

**Files likely touched:**
- `backend/app/routers/studios.py`
- `backend/tests/test_studios_routes.py`

**Estimated scope:** Small (1-2 files)

---

## Task 4: Extender `ImportIn` + `insert_verbatims` con `field_selections`

**Description:** Agregar `field_selections: list[FieldSelection] | None = None`
a `ImportIn` (`FieldSelection = {field: str, included: bool, coding_type: str | None}`).
Si es `None`, comportamiento idéntico a hoy. Si viene poblado:
filtrar en el parseo (`dau.parse_verbatims`/`excel.parse_verbatims`) los campos
con `included=False`; para campos con `coding_type` explícito, crear/asociar el
`Question` correspondiente en el momento del import (mismo camino que el
auto-match existente de `guess_coding_type`, `repositories.py:558`) para que no
caigan en `pending_questions`.

**Acceptance criteria:**
- [ ] Campo con `included=False` → no genera filas en `verbatims`, no aparece en `pending_questions`
- [ ] Campo con `coding_type` explícito en ronda con scope `"both"` → `Question` creado con ese `coding_type`, no aparece en `pending_questions`
- [ ] `field_selections=None` (tests/llamadas actuales) → comportamiento y respuesta idénticos al pipeline actual (regresión cero)
- [ ] Campo con `coding_type` fuera del scope configurado de la ronda → rechazado con error claro (aprovecha para cerrar el hueco de validación ya identificado, ver plan.md)

**Verification:**
- [ ] Tests: `pytest backend/tests/ -v -k import` en verde, incluidos los existentes de `.dau`/Excel
- [ ] Manual: import con `field_selections` variado vs. sin el campo, comparar `pending_questions` resultante

**Dependencies:** Task 3 (comparte el contrato `FieldSelection`)

**Files likely touched:**
- `backend/app/routers/studios.py`
- `backend/app/repositories.py`
- `backend/tests/test_studios_routes.py`

**Estimated scope:** Medium (2-3 files)

### Checkpoint: Core Features
- [ ] Suite completa de backend (`pytest backend/tests/ -v`) en verde
- [ ] Import con selección de campos y clasificación inline probado manualmente contra un `.dau` y un `.xlsx` reales

---

## Fase 3 — Frontend

## Task 5: Componente `SegmentedControl`

**Description:** Componente genérico y accesible: grupo de `<input type="radio">`
ocultos + labels estilizados con Tailwind como segmentos. Props: `options`,
`value`, `onChange`, `name`. Sin dependencias nuevas (no Radix/shadcn — el repo
no los tiene instalados).

**Acceptance criteria:**
- [ ] Navegable por teclado (radios nativos lo dan gratis)
- [ ] Reusable para 2 o más opciones (min. `brands`/`reasons`)
- [ ] Sin `any`, tipado estricto (regla del proyecto)

**Verification:**
- [ ] `bunx tsc --noEmit` limpio
- [ ] Manual: render en Storybook-less smoke — probar en el propio wizard (Task 8)

**Dependencies:** None

**Files likely touched:**
- `frontend/src/components/SegmentedControl.tsx`

**Estimated scope:** Small (1 file)

---

## Task 6: Tipos + cliente API

**Description:** Agregar `FieldPreview` y `FieldSelection` a `types.ts`;
`previewFields(roundId, fileId, sheet?)` y extender `importFile(...)` en
`client.ts` para aceptar `field_selections`.

**Acceptance criteria:**
- [ ] Tipos reflejan exactamente el shape de Task 3/4
- [ ] `client.ts` no usa `any`

**Verification:**
- [ ] `bunx tsc --noEmit` limpio

**Dependencies:** Task 3, Task 4 (contratos ya definidos en backend)

**Files likely touched:**
- `frontend/src/api/types.ts`
- `frontend/src/api/client.ts`

**Estimated scope:** Small (2 files)

---

## Task 7: Componente compartido `FieldSelectionTable`

**Description:** Tabla/lista: por fila, checkbox incluir/excluir, nombre de
campo, muestra de valores (`sample_values`), y `SegmentedControl` (Task 5) que
solo se renderiza si el `codingScope` de la ronda es `"both"` — recibe esa
prop desde el wizard padre. Pre-selecciona el segmento si `suggested_coding_type`
viene poblado, mostrando `reason` como texto de ayuda/tooltip.

**Acceptance criteria:**
- [ ] `codingScope !== "both"` → no renderiza ningún segmentado, campo hereda el tipo de la ronda implícitamente
- [ ] `codingScope === "both"` y hay sugerencia (`.dau`) → segmentado pre-marcado + razón visible
- [ ] `codingScope === "both"` sin sugerencia (Excel) → segmentado sin preselección
- [ ] Checkbox de exclusión funciona independiente del segmentado

**Verification:**
- [ ] `bunx tsc --noEmit` limpio
- [ ] Manual: usado dentro de Task 8/9

**Dependencies:** Task 5, Task 6

**Files likely touched:**
- `frontend/src/components/FieldSelectionTable.tsx`

**Estimated scope:** Medium (1 file, lógica condicional no trivial)

---

## Task 8: Integrar en `CreationWizard.tsx`

**Description:** Tras seleccionar la hoja/archivo, llamar `previewFields`, mostrar
`FieldSelectionTable`, y al confirmar enviar `field_selections` en `importFile`.

**Acceptance criteria:**
- [ ] Flujo completo `.dau`: file-drop → sugerencia+razón+muestra → importar respeta selección
- [ ] Flujo completo Excel: file-drop → muestra (sin sugerencia) → importar respeta selección
- [ ] Scope único (`brands`/`reasons`) → tabla sin segmentado, import funciona igual

**Verification:**
- [ ] `bunx tsc --noEmit` limpio
- [ ] Manual en navegador: `cd frontend && bun run dev`, probar ambos formatos y ambos scopes

**Dependencies:** Task 7

**Files likely touched:**
- `frontend/src/components/CreationWizard.tsx`

**Estimated scope:** Medium (1 file, wizard existente)

---

## Task 9: Integrar en `AddLoadView.tsx`

**Description:** Mismo cambio que Task 8, aplicado al flujo de carga adicional (REQ-03).

**Acceptance criteria:**
- [ ] Mismo comportamiento que Task 8, verificado en este flujo
- [ ] `CreationWizard` y `AddLoadView` usan el mismo `FieldSelectionTable` (no hay segunda implementación divergente)

**Verification:**
- [ ] `bunx tsc --noEmit` limpio
- [ ] Manual: flujo de "carga adicional" end-to-end

**Dependencies:** Task 7 (puede ir en paralelo con Task 8, ambos consumen el mismo componente)

**Files likely touched:**
- `frontend/src/components/AddLoadView.tsx`

**Estimated scope:** Small (1 file, reusa Task 7)

### Checkpoint: Complete
- [ ] Todos los criterios de aceptación de Tasks 1-9 cumplidos
- [ ] `pytest backend/tests/ -v` y `bunx tsc --noEmit` limpios
- [ ] Recorrido manual completo: `.dau`+`both`, Excel+`both`, cualquiera+scope único
- [ ] Ready for review

## Parallelization

- **Paralelizable:** Task 1 y Task 5 (no comparten archivos ni contrato)
- **Secuencial obligatorio:** Task 2 depende de Task 1; Task 3-4 dependen de Task 2; Task 6 depende de contratos de Task 3-4
- **Necesita coordinación:** Task 8 y Task 9 comparten el componente de Task 7 — definir su prop-interface antes de tocar ambos wizards en paralelo
