import { useEffect, useMemo, useState } from "react";
import { BookCheck, Check, Loader2, X } from "lucide-react";

import { approveCodebookDraft, getCodebookDraft } from "@/api/client";
import type { CodebookDraft, CodebookDraftDecision } from "@/api/types";
import { useVerbatixStore } from "@/store/useVerbatixStore";

interface Props {
  subprojectId: string;
  onApproved: (readyToProcess: boolean) => Promise<void> | void;
}

export default function CodebookDraftReview({ subprojectId, onApproved }: Props) {
  const showToast = useVerbatixStore((state) => state.showToast);
  const [draft, setDraft] = useState<CodebookDraft | null>(null);
  const [decisions, setDecisions] = useState<Record<string, CodebookDraftDecision>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setLoading(true);
    getCodebookDraft(subprojectId)
      .then((result) => {
        setDraft(result);
        setDecisions(Object.fromEntries(
          result.codes
            .filter((code) => !code.is_system && code.approval_status === "pending")
            .map((code) => [code.id, {
              code_id: code.id,
              decision: "approve" as const,
              label: code.label,
              net_name: code.net_name,
              definition: code.definition,
              inclusion_criteria: code.inclusion_criteria,
              exclusion_criteria: code.exclusion_criteria,
              examples: code.examples,
            }]),
        ));
      })
      .catch(() => showToast("No se pudo cargar la propuesta del libro", "error"))
      .finally(() => setLoading(false));
  }, [showToast, subprojectId]);

  const pending = useMemo(
    () => draft?.codes.filter((code) => !code.is_system && code.approval_status === "pending") ?? [],
    [draft],
  );
  const approvedCount = Object.values(decisions).filter((item) => item.decision === "approve").length;

  const patch = (id: string, values: Partial<CodebookDraftDecision>) => {
    setDecisions((current) => {
      const existing = current[id];
      return existing ? { ...current, [id]: { ...existing, ...values } } : current;
    });
  };

  const submit = async () => {
    if (!pending.length || approvedCount === 0) return;
    setSaving(true);
    try {
      const result = await approveCodebookDraft(subprojectId, Object.values(decisions));
      showToast(
        result.ready_to_process
          ? "Libro aprobado. La clasificación continúa automáticamente."
          : "Libro aprobado. Falta revisar el otro subproyecto.",
        "success",
      );
      await onApproved(result.ready_to_process);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "No se pudo aprobar el libro", "error");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="card p-8 flex items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-p-accent" /></div>;
  }
  if (!draft || !pending.length) return null;

  return (
    <section className="card p-5 space-y-4 border-p-warning/30">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2"><BookCheck className="h-5 w-5 text-p-accent" /><h2 className="font-heading font-semibold text-p-text">Revisar propuesta del libro</h2></div>
          <p className="mt-1 text-xs text-p-text-muted">{draft.coding_type === "brands" ? "Marcas" : "Razones"}: {pending.length} categorías candidatas, ordenadas por impacto. Puedes renombrar o rechazar antes de clasificar.</p>
        </div>
        <button type="button" className="btn-primary justify-center" disabled={saving || approvedCount === 0} onClick={() => void submit()}>
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
          Aprobar {approvedCount} categoría{approvedCount === 1 ? "" : "s"}
        </button>
      </div>

      <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
        {pending.map((code) => {
          const decision = decisions[code.id];
          const accepted = decision?.decision === "approve";
          return (
            <article key={code.id} className={`rounded-xl border p-4 ${accepted ? "border-p-border bg-p-surface" : "border-p-error/25 bg-p-error/5"}`}>
              <div className="flex items-start gap-3">
                <button type="button" onClick={() => patch(code.id, { decision: accepted ? "reject" : "approve" })} className={`mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${accepted ? "bg-p-success text-white" : "bg-p-error/15 text-p-error"}`} aria-label={accepted ? "Rechazar categoría" : "Aprobar categoría"}>
                  {accepted ? <Check className="h-3.5 w-3.5" /> : <X className="h-3.5 w-3.5" />}
                </button>
                <div className="min-w-0 flex-1 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="chip text-[10px]">Código {code.code_number}</span>
                    <span className="text-xs text-p-text-muted">{code.mentions} menciones · {code.mention_groups} formas</span>
                  </div>
                  <input className="input w-full font-medium" value={decision?.label ?? code.label} disabled={!accepted} onChange={(event) => patch(code.id, { label: event.target.value })} aria-label={`Nombre de categoría ${code.code_number}`} />
                  {draft.coding_type === "reasons" ? (
                    <input className="input w-full text-xs" value={decision?.net_name ?? ""} disabled={!accepted} placeholder="Neto temático" onChange={(event) => patch(code.id, { net_name: event.target.value || null })} aria-label={`Neto de categoría ${code.code_number}`} />
                  ) : null}
                  <textarea className="input w-full min-h-16 text-xs" value={decision?.definition ?? ""} disabled={!accepted} placeholder="Definición operativa" onChange={(event) => patch(code.id, { definition: event.target.value || null })} />
                  <textarea className="input w-full min-h-16 text-xs" value={(decision?.inclusion_criteria ?? []).join("\n")} disabled={!accepted} placeholder="Criterios de inclusión, uno por línea" onChange={(event) => patch(code.id, { inclusion_criteria: event.target.value.split("\n").map((value) => value.trim()).filter(Boolean) })} />
                  <textarea className="input w-full min-h-16 text-xs" value={(decision?.exclusion_criteria ?? []).join("\n")} disabled={!accepted} placeholder="Criterios de exclusión, uno por línea" onChange={(event) => patch(code.id, { exclusion_criteria: event.target.value.split("\n").map((value) => value.trim()).filter(Boolean) })} />
                  <div className="flex flex-wrap gap-1.5">
                    {code.groups.slice(0, 8).map((group) => <span key={group.id} className="chip text-[10px]" title={`${group.frequency} menciones`}>{group.text || group.normalized_text} · {group.frequency}</span>)}
                  </div>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
