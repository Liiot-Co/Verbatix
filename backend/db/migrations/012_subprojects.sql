-- DB v8 Fase 2, Tarea 6: subprojects reemplaza a studio (Marcas/Razones),
-- ahora colgando de round_id en vez de project_id — cada ronda define
-- sus propios subproyectos por coding_type.
create table subprojects (
  id           uuid primary key default gen_random_uuid(),
  round_id     uuid not null references rounds(id) on delete cascade,
  codebook_id  uuid references codebooks(id),
  coding_type  text not null check (coding_type in ('brands','reasons')),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  unique (round_id, coding_type)
);
create index on subprojects (round_id);

create trigger t_subprojects before update on subprojects for each row execute function touch_updated_at();

do $$
begin
  execute 'alter table public.subprojects enable row level security';
  execute 'revoke all on public.subprojects from anon, authenticated';
end $$;

-- studio ya no tiene rol en la jerarquía v8 (rounds cuelga de projects
-- desde 011). repositories.py/pipeline quedan con referencias rotas a
-- Studio/studio_id hasta el siguiente REQ (aceptado explícitamente).
drop table studio cascade;
