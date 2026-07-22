/** Heurística de columnas para Excel de verbatims (no aplica a .dau). */
export function guessExcelColumnMap(columns: string[]): {
  respondent_id?: string;
  verbatim?: string;
  brands?: string;
  reasons?: string;
} {
  const normalized = columns.map((raw) => ({
    raw,
    low: raw.trim().toLowerCase(),
  }));
  const find = (...aliases: string[]) =>
    normalized.find((c) => aliases.includes(c.low))?.raw;

  const respondentId = find("respondent id", "serial", "respondent_id");
  const verbatim = find("verbatim");
  const brands = find("brands", "marcas");
  const reasons = find("reasons", "razones");

  return {
    ...(respondentId !== undefined ? { respondent_id: respondentId } : {}),
    ...(verbatim !== undefined ? { verbatim } : {}),
    ...(brands !== undefined ? { brands } : {}),
    ...(reasons !== undefined ? { reasons } : {}),
  };
}
