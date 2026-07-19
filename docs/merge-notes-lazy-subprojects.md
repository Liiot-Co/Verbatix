# Notas de merge — creación perezosa de subproyectos

Documentación de los cambios sin commitear en `developer` (rama `feature/dau-import`
en progreso) antes de mergear con la otra rama, para acelerar la resolución de
conflictos. Cambio central: **una Ronda ya no crea Marcas/Razones a ciegas al
crearse** — cada subproyecto nace perezosamente cuando un archivo importado trae
filas de ese `coding_type`.

## backend/app/pipeline/ingest/dau.py
- Añade `_NON_RESPONSE_FIELDS`: `VXY.Other`, `VYH.Other` (campos "otro,
  especifique" de preguntas cerradas — no son verbatims).
- Añade `_KNOWN_CODING_TYPES` + `guess_coding_type(question_key)`: reconoce por
  regex la plantilla Ascribe/IBM MDM `NBS_UNAID*` (y `VYK[` específico del
  script 32406358 HBG LECHES) para auto-clasificar sin pedirle al analista.
  Si no matchea ningún patrón, devuelve `None` → el caller la trata como
  variable nueva pendiente de clasificación manual.
- **Riesgo de conflicto**: si la otra rama toca `_NON_RESPONSE_FIELDS` o el
  bloque de constantes de este archivo.

## backend/app/pipeline/llm/client.py
- Añade `_build_naming_prompt` + `name_clusters(representative_texts)`: 1
  llamado LLM que le pone nombre de categoría a cada texto representativo de
  un cluster semántico (usa `pipeline/semantic/cluster.py`, archivo nuevo sin
  trackear). Fallback: si el LLM omite un índice, usa el texto original
  capitalizado.
- Solo agrega funciones al final del archivo — bajo riesgo de conflicto salvo
  que la otra rama también agregue al final.

## backend/app/repositories.py
- `insert_verbatims`: nuevos params opcionales `min_mentions_threshold`,
  `audit_percentage` (solo se usan si hace falta crear un subproyecto nuevo).
- Import de `questions`/`question_aliases` pasa de 1 SELECT por fila
  (`question_cache`/`_resolve_question_id`) a precarga completa por proyecto
  (`questions_by_key`) — elimina N+1.
- Si una `question_key` no está en `questions_by_key`, primero prueba
  `guess_coding_type` (plantilla NBS_UNAID*); si matchea, la clasifica sola
  vía `classify_question`; si no, va a `pending` como antes.
- `rows_by_coding_type` ya no asume `{"brands": [...], "reasons": [...]}` fijo
  — usa `.setdefault(coding_type, [])`.
- Cuando no existe `subproject_by_coding_type[coding_type]`, en vez de
  `continue` (skip silencioso, asumía que `create_round` ya lo había creado)
  ahora llama a `get_or_create_subproject(...)`.
- Inserción de respondents y verbatims pasa de fila-por-fila a batch
  (`INSERT ... ON CONFLICT` con lista de params) — mismo comportamiento,
  menos roundtrips.
- **Nueva función `get_or_create_subproject(db, round_id, project_id,
  coding_type, min_mentions_threshold=None, audit_percentage=None)`**:
  reemplaza la lógica que antes vivía en `studios.py::create_round` (creación
  de codebook compartido + homologación cross-estudio si `origin_mode ==
  'homologated'`). Defaults `3`/`10` si no vienen del wizard.
- **Riesgo de conflicto alto**: `insert_verbatims` es el corazón del import;
  si la otra rama también toca esta función (p. ej. para otro formato de
  archivo o distinta resolución de `question_id`), el conflicto va a ser
  estructural, no de líneas sueltas — revisar con cuidado el flujo completo,
  no solo aceptar "ours"/"theirs".

## backend/app/routers/studios.py
- `create_round`: ya NO crea los 2 subprojects (Marcas/Razones). Solo inserta
  la fila de `rounds` y devuelve `"subprojects": []`. Se eliminó
  `_get_or_create_codebook` (movida/fusionada a `get_or_create_subproject` en
  repositories.py) y los imports `create_codebook`/`seed_system_codes` (ya no
  se usan acá directamente).
- `get_round`: el SELECT de subprojects ahora también trae `status`,
  `origin_mode`, `source_subproject_id`, `min_mentions_threshold`,
  `audit_percentage` (antes esos campos no se exponían al frontend).
- **Nuevo endpoint** `PATCH /api/v1/subprojects/{subproject_id}`
  (`SubprojectUpdateIn`): homologación *por subproyecto*, movida acá desde
  `create_round` (antes la homologación era a nivel Ronda, ahora es a nivel
  Subproyecto porque ya no nacen juntos). Solo permite cambiar `origin_mode`/
  `source_round_id`, y solo si `status == 'created'` (no procesó todavía).
  `min_mentions_threshold`/`audit_percentage` explícitamente NO editables acá
  (comentario in-code explica por qué: catálogo por frecuencia + muestreo de
  auditoría quedan inconsistentes si cambian post-proceso).
- `ImportIn`: nuevos campos opcionales `min_mentions_threshold`,
  `audit_percentage`, capturados en el wizard al soltar el archivo.
- `import_file`: pasa esos dos campos a `insert_verbatims`; si hay
  `codebook_sheet`, llama `get_or_create_subproject` antes de buscar el
  `codebook_id` (el subproyecto de ese coding_type puede no existir todavía).
- **Riesgo de conflicto alto**: si la otra rama toca `create_round` o
  `get_round` (firma de respuesta, campos de `RoundIn`/`ImportIn`), esperar
  conflicto de intención, no solo de texto — la otra rama probablemente
  todavía asume "2 subprojects siempre existen".

## frontend/src/api/client.ts
- `CreateRoundInput`: perdió `min_mentions_threshold`, `audit_percentage`,
  `origin_mode`, `source_round_id` (ya no se mandan al crear la ronda).
- `importFile`: firma cambió de params posicionales
  (`codebookSheet?, codebookCodingType?`) a un solo objeto
  **`ImportSettings`** (`codebookSheet`, `codebookCodingType`,
  `minMentionsThreshold`, `auditPercentage`). **Breaking change de firma** —
  todo caller existente en la otra rama que llame `importFile(...)`
  posicionalmente va a fallar en compilación, no en runtime.

## frontend/src/api/types.ts
- `RoundSubproject`: añade campos opcionales `status`, `origin_mode`,
  `source_subproject_id`, `min_mentions_threshold`, `audit_percentage`
  (reflejan el nuevo SELECT de `get_round` en el backend).

## frontend/src/components/CreationWizard.tsx
- **Elimina el paso "studio" del wizard** (`WizardStep` pasa de
  `"project" | "studio" | "round"` a `"project" | "round"`). Se borra todo el
  bloque JSX del step 2 (~150 líneas: ToggleGroup de coding_type/origen,
  selector de estudio origen para homologar, `homologationCandidates`,
  `handleContinueFromStudio`).
- El threshold/auditoría (`rThreshold`/`rAudit`) ahora se piden siempre en el
  step de Ronda (antes el mínimo de menciones solo se mostraba si
  `newStudyCodingType === "brands"`).
- `handleCreateProject`/efecto inicial: al crear o cargar proyecto, saltan
  directo a `goToStep("round")` en vez de `"studio"`.
- `ensureRound`/`createRound` en el batch upload: ya no mandan
  `min_mentions_threshold`/`audit_percentage`/`origin_mode`/`source_round_id`
  al crear la ronda; se los pasa a `importFile` vía `ImportSettings` en su
  lugar.
- Llamadas a `importFile` migradas al nuevo objeto `ImportSettings`.
- Mensaje de `pendingQuestions` ahora distingue `.dau` vs Excel: para `.dau`
  muestra un aviso de "contacta a ingeniería" (variables fuera de plantilla
  NBS_UNAID*) en vez del flujo de auto-clasificación manual que sigue
  existiendo para Excel.
- **Riesgo de conflicto alto**: si la otra rama toca el wizard (cualquier
  step), el diff es grande y estructural (borra un step completo) — probable
  que Git no pueda hacer merge automático de esta sección; conviene revisar
  a mano contra la intención de ambas ramas en vez de resolver línea por
  línea.

## Resumen de riesgo
| Archivo | Riesgo | Motivo |
|---|---|---|
| studios.py | Alto | `create_round`/`ImportIn`/`get_round` cambian de contrato |
| repositories.py | Alto | `insert_verbatims` reescrita (N+1→batch) + nueva función |
| CreationWizard.tsx | Alto | Borra un step completo del wizard |
| client.ts | Medio | `importFile` cambia de firma (breaking) |
| types.ts | Bajo | Solo campos opcionales añadidos |
| dau.py | Bajo | Solo agrega constantes/función nueva |
| client.py (llm) | Bajo | Solo agrega función nueva al final |
