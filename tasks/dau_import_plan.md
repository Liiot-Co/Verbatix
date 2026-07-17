# Implementation Plan: Importación de archivos .dau (REQ-01)

## Overview

Permitir subir un archivo `.dau` (export crudo de Ascribe/IBM MDM) por el mismo
input de archivos que ya acepta `.xlsx`/`.xls` en el wizard de creación de
ronda, y que fluya por el mismo camino de importación (`upload_file` →
selección de "hoja"/columna de verbatim → `import_file` → `insert_verbatims`
→ scheduler). No se toca el motor de clasificación ni el modelo de datos de
verbatims: un `.dau` parseado termina siendo filas `{respondent_external_id,
question_key, original_text}` — la misma forma que ya produce
`excel.parse_verbatims`.

Fuentes revisadas: `parse_dau.py` (prototipo standalone en
`import-export-verbatix`, ya probado contra el `.dau` real de HBG Leches) y
`Formato DAU.md` (documento de investigación del cliente: estructura
`##recstart`/`##v`/`##end`, 42 campos, y qué campos son texto libre a
clasificar vs. metadata/demografía/marca codificada).

## Hallazgos clave que determinan el diseño

- Un `.dau` no tiene "hojas" — es una lista plana de registros (uno por
  encuestado), cada uno con un dict de `campo → valor` de tamaño variable
  (no todos los campos están en todos los registros).
- El campo de identificación de encuestado es siempre `realid`.
- Los campos de texto libre a clasificar son *slots* con nombres como
  `NBS_UNAIDBlock[{_1}].NBS_UNAID`, `NBS_UNAIDBlock[{_2}].NBS_UNAID`, etc. —
  el nombre exacto de estos campos **es específico de cada estudio** (varía
  con el diseño del cuestionario en Ascribe). No hay forma genérica de
  adivinar "el campo de verbatim" como sí la hay en Excel (columna llamada
  literalmente "Verbatim").
- El `.dau` **no trae libro de códigos** — es dato crudo. La importación de
  DAU nunca tiene "hoja de codebook".
- El wizard actual (`CreationWizard.tsx`) ya tiene un selector de "columna de
  verbatim" poblado desde `detected_sheets[i].columns` — si el backend
  devuelve un `.dau` como una única "hoja" virtual con `columns` = lista de
  campos detectados, el flujo de selección de UI sirve sin cambios de
  layout.
- Nota: hoy `column_map` viaja del frontend al backend en `ImportIn` pero
  `import_file()` no lo lee — `parse_verbatims` de Excel resuelve la columna
  buscando el header `"verbatim"` a ciegas. Para xlsx da igual porque el
  usuario no puede evitar que la columna se llame así. Para `.dau` **no hay
  ese header implícito**, así que esta pieza muerta hay que activarla: es el
  único modo de que el usuario diga "este campo es el verbatim".

## Architecture Decisions

- **Dispatch por contenido, no por extensión.** `upload_file` sniffea los
  primeros bytes (`\xff\xfe` BOM → `.dau`; `PK\x03\x04` → xlsx/zip) en vez de
  confiar en el nombre de archivo. Más robusto y es lo mismo que ya hace
  `parse_dau._check_encoding`.
- **Nuevo módulo `backend/app/pipeline/ingest/dau.py`**, hermano de
  `excel.py`, con la misma forma de interfaz (`detect_sheets`,
  `parse_verbatims`) para que `studios.py` no necesite ramas nuevas más allá
  del dispatch inicial. El parser interno (`##recstart`/`##v`/`##end`,
  BOM UTF-16LE) se porta tal cual desde `parse_dau.py` — ya está probado
  contra el archivo real, no hay razón para reescribirlo.
- **Un registro DAU = una "hoja" virtual de una sola fila-tipo.**
  `detect_sheets` para `.dau` devuelve `[{"name": "Registros DAU", "rows":
  N, "guessed_as": "verbatims", "columns": [<campos únicos ordenados>]}]`.
  Sin adivinación de campo "correcto" — el usuario elige el campo de verbatim
  igual que elegiría una columna de Excel.
