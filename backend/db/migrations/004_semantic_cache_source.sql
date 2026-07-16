-- Distingue un hit del caché semántico (Task C3) de una clasificación LLM
-- real en verbatim_codes.source — el LLM nunca se llamó para esta fila.
alter table verbatim_codes drop constraint if exists verbatim_codes_source_check;

alter table verbatim_codes add constraint verbatim_codes_source_check
  check (source in ('engine_exact','engine_fuzzy','llm_classified','semantic_cache','homologation','analyst_manual','audit_correction'));
