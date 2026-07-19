-- =====================================================================
-- VERBATIX — REQ-07: procedencia e invariantes del catálogo
-- =====================================================================
-- Migración aditiva. No modifica números existentes ni recrea tablas.

-- Los códigos entregados por el cliente necesitan una procedencia propia.
alter table codes drop constraint if exists codes_origin_check;
alter table codes add constraint codes_origin_check
  check (origin in ('inherited', 'engine_auto', 'analyst_manual', 'imported_client'));

-- Un código de sistema desplazado nace directamente en 995..999. Nunca se
-- mueve desde 95..99 después de persistirse.
do $$ begin
  if not exists (
    select 1 from pg_constraint
     where conname = 'codes_overflow_base_system_type_check'
  ) then
    alter table codes add constraint codes_overflow_base_system_type_check
      check (
        overflow_base_system_type is null
        or overflow_base_system_type in
          ('anomaly', 'no_answer', 'other_mentions', 'none', 'no_recall')
      );
  end if;
end $$;

do $$ begin
  if not exists (
    select 1 from pg_constraint
     where conname = 'codes_system_overflow_consistency_check'
  ) then
    alter table codes add constraint codes_system_overflow_consistency_check
      check (
        (
          is_system_overflow
          and is_system
          and code_number between 995 and 999
          and overflow_base_system_type is not null
          and system_type = overflow_base_system_type
        )
        or (
          not is_system_overflow
          and overflow_base_system_type is null
        )
      );
  end if;
end $$;

create unique index if not exists codes_codebook_active_system_type_uidx
  on codes (codebook_id, system_type)
  where is_system and system_type is not null and is_active;

create index if not exists codes_inherited_from_code_idx
  on codes (inherited_from_code_id)
  where inherited_from_code_id is not null;

create index if not exists codebooks_parent_codebook_idx
  on codebooks (parent_codebook_id)
  where parent_codebook_id is not null;

-- Garantía fuerte de REQ-07: un code_number persistido es inmutable.
create or replace function prevent_code_number_reassignment()
returns trigger
language plpgsql
as $$
begin
  if new.code_number is distinct from old.code_number then
    raise exception 'code_number is immutable for code %', old.id
      using errcode = '23514';
  end if;
  return new;
end;
$$;

drop trigger if exists codes_code_number_immutable on codes;
create trigger codes_code_number_immutable
before update of code_number on codes
for each row execute function prevent_code_number_reassignment();
