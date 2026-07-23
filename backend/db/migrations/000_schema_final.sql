-- =====================================================================
-- VERBATIX — FINAL SCHEMA (flattened from 20 incremental migrations)
-- =====================================================================
-- This file replaces all incremental migrations (001–012) with a single
-- schema definition using canonical table/column names. It is safe to run
-- on an empty database only (docker compose down -v && docker compose up).
--
-- Canonical naming (post-rename):
--   projects  ← proyectos
--   studies   ← projects → studios → studies
--   study_id  ← project_id on rounds/categories/questions/codebooks/assignments
--   project_id on studies (FK to projects, was proyecto_id)
-- =====================================================================

create extension if not exists "pgcrypto";
create extension if not exists "pg_trgm";
create extension if not exists vector;

-- =====================================================================
-- 0. AUTH STUB (local dev only — omit for real Supabase)
-- =====================================================================
create schema if not exists auth;
create table if not exists auth.users (id uuid primary key);

insert into auth.users (id)
values ('00000000-0000-0000-0000-000000000001')
on conflict (id) do nothing;

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated;
  end if;
end $$;

-- =====================================================================
-- 1. FUNCTIONS
-- =====================================================================
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

create or replace function touch_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end; $$;

create or replace function prevent_code_number_reassignment()
returns trigger language plpgsql as $$
begin
  if new.code_number is distinct from old.code_number then
    raise exception 'code_number is immutable for code %', old.id using errcode = '23514';
  end if;
  return new;
end; $$;

create or replace function prevent_ready_dataset_snapshot_update()
returns trigger language plpgsql as $$
begin
  if old.dataset_snapshot is not null
     and old.dataset_snapshot ->> 'status' = 'ready'
     and new.dataset_snapshot is distinct from old.dataset_snapshot then
    raise exception 'dataset_snapshot ready es inmutable para imported_file %', old.id;
  end if;
  return new;
end; $$;

-- =====================================================================
-- 2. USERS & AUTH
-- =====================================================================
create table if not exists users (
  id                   uuid primary key references auth.users(id) on delete cascade,
  email                text not null,
  name                 text,
  is_active            boolean not null default true,
  password_hash        text,
  account_status       text not null default 'pending',
  approved_by          uuid references users(id),
  approved_at          timestamptz,
  session_status       text not null default 'offline',
  last_activity_at     timestamptz,
  presence_status      text not null default 'disponible',
  presence_changed_at  timestamptz,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  constraint users_account_status_check check (account_status in ('pending','active','suspended')),
  constraint users_session_status_check check (session_status in ('active','away','offline'))
);

create unique index if not exists users_email_lower_uidx on users (lower(btrim(email)));

create table if not exists user_roles (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references users(id) on delete cascade,
  role_code     text not null check (role_code in ('admin','codificador','supervisor')),
  assigned_by   uuid references users(id),
  assigned_at   timestamptz not null default now(),
  unique (user_id, role_code)
);

create table if not exists auth_sessions (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references users(id) on delete cascade,
  token_hash    text not null unique,
  expires_at    timestamptz not null,
  revoked_at    timestamptz,
  created_at    timestamptz not null default now(),
  last_used_at  timestamptz
);

create index if not exists auth_sessions_user_active_idx
  on auth_sessions (user_id, expires_at) where revoked_at is null;

create table if not exists password_recovery_codes (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references users(id) on delete cascade,
  code_hash   text not null unique,
  used_at     timestamptz,
  revoked_at  timestamptz,
  created_at  timestamptz not null default now()
);

create index if not exists recovery_codes_user_active_idx
  on password_recovery_codes (user_id, created_at desc)
  where used_at is null and revoked_at is null;

