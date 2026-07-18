-- DB v8 Fase 3, Tarea 8: separa el Serial (respondent_external_id) de
-- verbatims a su propia tabla por ronda, para no repetirlo en cada fila.
create table respondents (
  id                       uuid primary key default gen_random_uuid(),
  round_id                 uuid not null references rounds(id) on delete cascade,
  respondent_external_id   text not null,
  created_at               timestamptz not null default now(),
  unique (round_id, respondent_external_id)
);
create index on respondents (round_id);

do $$
begin
  execute 'alter table public.respondents enable row level security';
  execute 'revoke all on public.respondents from anon, authenticated';
end $$;
