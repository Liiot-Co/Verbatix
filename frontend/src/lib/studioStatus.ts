// Studio.status values (backend/db/migrations/001_schema_v5.sql) are English
// snake_case for the DB/API — never render them raw, map through here.
export const STUDIO_STATUS_LABELS: Record<string, string> = {
  created: "Creado",
  files_uploaded: "Archivo cargado",
  processing: "Procesando",
  preliminary_ready: "Preliminar listo",
  manual_coding: "Codificación manual",
  audit_pending: "Auditoría pendiente",
  audit_approved: "Auditoría aprobada",
  nets_review: "Revisión de nets",
  ready_to_export: "Listo para exportar",
  completed: "Completado",
  failed: "Falló",
};

export const STUDIO_STATUS_TONE: Record<string, string> = {
  created: "text-p-text-faint bg-p-bg-subtle border-p-border",
  files_uploaded: "text-p-accent bg-p-accent-soft border-p-accent/20",
  processing: "text-p-accent bg-p-accent-soft border-p-accent/20",
  preliminary_ready: "text-p-accent bg-p-accent-soft border-p-accent/20",
  manual_coding: "text-p-accent bg-p-accent-soft border-p-accent/20",
  audit_pending: "text-p-accent bg-p-accent-soft border-p-accent/20",
  audit_approved: "text-p-success bg-p-success/10 border-p-success/20",
  nets_review: "text-p-accent bg-p-accent-soft border-p-accent/20",
  ready_to_export: "text-p-success bg-p-success/10 border-p-success/20",
  completed: "text-p-success bg-p-success/10 border-p-success/20",
  failed: "text-p-error bg-p-error/10 border-p-error/20",
};

export function studioStatusLabel(status: string): string {
  return STUDIO_STATUS_LABELS[status] ?? status;
}
