# Todo: Importación de archivos .dau (REQ-01)

## Task 1: Parser `.dau` puro (`backend/app/pipeline/ingest/dau.py`) — [x] Done

**Description:** Portar el parser probado de `parse_dau.py`
(import-export-verbatix) a `backend/app/pipeline/ingest/dau.py`, con la misma
interfaz que `excel.py` para minimizar ramas en el router: `detect_sheets(content:
bytes) -> list[dict]` (una hoja virtual con todos los campos únicos como
columnas) y `parse_verbatims(content: bytes, sheet: str, verbatim_field: str)
-> list[dict]` (una fila por registro con valor no vacío en `verbatim_field`,
`respondent_external_id` = `realid`, `question_key` = `verbatim_field`).

**Acceptance criteria:**
- [ ] `detect_sheets(content)` sobre el `.dau` real devuelve una lista de un
  elemento: `{"name": "Registros DAU", "rows": 1935, "guessed_as":
  "verbatims", "columns": [...42 campos...]}`
- [ ] `parse_verbatims(content, "Registros DAU", "NBS_UNAIDBlock[{_1}].NBS_UNAID")`
  devuelve ~673 filas (según conteo documentado en `Formato DAU.md`), cada una
  con `respondent_external_id`, `question_key="NBS_UNAIDBlock[{_1}].NBS_UNAID"`,
  `original_text`, `input_code_number=None`, `truth_code_number=None`
- [ ] BOM inválido o archivo vacío levanta un error claro (reusa
  `DauFormatError` del prototipo)
- [ ] Comilla simple sin escapar en un valor: comportamiento documentado con
  comentario `ponytail:` (heredado del prototipo, no se corrige aquí)

**Verification:**
- [ ] `pytest backend/tests/test_dau.py -v` pasa
- [ ] Fixture `backend/tests/fixtures/sample.dau` (copiado del repo
  `import-export-verbatix`) presente

**Dependencies:** None

**Files likely touched:**
- `backend/app/pipeline/ingest/dau.py`
- `backend/tests/test_dau.py`
- `backend/tests/fixtures/sample.dau`

**Estimated scope:** Small: 2-3 files

---

## Task 2: Dispatch por contenido en `upload_file` + migración `file_type` — [x] Done

**Description:** En `POST /rounds/{round_id}/files`, sniffear los primeros
bytes del contenido subido: BOM `\xff\xfe` → tratar como `.dau` (llamar
`dau.detect_sheets`, insertar `file_type='dau'`); si no, comportamiento actual
(`excel.detect_sheets`, `file_type='combined_xlsx'`). Migración: agregar
`'dau'` al `check` constraint de `imported_files.file_type` en
`backend/db/migrations/`.

**Acceptance criteria:**
- [ ] Subir un `.dau` inserta `imported_files.file_type = 'dau'`
- [ ] Subir un `.xlsx` sigue insertando `'combined_xlsx'` (sin regresión)
- [ ] Migración nueva (no editar `001_schema_v5.sql` a mano si el proyecto
  usa migraciones incrementales — verificar convención antes de escribirla)

**Verification:**
- [ ] Test de integración: `POST /rounds/{id}/files` con el fixture `.dau`
  responde 201 con `detected_sheets` de una hoja
- [ ] Test de integración existente de subida `.xlsx` sigue pasando

**Dependencies:** Task 1

**Files likely touched:**
- `backend/app/routers/studios.py`
- `backend/db/migrations/<nueva>.sql`
- `backend/tests/test_studios.py` (o el archivo de tests de rounds/files existente)

**Estimated scope:** Small: 2-3 files

---

## Task 3: Activar `column_map.verbatim` en `import_file` — [x] Done

**Description:** `import_file()` hoy recibe `payload.column_map` pero nunca lo
usa — `excel.parse_verbatims` resuelve la columna de verbatim buscando el
header `"verbatim"` a ciegas. Pasar `payload.column_map` a
`parse_verbatims`/`dau.parse_verbatims`; en `excel.parse_verbatims`, si
`column_map` trae `"verbatim"`, usar esa columna explícita en vez del
header-sniffing; si no viene, comportamiento actual sin cambios.

**Acceptance criteria:**
- [ ] `excel.parse_verbatims(content, sheet, column_map={"verbatim": "Col X"})`
  usa `"Col X"` como columna de texto
- [ ] `excel.parse_verbatims(content, sheet)` (sin `column_map`, como hoy)
  se comporta idéntico a antes de este cambio
- [ ] `dau.parse_verbatims` requiere `column_map["verbatim"]` (no hay
  header-sniffing posible para `.dau` — sin este campo, error 400 claro)

**Verification:**
- [ ] Test de regresión: importar el fixture `.xlsx` existente sin
  `column_map` da el mismo resultado que antes del cambio
- [ ] Test nuevo: importar el fixture `.dau` con `column_map.verbatim` inserta
  las filas esperadas

**Dependencies:** Task 1, Task 2

**Files likely touched:**
- `backend/app/routers/studios.py`
- `backend/app/pipeline/ingest/excel.py`
- `backend/tests/test_dau.py`

**Estimated scope:** Small: 2 files

---

## Task 4: Frontend — aceptar `.dau` en el dropzone — [x] Done

**Description:** `CreationWizard.tsx` — agregar `.dau` al objeto `accept` de
`useDropzone` (mime genérico `application/octet-stream` ya que `.dau` no
tiene mime estándar registrado). Sin más cambios: el selector de "hoja de
verbatims" y "columna de verbatim" ya existente cubre la selección de campo
DAU una vez que el backend devuelve la hoja virtual.

**Acceptance criteria:**
- [ ] Arrastrar un `.dau` al dropzone no lo rechaza
- [ ] El flujo de selección de hoja/columna se comporta igual que con Excel
  (una sola opción de "hoja", lista de columnas = campos del `.dau`)

**Verification:**
- [ ] `bunx tsc --noEmit` limpio
- [ ] Manual: subir el `.dau` real, elegir campo, importar, ver verbatims en
  la ronda

**Dependencies:** Task 2, Task 3

**Files likely touched:**
- `frontend/src/components/CreationWizard.tsx`

**Estimated scope:** Small: 1 file

---

## Checkpoint: Foundation (después de Task 1)
- [ ] Parser `.dau` probado en aislamiento, sin tocar el router

## Checkpoint: Backend end-to-end (después de Task 3)
- [ ] Subida + importación completa de `.dau` funciona vía API
- [ ] Sin regresión en el flujo `.xlsx` existente

## Checkpoint: Complete (después de Task 4)
- [ ] Flujo completo probado manualmente en el navegador con el `.dau` real
- [ ] `pytest backend/tests/ -v` y `bunx tsc --noEmit` limpios
