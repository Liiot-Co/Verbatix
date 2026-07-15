# Implementation Plan: Concurrencia entre rondas + Caché semántico local

## Overview

Reparar la topología del pipeline de clasificación (`backend/app/pipeline/`) para (1) procesar varias rondas del mismo estudio en paralelo sin agregar un broker de mensajes, (2) promocionar automáticamente resultados LLM aprobados al catálogo fuzzy (marcas) y a un caché semántico local (razones), y (3) usar `source_round_id` para que una ronda nueva arranque con el conocimiento de la anterior. Objetivo: reducir el volumen de verbatims que necesita una llamada real a DeepSeek, que es el cuello de botella medido (~20-25s/batch). **Fuera de alcance:** reescritura en Rust (ver Not Doing) — se revisita solo si, tras medir el impacto de este plan, el overhead de orquestación Python (no la red al LLM) resulta ser el cuello de botella dominante.

## Decisiones de Arquitectura

- **Sin Redis/Celery/RabbitMQ.** El trabajo entre rondas es I/O-bound (HTTP a DeepSeek); un pool de threads en proceso ya libera el GIL en la espera de red. Se usa un scheduler in-process (cola stdlib + N workers arrancados en el lifecycle de FastAPI), con estado visible en la tabla `processing_runs` que ya existe (columna `status`: queued/running/completed/failed).
- **Sin base de datos vectorial standalone.** Se usa `pgvector` como extensión del Postgres existente (imagen `pgvector/pgvector:pg16` en vez de `postgres:16-alpine`), no Milvus/Qdrant.
- **Promoción de marcas ≠ promoción de razones.** `fuzzy/matcher.py` documenta explícitamente por qué fuzzy no se usa para razones (falsos positivos tipo "frescura"~"firme"). La promoción automática de LLM-aprobado va al catálogo fuzzy (`code_aliases`) SOLO para `coding_type=='brands'`; para razones va al caché semántico nuevo (pgvector), nunca al catálogo fuzzy.
- **Corrección de dato previo a todo lo demás:** hoy `backend/app/pipeline/llm/classify.py` inserta resultados LLM en `verbatim_codes` con `source='engine_fuzzy'` (línea ~181-198), lo cual es incorrecto — no hay forma de distinguir un resultado LLM de uno fuzzy real en el dato histórico. Esto se corrige primero (Task A1) porque toda la lógica de promoción depende de saber el origen real de una clasificación.
- **Umbral de promoción más estricto que el umbral de auto-aceptación.** El umbral actual (`llm_confidence_threshold=0.6`) sigue rigiendo si un resultado se auto-acepta o va a revisión. Para *promocionar* ese resultado a un catálogo reutilizable (alias fuzzy o embedding cacheado) se introduce un umbral nuevo y más alto, configurable por tipo, para minimizar falsos positivos que contaminen el catálogo.
- **Modelo de embeddings:** se recomienda `fastembed` (ONNX puro, sin dependencia de `torch`) sobre `sentence-transformers` completo, por peso de dependencia — a confirmar en Task C1 (ver Open Questions).

## Task List

### Phase A: Fundamento — fuente correcta, thresholds por tipo, concurrencia entre rondas

- [x] **Task A1** (S): Corregir el `source` de resultados LLM en `verbatim_codes`
- [x] **Task A2** (S): Thresholds de confianza separados por tipo (brands/reasons) y umbral de promoción
- [x] **Task A3** (M): Scheduler in-process para procesar múltiples rondas en paralelo

### Checkpoint A
- [x] `pytest backend/tests/ -v` pasa completo (76 pasan; 3 fallos preexistentes no relacionados con Fase A)
- [x] Procesar 1 ronda sola se comporta igual que hoy (sin regresión)
- [x] `verbatim_codes.source` distingue LLM de fuzzy en datos nuevos
- [x] 3 rondas enviadas a la vez respetan el límite `round_parallel_workers` (verificado con test)

### Phase B: Promoción automática — marcas

- [x] **Task B1** (S): Función de promoción de alias fuzzy para marcas + call site en classify.py

