-- ---------------------------------------------------------------------
-- 10. PRESENCIA DECLARADA: estado actual + historial para futuros tiempos
-- ---------------------------------------------------------------------
-- No reutiliza session_status/last_activity_at (REQ-16): este dato expresa
-- lo que la persona declara estar haciendo, incluso con la sesión activa.
alter table users
  add column if not exists presence_status text not null default 'disponible',
  add column if not exists presence_changed_at timestamptz;

create table if not exists user_status_events (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references users(id) on delete cascade,
  status     text not null,
  started_at timestamptz not null default now(),
  ended_at   timestamptz
);

create index if not exists user_status_events_user_started_idx
  on user_status_events (user_id, started_at desc);
