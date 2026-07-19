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
}

export default function FieldSelectionTable({ fields, value, onChange, showCodingType }: FieldSelectionTableProps) {
  const byField = new Map(value.map((fs) => [fs.field, fs]));

  const update = (field: string, patch: Partial<FieldSelection>) => {
    onChange(value.map((fs) => (fs.field === field ? { ...fs, ...patch } : fs)));
  };

  return (
    <div className="rounded-xl border border-p-border divide-y divide-p-border overflow-hidden">
      {fields.map((preview) => {
        const selection = byField.get(preview.field);
        if (!selection) return null;
        return (
          <div key={preview.field} className="flex items-start gap-3 px-3 py-2.5">
            <input
              type="checkbox"
              checked={selection.included}
              onChange={(e) => update(preview.field, { included: e.target.checked })}
              className="mt-1 h-4 w-4 rounded border-p-border-mid accent-p-accent"
              aria-label={`Incluir campo ${preview.field}`}
            />
            <div className="min-w-0 flex-1 space-y-1">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium text-p-text truncate">{preview.field}</span>
                {showCodingType && selection.included && (
                  <SegmentedControl
                    name={`coding-type-${preview.field}`}
                    options={CODING_OPTIONS}
                    value={selection.coding_type}
                    onChange={(coding_type) => update(preview.field, { coding_type })}
                    ariaLabel={`Tipo de clasificación para ${preview.field}`}
                  />
                )}
              </div>
              {preview.reason && <p className="text-xs text-p-text-muted">{preview.reason}</p>}
              {preview.sample_values.length > 0 && (
                <p className="text-xs text-p-text-faint truncate">Ej: {preview.sample_values.join(" · ")}</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Semilla inicial de FieldSelection[] a partir del preview del backend —
// pre-marca el segmentado con la sugerencia de .dau; Excel queda sin sugerencia.
export function initialFieldSelections(fields: FieldPreview[]): FieldSelection[] {
  return fields.map((f) => ({
    field: f.field,
    included: true,
    coding_type: f.suggested_coding_type,
  }));
}
