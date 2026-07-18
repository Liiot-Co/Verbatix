-- DB v8 Fase 2, Tarea 5: rounds cuelga de projects/categories, no de studio.
-- Entorno dev sin datos reales que preservar (confirmado con el usuario) —
-- truncamos rounds (cascada) antes de forzar NOT NULL en project_id, ya que
-- no hay backfill posible desde studio_id.
truncate table rounds cascade;

alter table rounds add column project_id uuid references projects(id) on delete cascade;
alter table rounds add column category_id uuid references categories(id);
alter table rounds alter column project_id set not null;

alter table rounds drop constraint rounds_studio_id_round_number_key;
alter table rounds add constraint rounds_project_id_round_number_key unique (project_id, round_number);

alter table rounds drop column studio_id;
