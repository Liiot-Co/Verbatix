-- =====================================================================
-- VERBATIX — MIGRACIÓN 003: UMBRALES A NIVEL DE RONDA
-- =====================================================================
-- min_mentions_threshold y audit_percentage vivían en studio, pero
-- conceptualmente aplican a la ronda completa (todos los estudios de
-- una misma ronda comparten la misma ola de datos). Se mueven a rounds.
-- =====================================================================

alter table rounds
  add column min_mentions_threshold int not null default 3,
  add column audit_percentage numeric(5,2) not null default 10;

update rounds r
  set min_mentions_threshold = s.min_mentions_threshold,
      audit_percentage = s.audit_percentage
  from studio s
  where s.round_id = r.id and s.id = (
    select id from studio where round_id = r.id order by created_at limit 1
  );

alter table studio
  drop column min_mentions_threshold,
  drop column audit_percentage;
