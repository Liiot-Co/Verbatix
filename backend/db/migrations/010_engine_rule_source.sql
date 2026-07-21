-- El bucket residual (95 confuso / 97 otras) escribe verbatim_codes con
-- source='engine_rule'. Ese valor no estaba en el check de 009, así que
-- process_round reventaba con CheckViolation al cerrar la cobertura.

alter table verbatim_codes drop constraint if exists verbatim_codes_source_check;
alter table verbatim_codes add constraint verbatim_codes_source_check
  check (source in (
    'engine_exact','engine_fuzzy','engine_rule','llm_classified','llm_suggestion',
    'semantic_cache','rule_brand_in_reason','homologation','analyst_manual',
    'audit_correction'
  ));
