-- Caché semántico local de razones: cuando classify_round aprueba una razón
-- sobre el umbral de promoción, se cachea su embedding aquí para que futuros
-- verbatims casi idénticos no vuelvan a tocar el LLM (lookup en Task C3).
-- No se usa fuzzy para razones (falsos positivos tipo "frescura"~"firme"),
-- ver fuzzy/matcher.py.
create table reason_embeddings (
  id           uuid primary key default gen_random_uuid(),
  codebook_id  uuid not null references codebooks(id) on delete cascade,
  code_id      uuid not null references codes(id) on delete cascade,
  source_text  text not null,
  embedding    vector(384) not null,
  confidence   numeric(4,3),
  created_at   timestamptz not null default now()
);
create index on reason_embeddings (codebook_id);
create index reason_embeddings_hnsw_idx on reason_embeddings
  using hnsw (embedding vector_cosine_ops);
