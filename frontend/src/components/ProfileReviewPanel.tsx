import { useMemo, useState } from "react";
import { AlertTriangle, Check, Loader2, UserMinus, UserPlus } from "lucide-react";
import { resolveAllProfileForFile, resolveImportFlag } from "@/api/client";
import type { ProfileCandidateFlag, ProfileReviewSummary } from "@/api/types";
import { playSuccess, playTick } from "@/lib/sound";

type Props = {
  roundId: string;
  fileId: string;
  summary: ProfileReviewSummary | null;
  candidates: ProfileCandidateFlag[];
  onCandidatesChange: (next: ProfileCandidateFlag[]) => void;
  /** Called when every pending import-review flag reaches 0 (motor can start). */
  onAllResolved?: () => void;
  showToast: (message: string, kind?: "success" | "error" | "info") => void;
};

const TYPE_LABEL: Record<string, string> = {
  brands: "Marcas",
  reasons: "Razones",
};

/**
 * REQ-05 — cruce vs perfil + decisión masiva o por fila.
 * No borra registros: "excluir" marca excluded_confirmed (combinado) o
 * desengancha solo el tipo (split).
 */
export default function ProfileReviewPanel({
  roundId,
  fileId,
  summary,
  candidates,
  onCandidatesChange,
  onAllResolved,
  showToast,
}: Props) {
  const [busyAction, setBusyAction] = useState<"keep" | "remove" | string | null>(null);

  const pending = useMemo(
    () => candidates.filter((c) => c.status === "pending"),
    [candidates]
  );
  const pendingCount = pending.length;
  const hasProfile = Boolean(summary?.has_profile) || candidates.length > 0;
  const isSplit = summary?.mode === "split"
    || candidates.some((c) => c.coding_type === "brands" || c.coding_type === "reasons");

  const groups = useMemo(() => {
    if (!isSplit) {
      return [{ key: "all", label: null as string | null, items: candidates }];
    }
    const order = ["brands", "reasons", "other"] as const;
    const map: Record<string, ProfileCandidateFlag[]> = {
      brands: [],
      reasons: [],
      other: [],
    };
    for (const c of candidates) {
      if (c.coding_type === "brands") map.brands!.push(c);
      else if (c.coding_type === "reasons") map.reasons!.push(c);
      else map.other!.push(c);
    }
    return order
      .filter((k) => map[k]!.length > 0)
      .map((k) => ({
        key: k,
        label: k === "other" ? "Sin tipo" : TYPE_LABEL[k],
        items: map[k]!,
      }));
  }, [candidates, isSplit]);

  if (!hasProfile) return null;

  const applyStatuses = (ids: Set<string>, status: ProfileCandidateFlag["status"]) => {
    onCandidatesChange(
      candidates.map((c) => (ids.has(c.flag_id) ? { ...c, status } : c))
    );
  };

  const resolveOne = async (
    flag: ProfileCandidateFlag,
    action: "keep" | "remove",
  ) => {
    if (busyAction || flag.status !== "pending") return;
    setBusyAction(flag.flag_id);
    try {
      const result = await resolveImportFlag(flag.flag_id, action);
      applyStatuses(new Set([flag.flag_id]), result.status);
      playTick();
      if (result.pending_flags === 0) {
        playSuccess();
        onAllResolved?.();
      }
    } catch {
      showToast("No se pudo resolver la decisión.", "error");
    } finally {
      setBusyAction(null);
    }
  };

  const resolveAll = async (action: "keep" | "remove") => {
    if (busyAction || pendingCount === 0) return;
    setBusyAction(action);
    const targetStatus = action === "keep" ? "approved_keep" : "approved_remove";
    const pendingIds = new Set(pending.map((p) => p.flag_id));
    try {
      const result = await resolveAllProfileForFile(roundId, fileId, action);
      applyStatuses(pendingIds, targetStatus);
      playSuccess();
      showToast(
        action === "keep"
          ? `Se mantienen ${result.resolved || pendingCount} en el procesamiento.`
          : `Se excluyen ${result.resolved || pendingCount} del procesamiento (registros conservados).`,
        "success",
      );
      if (result.pending_flags === 0) {
        onAllResolved?.();
      }
    } catch (err) {
      showToast(
        err instanceof Error ? err.message : "No se pudieron aplicar las decisiones.",
        "error",
      );
    } finally {
      setBusyAction(null);
    }
  };

  const expected = summary?.expected ?? 0;
  const arrived = summary?.arrived ?? 0;
  const extra = summary?.extra ?? pendingCount;

  return (
    <section className="overflow-hidden rounded-2xl border border-p-border bg-p-surface shadow-sm">
      <div className="border-b border-p-border bg-gradient-to-br from-p-warning/10 via-p-bg-subtle to-transparent px-4 py-3.5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-p-warning/15 text-p-warning">
                <AlertTriangle className="h-4 w-4" />
              </span>
              <div>
                <h2 className="text-sm font-semibold text-p-text tracking-tight">
                  Cruce con perfil
                </h2>
                <p className="text-[11px] text-p-text-muted">
                  Calza por Respondent ID o realid · nada se borra
                  {isSplit ? " · exclusión por tipo (Marcas / Razones)" : ""}
                </p>
              </div>
            </div>
          </div>
          <span
            className={
              pendingCount > 0 ? "badge-warning shrink-0" : "badge-success shrink-0"
            }
          >
            {pendingCount > 0 ? `${pendingCount} por decidir` : "Listo"}
          </span>
        </div>

        <div className="mt-3 grid grid-cols-3 gap-2">
          <Stat label="IDs en perfil" value={expected} tone="neutral" />
          <Stat label="IDs en data" value={arrived} tone="neutral" />
          <Stat label="IDs de más" value={extra} tone={extra > 0 ? "warn" : "ok"} />
        </div>

        <p className="mt-2.5 text-xs text-p-text-muted leading-relaxed">
          {summary?.summary
            ?? `El perfil tiene ${expected} IDs; en la data hay ${arrived}; ${extra} no están en el perfil.`}
        </p>
      </div>

      <div className="px-4 py-3 space-y-3">
        {candidates.length === 0 ? (
          <div className="flex items-center gap-2 rounded-xl border border-p-success/25 bg-p-success/5 px-3 py-2.5 text-sm text-p-text">
            <Check className="h-4 w-4 text-p-success shrink-0" />
            Todos los IDs calzan con el perfil.
          </div>
        ) : (
          <>
            {pendingCount > 0 && (
              <div className="flex flex-col sm:flex-row gap-2">
                <button
                  type="button"
                  className="btn-primary text-sm py-2.5 flex-1 justify-center gap-2"
                  disabled={Boolean(busyAction)}
                  onClick={() => void resolveAll("keep")}
                >
                  {busyAction === "keep" ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <UserPlus className="h-4 w-4" />
                  )}
                  Mantener todos ({pendingCount})
                </button>
                <button
                  type="button"
                  className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl border border-p-error/35 bg-p-error/5 px-3 py-2.5 text-sm font-medium text-p-error hover:bg-p-error/10 transition-colors disabled:opacity-50"
                  disabled={Boolean(busyAction)}
                  onClick={() => void resolveAll("remove")}
                >
                  {busyAction === "remove" ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <UserMinus className="h-4 w-4" />
                  )}
                  Excluir todos ({pendingCount})
                </button>
              </div>
            )}

            <p className="text-[11px] text-p-text-faint">
              O decide uno por uno si hace falta una excepción.
            </p>

            {groups.map((group) => (
              <div key={group.key} className="space-y-1.5">
                {group.label && (
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-p-text-muted px-0.5">
                    {group.label}
                    {" · "}
                    {group.items!.filter((i) => i.status === "pending").length} pendientes
                  </div>
                )}
                <div className="max-h-64 overflow-y-auto rounded-xl border border-p-border divide-y divide-p-border">
                  {group.items!.map((flag) => {
                    const isPending = flag.status === "pending";
                    const rowBusy = busyAction === flag.flag_id;
                    return (
                      <div
                        key={flag.flag_id}
                        className="flex items-center justify-between gap-3 px-3 py-2.5 bg-p-bg-subtle/40 hover:bg-p-bg-subtle/80 transition-colors"
                      >
                        <div className="min-w-0">
                          <div className="text-xs font-semibold text-p-text truncate">
                            {flag.serial
                              ? `Respondent ID ${flag.serial}`
                              : `realid ${flag.realid ?? "—"}`}
                          </div>
                          <div className="text-[10px] text-p-text-faint font-mono truncate">
                            {flag.serial && flag.realid
                              ? `realid ${flag.realid}`
                              : flag.serial
                                ? "sin realid"
                                : "sin Respondent ID"}
                          </div>
                        </div>
                        {!isPending ? (
                          <span
                            className={
                              flag.status === "approved_remove"
                                ? "badge-pending shrink-0"
                                : "badge-success shrink-0"
                            }
                          >
                            {flag.status === "approved_keep"
                              ? "Se mantiene"
                              : flag.status === "approved_remove"
                                ? "Excluido"
                                : flag.status}
                          </span>
                        ) : (
                          <div className="flex items-center gap-1 shrink-0">
                            <button
                              type="button"
                              className="btn-ghost text-[11px] py-1 px-2"
                              disabled={Boolean(busyAction)}
                              onClick={() => void resolveOne(flag, "keep")}
                            >
                              {rowBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : "Mantener"}
                            </button>
                            <button
                              type="button"
                              className="text-[11px] py-1 px-2 rounded-lg text-p-error hover:bg-p-error/10 disabled:opacity-50"
                              disabled={Boolean(busyAction)}
                              onClick={() => void resolveOne(flag, "remove")}
                            >
                              Excluir
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </>
        )}
      </div>
    </section>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "neutral" | "warn" | "ok";
}) {
  const valueClass =
    tone === "warn"
      ? "text-p-warning"
      : tone === "ok"
        ? "text-p-success"
        : "text-p-text";
  return (
    <div className="rounded-xl border border-p-border/80 bg-p-surface/80 px-2.5 py-2 text-center">
      <div className={`text-lg font-semibold tabular-nums tracking-tight ${valueClass}`}>
        {value}
      </div>
      <div className="text-[10px] uppercase tracking-wide text-p-text-faint font-medium">
        {label}
      </div>
    </div>
  );
}
