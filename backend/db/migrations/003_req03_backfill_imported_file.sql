-- =====================================================================
-- VERBATIX — REQ-03: backfill de respondents.imported_file_id
-- =====================================================================
-- El esquema v9 (002_schema_v9.sql) agregó imported_file_id a respondents,
-- pero los encuestados importados antes de v9 quedaron con NULL. Decisión de
-- producto: si la ronda tiene UNA sola carga de verbatims registrada (el caso
-- real de HBG Leches, un único .dau), ese imported_file_id se asigna
-- automáticamente — no hay otra carga con la que confundirse. El NULL se
-- reserva para el caso genuinamente ambiguo (ronda con varias cargas
-- históricas sin trazabilidad), que la UI muestra como
-- "Carga original / sin registrar".
--
-- Idempotente: re-ejecutarla no toca filas ya asignadas.

update respondents r
   set imported_file_id = unica.id
  from (
    select f.round_id, min(f.id::text)::uuid as id
      from imported_files f
     where f.file_type in ('verbatims_xlsx', 'combined_xlsx', 'dau')
     group by f.round_id
    having count(*) = 1
  ) unica
 where r.round_id = unica.round_id
   and r.imported_file_id is null;
