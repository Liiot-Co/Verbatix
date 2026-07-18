-- DB v8 Fase 3, Tarea 9: verbatims cuelga de subproject_id (no round_id),
-- usa la nueva tabla respondents, y se enlaza a questions.
-- Entorno dev sin datos reales que preservar (confirmado con el usuario) —
-- truncamos verbatims antes de forzar NOT NULL en subproject_id, ya que no
-- hay backfill posible desde round_id (una ronda puede tener 1+ subprojects).
truncate table verbatims cascade;

alter table verbatims add column subproject_id uuid references subprojects(id) on delete cascade;
alter table verbatims add column respondent_id uuid references respondents(id);
alter table verbatims add column question_id uuid references questions(id);
alter table verbatims rename column question_key to source_question_key;

alter table verbatims alter column subproject_id set not null;

alter table verbatims drop constraint verbatims_round_id_respondent_external_id_question_key_key;
alter table verbatims drop column round_id;
alter table verbatims drop column respondent_external_id;

alter table verbatims add constraint verbatims_subproject_id_respondent_id_source_question_key_key
  unique (subproject_id, respondent_id, source_question_key);
