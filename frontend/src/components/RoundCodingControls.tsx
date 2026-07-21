import type { CodingType } from "../api/types";
import SegmentedControl from "./SegmentedControl";

const CODING_LABELS: Record<CodingType, string> = {
  brands: "Marcas",
  reasons: "Razones",
};

const SINGLE_CODE_OPTIONS: { value: "yes" | "no"; label: string }[] = [
  { value: "yes", label: "Sí" },
  { value: "no", label: "No" },
];

export interface RoundCodingControlsValue {
  singleCodeByType: Partial<Record<CodingType, boolean>>;
  expectedMaxMentions: number | null;
  mentionsDecision: "process_all" | "limit_to_expected" | null;
}

interface RoundCodingControlsProps {
  codingTypes: CodingType[];
  value: RoundCodingControlsValue;
  onChange: (next: RoundCodingControlsValue) => void;
  /** Máximo de menciones detectado en el archivo (entre preguntas multi). */
  detectedMaxMentions: number;
}

/** Controles REQ-08/04 a nivel ronda: un interruptor por Marcas/Razones y un
 * máximo esperado general (no por question_id). */
export default function RoundCodingControls({
  codingTypes,
  value,
  onChange,
  detectedMaxMentions,
}: RoundCodingControlsProps) {
  const anyMulti = codingTypes.some((ct) => !(value.singleCodeByType[ct] ?? false));
  const expected = value.expectedMaxMentions;
  const needsDecision =
    anyMulti
    && typeof expected === "number"
    && expected > 0
    && detectedMaxMentions > expected
    && !value.mentionsDecision;

  const patch = (partial: Partial<RoundCodingControlsValue>) => {
    onChange({ ...value, ...partial });
  };

  return (
    <div className="space-y-2.5 rounded-xl border border-p-border bg-p-surface p-2.5">
      <div className="space-y-1.5">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-p-text-muted">
          Código único por respuesta
        </p>
        <p className="text-xs text-p-text-muted">
          Se pregunta una vez por tipo (Marcas / Razones), no por cada pregunta.
        </p>
        <div className="flex flex-wrap gap-3">
          {codingTypes.map((ct) => {
            const single = value.singleCodeByType[ct] ?? false;
            return (
              <div key={ct} className="space-y-1">
                <span className="text-xs font-medium text-p-text">{CODING_LABELS[ct]}</span>
                <SegmentedControl
                  name={`single-code-${ct}`}
                  options={SINGLE_CODE_OPTIONS}
                  value={single ? "yes" : "no"}
                  onChange={(v) => patch({
                    singleCodeByType: {
                      ...value.singleCodeByType,
                      [ct]: v === "yes",
                    },
                    mentionsDecision: null,
                  })}
                  ariaLabel={`Código único para ${CODING_LABELS[ct]}`}
                />
              </div>
            );
          })}
        </div>
      </div>

      {anyMulti && (
        <div className="space-y-1.5 border-t border-p-border pt-2">
          <div className="flex flex-nowrap items-center gap-2 text-xs text-p-text-muted">
            <span className="font-semibold uppercase tracking-wide whitespace-nowrap">Máx. menciones esperado (ronda)</span>
            <input
              type="number"
              min={1}
              className="input w-16 py-1 text-xs"
              aria-label="Máximo esperado de menciones para la ronda"
              value={expected ?? ""}
              placeholder="—"
              onChange={(e) => {
                const raw = e.target.value;
                patch({
                  expectedMaxMentions: raw === "" ? null : Number(raw),
                  mentionsDecision: null,
                });
              }}
            />
            {detectedMaxMentions > 0 && (
              <span className="text-[11px] text-p-text-faint whitespace-nowrap">
                Archivo detecta hasta {detectedMaxMentions}
              </span>
            )}
          </div>

          {needsDecision && (
            <div className="rounded-lg border border-p-warning/40 bg-p-warning/10 p-1.5 space-y-1">
              <p className="text-xs text-p-text-muted">
                Archivo trae hasta {detectedMaxMentions} menciones (esperado {expected}). ¿Qué hacemos?
              </p>
              <div className="flex gap-1">
                <button
                  type="button"
                  className="btn-secondary text-xs py-1 px-1.5"
                  onClick={() => patch({ mentionsDecision: "process_all" })}
                >
                  Procesar todas
                </button>
                <button
                  type="button"
                  className="btn-primary text-xs py-1 px-1.5"
                  onClick={() => patch({ mentionsDecision: "limit_to_expected" })}
                >
                  Limitar a {expected}
                </button>
              </div>
            </div>
          )}
          {value.mentionsDecision && (
            <p className="text-[10px] text-p-accent">
              {value.mentionsDecision === "process_all"
                ? `Decisión: procesar las ${detectedMaxMentions}`
                : `Decisión: limitar a ${expected}`}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export function hasPendingRoundMentionDecision(
  value: RoundCodingControlsValue,
  detectedMaxMentions: number,
  codingTypes: CodingType[],
): boolean {
  const anyMulti = codingTypes.some((ct) => !(value.singleCodeByType[ct] ?? false));
  if (!anyMulti) return false;
  const expected = value.expectedMaxMentions;
  if (typeof expected !== "number" || expected <= 0) return false;
  return detectedMaxMentions > expected && !value.mentionsDecision;
}

export function detectedMaxFromFields(
  fields: { detected_max_mentions?: number }[],
): number {
  return Math.max(0, ...fields.map((f) => f.detected_max_mentions ?? 0));
}
