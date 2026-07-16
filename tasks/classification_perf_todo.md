# Concurrencia entre rondas + Caché semántico — Backlog (detalle en tasks/classification_perf_plan.md)

Alcance: Fase 1 (V4+V7 ajustadas) + Fase 2 (V1+V2+V3) del ideation. Fase 3 (Rust/gRPC) explícitamente en Not Doing.

## Phase A — Fundamento

- [x] **A1** Corregir `source` de resultados LLM en `verbatim_codes` (migración + `classify.py`) — S
- [x] **A2** Thresholds de confianza por tipo (brands/reasons) + umbral de promoción separado (`config.py`, `classify.py`) — S
- [x] **A3** Scheduler in-process para paralelismo entre rondas, sin broker nuevo (`core/scheduler.py`, `studios.py`, `main.py`) — M

### Checkpoint A
- [x] `pytest backend/tests/ -v` en verde (76 pasan; 3 fallos preexistentes no relacionados)
- [x] Una sola ronda se comporta igual que antes (sin regresión)
- [x] 3 rondas concurrentes respetan `round_parallel_workers`

## Phase B — Promoción automática (marcas)

- [x] **B1** Alias fuzzy auto-promovido desde LLM aprobado (`fuzzy/catalog.py`, `llm/classify.py`, migración) — S

### Checkpoint B
- [x] Marca LLM-aprobada sobre umbral genera alias nuevo (`origin='llm_promoted'`), sin duplicados

## Phase C — Caché semántico local (razones)

- [x] **C1** Infra pgvector: imagen docker + extensión + dependencia de embeddings — S (fastembed, 384-dim, confirmado)
- [x] **C2** Esquema `reason_embeddings` + escritura al aprobar razón LLM — M
- [x] **C3** Lookup de caché antes de despachar razones a LLM — M
- [x] **C4** Arranque en caliente vía `source_round_id` entre rondas del mismo estudio — S
- [x] **C5** Script de calibración del umbral de similitud coseno (dataset no existe, se construye) — S

### Checkpoint C (final)
- [x] `pytest backend/tests/ -v` en verde (91 pasan; 3 fallos preexistentes no relacionados)
- [x] E2E: ronda de razones con caché semántico, funcionando — verificado con datos sembrados (sin ronda histórica real disponible): ronda 1 (from_scratch) clasifica por LLM y escribe en `reason_embeddings`; script desechable, no comiteado, limpiado después
- [x] Ronda homologada obtiene hits de caché desde el primer procesamiento — verificado: ronda 2 (`origin_mode='homologated'`, `source_round_id`=ronda 1) resuelve el grupo vía caché semántico de la ronda origen SIN llamar a `classify_batch` (0 llamadas), remapea correctamente al code_id propio vía `inherited_from_code_id`, `verbatim_codes.source='semantic_cache'`

## Not Doing

- Reescritura en Rust — cuello de botella medido es red a DeepSeek, no runtime; revisitar solo si Fase A+B+C no lo resuelve y el overhead de orquestación Python se vuelve dominante
- gRPC — overhead de serialización irrelevante frente a 20-25s de espera LLM
- Redis/Celery/RabbitMQ — pool in-process cubre el caso sin infraestructura nueva
- Vector DB standalone (Milvus/Qdrant) — pgvector sobre Postgres existente alcanza

## Open Questions (bloquean decisiones de detalle, no el arranque de Phase A)

- ¿Backfill de `source` histórico mal etiquetado, o solo corrige hacia adelante?
- Confirmar `fastembed` vs alternativa como librería de embeddings (Task C1)
- Valor inicial seguro de concurrencia combinada (`round_parallel_workers` × `llm_parallel_requests`) sin rate limits conocidos de DeepSeek
- ¿`POST /rounds/{round_id}/process` sigue bloqueante o pasa a encolar tras Task A3?