### Checkpoint B
- [x] Un verbatim de marca clasificado por LLM sobre el umbral de promoción genera una fila nueva en `code_aliases` con `origin='llm_promoted'`
- [x] Reprocesar el mismo texto no duplica el alias (maneja conflicto de la unique constraint)

### Phase C: Caché semántico local — razones

- [ ] **Task C1** (S): Infra pgvector (imagen docker, extensión, dependencia de embeddings)
- [ ] **Task C2** (M): Esquema + escritura del caché semántico (promoción de razones)
- [ ] **Task C3** (M): Lectura del caché antes de despachar a LLM
- [ ] **Task C4** (S): Arranque en caliente vía `source_round_id`
- [ ] **Task C5** (S): Dataset y script de calibración del umbral de similitud coseno

### Checkpoint C (final)
- [ ] `pytest backend/tests/ -v` pasa completo
- [ ] Flujo E2E de prueba: ronda de marcas con promoción activa + ronda de razones con caché semántico activo, ambas dentro del NFR medido en un entorno de prueba (no garantizado hasta calibrar, ver Open Questions)
- [ ] Ronda homologada (`source_round_id` set) muestra hits de caché desde el primer procesamiento

---

## Task A1: Corregir el `source` de resultados LLM en `verbatim_codes`

**Descripción:** `backend/app/pipeline/llm/classify.py` (línea ~181-198) inserta resultados clasificados por LLM con `source='engine_fuzzy'`, heredado de un copy-paste del path fuzzy. Esto hace indistinguible un resultado LLM de uno fuzzy real, lo cual bloquea toda la lógica de promoción (Tasks B1/C2) que necesita saber si un resultado vino del LLM. Se añade `'llm_classified'` al `check constraint` de `verbatim_codes.source` vía nueva migración, y se corrige el INSERT en `classify.py` para usar ese valor.

**Criterios de aceptación:**
- [ ] Nueva migración `backend/db/migrations/002_llm_source.sql` agrega `'llm_classified'` al check constraint de `verbatim_codes.source` (sin tocar `001_schema_v5.sql`, que es fuente de verdad congelada)
- [ ] El INSERT en `classify.py` usa `source='llm_classified'` en vez de `'engine_fuzzy'`
- [ ] Filas existentes (`source='engine_fuzzy'` de origen LLM) NO se backfillean automáticamente (ver Open Questions — decisión explícita pendiente)

**Verificación:**
- [ ] `pytest backend/tests/ -v` — test existente de `classify_round` actualizado para verificar `source='llm_classified'`
- [ ] Migración corre limpia sobre una DB de dev recreada (`docker compose down -v && docker compose up db`)

**Dependencias:** Ninguna.

**Archivos:**
- `backend/db/migrations/002_llm_source.sql` (crear)
- `backend/app/pipeline/llm/classify.py` (modificar, línea ~181-198)
- `backend/tests/` (test relevante a classify_round, actualizar assert de source)

**Tamaño:** S (2-3 archivos)

---

## Task A2: Thresholds de confianza separados por tipo + umbral de promoción

**Descripción:** Hoy `settings.llm_confidence_threshold=0.6` (`backend/app/core/config.py:21`) es un único valor global usado en `classify.py:161` sin distinguir `coding_type`. Se añaden campos separados para brands/reasons (auto-aceptación) y un tercer campo, más estricto, exclusivo para gatear la promoción a catálogos reutilizables (Tasks B1/C2).

**Criterios de aceptación:**
- [ ] `Settings` gana `llm_confidence_threshold_brands: float`, `llm_confidence_threshold_reasons: float` (default ambos = 0.6 para no romper comportamiento actual; documentar que reasons puede subirse vía env sin tocar código)
- [ ] `Settings` gana `llm_promotion_confidence_threshold: float` (default conservador, ej. 0.9) — usado únicamente por Tasks B1/C2, no por la aceptación estándar
- [ ] `classify.py:161` selecciona el threshold de aceptación según `coding_type` en vez del valor único
- [ ] Comportamiento actual (threshold único 0.6) se preserva exactamente si no se cambian los defaults — regresión cero

**Verificación:**
- [ ] `pytest backend/tests/ -v`
- [ ] Test nuevo: mismo confidence_score, distinto `coding_type`, verifica que el threshold aplicado corresponde al tipo

