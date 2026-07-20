-- =====================================================================
-- REQ-05: índices y soporte de cruce perfil ↔ Respondent ID
-- =====================================================================
-- Tablas profile_files / profile_entries y respondents.profile_status ya
-- existen en 002_schema_v9. Esta migración solo agrega índices útiles para
-- el cruce por respondent_external_id (Serial / Respondent ID) — NUNCA por
-- realid (eso es REQ-03/REQ-06).

create index if not exists profile_entries_serial_idx
  on profile_entries (profile_file_id, respondent_external_id);

create index if not exists respondents_profile_status_idx
  on respondents (round_id, profile_status);