- **`column_map.verbatim` se activa en el backend** (hoy dead code) porque
  sin él no hay forma de que `.dau` funcione: `import_file()` pasa
  `payload.column_map` a `parse_verbatims`; el parser de Excel lo usa si
  viene (columna explícita) y si no cae al header-sniffing actual
  (retrocompatible, cero cambio de comportamiento para rondas existentes).
- **Un campo por importación, no auto-unpivot de slots (`NBS_UNAID[1..3]`).**
  Combinar los 3 slots en una sola importación (una fila por slot no vacío)
  sería más "completo" pero es una decisión de producto no validada
  (¿se combinan como 3 filas del mismo respondente? ¿se conserva el índice de
  slot?) — fuera de alcance de REQ-01, que solo pide "importar por el mismo
  input". Documentado como pregunta abierta abajo.
- **Sin libro de códigos para `.dau`.** El selector de "hoja de codebook" del
  wizard simplemente no tendrá opciones más allá de "Ninguna" cuando el
  archivo subido sea un `.dau` (la única "hoja" es la de verbatims).
- **Migración mínima**: `imported_files.file_type` gana el valor `'dau'` en
  el `check` constraint. `upload_file` ya hardcodea `'combined_xlsx'` para
  todo lo que sube (bug preexistente, fuera de alcance) — para `.dau`
  hardcodeamos `'dau'` en esa misma rama nueva.
- **Frontend**: el dropzone de `CreationWizard.tsx` agrega `.dau` a `accept`
  (mime `application/octet-stream` genérico, ya que `.dau` no tiene mime
  estándar). Sin más cambios de layout — reutiliza el selector de hoja/columna
  existente.

## Task List

### Phase 1: Foundation (parser puro, sin tocar API)
- [ ] Task 1: Portar `parse_dau.py` a `backend/app/pipeline/ingest/dau.py`
  con `detect_sheets(content: bytes)` y `parse_verbatims(content: bytes,
  sheet: str, verbatim_field: str) -> list[dict]`, más
  `test_dau.py` con el fixture real (copiar `sample.dau` a
  `backend/tests/fixtures/`).

### Checkpoint: Foundation
- [ ] `pytest backend/tests/test_dau.py -v` pasa contra el fixture real
- [ ] `detect_sheets` sobre el fixture devuelve 1 hoja virtual con 42 columnas

### Phase 2: Wire-up backend (activa `.dau` en el mismo endpoint)
- [ ] Task 2: Dispatch por contenido en `upload_file` (BOM → `dau.py`, si no
  → `excel.py`), inserta `imported_files.file_type = 'dau'` en ese caso.
  Migración: agregar `'dau'` al check constraint de `file_type`.
- [ ] Task 3: `import_file` pasa `payload.column_map` a
  `excel.parse_verbatims`/`dau.parse_verbatims`; `excel.parse_verbatims` usa
  `column_map.get("verbatim")` si viene, si no cae al comportamiento actual.

### Checkpoint: Backend end-to-end
- [ ] Subir el `.dau` fixture vía `POST /rounds/{id}/files` devuelve
  `detected_sheets` con la hoja virtual
- [ ] `POST /rounds/{id}/files/{id}/import` con `column_map.verbatim =
  "NBS_UNAIDBlock[{_1}].NBS_UNAID"` inserta verbatims y dispara el scheduler
  igual que un `.xlsx`
- [ ] Import de un `.xlsx` existente sigue funcionando igual (regresión)

### Phase 3: Frontend (mínimo)
- [ ] Task 4: `accept` del dropzone en `CreationWizard.tsx` incluye `.dau`.
  Sin cambios de UI adicionales — el selector de hoja/columna ya existente
  cubre la selección de campo.

### Checkpoint: Complete
- [ ] Manual: arrastrar el `.dau` real al wizard, elegir el campo
  `NBS_UNAIDBlock[{_1}].NBS_UNAID` como verbatim, importar, confirmar que las
  filas aparecen en la ronda con `respondent_external_id` = `realid`
