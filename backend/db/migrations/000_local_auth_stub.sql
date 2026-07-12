-- =====================================================================
-- LOCAL-ONLY: stub de auth.users
-- =====================================================================
-- profiles.id referencia auth.users(id), que en Supabase gestiona el
-- servicio de Auth. Localmente no existe ese servicio, así que este
-- stub crea lo mínimo para que la FK no rompa, y siembra el dev user
-- fijo que usa app.core.auth en app_mode=local (Settings.local_dev_user_id).
--
-- NO correr contra Supabase: ese proyecto ya tiene un auth.users real.
-- =====================================================================

create schema if not exists auth;

create table if not exists auth.users (
  id uuid primary key
);

insert into auth.users (id)
values ('00000000-0000-0000-0000-000000000001')
on conflict (id) do nothing;

-- 001_schema_v5.sql revokes grants from these Supabase platform roles
-- (RLS setup); plain Postgres doesn't have them.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated;
  end if;
end $$;
