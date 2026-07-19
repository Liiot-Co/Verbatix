-- VERBATIX — autenticación local y RBAC acumulable
-- Incremental, transaccional e idempotente. Conserva todos los UUID y datos v8.
\set ON_ERROR_STOP on
begin;

-- users deja de depender operativamente de auth.users.
do $$
declare constraint_name text;
begin
  select c.conname into constraint_name
  from pg_constraint c
  join pg_class t on t.oid = c.conrelid
  join pg_class rt on rt.oid = c.confrelid
  join pg_namespace rn on rn.oid = rt.relnamespace
  where t.relname = 'users' and rn.nspname = 'auth' and rt.relname = 'users'
  limit 1;
  if constraint_name is not null then
    execute format('alter table public.users drop constraint %I', constraint_name);
  end if;
end $$;

alter table users add column if not exists password_hash text;
alter table users add column if not exists account_status text;
alter table users add column if not exists approved_by uuid references users(id);
alter table users add column if not exists approved_at timestamptz;
alter table users add column if not exists updated_at timestamptz not null default now();

update users set account_status = case when is_active then 'active' else 'suspended' end
where account_status is null;
alter table users alter column account_status set default 'pending';
alter table users alter column account_status set not null;
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'users_account_status_check') then
    alter table users add constraint users_account_status_check
      check (account_status in ('pending','active','suspended'));
  end if;
end $$;
create unique index if not exists users_email_lower_uidx on users (lower(btrim(email)));

alter table assignments alter column role_context drop not null;
alter table assignments add column if not exists revoked_at timestamptz;

create table if not exists auth_sessions (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references users(id) on delete cascade,
  token_hash  text not null unique,
  expires_at  timestamptz not null,
  revoked_at  timestamptz,
  created_at  timestamptz not null default now(),
  last_used_at timestamptz
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

create table if not exists audit_comments (
  id            uuid primary key default gen_random_uuid(),
  audit_item_id uuid not null references audit_items(id) on delete cascade,
  author_id     uuid references users(id) on delete set null,
  content       text not null check (length(btrim(content)) > 0),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  deleted_at    timestamptz
);
create index if not exists audit_comments_item_created_idx
  on audit_comments (audit_item_id, created_at);

insert into audit_comments (audit_item_id, author_id, content, created_at, updated_at)
select ai.id, ai.reviewer_id, ai.comment,
       coalesce(ai.reviewed_at, now()), coalesce(ai.reviewed_at, now())
from audit_items ai
where nullif(btrim(ai.comment), '') is not null
  and not exists (
    select 1 from audit_comments ac
    where ac.audit_item_id = ai.id and ac.content = ai.comment
  );

do $$
begin
  if not exists (select 1 from pg_trigger where tgname = 't_users') then
    create trigger t_users before update on users
      for each row execute function touch_updated_at();
  end if;
  if not exists (select 1 from pg_trigger where tgname = 't_audit_comments') then
    create trigger t_audit_comments before update on audit_comments
      for each row execute function touch_updated_at();
  end if;
end $$;

-- El usuario local preexistente sigue siendo el bootstrap y conserva su rol admin.
update users set account_status = 'active', approved_at = coalesce(approved_at, now())
where id = '00000000-0000-0000-0000-000000000001';

alter table auth_sessions enable row level security;
alter table password_recovery_codes enable row level security;
alter table audit_comments enable row level security;

commit;
