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
- [x] Campo con patrón conocido (`NBS_UNAID*`, `VYK[`) → `suggested_coding_type` poblado + `reason` describe el patrón
- [x] Campo sin patrón conocido → `suggested_coding_type=None`, `reason="sin patrón conocido..."`
- [x] Columna de Excel → siempre `suggested_coding_type=None`, `reason=None`
- [x] `sample_values` presente en ambos casos

**Verification:**
- [x] Tests: `pytest backend/tests/test_imports.py -v` (3 passed); suite completa 179 passed
- [x] Manual: N/A

**Dependencies:** Task 1

**Files likely touched:**
- `backend/app/pipeline/imports.py`
- `backend/tests/test_imports.py`

**Estimated scope:** Small (1 archivo + tests)

### Checkpoint: Foundation
- [x] Tests unitarios de Task 1-2 en verde
- [x] Ningún endpoint ni contrato de API tocado todavía

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
- [x] `.dau`: devuelve un item por `question_key` no-infraestructura, con sugerencia cuando aplica
- [x] Excel: devuelve un item por columna de la hoja indicada, sin sugerencia
- [x] No inserta filas ni crea `Question`/`Subproject` — idempotente, se puede llamar N veces
- [x] 404/400 apropiados si `file_id` no existe o `sheet` no existe en el archivo

**Verification:**
- [x] No existe patrón `TestClient`/HTTP en este repo (confirmado: 0 matches en `backend/tests/`) — la lógica nueva
      (`excel.read_rows`) queda cubierta a nivel unitario en `test_excel_column_map.py`; el endpoint es glue delgado
      sobre `field_metadata_for_dau/excel` (ya cubiertas en Task 2). Suite completa: 181 passed.
- [ ] Manual: `curl` contra un `.dau` y un `.xlsx` de prueba, verificar shape de respuesta (pendiente, requiere server corriendo)

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
- [x] Campo con `included=False` → no genera filas en `verbatims`, no aparece en `pending_questions`
- [x] Campo con `coding_type` explícito en ronda con scope `"both"` → `Question` creado con ese `coding_type`, no aparece en `pending_questions`
- [x] `field_selections=None` (tests/llamadas actuales) → comportamiento y respuesta idénticos al pipeline actual (regresión cero)
- [x] Campo con `coding_type` fuera del scope configurado de la ronda → rechazado con error claro (`ValueError` → 400; cierra el hueco de validación identificado en el plan)

**Verification:**
- [x] Tests: `pytest backend/tests/test_question_classification.py -v` (10 passed); suite completa 185 passed
- [ ] Manual: import con `field_selections` variado vs. sin el campo, comparar `pending_questions` resultante (pendiente, requiere server + archivo real)

**Dependencies:** Task 3 (comparte el contrato `FieldSelection`)

**Files likely touched:**
- `backend/app/routers/studios.py`
- `backend/app/repositories.py`
- `backend/tests/test_studios_routes.py`

**Estimated scope:** Medium (2-3 files)

### Checkpoint: Core Features
- [x] Suite completa de backend (`pytest backend/tests/ -v`) en verde (185 passed)
- [ ] Import con selección de campos y clasificación inline probado manualmente contra un `.dau` y un `.xlsx` reales

---

## Fase 3 — Frontend

## Task 5: Componente `SegmentedControl`

**Description:** Componente genérico y accesible: grupo de `<input type="radio">`
ocultos + labels estilizados con Tailwind como segmentos. Props: `options`,
`value`, `onChange`, `name`. Sin dependencias nuevas (no Radix/shadcn — el repo
no los tiene instalados).

**Acceptance criteria:**
- [x] Navegable por teclado (radios nativos lo dan gratis)
- [x] Reusable para 2 o más opciones (min. `brands`/`reasons`)
- [x] Sin `any`, tipado estricto (regla del proyecto)

**Verification:**
- [x] `bunx tsc --noEmit` limpio
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
- [x] Tipos reflejan exactamente el shape de Task 3/4
- [x] `client.ts` no usa `any`

