-- =====================================================================
-- VERBATIX — ESQUEMA v5
-- =====================================================================
-- Notas de diseño:
--  * Los estados van como TEXT + CHECK, no como ENUM: en 3 días vas a
--    cambiar de opinión sobre los estados, y alterar un ENUM en Postgres
--    duele. Un CHECK se cambia con un ALTER de una línea.
--  * RLS queda ACTIVO y SIN POLÍTICAS en todas las tablas. Es deliberado:
--    nadie puede leer nada desde el navegador. Solo el backend entra,
--    con la secret key.
-- =====================================================================

create extension if not exists "pgcrypto";
create extension if not exists "pg_trgm";   -- match difuso de marcas (alpna -> Alpina)

-- =====================================================================
-- 0. PERFILES  (se apoya en auth.users de Supabase, no la reemplaza)
-- =====================================================================
create table profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  email       text not null,
  name        text,
  role        text not null default 'analyst' check (role in ('admin','analyst')),
  is_active   boolean not null default true,
  created_at  timestamptz not null default now()
);

-- Cada usuario que se cree en Auth obtiene su perfil automáticamente
create or replace function handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into profiles (id, email, name)
  values (new.id, new.email, coalesce(new.raw_user_meta_data->>'name', new.email))
  on conflict (id) do nothing;
  return new;
end; $$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();

-- 000_local_auth_stub.sql seeds the fixed local dev user into auth.users
-- *before* this trigger exists, so it never fires for that row. Seed the
-- matching profile here instead; no-op against real Supabase (that id
-- never exists in its auth.users).
insert into profiles (id, email, name)
select id, 'dev@local.test', 'Dev User'
from auth.users
where id = '00000000-0000-0000-0000-000000000001'
on conflict (id) do nothing;

