-- =====================================================================
-- VERBATIX — MIGRACIÓN 002: CASCADE DELETE FIX
-- =====================================================================
-- Las FKs processing_run_id en verbatim_codes y created_by_run_id en
-- mention_groups no tenían ON DELETE, causando IntegrityError al borrar
-- un estudio (Postgres procesa los CASCADE de processing_runs antes que
-- los de verbatims, dejando filas huérfanas que referencian el run).
--
-- Solución: SET NULL — al borrar el processing_run, las filas hijas
-- pierden la referencia pero no se pierden (el verbatim_code sigue
-- siendo válido sin el run de origen).
-- =====================================================================

alter table verbatim_codes
  drop constraint if exists verbatim_codes_processing_run_id_fkey,
  add constraint verbatim_codes_processing_run_id_fkey
  foreign key (processing_run_id) references processing_runs(id)
  on delete set null;

alter table mention_groups
  drop constraint if exists mention_groups_created_by_run_id_fkey,
  add constraint mention_groups_created_by_run_id_fkey
  foreign key (created_by_run_id) references processing_runs(id)
  on delete set null;
