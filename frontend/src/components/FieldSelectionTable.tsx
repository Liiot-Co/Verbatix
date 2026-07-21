import type { CodingType, FieldPreview, FieldSelection } from "../api/types";
import SegmentedControl from "./SegmentedControl";

const CODING_OPTIONS: { value: CodingType; label: string }[] = [
  { value: "brands", label: "Marcas" },
  { value: "reasons", label: "Razones" },
];

interface FieldSelectionTableProps {
  fields: FieldPreview[];
  value: FieldSelection[];
  onChange: (next: FieldSelection[]) => void;
  // true solo cuando el codingScope de la ronda es "both" — con scope único,
  // el campo hereda el tipo de la ronda sin preguntar (sin segmentado).
  showCodingType: boolean;
  // Excel: sus filas ya traen question_key desde la columna "Question ID"
  // del sheet, no desde el nombre de columna — un checkbox/segmentado por
  // columna no correspondería a nada real en el import. Solo se muestra la
  // muestra de valores, sin controles.
  readOnly?: boolean;
}

export default function FieldSelectionTable({
  fields, value, onChange, showCodingType, readOnly = false,
}: FieldSelectionTableProps) {
  const byField = new Map(value.map((fs) => [fs.field, fs]));

  const update = (field: string, patch: Partial<FieldSelection>) => {
    onChange(value.map((fs) => (fs.field === field ? { ...fs, ...patch } : fs)));
  };

  const showTypeColumn = !readOnly && showCodingType;

  return (
    <div className="rounded-xl border border-p-border overflow-hidden">
      <div className="max-h-80 overflow-y-auto">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 z-10 bg-p-surface">
            <tr className="border-b border-p-border text-[11px] font-semibold uppercase tracking-wide text-p-text-muted">
              {!readOnly && (
                <th scope="col" className="w-9 px-3 py-2 text-left">
                  <span className="sr-only">Incluir</span>
                </th>
              )}
              <th scope="col" className="px-3 py-2 text-left">Campo</th>
              {showTypeColumn && <th scope="col" className="w-40 px-3 py-2 text-left">Tipo</th>}
              <th scope="col" className="px-3 py-2 text-left">Muestra de valores</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-p-border">
            {fields.map((preview) => {
              const selection = byField.get(preview.field);
              if (!readOnly && !selection) return null;

              return (
                <tr key={preview.field} className="align-top">
                  {!readOnly && selection && (
                    <td className="px-3 py-2.5">
                      <input
                        id={`field-${preview.field}`}
                        type="checkbox"
                        checked={selection.included}
                        onChange={(e) => update(preview.field, { included: e.target.checked })}
                        className="mt-0.5 h-4 w-4 cursor-pointer rounded border-p-border-mid accent-p-accent"
                        aria-label={`Incluir campo ${preview.field}`}
                      />
                    </td>
                  )}
                  <td className="min-w-0 max-w-[14rem] px-3 py-2.5">
                    <label htmlFor={`field-${preview.field}`} className="block truncate text-sm font-medium text-p-text cursor-pointer select-none" title={preview.field}>
                      {preview.field}
                    </label>
                  </td>
                  {showTypeColumn && (
                    <td className="px-3 py-2.5">
                      {selection && selection.included && (
                        <SegmentedControl
                          name={`coding-type-${preview.field}`}
                          options={CODING_OPTIONS}
                          value={selection.coding_type}
                          onChange={(coding_type) => update(preview.field, { coding_type })}
                          ariaLabel={`Tipo de clasificación para ${preview.field}`}
                        />
                      )}
                    </td>
                  )}
                  <td className="px-3 py-2.5">
                    {preview.sample_values.length > 0 ? (
                      <div className="flex flex-wrap gap-1.5">
                        {preview.sample_values.map((sample, i) => (
                          <span
                            key={i}
                            title={sample}
                            className="max-w-[14rem] truncate rounded-md bg-p-bg-subtle border border-p-border/60 px-2 py-0.5 text-xs text-p-text-muted"
                          >
                            {sample}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-xs text-p-text-faint italic">Sin datos</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function initialFieldSelections(fields: FieldPreview[]): FieldSelection[] {
  return fields.map((f) => ({
    field: f.field,
    included: true,
    coding_type: f.suggested_coding_type,
  }));
}