**Dependencias:** Ninguna (paralelizable con A1).

**Archivos:**
- `backend/app/core/config.py` (modificar)
- `backend/app/pipeline/llm/classify.py` (modificar, línea ~161)
- `backend/tests/` (nuevo test o extensión)

**Tamaño:** S (2 archivos)

---

## Task A3: Scheduler in-process para procesar múltiples rondas en paralelo

**Descripción:** Hoy `process_round` (`backend/app/pipeline/process.py:211`) se dispara vía `background_tasks.add_task` (fire-and-forget, sin límite de concurrencia) desde `routers/studios.py:506`, o de forma síncrona en `routers/studios.py:531`. No hay límite global de rondas concurrentes ni coordinación entre ellas. Se reemplaza el disparo directo por un scheduler in-process: una cola (`queue.Queue`) + N worker threads persistentes arrancados en el lifespan de FastAPI, que consumen `round_id`s y llaman a `process_round`. El límite de workers (`round_parallel_workers`, nuevo setting) protege contra saturar los rate limits desconocidos de DeepSeek — combinado con `llm_parallel_requests` existente, el total de requests concurrentes al LLM queda acotado y configurable.

**Criterios de aceptación:**
- [ ] Nuevo módulo `backend/app/core/scheduler.py`: cola + pool de N workers (`round_parallel_workers`, default conservador = 2), arrancado/detenido en el lifespan de la app FastAPI
- [ ] `routers/studios.py` reemplaza `background_tasks.add_task(_process_round_task, round_id)` (línea 506) por `scheduler.submit(round_id)`
- [ ] El endpoint síncrono `POST /rounds/{round_id}/process` (línea 524-531) se mantiene sin cambios de contrato (puede seguir llamando `process_round` directo, o encolar y esperar — decidir en implementación, no bloquea el resto)
- [ ] Enviar 3 rondas simultáneamente resulta en máximo `round_parallel_workers` corriendo a la vez; el resto queda visible como `processing_runs.status='queued'`
- [ ] Cada ronda mantiene su propia sesión de DB (patrón actual de `_process_round_task` con `SessionLocal()` propio) — sin compartir sesión entre threads

**Verificación:**
- [ ] `pytest backend/tests/ -v` — test nuevo con un `process_round` fake/lento (sleep) verificando concurrencia acotada vía threading
- [ ] Procesar una sola ronda produce el mismo resultado que antes de este cambio (test de regresión)

**Dependencias:** Ninguna (paralelizable con A1/A2), pero debe fusionarse después de A1 si A1 toca el mismo archivo `classify.py` en paralelo (bajo riesgo de conflicto, no de acoplamiento funcional).

**Archivos:**
- `backend/app/core/scheduler.py` (crear)
- `backend/app/core/config.py` (modificar: agregar `round_parallel_workers`)
- `backend/app/routers/studios.py` (modificar, línea ~506)
- `backend/app/main.py` (modificar: lifespan hook para arrancar/parar el scheduler)
- `backend/tests/test_scheduler.py` (crear)

**Tamaño:** M (4-5 archivos)

---

## Task B1: Promoción de alias fuzzy para marcas

**Descripción:** Cuando `classify_round` clasifica un verbatim de `coding_type=='brands'` con confidence ≥ `llm_promotion_confidence_threshold` (Task A2), se inserta una fila nueva en `code_aliases` con `origin='llm_promoted'` (nuevo valor de check constraint) para que futuras rondas lo capturen en la capa fuzzy sin volver a tocar el LLM. `catalog.py` no tiene hoy una función dedicada de "agregar alias" — la más cercana es la lógica inline de `discover_catalog_from_frequency` (línea 96); se añade una función nueva y explícita en vez de reutilizar esa por tener disparadores distintos (frecuencia vs. aprobación LLM).

**Criterios de aceptación:**
- [ ] Nueva migración agrega `'llm_promoted'` al check constraint de `code_aliases.origin`
- [ ] Nueva función `promote_llm_result_to_alias(db, code_id, alias_normalized, alias_sample, match_score) -> None` en `catalog.py`
- [ ] Call site en `classify.py`: solo quando `coding_type=='brands'` y confidence ≥ umbral de promoción
- [ ] Alias duplicado para el mismo `(codebook_id, alias_normalized, code_id)` no falla — incrementa `occurrences` en vez de violar la unique constraint (`ON CONFLICT DO UPDATE` o manejo explícito)

