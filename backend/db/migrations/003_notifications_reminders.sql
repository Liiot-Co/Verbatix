-- ---------------------------------------------------------------------
-- 8. NOTIFICACIONES: recordatorios de no leídas (aditivo e idempotente)
-- ---------------------------------------------------------------------
-- `notifications` nació en 002. Estos dos campos conservan el estado mínimo
-- para espaciar recordatorios y para que el cliente pueda detectar un push.
alter table notifications
  add column if not exists last_reminded_at timestamptz,
  add column if not exists reminder_count smallint not null default 0;

create index if not exists notifications_unread_created_idx
  on notifications (created_at) where is_read = false;
