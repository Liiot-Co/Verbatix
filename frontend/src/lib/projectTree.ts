import type { CodingType, ProjectDetail, RoundSummary, StudioSummary } from "@/api/types";

/** One studio instance tied to a specific round. */
export interface StudyRoundEntry {
  round_id: string;
  round_name: string;
  round_number: number;
  round_status: string;
  studio: StudioSummary;
}

/** Logical study (Marcas / Razones) spanning multiple rounds. */
export interface StudyGroup {
  key: string;
  name: string;
  coding_type: CodingType;
  rounds: StudyRoundEntry[];
}

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

export function studyKey(codingType: CodingType, name: string): string {
  return `${codingType}--${encodeURIComponent(name.trim())}`;
}

export function parseStudyKey(key: string): { coding_type: CodingType; name: string } | null {
  const sep = key.indexOf("--");
  if (sep <= 0) return null;
  const coding_type = key.slice(0, sep) as CodingType;
  if (coding_type !== "brands" && coding_type !== "reasons") return null;
  return { coding_type, name: decodeURIComponent(key.slice(sep + 2)) };
}

/** Flatten project.rounds[] into study-first groups for navigation. */
export function groupProjectByStudies(project: ProjectDetail): StudyGroup[] {
  const map = new Map<string, StudyGroup>();

  for (const round of project.rounds) {
    for (const studio of round.studios) {
      const key = studyKey(studio.coding_type, studio.name);
      let group = map.get(key);
      if (!group) {
        group = { key, name: studio.name, coding_type: studio.coding_type, rounds: [] };
        map.set(key, group);
      }
      group.rounds.push({
        round_id: round.id,
        round_name: round.name,
        round_number: round.round_number,
        round_status: round.status,
        studio,
      });
    }
  }

  for (const group of map.values()) {
    group.rounds.sort((a, b) => a.round_number - b.round_number);
  }

  const order: CodingType[] = ["brands", "reasons"];
  return [...map.values()].sort((a, b) => {
    const ti = order.indexOf(a.coding_type) - order.indexOf(b.coding_type);
    if (ti !== 0) return ti;
    return a.name.localeCompare(b.name, "es");
  });
}

export function countStudies(project: ProjectDetail): number {
  return groupProjectByStudies(project).length;
}

export function nextRoundNumber(rounds: RoundSummary[]): number {
  if (rounds.length === 0) return 1;
  return Math.max(...rounds.map((r) => r.round_number)) + 1;
}

export function findStudyGroup(project: ProjectDetail, key: string): StudyGroup | undefined {
  const groups = groupProjectByStudies(project);
  const exact = groups.find((g) => g.key === key);
  if (exact) return exact;

  // useParams puede devolver el segmento ya decodificado (%20 → espacio),
  // mientras groupProjectByStudies guarda la key con encodeURIComponent.
  const parsed = parseStudyKey(key);
  if (!parsed) return undefined;
  return groups.find(
    (g) => g.coding_type === parsed.coding_type && g.name === parsed.name
  );
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
export function studioPhasePath(studioId: string, status: string): string {
  if (REPORT_PRIMARY_STATUSES.has(status)) return `/studios/${studioId}/report`;
  return `/studios/${studioId}`;
}