**Verificación:**
- [ ] `pytest backend/tests/ -v` — test: verbatim de marca sobre el umbral genera alias nuevo; repetir el mismo texto no duplica fila, incrementa `occurrences`

**Dependencias:** Task A1 (necesita distinguir origen LLM), Task A2 (necesita el umbral de promoción).

**Archivos:**
- `backend/db/migrations/003_llm_promoted_alias.sql` (crear, o fusionar con 002 si aún no se ha aplicado)
- `backend/app/pipeline/fuzzy/catalog.py` (modificar)
- `backend/app/pipeline/llm/classify.py` (modificar: call site)
- `backend/tests/` (nuevo test)

**Tamaño:** S (3 archivos)

---

## Task C1: Infra pgvector

**Descripción:** Habilitar `pgvector` en el Postgres del proyecto y elegir la librería de embeddings. Cambio de imagen docker de `postgres:16-alpine` a `pgvector/pgvector:pg16` (mismo Postgres 16, extensión pre-instalada). Se agrega la dependencia de embeddings a `requirements.txt` — recomendado `fastembed` (ONNX puro, sin `torch`) para minimizar peso, a confirmar durante implementación (ver Open Questions).

**Criterios de aceptación:**
- [ ] `docker-compose.yml` (y `docker-compose.dev.yml`/`prod.yml` si aplica) usan `pgvector/pgvector:pg16`
- [ ] Nueva migración con `CREATE EXTENSION IF NOT EXISTS vector;`
- [ ] `SELECT * FROM pg_extension WHERE extname='vector';` devuelve una fila tras `docker compose up db`
- [ ] Librería de embeddings agregada a `requirements.txt`, confirmada por un smoke script que genera un vector de la dimensión esperada

**Verificación:**
- [ ] `docker compose up db` limpio, extensión verificada por SQL directo
- [ ] Script mínimo: `embed("texto de prueba")` devuelve vector de dimensión N

**Dependencias:** Ninguna (paralelizable con Phase A/B).

**Archivos:**
- `docker-compose.yml` (modificar)
- `backend/db/migrations/004_pgvector.sql` (crear)
- `backend/requirements.txt` (modificar)

**Tamaño:** S (3 archivos)

---

## Task C2: Esquema + escritura del caché semántico (razones)

**Descripción:** Nueva tabla `reason_embeddings` (columna `embedding vector(N)`, ligada a `code_id`, `codebook_id`, texto normalizado fuente, confidence). Cuando `classify_round` aprueba una razón con confidence ≥ `llm_promotion_confidence_threshold`, se calcula el embedding y se inserta una fila — espejo de la promoción de marcas (Task B1) pero para razones.

**Criterios de aceptación:**
- [ ] Migración crea `reason_embeddings` con índice HNSW o IVFFlat sobre `embedding` (pgvector soporta HNSW nativo)
- [ ] Nuevo módulo `backend/app/pipeline/semantic/embed.py` (función de embedding, envuelve la librería elegida en C1) y `semantic/cache.py` (función de escritura)
- [ ] Call site en `classify.py`: solo cuando `coding_type=='reasons'` y confidence ≥ umbral de promoción
- [ ] Tests usan una función de embedding determinística/mock (no cargan el modelo real) para no depender de red/peso en CI

**Verificación:**
- [ ] `pytest backend/tests/ -v` — test: razón aprobada sobre el umbral genera fila en `reason_embeddings` con la dimensión correcta

**Dependencias:** Task A1, Task A2, Task C1.

**Archivos:**
- `backend/db/migrations/005_reason_embeddings.sql` (crear)
- `backend/app/pipeline/semantic/embed.py` (crear)
- `backend/app/pipeline/semantic/cache.py` (crear)
- `backend/app/pipeline/llm/classify.py` (modificar: call site)
- `backend/tests/` (nuevo test, con mock de embedding)

