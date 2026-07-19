-- =====================================================================
-- VERBATIX — ESQUEMA v9 (delta sobre v8)
-- =====================================================================
-- Migración ADITIVA que lleva el esquema v8 (001_schema_v8.sql) al modelo v9
-- del ER definitivo (proyectos -> projects -> [categories] -> rounds ->
-- subprojects; cargas por ronda; encuestados con Serial + realid separados).
--
-- Flujo para el equipo: recrear la BD desde cero y aplicar toda la cadena.
--   docker compose down -v && docker compose up
-- docker-entrypoint-initdb.d corre 000_, 001_, 002_ en orden sobre un data dir
-- vacío, así que un contenedor nuevo queda directamente en v9.
--
-- Se escribe como 002 (no editando 001) para que el delta v8->v9 quede
-- explícito y auto-documentado. Todo es idempotente (IF NOT EXISTS / DROP IF
-- EXISTS) para poder reaplicarlo sin romper.
--
-- DOS DESVIACIONES DELIBERADAS frente al diagrama v9, para NO romper lo que ya
-- funciona (Fase 1–5):
--   1) audit_logs conserva `round_id` (el diagrama lo muestra como
--      subproject_id). Todo el logging actual (log_action + auditoría +
--      resolución) escribe round_id; renombrarlo rompería esas rutas. Se deja
--      como está; migrar a subproject_id es un cambio aparte.
--   2) rounds conserva min_mentions_threshold / audit_percentage / origin_mode
--      / source_round_id. El diagrama v9 los relocó a subprojects; aquí se
--      AGREGAN también a subprojects (abajo) pero se mantienen en rounds para
--      que create_round / get_round_audit_percentage / el motor sigan operando.
--      El código nuevo debe leerlos de subprojects; la limpieza en rounds es
--      un paso posterior una vez migrado ese código.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. ESTRUCTURA: categorías, subproyectos
-- ---------------------------------------------------------------------
alter table categories
  add column if not exists status text not null default 'created';
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'categories_status_check') then
    alter table categories add constraint categories_status_check
      check (status in ('created','in_progress','completed'));
  end if;
end $$;

-- subprojects gana la configuración de proceso/auditoría que v9 baja de ronda,
-- + nombre legible, homologación por subproyecto y tamaño de muestra pactado.
alter table subprojects
  add column if not exists name text,
  add column if not exists origin_mode text not null default 'from_scratch',
  add column if not exists source_subproject_id uuid references subprojects(id),
  add column if not exists min_mentions_threshold int not null default 3,
  add column if not exists audit_percentage numeric(5,2) not null default 10,
  add column if not exists target_sample_size int,
  add column if not exists status text not null default 'created';
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'subprojects_origin_mode_check') then
    alter table subprojects add constraint subprojects_origin_mode_check
      check (origin_mode in ('from_scratch','homologated'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'subprojects_status_check') then
    alter table subprojects add constraint subprojects_status_check
      check (status in ('created','files_uploaded','processing','preliminary_ready',
                        'manual_coding','audit_pending','audit_approved','nets_review',
                        'ready_to_export','completed','failed'));
  end if;
end $$;
-- Nombre por defecto legible cuando ya existen subproyectos (sin filas en init).
update subprojects
   set name = case coding_type when 'brands' then 'Marcas' else 'Razones' end
 where name is null;

-- ---------------------------------------------------------------------
-- 2. PREGUNTAS Y ALIAS (nivel estudio)
-- ---------------------------------------------------------------------
alter table questions
  add column if not exists display_label text,
  add column if not exists is_active boolean not null default true;

-- REQ-03 (caso Warner/Langwar Tub): de qué carga salió el alias y quién lo confirmó.
alter table question_aliases
  add column if not exists source_note text,
  add column if not exists created_by uuid references users(id);

-- ---------------------------------------------------------------------
-- 3. LIBRO DE CÓDIGOS (REQ-07 / REQ-14)
-- ---------------------------------------------------------------------
alter table codebooks
  add column if not exists origin text not null default 'scratch',
  add column if not exists overflow_threshold int;
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'codebooks_origin_check') then
    alter table codebooks add constraint codebooks_origin_check
      check (origin in ('scratch','inherited_round','imported_client_catalog'));
  end if;
end $$;

alter table codes
  add column if not exists is_system_overflow boolean not null default false,
  add column if not exists overflow_base_system_type text;

-- ---------------------------------------------------------------------
-- 4. CARGAS Y ENCUESTADOS (REQ-03 / REQ-04 / REQ-05)
-- ---------------------------------------------------------------------
-- source_label: diferencia Serials repetidos entre cargas ('Dimension Parte 1'
-- vs 'Enfield Parte 2'). detected_max_mentions / mentions_decision: REQ-04
-- (solo se preservan los campos, la lógica es de otro requerimiento).
alter table imported_files
  add column if not exists source_label text,
  add column if not exists detected_max_mentions int,
  add column if not exists mentions_decision text;
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'imported_files_mentions_decision_check') then
    alter table imported_files add constraint imported_files_mentions_decision_check
      check (mentions_decision is null or mentions_decision in ('process_all','limit_to_expected'));
  end if;
end $$;