- [ ] `bunx tsc --noEmit` limpio
- [ ] `pytest backend/tests/ -v` limpio

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| El campo de verbatim varía por estudio, no hay adivinación posible | Bajo — el usuario ya elige columna manualmente en el wizard | Ninguna adivinación automática; UI ya soporta selección manual |
| Activar `column_map.verbatim` en `excel.parse_verbatims` toca código usado en producción por rondas Excel existentes | Medio | Fallback explícito al comportamiento actual cuando `column_map` es `None` o no trae `verbatim`; test de regresión con fixture Excel existente |
| Un valor con comilla simple sin escapar rompe el regex del parser (límite conocido, documentado en `parse_dau.py` con `ponytail:`) | Bajo (no ocurre en el archivo real del cliente) | Se hereda el mismo límite documentado; no se resuelve en esta fase |

## Open Questions

- ¿Se necesita extraer demografía de `dumurl` (edad, género, NSE, región) ya
  en esta importación, o es un requerimiento posterior de reporting? El
  documento de investigación lo marca como "no para clasificación en sí,
  pero sí para reporting" — no bloquea REQ-01.

## Actualización 1 (post-implementación): auto-selección "tomar todo" — revertida

Primer intento tras el diseño original: quitar el picker de campo y tomar
TODO campo `##v` con valor no vacío como fila (excepto `realid`). Probado
contra un `.dau` real de otro cliente (no HBG Leches) y falló: mezclaba
metadata/variables codificadas con verbatims reales, porque los nombres de
campo no siguen ninguna convención común entre estudios (`NBS_UNAID*` en un
cliente, `CAT_DIFF`/`PRICE_DA`/`VYK*` en otro) — no hay forma de adivinar
genéricamente "esto es texto libre" solo por el nombre del campo.

## Actualización 2: selección explícita multi-campo — también revertida

Segundo intento: checkboxes para que el analista elija manualmente los
campos de verbatim. Correcto pero no lo que se pidió — el requerimiento es
auto-selección ahora, con la posibilidad de parametrizar por estudio más
adelante (no una elección manual en cada importación).

## Actualización 3: exclusión por infraestructura conocida (diseño final)

Se revisó el `.dau` real completo del cliente (`Datos Cliente/
32406358_HBG_LECHES_2026.dau`) junto con su `MetaData.txt` (codebook de
salida de Ascribe — confirma que `NBS_UNAID_FUP_ADD[{_N}].Slice`, `VYK[N]
.Slice`, etc. son variables de marca que Ascribe termina codificando con
`CB_#`, es decir, contenido de respuesta real, no infraestructura) para
confirmar la categorización de `Formato DAU.md`: 21 campos son
infraestructura de la plataforma (IBM MDM/Ascribe) que aparece en **todo**
`.dau` sin importar el diseño del cuestionario — identificación (`realid`,
`panelDetails.*`), metadata de proyecto, fechas, URLs y control de calidad
(`DQM.*`). Esa lista (`dau._NON_RESPONSE_FIELDS`) es la que se excluye;
**todo lo demás se autoincluye como respuesta abierta**, sin necesidad de
que el analista elija nada. Esto generaliza entre estudios porque la lista
de exclusión es infraestructura de la plataforma (constante), no nombres de
pregunta (que sí varían por estudio — `NBS_UNAID*` en un cliente,
`CAT_DIFF`/`PRICE_DA` en otro — y por eso SÍ se autoincluyen).

Marcado con `ponytail:` en el código: la exclusión es por nombre exacto, no
por prefijo, y no hay forma de parametrizarla por estudio todavía — si un
cliente futuro trae infraestructura adicional de otro export tool, o un
estudio necesita excluir un campo de pregunta que no es texto libre (p.ej.
una selección categórica con nombre no reconocible), hoy no hay override.
Confirmado con el usuario que esto es intencional: la parametrización por
estudio es un requerimiento posterior, no de REQ-01.
