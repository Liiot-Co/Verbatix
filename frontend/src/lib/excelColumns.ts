/** Heurística de columnas para Excel de verbatims (no aplica a .dau). */
export function guessExcelColumnMap(columns: string[]): {
  respondent_id?: string;
  verbatim?: string;
} {
  const normalized = columns.map((raw) => ({
    raw,
    low: raw.trim().toLowerCase(),
  }));
  const find = (...aliases: string[]) =>
    normalized.find((c) => aliases.includes(c.low))?.raw;

  return {
    respondent_id: find("respondent id", "serial", "respondent_id"),
    verbatim: find("verbatim"),
  };
}
