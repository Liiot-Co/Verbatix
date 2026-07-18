import type { CodingType, RoundSummary } from "@/api/types";

/** Label de tipo para UI: "Marcas" | "Razones". */
export function codingTypeLabel(codingType: CodingType): string {
  return codingType === "brands" ? "Marcas" : "Razones";
}

/**
 * Nombre a mostrar: si el estudio quedó con el default "Marcas"/"Razones"
 * desalineado del tipo real, prioriza el coding_type.
 */
export function studyDisplayName(name: string, codingType: CodingType): string {
  if (name === "Marcas" || name === "Razones") return codingTypeLabel(codingType);
  return name;
}

/** Sustantivo singular para copy del centro de resolución / auditoría. */
export function codingTypeNoun(codingType: CodingType): string {
  return codingType === "reasons" ? "razón" : "marca";
}

export function nextRoundNumber(rounds: RoundSummary[]): number {
  if (rounds.length === 0) return 1;
  return Math.max(...rounds.map((r) => r.round_number)) + 1;
}

/** Estados con preliminar procesado — el reporte es consultable. */
const REPORT_ACCESS_STATUSES = new Set([
  "preliminary_ready",
  "manual_coding",
  "audit_pending",
  "audit_approved",
  "nets_review",
  "ready_to_export",
  "completed",
]);

/** Tras resolución manual completa, el reporte es la fase principal. */
const REPORT_PRIMARY_STATUSES = new Set([
  "audit_pending",
  "audit_approved",
  "nets_review",
  "ready_to_export",
  "completed",
]);

export function hasReportAccess(status: string): boolean {
  return REPORT_ACCESS_STATUSES.has(status);
}

/** Ruta de la fase actual de una ronda. */
export function roundPhasePath(roundId: string, status: string): string {
  if (REPORT_PRIMARY_STATUSES.has(status)) return `/rounds/${roundId}/report`;
  return `/rounds/${roundId}`;
}
