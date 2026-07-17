-- Permite el file_type 'dau' (export crudo Ascribe/IBM MDM) en imported_files,
-- para importar por el mismo input que .xlsx (REQ-01).
alter table imported_files drop constraint if exists imported_files_file_type_check;

alter table imported_files add constraint imported_files_file_type_check
  check (file_type in ('verbatims_xlsx','codebook_xlsx','combined_xlsx','dau'));