**Tamaño:** M (5 archivos)

---

## Task C3: Lectura del caché antes de despachar a LLM

**Descripción:** En `process.py`, antes de que los `mention_groups` de razones lleguen a `classify_round`, se calcula el embedding de cada texto único y se busca por similitud coseno en `reason_embeddings` (acotado al mismo `codebook_id`/estudio). Los que superan `semantic_cache_similarity_threshold` (nuevo setting, default inicial 0.90 — sin calibrar, ver Task C5) se auto-clasifican sin tocar el LLM; el resto sigue el flujo actual.

**Criterios de aceptación:**
- [ ] Nueva función en `semantic/cache.py`: `lookup(db, codebook_id, normalized_text) -> match | None`
- [ ] `process.py` filtra `mention_groups` de razones contra el caché antes de armar los batches para `classify_round`; los hits se escriben en `verbatim_codes` con un `source` distinguible (ej. `'semantic_cache'` — requiere agregar este valor al check constraint también)
- [ ] Con una fila sembrada en `reason_embeddings` y un verbatim casi idéntico entrante, el test verifica que `classify_round`/`_classify_batch_with_retry` NO se invoca para ese grupo (spy/mock)

**Verificación:**
- [ ] `pytest backend/tests/ -v`
- [ ] Test de integración: ronda con caché sembrado reduce el conteo de grupos enviados a LLM

**Dependencias:** Task C2.

**Archivos:**
- `backend/db/migrations/006_semantic_cache_source.sql` (crear: agrega `'semantic_cache'` a `verbatim_codes.source`)
- `backend/app/pipeline/semantic/cache.py` (modificar: agregar `lookup`)
- `backend/app/pipeline/process.py` (modificar)
- `backend/app/core/config.py` (modificar: `semantic_cache_similarity_threshold`)
- `backend/tests/` (nuevo test)

**Tamaño:** M (5 archivos)

---

## Task C4: Arranque en caliente vía `source_round_id`

**Descripción:** Cuando una ronda nueva tiene `origin_mode='homologated'` y `source_round_id` set, el lookup del caché semántico (Task C3) debe incluir también las filas de `reason_embeddings` asociadas al `codebook_id` de la ronda origen — así la Ronda 2 aprovecha desde el primer procesamiento lo aprendido en la Ronda 1, sin reprocesar nada.

**Criterios de aceptación:**
- [ ] `lookup()` (Task C3) acepta un `codebook_id` adicional o una lista de codebooks a considerar, resuelta a partir de `source_round_id` cuando existe
- [ ] Ronda homologada con `source_round_id` apuntando a una ronda con `reason_embeddings` pobladas obtiene hits de caché en su primer procesamiento (test con datos sembrados en la ronda origen)

**Verificación:**
- [ ] `pytest backend/tests/ -v` — test de integración con dos rondas (origen + homologada) y verificación de hit cruzado

**Dependencias:** Task C3.

**Archivos:**
- `backend/app/pipeline/semantic/cache.py` (modificar: resolución de codebooks vía `source_round_id`)
- `backend/app/pipeline/process.py` (modificar: pasar el scope correcto al lookup)
- `backend/tests/` (nuevo test)

**Tamaño:** S (2-3 archivos)

---

## Task C5: Dataset y script de calibración del umbral de similitud coseno

**Descripción:** No existe hoy un dataset etiquetado para validar `semantic_cache_similarity_threshold`. Se construye un script (`backend/scripts/calibrate_semantic_threshold.py`) que toma un `round_id` ya procesado y aprobado (usando `verbatim_codes` con `source` en `analyst_manual`/`audit_correction`/`llm_classified` de alta confianza como ground truth), calcula embeddings, barre el umbral (ej. 0.80 a 0.95, paso 0.02) y reporta precisión/recall por umbral — mismo enfoque empírico que se usó para calibrar `SCORE_THRESHOLD=80` en fuzzy.

**Criterios de aceptación:**
- [ ] Script corre contra un `round_id` real y produce una tabla precisión/recall por umbral
- [ ] El default de `semantic_cache_similarity_threshold` en `config.py` se actualiza según el resultado (paso manual, no automatizado — documentar el valor elegido y por qué)

