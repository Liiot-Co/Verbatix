-- =====================================================================
-- VERBATIX — ESQUEMA v8
-- =====================================================================
-- Jerarquía: proyectos -> projects (Estudio) -> [categories] -> rounds
--            -> subprojects (Marcas/Razones, por ronda)
-- Reemplaza v5 (proyecto -> studio -> rounds): sin datos reales que
-- preservar en entorno dev, se recrea el esquema completo en un solo
-- archivo en vez de encadenar migraciones incrementales.
--
-- Notas de diseño:
--  * Los estados van como TEXT + CHECK, no como ENUM: en 3 días vas a
--    cambiar de opinión sobre los estados, y alterar un ENUM en Postgres
--    duele. Un CHECK se cambia con un ALTER de una línea.
--  * RLS queda ACTIVO y SIN POLÍTICAS en todas las tablas. Es deliberado:
--    nadie puede leer nada desde el navegador. Solo el backend entra,
--    con la secret key.
--  * Alcance de esta migración: solo esquema (models.py + SQL).
--    `repositories.py`, el pipeline (DAU/Excel/fuzzy/LLM) y el frontend
--    quedan rotos hasta el siguiente requerimiento — prerrequisito, no
--    entrega funcional.
-- =====================================================================

-- Si v5 se aplicó vía initdb (primer arranque del volumen), dropeamos
-- tablas v8 para que el CREATE TABLE de abajo las cree con el esquema
-- correcto. Solo toca tablas de este archivo — las migraciones posteriores
-- (002+, que alteran estas tablas) se re-aplicarán solas.
drop table if exists
  code_stats, export_files, export_jobs, audit_logs, audit_items,
  audit_code_reviews, audit_sessions, verbatim_codes, verbatims,
  mention_groups, processing_runs, reason_embeddings, net_codes, nets,
  code_aliases, codes, codebooks, imported_files, assignments,
  respondents, subprojects, rounds, question_aliases, questions,
  categories, projects, proyectos, user_roles, users
cascade;

create extension if not exists "pgcrypto";
create extension if not exists "pg_trgm";   -- match difuso de marcas (alpna -> Alpina)
create extension if not exists vector;      -- caché semántico de razones (reason_embeddings)

-- =====================================================================
-- 0. USUARIOS (se apoya en auth.users de Supabase, no la reemplaza)
-- =====================================================================
create table if not exists users (
  id          uuid primary key references auth.users(id) on delete cascade,
  email       text not null,
  name        text,
  is_active   boolean not null default true,
  created_at  timestamptz not null default now()
);

create table if not exists user_roles (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references users(id) on delete cascade,
  role_code  text not null check (role_code in ('admin','codificador','supervisor')),
  unique (user_id, role_code)
);

-- Cada usuario que se cree en Auth obtiene su registro + rol por defecto
create or replace function handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into users (id, email, name)
  values (new.id, new.email, coalesce(new.raw_user_meta_data->>'name', new.email))
  on conflict (id) do nothing;
  insert into user_roles (user_id, role_code)
  values (new.id, 'codificador')
  on conflict (user_id, role_code) do nothing;
  return new;
end; $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();

-- 000_local_auth_stub.sql seeds the fixed local dev user into auth.users
-- *before* this trigger exists, so it never fires for that row. Seed the
-- matching user + rol here instead; no-op against real Supabase (that id
-- never exists in its auth.users).
insert into users (id, email, name)
select id, 'dev@local.test', 'Dev User'
from auth.users
where id = '00000000-0000-0000-0000-000000000001'
on conflict (id) do nothing;

insert into user_roles (user_id, role_code)
select '00000000-0000-0000-0000-000000000001', 'admin'
where exists (select 1 from users where id = '00000000-0000-0000-0000-000000000001')
on conflict (user_id, role_code) do nothing;