-- =====================================================================
-- 1. ESTRUCTURA:  Proyecto -> Estudio -> Ronda
-- =====================================================================
-- El Estudio (Marcas / Razones) es la entidad persistente dentro de un
-- proyecto: define el coding_type y la pregunta de encuesta, y se mantiene
-- igual a través de las rondas. Cada Ronda es una ola de datos independiente
-- (su propio Excel, verbatims, codebook) y por eso cuelga del Estudio, no
-- del Proyecto — dos estudios del mismo proyecto pueden tener "Ronda 1"
-- cada uno sin chocar entre sí.
create table projects (
  id             uuid primary key default gen_random_uuid(),
  external_code  text unique,
  name           text not null,
  created_by     uuid references profiles(id),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create table studio (
  id                uuid primary key default gen_random_uuid(),
  project_id        uuid not null references projects(id) on delete cascade,
  name              text not null,                       -- 'Marcas' | 'Razones'
  coding_type       text not null check (coding_type in ('brands','reasons')),
  survey_question   text,                                -- el contexto del estudio (fijo entre rondas)
  created_by        uuid references profiles(id),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (project_id, name)
);
create index on studio (project_id);

create table rounds (
  id                      uuid primary key default gen_random_uuid(),
  studio_id               uuid not null references studio(id) on delete cascade,
  name                    text not null,
  round_number            int  not null,
  status                  text not null default 'created'
                          check (status in ('created','files_uploaded','processing',
                                            'preliminary_ready','manual_coding','audit_pending',
                                            'audit_approved','nets_review','ready_to_export',
                                            'completed','failed')),
  min_mentions_threshold  int  not null default 3,
  audit_percentage        numeric(5,2) not null default 10,
  origin_mode             text not null default 'from_scratch'
                          check (origin_mode in ('from_scratch','homologated')),
  source_round_id         uuid references rounds(id),     -- de qué ronda hereda (homologación)
  created_by              uuid references profiles(id),
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now(),
  unique (studio_id, round_number)
);
create index on rounds (studio_id);

-- =====================================================================
-- 2. ARCHIVOS
-- =====================================================================
create table imported_files (
  id                uuid primary key default gen_random_uuid(),
  round_id          uuid not null references rounds(id) on delete cascade,
  file_type         text not null check (file_type in ('verbatims_xlsx','codebook_xlsx','combined_xlsx')),
  sheet_name        text,
  original_filename text not null,
  storage_path      text,               -- ruta en Supabase Storage (bucket privado)
  checksum          text,               -- sha256: evita importar dos veces lo mismo
  total_rows        int,
  status            text not null default 'uploaded'
                    check (status in ('uploaded','validating','validated','failed')),
  error_log         jsonb,
  uploaded_by       uuid references profiles(id),
  created_at        timestamptz not null default now()
);
create index on imported_files (round_id);

-- =====================================================================
-- 3. LIBRO DE CÓDIGOS
-- =====================================================================
create table codebooks (
  id                     uuid primary key default gen_random_uuid(),
  round_id               uuid not null references rounds(id) on delete cascade,
  version                int  not null default 1,
  parent_codebook_id     uuid references codebooks(id),   -- NULL = creado desde CERO
  imported_from_file_id  uuid references imported_files(id),
  status                 text not null default 'draft'
                         check (status in ('draft','in_review','approved','exported')),
  approved_by            uuid references profiles(id),
  approved_at            timestamptz,
  created_at             timestamptz not null default now(),
  unique (round_id, version)
);

create table codes (
  id                     uuid primary key default gen_random_uuid(),
  codebook_id            uuid not null references codebooks(id) on delete cascade,
  code_number            int  not null,
  label                  text not null,
  origin                 text not null default 'analyst_manual'
                         check (origin in ('inherited','engine_auto','analyst_manual')),
  is_system              boolean not null default false,
  system_type            text check (system_type in ('anomaly','no_answer','other_mentions','none','no_recall')),
  inherited_from_code_id uuid references codes(id),   -- el mismo código a través de rondas
  is_active              boolean not null default true,
  created_by             uuid references profiles(id),
  created_at             timestamptz not null default now(),
  unique (codebook_id, code_number)
);
create index on codes (codebook_id) where is_active;

create table code_aliases (
  id               uuid primary key default gen_random_uuid(),
  codebook_id      uuid not null references codebooks(id) on delete cascade,
  code_id          uuid not null references codes(id) on delete cascade,
  alias_normalized text not null,
  alias_sample     text,
  occurrences      int  default 1,
  origin           text not null default 'analyst_manual'
                   check (origin in ('inherited','engine_fuzzy','analyst_manual','imported_xlsx')),
  match_score      numeric(4,3),
  approved_by      uuid references profiles(id),
  created_at       timestamptz not null default now(),
  unique (codebook_id, alias_normalized, code_id)
);
create index on code_aliases (codebook_id, alias_normalized);
create index code_aliases_trgm_idx on code_aliases using gin (alias_normalized gin_trgm_ops);

create table nets (
  id            uuid primary key default gen_random_uuid(),
  codebook_id   uuid not null references codebooks(id) on delete cascade,
  name          text not null,
  origin        text not null default 'analyst_manual'
                check (origin in ('engine_auto','analyst_manual')),
  display_order int not null default 0,
  created_by    uuid references profiles(id),
  created_at    timestamptz not null default now()
);

create table net_codes (
  id            uuid primary key default gen_random_uuid(),
  net_id        uuid not null references nets(id) on delete cascade,
  code_id       uuid not null references codes(id) on delete cascade,
  display_order int not null default 0,
  unique (net_id, code_id)
);

-- =====================================================================
-- 4. MOTOR (histórico de corridas)
-- =====================================================================
create table processing_runs (
  id                     uuid primary key default gen_random_uuid(),
  round_id               uuid not null references rounds(id) on delete cascade,
  run_type               text not null check (run_type in ('initial','homologation','reprocess')),
  algorithm              text,
  min_mentions_threshold int,
  audit_percentage       numeric(5,2),
  random_seed            int,
  status                 text not null default 'queued'
                         check (status in ('queued','running','completed','failed')),
  total_verbatims        int default 0,
  auto_coded_count       int default 0,
  manual_coded_count     int default 0,
  new_codes_count        int default 0,
  anomalies_count        int default 0,
  metrics                jsonb,
  error_message          text,
  started_at             timestamptz,
  finished_at            timestamptz,
  executed_by            uuid references profiles(id),
  created_at             timestamptz not null default now()
);
create index on processing_runs (round_id, created_at desc);

-- =====================================================================
-- 5. DATOS
-- =====================================================================
create table mention_groups (
  id                uuid primary key default gen_random_uuid(),
  round_id          uuid not null references rounds(id) on delete cascade,
  normalized_text   text not null,
  sample_text       text,
  frequency_count   int  not null default 0,
  status            text not null default 'pending_review'
                    check (status in ('auto_coded','below_threshold','anomaly','pending_review','resolved')),
  suggested_code_id uuid references codes(id),
  created_by_run_id uuid references processing_runs(id) on delete set null,
  resolved_by       uuid references profiles(id),
  resolved_at       timestamptz,
  created_at        timestamptz not null default now(),
  unique (round_id, normalized_text)
);
create index on mention_groups (round_id, status);

create table verbatims (
  id                     uuid primary key default gen_random_uuid(),
  round_id               uuid not null references rounds(id) on delete cascade,
  mention_group_id       uuid references mention_groups(id),
  imported_file_id       uuid references imported_files(id),
  respondent_external_id text not null,
  question_key           text,
  original_text          text not null,
  normalized_text        text,
  input_code_number      int,
  coding_status          text not null default 'pending'
                         check (coding_status in ('pending','auto_coded','needs_review','manually_coded','unknown')),
  created_at             timestamptz not null default now(),
  unique (round_id, respondent_external_id, question_key)
);
create index on verbatims (round_id, coding_status);
create index on verbatims (mention_group_id);

create table verbatim_codes (
  id                 uuid primary key default gen_random_uuid(),
  verbatim_id        uuid not null references verbatims(id) on delete cascade,
  code_id            uuid not null references codes(id) on delete cascade,
  output_index       int  not null default 1,
  source             text not null
                     check (source in ('engine_exact','engine_fuzzy','homologation','analyst_manual','audit_correction')),
  confidence_score   numeric(4,3),
  matched_alias      text,  -- alias del catálogo que matcheó (transparencia: por qué el fuzzy asignó este código)
  processing_run_id  uuid references processing_runs(id) on delete set null,
  assigned_by        uuid references profiles(id),
  is_active          boolean not null default true,
  created_at         timestamptz not null default now(),
  unique (verbatim_id, code_id)
);
create index on verbatim_codes (code_id) where is_active;
create index on verbatim_codes (verbatim_id) where is_active;

-- =====================================================================
-- 6. AUDITORÍA
-- =====================================================================
create table audit_sessions (
  id                 uuid primary key default gen_random_uuid(),
  round_id           uuid not null references rounds(id) on delete cascade,
  processing_run_id  uuid references processing_runs(id) on delete set null,
  target_percentage  numeric(5,2) not null,
  total_items        int not null default 0,
  reviewed_items     int not null default 0,
  target_met         boolean not null default false,
  status             text not null default 'pending'
                     check (status in ('pending','in_progress','approved')),
  approved_by        uuid references profiles(id),
  approved_at        timestamptz,
  created_at         timestamptz not null default now()
);

create table audit_code_reviews (
  id                uuid primary key default gen_random_uuid(),
  audit_session_id  uuid not null references audit_sessions(id) on delete cascade,
  code_id           uuid not null references codes(id) on delete cascade,
  items_count       int not null default 0,
  corrections_count int not null default 0,
  status            text not null default 'pending'
                    check (status in ('pending','approved','with_corrections')),
  reviewer_id       uuid references profiles(id),
  reviewed_at       timestamptz,
  unique (audit_session_id, code_id)
);

create table audit_items (
  id                    uuid primary key default gen_random_uuid(),
  audit_code_review_id  uuid not null references audit_code_reviews(id) on delete cascade,
  verbatim_id           uuid not null references verbatims(id) on delete cascade,
  codes_snapshot        jsonb,
  status                text not null default 'pending'
                        check (status in ('pending','correct','reassigned')),
  reviewer_id           uuid references profiles(id),
  reviewed_at           timestamptz,
  comment               text,
  unique (audit_code_review_id, verbatim_id)
);

create table audit_logs (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid references profiles(id),
  round_id      uuid references rounds(id) on delete cascade,
  entity_name   text not null,
  entity_id     uuid,
  action        text not null,
  old_value     jsonb,
  new_value     jsonb,
  created_at    timestamptz not null default now()
);
create index on audit_logs (round_id, created_at desc);
create index on audit_logs (entity_name, entity_id);

-- =====================================================================
-- 7. EXPORTACIÓN
-- =====================================================================
create table export_jobs (
  id               uuid primary key default gen_random_uuid(),
  round_id         uuid not null references rounds(id) on delete cascade,
  include_nets     boolean not null default false,
  status           text not null default 'queued'
                   check (status in ('queued','running','completed','failed')),
  zip_storage_path text,
  error_message    text,
  requested_by     uuid references profiles(id),
  created_at       timestamptz not null default now(),
  finished_at      timestamptz
);

create table export_files (
  id             uuid primary key default gen_random_uuid(),
  export_job_id  uuid not null references export_jobs(id) on delete cascade,
  round_id       uuid references rounds(id),
  file_type      text not null
                 check (file_type in ('codebook_xlsx','codebook_nets_xlsx','coded_verbatims_xlsx','mdd_1','mdd_2')),
  storage_path   text not null,
  size_bytes     bigint,
  created_at     timestamptz not null default now()
);

-- =====================================================================
-- 8. FRECUENCIAS
-- =====================================================================
create table code_stats (
  id             uuid primary key default gen_random_uuid(),
  codebook_id    uuid not null references codebooks(id) on delete cascade,
  code_id        uuid not null references codes(id) on delete cascade,
  mentions_count int not null default 0,
  base_mentions  int not null default 0,
  percentage     numeric(6,3),
  computed_at    timestamptz not null default now(),
  unique (codebook_id, code_id)
);

-- =====================================================================
-- 9. SEGURIDAD:  RLS ACTIVO Y SIN POLÍTICAS
-- =====================================================================
do $$
declare t text;
begin
  foreach t in array array[
    'profiles','projects','rounds','studio','imported_files',
    'codebooks','codes','code_aliases','nets','net_codes',
    'processing_runs','mention_groups','verbatims','verbatim_codes',
    'audit_sessions','audit_code_reviews','audit_items','audit_logs',
    'export_jobs','export_files','code_stats'
  ] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
  end loop;
end $$;

-- =====================================================================
-- 10. updated_at automático
-- =====================================================================
create or replace function touch_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end; $$;

create trigger t_projects before update on projects for each row execute function touch_updated_at();
create trigger t_studio  before update on studio  for each row execute function touch_updated_at();
create trigger t_rounds  before update on rounds  for each row execute function touch_updated_at();