**Verification:**
- [x] `bunx tsc --noEmit` limpio

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
- [x] `codingScope !== "both"` → no renderiza ningún segmentado, campo hereda el tipo de la ronda implícitamente (prop `showCodingType`, computada por el wizard padre)
- [x] `codingScope === "both"` y hay sugerencia (`.dau`) → segmentado pre-marcado + razón visible (`initialFieldSelections` siembra `coding_type` desde `suggested_coding_type`)
- [x] `codingScope === "both"` sin sugerencia (Excel) → segmentado sin preselección (`SegmentedControl` ahora acepta `value: T | null`)
- [x] Checkbox de exclusión funciona independiente del segmentado

**Verification:**
- [x] `bunx tsc --noEmit` limpio
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
- [x] Flujo completo `.dau`: file-drop → sugerencia+razón+muestra → importar respeta selección (`fieldSelections` enviado a `importFile`)
- [x] Flujo completo Excel: file-drop + hoja elegida → muestra (sin sugerencia), tabla en modo `readOnly` (decisión del usuario: Excel es
      solo-muestra en este incremento — sus filas usan `question_key` de la columna "Question ID" del sheet, no el nombre de columna, así
      que field_selections no correspondería a nada real ahí; import de Excel sigue el flujo `columnMap` de siempre, sin tocar)
- [x] Scope único (`brands`/`reasons`) → `showCodingType=false`, tabla sin segmentado, import funciona igual

**Verification:**
- [x] `bunx tsc --noEmit` limpio; `bun run build` limpio
- [ ] Manual en navegador: `cd frontend && bun run dev`, probar ambos formatos y ambos scopes (pendiente, requiere backend corriendo + archivos reales)

**Dependencies:** Task 7

**Files likely touched:**
- `frontend/src/components/CreationWizard.tsx`

**Estimated scope:** Medium (1 file, wizard existente)

---

## Task 9: Integrar en `AddLoadView.tsx`

**Description:** Mismo cambio que Task 8, aplicado al flujo de carga adicional (REQ-03).

**Acceptance criteria:**
- [x] Mismo comportamiento que Task 8, verificado en este flujo (`showCodingType = round.subprojects.length > 1`, mismo readOnly-for-Excel)
- [x] `CreationWizard` y `AddLoadView` usan el mismo `FieldSelectionTable` (no hay segunda implementación divergente)

**Verification:**
- [x] `bunx tsc --noEmit` limpio; `bun run build` limpio
- [ ] Manual: flujo de "carga adicional" end-to-end (pendiente, requiere backend corriendo + ronda real)

**Dependencies:** Task 7 (puede ir en paralelo con Task 8, ambos consumen el mismo componente)

**Files likely touched:**
- `frontend/src/components/AddLoadView.tsx`

**Estimated scope:** Small (1 file, reusa Task 7)

### Checkpoint: Complete
- [x] Todos los criterios de aceptación de Tasks 1-9 cumplidos (salvo verificación manual en navegador, pendiente de server real)
- [x] `pytest backend/tests/ -v` (185 passed) y `bunx tsc --noEmit` / `bun run build` limpios
- [ ] Recorrido manual completo: `.dau`+`both`, Excel+`both`, cualquiera+scope único (pendiente — requiere backend + frontend corriendo con datos reales)
- [x] Ready for review

## Decisión tomada durante la implementación (Task 8)

Excel field_selections quedó fuera de alcance funcional en este incremento: sus filas ya traen `question_key`
desde la columna "Question ID" del sheet (valores, no encabezados), así que un checkbox/segmentado por columna
no correspondería a nada real en `insert_verbatims`. Se preguntó al usuario y se optó por: Excel usa
`FieldSelectionTable` en modo `readOnly` (solo `sample_values`, sin controles), y el import de Excel sigue el
flujo `columnMap` de siempre sin tocar. `.dau` sí tiene selección funcional completa. Si se necesita selección
funcional para Excel más adelante, requiere un modo "wide" nuevo en `excel.parse_verbatims` (fuera del alcance
de este plan, tocaría `excel.py` y `repositories.py` de nuevo).

## Parallelization

- **Paralelizable:** Task 1 y Task 5 (no comparten archivos ni contrato)
- **Secuencial obligatorio:** Task 2 depende de Task 1; Task 3-4 dependen de Task 2; Task 6 depende de contratos de Task 3-4
- **Necesita coordinación:** Task 8 y Task 9 comparten el componente de Task 7 — definir su prop-interface antes de tocar ambos wizards en paralelo
