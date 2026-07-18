-- DB v8 Fase 2, Tarea 7: el libro de códigos sube de nivel Ronda a nivel
-- Estudio (project_id), compartido entre categorías/rondas — una Ronda 2
-- puede heredar el mismo libro sin reprocesarlo.
-- Entorno dev sin datos reales que preservar (confirmado con el usuario) —
-- truncamos codebooks (cascada) antes de forzar NOT NULL, ya que no hay
-- backfill posible desde round_id a project_id.
truncate table codebooks cascade;

alter table codebooks add column project_id uuid references projects(id) on delete cascade;
alter table codebooks add column coding_type text check (coding_type in ('brands','reasons'));
alter table codebooks alter column project_id set not null;
alter table codebooks alter column coding_type set not null;

alter table codebooks drop constraint codebooks_round_id_version_key;
alter table codebooks add constraint codebooks_project_id_coding_type_version_key
  unique (project_id, coding_type, version);

alter table codebooks drop column round_id;

alter table subprojects alter column codebook_id set not null;