-- =====================================================================
-- 3. PROJECT STRUCTURE
-- =====================================================================
create table if not exists projects (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  created_by  uuid references users(id),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table if not exists studies (
  id             uuid primary key default gen_random_uuid(),
  project_id     uuid references projects(id),
  external_code  text unique,
  name           text not null,
  created_by     uuid references users(id),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create table if not exists categories (
  id          uuid primary key default gen_random_uuid(),
  study_id    uuid not null references studies(id) on delete cascade,
  name        text not null,
  status      text not null default 'created',
  created_at  timestamptz not null default now(),
  constraint categories_status_check check (status in ('created','in_progress','completed'))
);

create index if not exists categories_study_id_idx on categories (study_id);

create table if not exists questions (
  id                        uuid primary key default gen_random_uuid(),
  study_id                  uuid not null references studies(id) on delete cascade,
  coding_type               text not null check (coding_type in ('brands','reasons')),
  question_key              text not null,
  single_code_per_response  boolean not null default false,
  expected_max_mentions     int,
  display_label             text,
  is_active                 boolean not null default true,
  created_at                timestamptz not null default now(),
  unique (study_id, question_key)
);

create index if not exists questions_study_id_idx on questions (study_id);

create table if not exists question_aliases (
  id                     uuid primary key default gen_random_uuid(),
  canonical_question_id  uuid not null references questions(id) on delete cascade,
  alias_key              text not null,
  source_note            text,
  created_by             uuid references users(id),
  created_at             timestamptz not null default now(),
  unique (canonical_question_id, alias_key)
);

create table if not exists rounds (
  id                      uuid primary key default gen_random_uuid(),
  study_id                uuid not null references studies(id) on delete cascade,
  category_id             uuid references categories(id),
  name                    text not null,
  round_number            int not null,
  status                  text not null default 'created',
  min_mentions_threshold  int not null default 3,
  audit_percentage        numeric(5,2) not null default 10,
  origin_mode             text not null default 'from_scratch',
  source_round_id         uuid references rounds(id),
  expected_max_mentions   int,
  created_by              uuid references users(id),
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now(),
  unique (study_id, round_number),
  constraint rounds_status_check check (status in ('created','files_uploaded','processing','codebook_review','preliminary_ready','manual_coding','audit_pending','audit_approved','nets_review','ready_to_export','completed','failed')),
  constraint rounds_origin_mode_check check (origin_mode in ('from_scratch','homologated'))
);

create index if not exists rounds_study_id_idx on rounds (study_id);

-- =====================================================================
-- 4. ASSIGNMENTS
-- =====================================================================
create table if not exists assignments (
  id            uuid primary key default gen_random_uuid(),
  study_id      uuid not null references studies(id) on delete cascade,
  user_id       uuid not null references users(id) on delete cascade,
  role_context  text check (role_context in ('codificador','supervisor')),
  status        text not null default 'active' check (status in ('active','completed','reassigned')),
  assigned_by   uuid references users(id),
  revoked_at    timestamptz,
  assigned_at   timestamptz not null default now(),
  unique (study_id, user_id)
);

-- =====================================================================
-- 5. FILES
-- =====================================================================
create table if not exists imported_files (
  id                     uuid primary key default gen_random_uuid(),
  round_id               uuid not null references rounds(id) on delete cascade,
  file_type              text not null check (file_type in ('verbatims_xlsx','codebook_xlsx','combined_xlsx','dau')),
  sheet_name             text,
  original_filename      text not null,
  storage_path           text,
  checksum               text,
  total_rows             int,
  status                 text not null default 'uploaded' check (status in ('uploaded','validating','validated','failed')),
  error_log              jsonb,
  source_label           text,
  detected_max_mentions  int,
  mentions_decision      text,
  dataset_snapshot       jsonb,
  uploaded_by            uuid references users(id),
  created_at             timestamptz not null default now(),
  constraint imported_files_mentions_decision_check check (mentions_decision is null or mentions_decision in ('process_all','limit_to_expected'))
);

create index if not exists imported_files_round_id_idx on imported_files (round_id);

create table if not exists profile_files (
  id                uuid primary key default gen_random_uuid(),
  round_id          uuid not null references rounds(id) on delete cascade,
  original_filename text not null,
  storage_path      text,
  total_rows        int,
  coding_type       text,
  uploaded_by       uuid references users(id),
  created_at        timestamptz not null default now(),
  constraint profile_files_coding_type_check check (coding_type is null or coding_type in ('brands', 'reasons'))
);

create index if not exists profile_files_round_idx on profile_files (round_id);
create index if not exists profile_files_round_coding_idx on profile_files (round_id, coding_type, created_at desc);

create table if not exists profile_entries (
  id                     uuid primary key default gen_random_uuid(),
  profile_file_id        uuid not null references profile_files(id) on delete cascade,
  respondent_external_id text,
  realid                 text,
  completion_indicator   text,
  quotas                 jsonb,
  created_at             timestamptz not null default now()
);

create index if not exists profile_entries_file_idx on profile_entries (profile_file_id);
create index if not exists profile_entries_serial_idx on profile_entries (profile_file_id, respondent_external_id);

-- =====================================================================
-- 6. RESPONDENTS
-- =====================================================================
create table if not exists respondents (
  id                       uuid primary key default gen_random_uuid(),
  round_id                 uuid not null references rounds(id) on delete cascade,
  respondent_external_id   text not null,
  imported_file_id         uuid references imported_files(id),
  realid                   text,
  profile_status           text not null default 'not_checked',
  created_at               timestamptz not null default now(),
  unique (round_id, imported_file_id, respondent_external_id),
  constraint respondents_profile_status_check check (profile_status in ('matched','not_in_profile','excluded_confirmed','not_checked'))
);

create index if not exists respondents_round_id_idx on respondents (round_id);
create index if not exists respondents_profile_status_idx on respondents (round_id, profile_status);

-- =====================================================================
-- 7. CODEBOOKS & CODES
-- =====================================================================
create table if not exists codebooks (
  id                     uuid primary key default gen_random_uuid(),
  study_id               uuid not null references studies(id) on delete cascade,
  coding_type            text not null check (coding_type in ('brands','reasons')),
  version                int not null default 1,
  parent_codebook_id     uuid references codebooks(id),
  imported_from_file_id  uuid references imported_files(id),
  origin                 text not null default 'scratch',
  overflow_threshold     int,
  status                 text not null default 'draft',
  approved_by            uuid references users(id),
  approved_at            timestamptz,
  created_at             timestamptz not null default now(),
  unique (study_id, coding_type, version),
  constraint codebooks_origin_check check (origin in ('scratch','inherited_round','imported_client_catalog')),
  constraint codebooks_status_check check (status in ('draft','in_review','approved','exported'))
);

create index if not exists codebooks_parent_codebook_idx on codebooks (parent_codebook_id) where parent_codebook_id is not null;

create table if not exists codes (
  id                          uuid primary key default gen_random_uuid(),
  codebook_id                 uuid not null references codebooks(id) on delete cascade,
  code_number                 int not null,
  label                       text not null,
  origin                      text not null default 'analyst_manual',
  is_system                   boolean not null default false,
  system_type                 text check (system_type in ('anomaly','no_answer','other_mentions','none','no_recall')),
  inherited_from_code_id      uuid references codes(id),
  is_active                   boolean not null default true,
  is_system_overflow          boolean not null default false,
  overflow_base_system_type   text,
  definition                  text,
  inclusion_criteria          jsonb not null default '[]'::jsonb,
  exclusion_criteria          jsonb not null default '[]'::jsonb,
  examples                    jsonb not null default '[]'::jsonb,
  approval_status             text not null default 'approved',
  created_by                  uuid references users(id),
  created_at                  timestamptz not null default now(),
  unique (codebook_id, code_number),
  constraint codes_origin_check check (origin in ('inherited','engine_auto','analyst_manual','imported_client')),
  constraint codes_approval_status_check check (approval_status in ('pending','approved','revoked')),
  constraint codes_overflow_base_system_type_check check (overflow_base_system_type is null or overflow_base_system_type in ('anomaly','no_answer','other_mentions','none','no_recall')),
  constraint codes_system_overflow_consistency_check check (
    (is_system_overflow and is_system and code_number between 995 and 999 and overflow_base_system_type is not null and system_type = overflow_base_system_type)
    or (not is_system_overflow and overflow_base_system_type is null))
);

create index if not exists codes_codebook_id_active_idx on codes (codebook_id) where is_active;
create index if not exists codes_inherited_from_code_idx on codes (inherited_from_code_id) where inherited_from_code_id is not null;
create unique index if not exists codes_codebook_active_system_type_uidx on codes (codebook_id, system_type) where is_system and system_type is not null and is_active;

create table if not exists code_aliases (
  id                     uuid primary key default gen_random_uuid(),
  codebook_id            uuid not null references codebooks(id) on delete cascade,
  code_id                uuid not null references codes(id) on delete cascade,
  alias_normalized       text not null,
  alias_sample           text,
  occurrences            int default 1,
  origin                 text not null default 'analyst_manual',
  match_score            numeric(4,3),
  alias_kind             text not null default 'positive',
  status                 text not null default 'approved',
  normalization_version  text not null default 'canonical-v1',
  evidence               jsonb not null default '{}'::jsonb,
  approved_at            timestamptz,
  revoked_at             timestamptz,
  approved_by            uuid references users(id),
  created_at             timestamptz not null default now(),
  unique (codebook_id, alias_normalized, code_id),
  constraint code_aliases_origin_check check (origin in ('inherited','engine_fuzzy','analyst_manual','imported_xlsx','llm_promoted')),
  constraint code_aliases_alias_kind_check check (alias_kind in ('positive','negative','system')),
  constraint code_aliases_status_check check (status in ('pending','approved','revoked','conflict'))
);

create index if not exists code_aliases_codebook_alias_idx on code_aliases (codebook_id, alias_normalized);
create index if not exists code_aliases_trgm_idx on code_aliases using gin (alias_normalized gin_trgm_ops);
create unique index if not exists code_aliases_one_approved_target_uidx on code_aliases (codebook_id, alias_normalized) where status = 'approved' and alias_kind in ('positive', 'system');

create table if not exists nets (
  id            uuid primary key default gen_random_uuid(),
  codebook_id   uuid not null references codebooks(id) on delete cascade,
  name          text not null,
  origin        text not null default 'analyst_manual' check (origin in ('engine_auto','analyst_manual')),
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

create table if not exists reason_embeddings (
  id               uuid primary key default gen_random_uuid(),
  codebook_id      uuid not null references codebooks(id) on delete cascade,
  code_id          uuid not null references codes(id) on delete cascade,
  source_text      text not null,
  embedding        vector(384) not null,
  confidence       numeric(4,3),
  approval_status  text not null default 'pending',
  source           text not null default 'legacy_llm',
  created_at       timestamptz not null default now(),
  constraint reason_embeddings_approval_status_check check (approval_status in ('pending','approved','revoked'))
);

create index if not exists reason_embeddings_codebook_id_idx on reason_embeddings (codebook_id);
create index if not exists reason_embeddings_hnsw_idx on reason_embeddings using hnsw (embedding vector_cosine_ops);

-- =====================================================================
-- 8. SUBPROJECTS
-- =====================================================================
create table if not exists subprojects (
  id                        uuid primary key default gen_random_uuid(),
  round_id                  uuid not null references rounds(id) on delete cascade,
  codebook_id               uuid not null references codebooks(id),
  coding_type               text not null check (coding_type in ('brands','reasons')),
  name                      text,
  origin_mode               text not null default 'from_scratch',
  source_subproject_id      uuid references subprojects(id),
  min_mentions_threshold    int not null default 3,
  audit_percentage          numeric(5,2) not null default 10,
  target_sample_size        int,
  status                    text not null default 'created',
  single_code_per_response  boolean not null default false,
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now(),
  unique (round_id, coding_type),
  constraint subprojects_origin_mode_check check (origin_mode in ('from_scratch','homologated')),
  constraint subprojects_status_check check (status in ('created','files_uploaded','processing','codebook_review','preliminary_ready','manual_coding','audit_pending','audit_approved','nets_review','ready_to_export','completed','failed'))
);

create index if not exists subprojects_round_id_idx on subprojects (round_id);

-- =====================================================================
-- 9. PROCESSING & MENTIONS
-- =====================================================================
create table if not exists processing_runs (
  id                     uuid primary key default gen_random_uuid(),
  subproject_id          uuid not null references subprojects(id) on delete cascade,
  run_type               text not null check (run_type in ('initial','homologation','reprocess')),
  algorithm              text,
  min_mentions_threshold int,
  audit_percentage       numeric(5,2),
  random_seed            int,
  status                 text not null default 'queued' check (status in ('queued','running','completed','failed')),
  total_verbatims        int default 0,
  auto_coded_count       int default 0,
  manual_coded_count     int default 0,
  new_codes_count        int default 0,
  anomalies_count        int default 0,
  metrics                jsonb,
  total_groups           int not null default 0,
  policy_version         text,
  prompt_version         text,
  model_name             text,
  error_message          text,
  started_at             timestamptz,
  finished_at            timestamptz,
  executed_by            uuid references users(id),
  created_at             timestamptz not null default now()
);

create index if not exists processing_runs_subproject_created_idx on processing_runs (subproject_id, created_at desc);

create table if not exists mention_groups (
  id                uuid primary key default gen_random_uuid(),
  subproject_id     uuid not null references subprojects(id) on delete cascade,
  normalized_text   text not null,
  sample_text       text,
  frequency_count   int not null default 0,
  status            text not null default 'pending_review',
  suggested_code_id uuid references codes(id),
  created_by_run_id uuid references processing_runs(id) on delete set null,
  resolved_by       uuid references users(id),
  resolved_at       timestamptz,
  created_at        timestamptz not null default now(),
  unique (subproject_id, normalized_text),
  constraint mention_groups_status_check check (status in ('auto_coded','below_threshold','anomaly','pending_review','resolved','suggested','garbage','engine_error','abstained','conflict'))
);

create index if not exists mention_groups_subproject_status_idx on mention_groups (subproject_id, status);

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
  source_row_number      int,
  mention_position       int not null default 1,
  coding_status          text not null default 'pending',
  created_at             timestamptz not null default now(),
  unique (subproject_id, respondent_id, source_question_key, mention_position),
  constraint verbatims_coding_status_check check (coding_status in ('pending','auto_coded','needs_review','manually_coded','unknown','suggested','garbage','engine_error','abstained','conflict')),
  constraint verbatims_source_row_number_check check (source_row_number is null or source_row_number > 0),
  constraint verbatims_mention_position_check check (mention_position > 0)
);

create index if not exists verbatims_subproject_status_idx on verbatims (subproject_id, coding_status);
create index if not exists verbatims_mention_group_id_idx on verbatims (mention_group_id);

create table if not exists verbatim_codes (
  id                 uuid primary key default gen_random_uuid(),
  verbatim_id        uuid not null references verbatims(id) on delete cascade,
  code_id            uuid not null references codes(id) on delete cascade,
  output_index       int not null default 1,
  source             text not null,
  confidence_score   numeric(4,3),
  matched_alias      text,
  processing_run_id  uuid references processing_runs(id) on delete set null,
  assigned_by        uuid references users(id),
  is_active          boolean not null default true,
  created_at         timestamptz not null default now(),
  unique (verbatim_id, code_id),
  constraint verbatim_codes_source_check check (source in ('engine_exact','engine_fuzzy','engine_rule','llm_classified','llm_suggestion','semantic_cache','rule_brand_in_reason','homologation','analyst_manual','audit_correction'))
);

create index if not exists verbatim_codes_code_active_idx on verbatim_codes (code_id) where is_active;
create index if not exists verbatim_codes_verbatim_active_idx on verbatim_codes (verbatim_id) where is_active;

-- =====================================================================
-- 10. AUDIT
-- =====================================================================
create table if not exists audit_sessions (
  id                 uuid primary key default gen_random_uuid(),
  subproject_id      uuid not null references subprojects(id) on delete cascade,
  processing_run_id  uuid references processing_runs(id) on delete set null,
  target_percentage  numeric(5,2) not null,
  total_items        int not null default 0,
  reviewed_items     int not null default 0,
  target_met         boolean not null default false,
  status             text not null default 'pending' check (status in ('pending','in_progress','approved')),
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
  status            text not null default 'pending' check (status in ('pending','approved','with_corrections')),
  reviewer_id       uuid references users(id),
  reviewed_at       timestamptz,
  unique (audit_session_id, code_id)
);

create table if not exists audit_items (
  id                    uuid primary key default gen_random_uuid(),
  audit_code_review_id  uuid not null references audit_code_reviews(id) on delete cascade,
  verbatim_id           uuid not null references verbatims(id) on delete cascade,
  codes_snapshot        jsonb,
  status                text not null default 'pending' check (status in ('pending','correct','reassigned')),
  reviewer_id           uuid references users(id),
  reviewed_at           timestamptz,
  comment               text,
  unique (audit_code_review_id, verbatim_id)
);

create table if not exists audit_comments (
  id            uuid primary key default gen_random_uuid(),
  audit_item_id uuid not null references audit_items(id) on delete cascade,
  author_id     uuid references users(id) on delete set null,
  content       text not null check (length(btrim(content)) > 0),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  deleted_at    timestamptz
);

create index if not exists audit_comments_item_created_idx on audit_comments (audit_item_id, created_at);

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

create index if not exists audit_logs_round_created_idx on audit_logs (round_id, created_at desc);
create index if not exists audit_logs_entity_idx on audit_logs (entity_name, entity_id);

-- =====================================================================
-- 11. IMPORT REVIEW & DECISIONS
-- =====================================================================
create table if not exists import_review_flags (
  id                    uuid primary key default gen_random_uuid(),
  imported_file_id      uuid not null references imported_files(id) on delete cascade,
  respondent_id         uuid references respondents(id) on delete cascade,
  question_id           uuid references questions(id),
  resolved_question_id  uuid references questions(id),
  flag_type             text not null check (flag_type in ('possible_duplicate','not_in_profile','mention_overflow','unmatched_question_column')),
  detail                jsonb,
  status                text not null default 'pending' check (status in ('pending','approved_remove','approved_keep','edited','resolved')),
  reviewed_by           uuid references users(id),
  reviewed_at           timestamptz,
  created_at            timestamptz not null default now()
);

create index if not exists import_review_flags_file_status_idx on import_review_flags (imported_file_id, status);
create index if not exists import_review_flags_type_status_idx on import_review_flags (flag_type, status);

create table if not exists question_mention_decisions (
  id                     uuid primary key default gen_random_uuid(),
  imported_file_id       uuid not null references imported_files(id) on delete cascade,
  question_id            uuid references questions(id) on delete set null,
  question_key           text not null,
  expected_max_mentions  int,
  detected_max_mentions  int not null,
  decision               text not null check (decision in ('process_all','limit_to_expected')),
  decided_by             uuid references users(id),
  decided_at             timestamptz not null default now(),
  unique (imported_file_id, question_key)
);

create index if not exists question_mention_decisions_file_idx on question_mention_decisions (imported_file_id);

-- =====================================================================
-- 12. NOTIFICATIONS & USER EVENTS
-- =====================================================================
create table if not exists notifications (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null references users(id) on delete cascade,
  sender_id         uuid references users(id) on delete set null,
  type              text not null,
  title             text,
  body              text,
  related_entity_id uuid,
  is_read           boolean not null default false,
  last_reminded_at  timestamptz,
  reminder_count    smallint not null default 0,
  created_at        timestamptz not null default now()
);

create index if not exists notifications_user_read_idx on notifications (user_id, is_read);
create index if not exists notifications_unread_created_idx on notifications (created_at) where is_read = false;
create index if not exists notifications_sender_idx on notifications (sender_id);

create table if not exists time_tracking_events (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references users(id) on delete cascade,
  subject_type text not null check (subject_type in ('project','subproject','export')),
  subject_id   uuid,
  event_type   text not null check (event_type in ('assigned','opened','last_activity','completed','export_downloaded')),
  occurred_at  timestamptz not null default now()
);

create index if not exists time_tracking_user_time_idx on time_tracking_events (user_id, occurred_at desc);

create table if not exists user_status_events (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references users(id) on delete cascade,
  status     text not null,
  started_at timestamptz not null default now(),
  ended_at   timestamptz
);

create index if not exists user_status_events_user_started_idx on user_status_events (user_id, started_at desc);

-- =====================================================================
-- 13. EXPORT
-- =====================================================================
create table if not exists export_jobs (
  id                   uuid primary key default gen_random_uuid(),
  round_id             uuid not null references rounds(id) on delete cascade,
  include_nets         boolean not null default false,
  requested_file_types text,
  status               text not null default 'queued' check (status in ('queued','running','completed','failed')),
  zip_storage_path     text,
  error_message        text,
  requested_by         uuid references users(id),
  created_at           timestamptz not null default now(),
  finished_at          timestamptz
);

create table if not exists export_files (
  id             uuid primary key default gen_random_uuid(),
  export_job_id  uuid not null references export_jobs(id) on delete cascade,
  round_id       uuid references rounds(id),
  subproject_id  uuid references subprojects(id),
  file_type      text not null check (file_type in ('codebook_xlsx','codebook_nets_xlsx','coded_verbatims_xlsx','mdd_1','mdd_2','mdd','sql','onnextcase')),
  storage_path   text not null,
  size_bytes     bigint,
  created_at     timestamptz not null default now()
);

-- =====================================================================
-- 14. CODE STATS
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
-- 15. TRIGGERS
-- =====================================================================
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();

drop trigger if exists t_projects on projects;
create trigger t_projects before update on projects   for each row execute function touch_updated_at();
drop trigger if exists t_studies on studies;
create trigger t_studies  before update on studies    for each row execute function touch_updated_at();
drop trigger if exists t_rounds on rounds;
create trigger t_rounds   before update on rounds     for each row execute function touch_updated_at();
drop trigger if exists t_subprojects on subprojects;
create trigger t_subprojects before update on subprojects for each row execute function touch_updated_at();
drop trigger if exists t_users on users;
create trigger t_users    before update on users      for each row execute function touch_updated_at();
drop trigger if exists t_audit_comments on audit_comments;
create trigger t_audit_comments before update on audit_comments for each row execute function touch_updated_at();

drop trigger if exists codes_code_number_immutable on codes;
create trigger codes_code_number_immutable
  before update of code_number on codes
  for each row execute function prevent_code_number_reassignment();

drop trigger if exists imported_files_ready_snapshot_immutable on imported_files;
create trigger imported_files_ready_snapshot_immutable
  before update of dataset_snapshot on imported_files
  for each row execute function prevent_ready_dataset_snapshot_update();

-- =====================================================================
-- 16. DEV USER SEED
-- =====================================================================
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
-- 17. ROW LEVEL SECURITY
-- =====================================================================
do $$
declare t text;
begin
  foreach t in array array[
    'users','user_roles','assignments','projects','studies','categories',
    'questions','question_aliases','rounds','subprojects','respondents',
    'imported_files','codebooks','codes','code_aliases','nets','net_codes',
    'processing_runs','mention_groups','verbatims','verbatim_codes',
    'audit_sessions','audit_code_reviews','audit_items','audit_logs',
    'export_jobs','export_files','code_stats',
    'import_review_flags','profile_files','profile_entries',
    'notifications','time_tracking_events',
    'auth_sessions','password_recovery_codes','audit_comments',
    'question_mention_decisions'
  ] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
  end loop;
end $$;