**Verificación:**
- [ ] Ejecutar el script contra al menos una ronda histórica real y revisar la tabla de salida

**Dependencias:** Task C2 (necesita embeddings ya escribiéndose) — puede correr en paralelo a C3/C4 una vez C2 esté lista.

**Archivos:**
- `backend/scripts/calibrate_semantic_threshold.py` (crear)
- `backend/app/core/config.py` (modificar: default del threshold, tras revisar resultados)

**Tamaño:** S (1-2 archivos)

---

## Not Doing (y por qué)

- **Reescritura del servicio en Rust (Fase 3 original).** El cuello de botella medido es la latencia de red a DeepSeek, no el runtime — Rust no reduce ese tiempo para lo que sí necesita LLM. Las capas donde Rust ganaría (fuzzy, embeddings) ya corren en código nativo (RapidFuzz en C++, ONNX runtime nativo). Revisitar solo si, tras medir Fase A+B+C en producción, el overhead de orquestación Python (no la espera de red) resulta ser el cuello de botella dominante.
- **gRPC en vez de HTTP+JSON.** Mismo argumento: el overhead de serialización es irrelevante comparado con 20-25s de espera al LLM.
- **Redis/Celery/RabbitMQ.** Ver Decisiones de Arquitectura — un pool de threads in-process ya cubre el paralelismo entre rondas sin nueva infraestructura operativa.
- **Base de datos vectorial standalone (Milvus/Qdrant).** pgvector sobre el Postgres existente cubre el caso de uso a la escala actual.
- **Backfill automático de `verbatim_codes.source` histórico** mal etiquetado antes de Task A1. Se deja como decisión explícita pendiente (ver Open Questions) en vez de asumir que se quiere tocar data histórica sin confirmación.

## Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| Rate limits reales de DeepSeek desconocidos | Alto (429s bajo concurrencia) | `round_parallel_workers` default conservador (2) y configurable; medir y ajustar con métricas reales antes de subirlo |
| Umbral de similitud coseno (0.90 inicial) sin calibrar | Alto (falsos positivos en razones, más graves que en marcas por ambigüedad semántica) | Task C5 obligatoria antes de confiar en el caché en producción; empezar con umbral conservador y logging de hits para auditoría manual temprana |
| Elección de librería de embeddings no confirmada (`fastembed` vs alternativas) | Medio | Confirmar en Task C1 antes de escribir C2; encapsulado en `semantic/embed.py` para poder cambiar de librería sin tocar el resto del pipeline |
| Promoción automática contamina catálogos con falsos positivos | Alto (degrada calidad futura, difícil de detectar) | Umbral de promoción separado y más estricto que el de auto-aceptación (Task A2); `origin='llm_promoted'`/fila de `reason_embeddings` queda auditable y reversible (se puede borrar por origen) |
| Migraciones nuevas (002-006) se acumulan sin proceso de migración formal (no hay Alembic) | Medio | Seguir el patrón ya usado en el proyecto (`001_schema_v5.sql` como base, archivos numerados incrementales aplicados por `docker-entrypoint-initdb.d` en dev) — confirmar que este patrón siga sirviendo o si hace falta herramienta de migración antes de que crezca más |

## Open Questions

- ¿Se quiere backfillear `verbatim_codes.source` histórico (hoy mal etiquetado como `'engine_fuzzy'` para resultados LLM) o se deja como está y el fix solo aplica hacia adelante?
- Confirmar librería de embeddings final (`fastembed` recomendado) — depende de si el equipo prefiere evitar cualquier dependencia ML nueva vs. aceptar una ligera (ONNX-only, sin `torch`).
- Valor inicial seguro de `round_parallel_workers` × `llm_parallel_requests` combinado — sin rate limits conocidos de DeepSeek, se parte conservador (2 rondas × 5 requests = máx 10 concurrentes) y se ajusta con métricas reales tras el primer despliegue.
- ¿El endpoint síncrono `POST /rounds/{round_id}/process` debe seguir siendo bloqueante, o pasa a encolar y devolver estado `queued` de inmediato una vez existe el scheduler (Task A3)? Afecta el contrato de API consumido por el frontend.
