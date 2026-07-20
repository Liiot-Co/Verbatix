-- =====================================================================
-- REQ-08 / REQ-04: historial de decisión de menciones por pregunta+carga
-- =====================================================================
-- questions.single_code_per_response y expected_max_mentions ya existen en
-- 001_schema_v8. imported_files.detected_max_mentions / mentions_decision
-- (002_schema_v9) son a nivel archivo y no alcanzan para decisión por
-- pregunta: esta tabla guarda el historial por (carga, question_key).

create table if not exists question_mention_decisions (
  id                     uuid primary key default gen_random_uuid(),
  imported_file_id       uuid not null references imported_files(id) on delete cascade,
  question_id            uuid references questions(id) on delete set null,
  question_key           text not null,
  expected_max_mentions  int,
  detected_max_mentions  int not null,
  decision               text not null
                         check (decision in ('process_all', 'limit_to_expected')),
  decided_by             uuid references users(id),
  decided_at             timestamptz not null default now(),
  unique (imported_file_id, question_key)
);

create index if not exists question_mention_decisions_file_idx
  on question_mention_decisions (imported_file_id);

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'alter table public.question_mention_decisions enable row level security';
    execute 'revoke all on public.question_mention_decisions from anon, authenticated';
  end if;
end $$;