-- =====================================================================
-- 1. ESTRUCTURA:  Proyecto -> Estudio -> [Categoría] -> Ronda -> Subproyecto
-- =====================================================================
-- proyectos: nivel superior que agrupa uno o varios Estudios.
create table if not exists proyectos (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  created_by  uuid references users(id),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

-- El Estudio (projects, = "Marcas"/"Razones" a nivel de estudio) define el
-- catálogo de preguntas y el codebook compartido entre rondas.
create table if not exists projects (
  id             uuid primary key default gen_random_uuid(),
  proyecto_id    uuid references proyectos(id),
  external_code  text unique,
  name           text not null,
  created_by     uuid references users(id),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create table if not exists categories (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid not null references projects(id) on delete cascade,
  name        text not null,
  created_at  timestamptz not null default now()
);
create index on categories (project_id);

-- Catálogo de variables por estudio, con alias para variables renombradas
-- entre plataformas/rondas.
create table if not exists questions (
  id                        uuid primary key default gen_random_uuid(),
  project_id                uuid not null references projects(id) on delete cascade,
  coding_type               text not null check (coding_type in ('brands','reasons')),
  question_key              text not null,
  single_code_per_response  boolean not null default false,
  expected_max_mentions     int,
  created_at                timestamptz not null default now(),
  unique (project_id, question_key)
);
create index on questions (project_id);

create table if not exists question_aliases (
  id                     uuid primary key default gen_random_uuid(),
  canonical_question_id  uuid not null references questions(id) on delete cascade,
  alias_key              text not null,
  created_at             timestamptz not null default now(),
  unique (canonical_question_id, alias_key)
);

-- Cada Ronda es una ola de datos independiente (su propio Excel, verbatims,
-- codebook heredado del Estudio) y cuelga de projects (+ categoría opcional).
create table if not exists rounds (
  id                      uuid primary key default gen_random_uuid(),
  project_id              uuid not null references projects(id) on delete cascade,
  category_id             uuid references categories(id),
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
  created_by              uuid references users(id),
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now(),
  unique (project_id, round_number)
);
create index on rounds (project_id);

-- Marcas/Razones: reemplaza al Estudio como entidad de codificación, ahora
-- por ronda — cada ronda define sus propios subproyectos por coding_type.
create table if not exists subprojects (
  id           uuid primary key default gen_random_uuid(),
  round_id     uuid not null references rounds(id) on delete cascade,
  codebook_id  uuid,   -- FK agregada tras crear codebooks (ver más abajo)
  coding_type  text not null check (coding_type in ('brands','reasons')),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  unique (round_id, coding_type)
);
create index on subprojects (round_id);

-- Serial del respondente, separado de verbatims para no repetirlo por fila.
create table if not exists respondents (
  id                       uuid primary key default gen_random_uuid(),
  round_id                 uuid not null references rounds(id) on delete cascade,
  respondent_external_id   text not null,
  created_at               timestamptz not null default now(),
  unique (round_id, respondent_external_id)
);
create index on respondents (round_id);

-- =====================================================================
-- 2. VISIBILIDAD POR PROYECTO
-- =====================================================================
create table if not exists assignments (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  user_id       uuid not null references users(id) on delete cascade,
  role_context  text not null check (role_context in ('codificador','supervisor')),
  status        text not null default 'active' check (status in ('active','completed','reassigned')),
  assigned_by   uuid references users(id),
  assigned_at   timestamptz not null default now(),
  unique (project_id, user_id)
);

-- =====================================================================
-- 3. ARCHIVOS
-- =====================================================================
create table if not exists imported_files (
  id                uuid primary key default gen_random_uuid(),
  round_id          uuid not null references rounds(id) on delete cascade,
  file_type         text not null check (file_type in ('verbatims_xlsx','codebook_xlsx','combined_xlsx','dau')),
  sheet_name        text,
  original_filename text not null,
  storage_path      text,               -- ruta en Supabase Storage (bucket privado)
  checksum          text,               -- sha256: evita importar dos veces lo mismo
  total_rows        int,
  status            text not null default 'uploaded'
                    check (status in ('uploaded','validating','validated','failed')),
  error_log         jsonb,
  uploaded_by       uuid references users(id),
  created_at        timestamptz not null default now()
);
create index on imported_files (round_id);

-- =====================================================================
-- 4. LIBRO DE CÓDIGOS
-- =====================================================================
-- Sube de nivel Ronda a nivel Estudio (project_id): compartido entre
-- categorías/rondas, así una Ronda 2 puede heredar el mismo libro sin
-- reprocesarlo.
create table if not exists codebooks (
  id                     uuid primary key default gen_random_uuid(),
  project_id             uuid not null references projects(id) on delete cascade,
  coding_type            text not null check (coding_type in ('brands','reasons')),
  version                int  not null default 1,
  parent_codebook_id     uuid references codebooks(id),   -- NULL = creado desde CERO
  imported_from_file_id  uuid references imported_files(id),
  status                 text not null default 'draft'
                         check (status in ('draft','in_review','approved','exported')),
  approved_by            uuid references users(id),
  approved_at            timestamptz,
  created_at             timestamptz not null default now(),
  unique (project_id, coding_type, version)
);

do $$ begin
  alter table subprojects add constraint subprojects_codebook_id_fkey
    foreign key (codebook_id) references codebooks(id);
exception when duplicate_object then null;
end $$;
do $$ begin
  alter table subprojects alter column codebook_id set not null;
exception when duplicate_object then null;
end $$;

create table if not exists codes (
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
  created_by             uuid references users(id),
  created_at             timestamptz not null default now(),
  unique (codebook_id, code_number)
);
create index on codes (codebook_id) where is_active;

create table if not exists code_aliases (
  id               uuid primary key default gen_random_uuid(),
  codebook_id      uuid not null references codebooks(id) on delete cascade,
  code_id          uuid not null references codes(id) on delete cascade,
  alias_normalized text not null,
  alias_sample     text,
  occurrences      int  default 1,
  origin           text not null default 'analyst_manual'
                   check (origin in ('inherited','engine_fuzzy','analyst_manual','imported_xlsx','llm_promoted')),
  match_score      numeric(4,3),
  approved_by      uuid references users(id),
  created_at       timestamptz not null default now(),
  unique (codebook_id, alias_normalized, code_id)
);
create index on code_aliases (codebook_id, alias_normalized);
create index code_aliases_trgm_idx on code_aliases using gin (alias_normalized gin_trgm_ops);

create table if not exists nets (
  id            uuid primary key default gen_random_uuid(),
  codebook_id   uuid not null references codebooks(id) on delete cascade,
  name          text not null,
  origin        text not null default 'analyst_manual'
                check (origin in ('engine_auto','analyst_manual')),
  display_order int not null default 0,
  created_by    uuid references users(id),
  created_at    timestamptz not null default now()
);

create table if not exists net_codes (
  id            uuid primary key default gen_random_uuid(),
  net_id        uuid not null references nets(id) on delete cascade,
  code_id       uuid not null references codes(id) on delete cascade,
  display_order int not null default 0,
  unique (net_id, code_id)
);

-- Caché semántico local de razones: cuando classify_round aprueba una razón
-- sobre el umbral de promoción, se cachea su embedding aquí para que futuros
-- verbatims casi idénticos no vuelvan a tocar el LLM. No se usa fuzzy para
-- razones (falsos positivos tipo "frescura"~"firme"), ver fuzzy/matcher.py.
create table if not exists reason_embeddings (
  id           uuid primary key default gen_random_uuid(),
  codebook_id  uuid not null references codebooks(id) on delete cascade,
  code_id      uuid not null references codes(id) on delete cascade,
  source_text  text not null,
  embedding    vector(384) not null,
  confidence   numeric(4,3),
  created_at   timestamptz not null default now()
);
create index on reason_embeddings (codebook_id);
create index reason_embeddings_hnsw_idx on reason_embeddings
  using hnsw (embedding vector_cosine_ops);

-- =====================================================================
-- 5. MOTOR (histórico de corridas)
-- =====================================================================
-- Corre por Marcas o por Razones por separado (subproject_id), no por la
-- ronda completa.
create table if not exists processing_runs (
  id                     uuid primary key default gen_random_uuid(),
  subproject_id          uuid not null references subprojects(id) on delete cascade,
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
  executed_by            uuid references users(id),
  created_at             timestamptz not null default now()
);
create index on processing_runs (subproject_id, created_at desc);

-- =====================================================================
-- 6. DATOS
-- =====================================================================
create table if not exists mention_groups (
  id                uuid primary key default gen_random_uuid(),
  subproject_id     uuid not null references subprojects(id) on delete cascade,
  normalized_text   text not null,
  sample_text       text,
  frequency_count   int  not null default 0,
  status            text not null default 'pending_review'
                    check (status in ('auto_coded','below_threshold','anomaly','pending_review','resolved')),
  suggested_code_id uuid references codes(id),
  created_by_run_id uuid references processing_runs(id) on delete set null,
  resolved_by       uuid references users(id),
  resolved_at       timestamptz,
  created_at        timestamptz not null default now(),
  unique (subproject_id, normalized_text)
);
create index on mention_groups (subproject_id, status);

create table if not exists verbatims (
  id                     uuid primary key default gen_random_uuid(),
  subproject_id          uuid not null references subprojects(id) on delete cascade,
  respondent_id          uuid references respondents(id),
  question_id            uuid references questions(id),
  mention_group_id       uuid references mention_groups(id),
  imported_file_id       uuid references imported_files(id),
  source_question_key    text,
  original_text          text not null,
  normalized_text        text,
  input_code_number      int,
  coding_status          text not null default 'pending'
                         check (coding_status in ('pending','auto_coded','needs_review','manually_coded','unknown')),
  created_at             timestamptz not null default now(),
  unique (subproject_id, respondent_id, source_question_key)
);
create index on verbatims (subproject_id, coding_status);
create index on verbatims (mention_group_id);

create table if not exists verbatim_codes (
  id                 uuid primary key default gen_random_uuid(),
  verbatim_id        uuid not null references verbatims(id) on delete cascade,
  code_id            uuid not null references codes(id) on delete cascade,
  output_index       int  not null default 1,
  source             text not null
                     check (source in ('engine_exact','engine_fuzzy','llm_classified','semantic_cache','homologation','analyst_manual','audit_correction')),
  confidence_score   numeric(4,3),
  matched_alias      text,  -- alias del catálogo que matcheó (transparencia: por qué el fuzzy asignó este código)
  processing_run_id  uuid references processing_runs(id) on delete set null,
  assigned_by        uuid references users(id),
  is_active          boolean not null default true,
  created_at         timestamptz not null default now(),
  unique (verbatim_id, code_id)
);
create index on verbatim_codes (code_id) where is_active;
create index on verbatim_codes (verbatim_id) where is_active;

-- =====================================================================
-- 7. AUDITORÍA
-- =====================================================================
create table if not exists audit_sessions (
  id                 uuid primary key default gen_random_uuid(),
  subproject_id      uuid not null references subprojects(id) on delete cascade,
  processing_run_id  uuid references processing_runs(id) on delete set null,
  target_percentage  numeric(5,2) not null,
  total_items        int not null default 0,
  reviewed_items     int not null default 0,
  target_met         boolean not null default false,
  status             text not null default 'pending'
                     check (status in ('pending','in_progress','approved')),
  approved_by        uuid references users(id),
  approved_at        timestamptz,
  created_at         timestamptz not null default now()
);

create table if not exists audit_code_reviews (
  id                uuid primary key default gen_random_uuid(),
  audit_session_id  uuid not null references audit_sessions(id) on delete cascade,
  code_id           uuid not null references codes(id) on delete cascade,
  items_count       int not null default 0,
  corrections_count int not null default 0,
  status            text not null default 'pending'
                    check (status in ('pending','approved','with_corrections')),
  reviewer_id       uuid references users(id),
  reviewed_at       timestamptz,
  unique (audit_session_id, code_id)
);

create table if not exists audit_items (
  id                    uuid primary key default gen_random_uuid(),
  audit_code_review_id  uuid not null references audit_code_reviews(id) on delete cascade,
  verbatim_id           uuid not null references verbatims(id) on delete cascade,
  codes_snapshot        jsonb,
  status                text not null default 'pending'
                        check (status in ('pending','correct','reassigned')),
  reviewer_id           uuid references users(id),
  reviewed_at           timestamptz,
  comment               text,
  unique (audit_code_review_id, verbatim_id)
);

create table if not exists audit_logs (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid references users(id),
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
-- 8. EXPORTACIÓN
-- =====================================================================
create table if not exists export_jobs (
  id               uuid primary key default gen_random_uuid(),
  round_id         uuid not null references rounds(id) on delete cascade,
  include_nets     boolean not null default false,
  status           text not null default 'queued'
                   check (status in ('queued','running','completed','failed')),
  zip_storage_path text,
  error_message    text,
  requested_by     uuid references users(id),
  created_at       timestamptz not null default now(),
  finished_at      timestamptz
);

create table if not exists export_files (
  id             uuid primary key default gen_random_uuid(),
  export_job_id  uuid not null references export_jobs(id) on delete cascade,
  round_id       uuid references rounds(id),
  subproject_id  uuid references subprojects(id),
  file_type      text not null
                 check (file_type in ('codebook_xlsx','codebook_nets_xlsx','coded_verbatims_xlsx','mdd_1','mdd_2')),
  storage_path   text not null,
  size_bytes     bigint,
  created_at     timestamptz not null default now()
);

-- =====================================================================
-- 9. FRECUENCIAS
-- =====================================================================
create table if not exists code_stats (
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
-- 10. SEGURIDAD:  RLS ACTIVO Y SIN POLÍTICAS
-- =====================================================================
do $$
declare t text;
begin
  foreach t in array array[
    'users','user_roles','assignments','proyectos','projects','categories',
    'questions','question_aliases','rounds','subprojects','respondents',
    'imported_files','codebooks','codes','code_aliases','nets','net_codes',
    'processing_runs','mention_groups','verbatims','verbatim_codes',
    'audit_sessions','audit_code_reviews','audit_items','audit_logs',
    'export_jobs','export_files','code_stats'
  ] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
  end loop;
end $$;

-- =====================================================================
-- 11. updated_at automático
-- =====================================================================
create or replace function touch_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end; $$;

drop trigger if exists t_proyectos   on proyectos;
create trigger t_proyectos   before update on proyectos   for each row execute function touch_updated_at();
drop trigger if exists t_projects    on projects;
create trigger t_projects    before update on projects    for each row execute function touch_updated_at();
drop trigger if exists t_rounds      on rounds;
create trigger t_rounds      before update on rounds      for each row execute function touch_updated_at();
drop trigger if exists t_subprojects on subprojects;
create trigger t_subprojects before update on subprojects for each row execute function touch_updated_at();
