-- =====================================================================
-- REQ-05: perfil por coding_type (marcas / razones) o combinado
-- =====================================================================
-- coding_type NULL  = Excel único (comportamiento histórico / unión)
-- coding_type brands|reasons = perfil acotado a ese subproyecto
-- Historial: se conservan filas previas; el cruce usa el más reciente
-- por (round_id, coding_type) o el combinado más reciente.

alter table profile_files
  add column if not exists coding_type text;

do $$ begin
  if not exists (
    select 1 from pg_constraint where conname = 'profile_files_coding_type_check'
  ) then
    alter table profile_files
      add constraint profile_files_coding_type_check
      check (coding_type is null or coding_type in ('brands', 'reasons'));
  end if;
end $$;

create index if not exists profile_files_round_coding_idx
  on profile_files (round_id, coding_type, created_at desc);
