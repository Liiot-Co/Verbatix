-- =====================================================================
-- Fidelidad de ingestión: snapshot por carga + identidad de menciones
-- =====================================================================
-- No se crea una tabla paralela: imported_files ya es el dueño natural de un
-- único snapshot de población por carga. El snapshot puede evolucionar mientras
-- está bloqueado; una vez ready, un trigger lo vuelve inmutable.

alter table imported_files
  add column if not exists dataset_snapshot jsonb;

alter table verbatims
  add column if not exists source_row_number int,
  add column if not exists mention_position int not null default 1;

do $$ begin
  if not exists (
    select 1 from pg_constraint where conname = 'verbatims_source_row_number_check'
  ) then
    alter table verbatims add constraint verbatims_source_row_number_check
      check (source_row_number is null or source_row_number > 0);
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'verbatims_mention_position_check'
  ) then
    alter table verbatims add constraint verbatims_mention_position_check
      check (mention_position > 0);
  end if;
end $$;

-- La identidad previa colapsaba dos respuestas legítimas con el mismo
-- respondent/question. La posición es determinista por orden de fuente y hace
-- idempotente un retry sin perder menciones repetidas.
alter table verbatims
  drop constraint if exists verbatims_subproject_id_respondent_id_source_question_key_key;

do $$ begin
  if not exists (
    select 1 from pg_constraint
     where conname = 'verbatims_source_mention_identity_key'
  ) then
    alter table verbatims add constraint verbatims_source_mention_identity_key
      unique (subproject_id, respondent_id, source_question_key, mention_position);
  end if;
end $$;

-- Backfill sólo con hechos presentes en BD. No afirma que la población legacy
-- haya sido reconciliada contra un perfil externo; lo declara explícitamente.
update imported_files f
   set dataset_snapshot = jsonb_build_object(
     'version', 'ingestion-snapshot-v1',
     'status', 'ready',
     'legacy_backfill', true,
     'population_reconciliation', 'legacy_not_verified',
     'source', jsonb_build_object(
       'checksum', f.checksum,
       'reported_rows', f.total_rows,
       'file_type', f.file_type
     ),
     'persisted', jsonb_build_object(
       'respondents', (select count(*) from respondents r where r.imported_file_id = f.id),
       'verbatims', (select count(*) from verbatims v where v.imported_file_id = f.id)
     )
   )
 where f.dataset_snapshot is null
   and f.status = 'validated'
   and f.file_type in ('verbatims_xlsx', 'combined_xlsx', 'dau');

create or replace function prevent_ready_dataset_snapshot_update()
returns trigger
language plpgsql
as $$
begin
  if old.dataset_snapshot is not null
     and old.dataset_snapshot ->> 'status' = 'ready'
     and new.dataset_snapshot is distinct from old.dataset_snapshot then
    raise exception 'dataset_snapshot ready es inmutable para imported_file %', old.id;
  end if;
  return new;
end;
$$;

drop trigger if exists imported_files_ready_snapshot_immutable on imported_files;
create trigger imported_files_ready_snapshot_immutable
before update of dataset_snapshot on imported_files
for each row execute function prevent_ready_dataset_snapshot_update();
