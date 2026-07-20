-- =====================================================================
-- REQ-08 / REQ-04: alcance por ronda / tipo (no por question_id)
-- =====================================================================
-- Código único se pregunta una vez por Marcas o Razones (subprojects).
-- Máximo esperado de menciones es de la ronda entera (rounds).
-- questions.single_code_per_response / expected_max_mentions quedan sin uso
-- nuevo (default schema); no se borran para no romper DBs existentes.

alter table rounds
  add column if not exists expected_max_mentions int;

alter table subprojects
  add column if not exists single_code_per_response boolean not null default false;
