-- Distingue resultados clasificados por LLM de fuzzy real en verbatim_codes.source.
-- classify.py insertaba LLM results con 'engine_fuzzy' (copy-paste del path fuzzy),
-- lo cual hacía indistinguible el origen real de una clasificación.
alter table verbatim_codes drop constraint if exists verbatim_codes_source_check;

alter table verbatim_codes add constraint verbatim_codes_source_check
  check (source in ('engine_exact','engine_fuzzy','llm_classified','homologation','analyst_manual','audit_correction'));
