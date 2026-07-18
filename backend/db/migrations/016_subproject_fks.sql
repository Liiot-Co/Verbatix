-- DB v8 Fase 3, Tarea 10 (checkpoint final): mention_groups, processing_runs,
-- audit_sessions y export_files cuelgan de subproject_id en vez de round_id
-- — el motor/auditoría/exportación corren por Marcas o por Razones por
-- separado, no por la ronda completa. imported_files y export_jobs se
-- quedan en round_id (confirmado en el documento v8, sección 2.4 y diagrama).
--
-- Con esta migración termina el prerrequisito de esquema DB v8: la
-- jerarquía `proyectos -> projects -> [categories] -> rounds -> subprojects`
-- queda completa en models.py + migraciones SQL. `repositories.py`
-- (referencias a Studio/studio_id), el pipeline (DAU/Excel/fuzzy, que
-- asume round_id en mention_groups/verbatims) y el frontend quedan ROTOS
-- deliberadamente — es un prerrequisito de esquema, no una entrega
-- funcional. El siguiente requerimiento debe tomar esto como punto de
-- partida conocido.

-- mention_groups
truncate table mention_groups cascade;
alter table mention_groups add column subproject_id uuid references subprojects(id) on delete cascade;
alter table mention_groups alter column subproject_id set not null;
alter table mention_groups drop constraint mention_groups_round_id_normalized_text_key;
alter table mention_groups add constraint mention_groups_subproject_id_normalized_text_key
  unique (subproject_id, normalized_text);
drop index if exists mention_groups_round_id_status_idx;
alter table mention_groups drop column round_id;
create index on mention_groups (subproject_id, status);

-- processing_runs
truncate table processing_runs cascade;
alter table processing_runs add column subproject_id uuid references subprojects(id) on delete cascade;
alter table processing_runs alter column subproject_id set not null;
drop index if exists processing_runs_round_id_created_at_idx;
alter table processing_runs drop column round_id;
create index on processing_runs (subproject_id, created_at desc);

-- audit_sessions
truncate table audit_sessions cascade;
alter table audit_sessions add column subproject_id uuid references subprojects(id) on delete cascade;
alter table audit_sessions alter column subproject_id set not null;
alter table audit_sessions drop column round_id;

-- export_files: conserva round_id (nullable, como en v5), solo agrega la
-- relación desde subprojects (nullable) — el diagrama no invalida rounds.
alter table export_files add column subproject_id uuid references subprojects(id);
