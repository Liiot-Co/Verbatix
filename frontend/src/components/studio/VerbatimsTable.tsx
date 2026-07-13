import { Sparkles, Bot, UserCheck, Clock, AlertTriangle, HelpCircle, type LucideIcon } from "lucide-react";
import type { CodingStatus, Verbatim, VerbatimCode } from "@/api/types";

export function engineLabel(code: VerbatimCode): { text: string; icon: typeof Sparkles } {
  if (code.source === "analyst_manual" || code.source === "audit_correction")
    return { text: "Manual", icon: UserCheck };
  if (code.source === "homologation")
    return { text: "Homologado", icon: UserCheck };
  if (code.confidence_score != null)
    return { text: `Fuzzy ${Math.round(code.confidence_score * 100)}%`, icon: Sparkles };
  return { text: "LLM", icon: Bot };
}

export const STATUS_BADGE: Record<string, string> = {
  pending: "badge-pending",
  auto_coded: "badge-auto",
  needs_review: "badge-warning",
  manually_coded: "badge-manual",
  unknown: "badge-error",
};

export const STATUS_LABELS: Record<CodingStatus, string> = {
  pending: "Pendiente",
  auto_coded: "Auto-codificado",
  needs_review: "Necesita revisión",
  manually_coded: "Codificado a mano",
  unknown: "Desconocida",
};

export const STATUS_ICON: Record<CodingStatus, LucideIcon> = {
  pending: Clock,
  auto_coded: Sparkles,
  needs_review: AlertTriangle,
  manually_coded: UserCheck,
  unknown: HelpCircle,
};

interface VerbatimsTableProps {
  loading: boolean;
  verbatims: Verbatim[];
  search: string;
}

export function VerbatimsTable({ loading, verbatims, search }: VerbatimsTableProps) {
  return (
    <div className="card overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-p-border text-left">
            <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">Respondent</th>
            <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">Verbatim</th>
            <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">Código</th>
            <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">Estado</th>
          </tr>
        </thead>
        <tbody>
          {loading ? (
            Array.from({ length: 6 }).map((_, i) => (
              <tr key={`skeleton-${i}`} className="border-b border-p-border last:border-0">
                <td className="px-4 py-2.5"><div className="skeleton h-3 w-10 rounded" /></td>
                <td className="px-4 py-2.5"><div className="skeleton h-3 w-3/4 rounded" /></td>
                <td className="px-4 py-2.5"><div className="skeleton h-3 w-24 rounded" /></td>
                <td className="px-4 py-2.5"><div className="skeleton w-8 h-8 rounded-full" /></td>
              </tr>
            ))
          ) : verbatims.length === 0 ? (
            <tr>
              <td colSpan={4} className="px-4 py-8 text-center text-p-text-faint text-sm">
                {search ? `Sin resultados para "${search}" en esta página.` : "Sin verbatims todavía."}
              </td>
            </tr>
          ) : (
            verbatims.map((v) => (
              <tr
                key={v.id}
                className="border-b border-p-border last:border-0 hover:bg-p-bg-subtle/50 transition-colors duration-100"
              >
                <td className="px-4 py-2.5 text-p-text-faint text-xs">{v.respondent_external_id ?? "—"}</td>
                <td className="px-4 py-2.5 text-p-text max-w-sm">
                  <div className="tooltip-trigger w-full">
                    <span className="block truncate">{v.original_text}</span>
                    <div className="tooltip whitespace-normal break-words max-w-xl">{v.original_text}</div>
                  </div>
                </td>
                <td className="px-4 py-2.5">
                  {v.codes.length === 0 ? (
                    <span className="text-xs text-p-text-faint">—</span>
                  ) : (
                    <div className="flex flex-col gap-1">
                      {v.codes.map((code, i) => (
                        <div key={i} className="flex items-center gap-1.5" title={code.matched_alias ? `Matcheó con "${code.matched_alias}"` : undefined}>
                          <span className="text-xs font-medium text-p-text">
                            {code.net ? <span className="text-p-text-faint">{code.net}/</span> : null}
                            {code.label}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </td>
                <td className="px-4 py-2.5">
                  {(() => {
                    const status = v.coding_status as CodingStatus;
                    const label = STATUS_LABELS[status] ?? v.coding_status;
                    const StatusIcon = STATUS_ICON[status] ?? HelpCircle;
                    return (
                      <span
                        className={["inline-flex items-center justify-center w-8 h-8 rounded-full border", STATUS_BADGE[v.coding_status] ?? STATUS_BADGE.pending].join(" ")}
                        title={label}
                        aria-label={label}
                      >
                        <StatusIcon className="w-5 h-5" />
                      </span>
                    );
                  })()}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
