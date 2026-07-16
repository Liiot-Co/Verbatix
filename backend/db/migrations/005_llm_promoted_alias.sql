-- Permite el origen 'llm_promoted' en code_aliases (alias promovido desde un
-- resultado LLM aprobado). El esquema v5 ya lo incluye; este ALTER actualiza
-- las BDs ya creadas cuyo CHECK quedó con la lista anterior.
alter table code_aliases drop constraint if exists code_aliases_origin_check;

alter table code_aliases add constraint code_aliases_origin_check
  check (origin in ('inherited','engine_fuzzy','analyst_manual','imported_xlsx','llm_promoted'));