-- respondents: Serial (respondent_external_id) y realid quedan SEPARADOS. El
-- id (uuid) sigue siendo la llave técnica invisible. imported_file_id marca de
-- qué carga vino cada encuestado (REQ-03). profile_status es de REQ-05.
alter table respondents
  add column if not exists imported_file_id uuid references imported_files(id),
  add column if not exists realid text,
  add column if not exists profile_status text not null default 'not_checked';
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'respondents_profile_status_check') then
    alter table respondents add constraint respondents_profile_status_check
      check (profile_status in ('matched','not_in_profile','excluded_confirmed','not_checked'));
  end if;
end $$;

-- El UNIQUE de v8 (round_id, respondent_external_id) impedía que dos cargas
-- distintas trajeran el mismo Serial corto (Dimension y Enfield numeran cada
-- una desde 1). REQ-03: son personas distintas y ambas se guardan — la unicidad
-- pasa a ser por (ronda, carga, Serial).
alter table respondents drop constraint if exists respondents_round_id_respondent_external_id_key;
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'respondents_round_file_serial_key') then
    alter table respondents add constraint respondents_round_file_serial_key
      unique (round_id, imported_file_id, respondent_external_id);
  end if;
end $$;

-- REQ-03 / REQ-06: cola de decisiones humanas del flujo de importación. Nada se
-- borra ni se auto-resuelve; todo posible duplicado, colisión o columna sin
-- calzar que el analista no decidió queda aquí en 'pending'.
create table if not exists import_review_flags (
  id                    uuid primary key default gen_random_uuid(),
  imported_file_id      uuid not null references imported_files(id) on delete cascade,
  respondent_id         uuid references respondents(id) on delete cascade,   -- NULL si es unmatched_question_column
  question_id           uuid references questions(id),                        -- NULL salvo unmatched_question_column / mention_overflow
  resolved_question_id  uuid references questions(id),
  flag_type             text not null
                        check (flag_type in ('possible_duplicate','not_in_profile','mention_overflow','unmatched_question_column')),
  detail                jsonb,
  status                text not null default 'pending'
                        check (status in ('pending','approved_remove','approved_keep','edited','resolved')),
  reviewed_by           uuid references users(id),
  reviewed_at           timestamptz,
  created_at            timestamptz not null default now()
);
create index if not exists import_review_flags_file_status_idx on import_review_flags (imported_file_id, status);
create index if not exists import_review_flags_type_status_idx on import_review_flags (flag_type, status);

-- ---------------------------------------------------------------------
-- 5. PERFIL PACTADO (REQ-05) — solo esquema, la lógica es de otro requerimiento
-- ---------------------------------------------------------------------
create table if not exists profile_files (
  id                uuid primary key default gen_random_uuid(),
  round_id          uuid not null references rounds(id) on delete cascade,
  original_filename text not null,
  storage_path      text,
  total_rows        int,
  uploaded_by       uuid references users(id),
  created_at        timestamptz not null default now()
);
create index if not exists profile_files_round_idx on profile_files (round_id);

create table if not exists profile_entries (
  id                    uuid primary key default gen_random_uuid(),
  profile_file_id       uuid not null references profile_files(id) on delete cascade,
  respondent_external_id text,
  realid                text,
  completion_indicator  text,
  quotas                jsonb,
  created_at            timestamptz not null default now()
);
create index if not exists profile_entries_file_idx on profile_entries (profile_file_id);

-- ---------------------------------------------------------------------
-- 6. USUARIOS / ROLES / NOTIFICACIONES / TIEMPOS
-- ---------------------------------------------------------------------
alter table users
  add column if not exists session_status text not null default 'offline',
  add column if not exists last_activity_at timestamptz;
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'users_session_status_check') then
    alter table users add constraint users_session_status_check
      check (session_status in ('active','away','offline'));
  end if;
end $$;

alter table user_roles
  add column if not exists assigned_by uuid references users(id),
  add column if not exists assigned_at timestamptz not null default now();

create table if not exists notifications (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null references users(id) on delete cascade,
  type              text not null,
  title             text,
  body              text,
  related_entity_id uuid,
  is_read           boolean not null default false,
  created_at        timestamptz not null default now()
);
create index if not exists notifications_user_read_idx on notifications (user_id, is_read);

create table if not exists time_tracking_events (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references users(id) on delete cascade,
  subject_type text not null check (subject_type in ('project','subproject','export')),
  subject_id   uuid,
  event_type   text not null check (event_type in ('assigned','opened','last_activity','completed','export_downloaded')),
  occurred_at  timestamptz not null default now()
);
create index if not exists time_tracking_user_time_idx on time_tracking_events (user_id, occurred_at desc);

-- ---------------------------------------------------------------------
-- 7. EXPORTACIÓN (REQ-13): sql / onnextcase como nuevos entregables
-- ---------------------------------------------------------------------
alter table export_jobs
  add column if not exists requested_file_types text;

alter table export_files drop constraint if exists export_files_file_type_check;
alter table export_files add constraint export_files_file_type_check
  check (file_type in ('codebook_xlsx','codebook_nets_xlsx','coded_verbatims_xlsx',
                       'mdd_1','mdd_2','mdd','sql','onnextcase'));

-- ---------------------------------------------------------------------
-- 8. RLS: activo y sin políticas en las tablas nuevas (mismo patrón que v8)
-- ---------------------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array[
    'import_review_flags','profile_files','profile_entries',
    'notifications','time_tracking_events'
  ] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
  end loop;
end $$;
