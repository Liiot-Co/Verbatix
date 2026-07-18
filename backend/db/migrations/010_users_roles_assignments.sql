-- DB v8 Fase 1, Tarea 4: reemplaza el rol único (profiles.role) por
-- multi-rol (user_roles.role_code), renombra profiles->users, y agrega
-- assignments para visibilidad por proyecto completo.

-- RENAME conserva automáticamente todas las FKs existentes (created_by,
-- uploaded_by, approved_by, etc. siguen apuntando a users.id).
alter table profiles rename to users;

create table user_roles (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references users(id) on delete cascade,
  role_code  text not null check (role_code in ('admin','codificador','supervisor')),
  unique (user_id, role_code)
);

-- Migrar rol existente antes de dropear la columna vieja.
insert into user_roles (user_id, role_code)
select id, case when role = 'admin' then 'admin' else 'codificador' end
from users;

alter table users drop column role;

create table assignments (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  user_id       uuid not null references users(id) on delete cascade,
  role_context  text not null check (role_context in ('codificador','supervisor')),
  status        text not null default 'active' check (status in ('active','completed','reassigned')),
  assigned_by   uuid references users(id),
  assigned_at   timestamptz not null default now(),
  unique (project_id, user_id)
);

-- El trigger de auth.users seguía insertando en "profiles"; ahora inserta
-- en users + user_roles (rol por defecto codificador).
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

do $$
declare t text;
begin
  foreach t in array array['user_roles','assignments'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
  end loop;
end $$;
