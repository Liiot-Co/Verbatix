-- DB v8 Fase 1, Tarea 3: catálogo de variables por estudio (project_id),
-- con alias para variables renombradas entre plataformas/rondas.
create table questions (
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

create table question_aliases (
  id                     uuid primary key default gen_random_uuid(),
  canonical_question_id  uuid not null references questions(id) on delete cascade,
  alias_key              text not null,
  created_at             timestamptz not null default now(),
  unique (canonical_question_id, alias_key)
);

do $$
declare t text;
begin
  foreach t in array array['questions','question_aliases'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
  end loop;
end $$;
