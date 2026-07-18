-- DB v8 Fase 1, Tarea 1: nivel jerárquico superior que agrupa uno o
-- varios Estudios (projects). Ver tasks/db_v8_migration_plan.md.
create table proyectos (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  created_by  uuid references profiles(id),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

alter table projects add column proyecto_id uuid references proyectos(id);

create trigger t_proyectos before update on proyectos for each row execute function touch_updated_at();

do $$
begin
  execute 'alter table public.proyectos enable row level security';
  execute 'revoke all on public.proyectos from anon, authenticated';
end $$;
