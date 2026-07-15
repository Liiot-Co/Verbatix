-- Permite marcar un alias fuzzy como promovido automáticamente desde un
-- resultado LLM aprobado (confidence >= llm_promotion_confidence_threshold),
-- distinto de 'engine_fuzzy' (semilla por frecuencia) y 'analyst_manual'.
alter table code_aliases drop constraint if exists code_aliases_origin_check;

alter table code_aliases add constraint code_aliases_origin_check
  check (origin in ('inherited','engine_fuzzy','analyst_manual','imported_xlsx','llm_promoted'));
