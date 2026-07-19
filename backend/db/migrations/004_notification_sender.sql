-- ---------------------------------------------------------------------
-- 9. NOTIFICACIONES: identidad de quien originó el evento
-- ---------------------------------------------------------------------
-- Nullable para conservar las notificaciones históricas, creadas antes de
-- guardar el remitente. Las nuevas emisiones siempre reciben `sender_id`.
alter table notifications
  add column if not exists sender_id uuid references users(id) on delete set null;

create index if not exists notifications_sender_idx on notifications (sender_id);
