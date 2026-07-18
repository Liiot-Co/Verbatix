-- DB v8 Fase 1, Tarea 2: nivel opcional entre Estudio y Ronda.
create table categories (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid not null references projects(id) on delete cascade,
  name        text not null,
  created_at  timestamptz not null default now()
);
create index on categories (project_id);

do $$
begin
  execute 'alter table public.categories enable row level security';
  execute 'revoke all on public.categories from anon, authenticated';
end $$;
