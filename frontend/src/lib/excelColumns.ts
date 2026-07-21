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

  const respondentId = find("respondent id", "serial", "respondent_id");
  const verbatim = find("verbatim");

  return {
    ...(respondentId !== undefined ? { respondent_id: respondentId } : {}),
    ...(verbatim !== undefined ? { verbatim } : {}),
  };
}
