-- Habilita pgvector (imagen pgvector/pgvector:pg16) para el caché semántico
-- de razones (reason_embeddings, Task C2) — sin base vectorial standalone.
create extension if not exists vector;
