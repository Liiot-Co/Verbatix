import { motion } from "framer-motion";
import type { VerbatimSummaryRow } from "@/api/types";
import ProcessingOverlay from "./ProcessingOverlay";

interface ProcessingOverlayData {
  visible: boolean;
  status: string | undefined;
  codedPct: number;
  autoCoded: number;
  pendingReview: number;
  anomalies: number;
  resolved: number;
  pollCount: number;
}

interface VerbatimsTableProps {
  loading: boolean;
  rows: VerbatimSummaryRow[];
  search: string;
  processingOverlay: ProcessingOverlayData | null;
}

export function VerbatimsTable({
  loading,
  rows,
  search,
  processingOverlay = null,
}: VerbatimsTableProps) {
  return (
    <div className="card overflow-hidden relative min-h-[500px]">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-p-border text-left">
            <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">
              #
            </th>
            <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">
              Código
            </th>
            <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">
              Mención principal
            </th>
            <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">
              Contenido
            </th>
            <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider text-right">
              Frecuencia
            </th>
            <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider text-right">
              %
            </th>
          </tr>
        </thead>
        <tbody>
          {loading ? (
            Array.from({ length: 8 }).map((_, i) => (
              <motion.tr
                key={`sk-${i}`}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: i * 0.1, duration: 0.35 }}
                className="border-b border-p-border last:border-0"
              >
                <td className="px-4 py-2.5">
                  <div className="skeleton h-3 w-6 rounded" />
                </td>
                <td className="px-4 py-2.5">
                  <div className="skeleton h-3 w-10 rounded" />
                </td>
                <td className="px-4 py-2.5">
                  <div className="skeleton h-3 w-36 rounded" />
                </td>
                <td className="px-4 py-2.5">
                  <div className="skeleton h-3 w-3/4 rounded" />
                </td>
                <td className="px-4 py-2.5">
                  <div className="skeleton h-3 w-10 rounded ml-auto" />
                </td>
                <td className="px-4 py-2.5">
                  <div className="skeleton h-3 w-10 rounded ml-auto" />
                </td>
              </motion.tr>
            ))
          ) : rows.length === 0 ? (
            <tr>
              <td colSpan={6} className="px-4 py-8 text-center text-p-text-faint text-sm">
                {search ? `Sin resultados para "${search}".` : "Nada por aquí todavía."}
              </td>
            </tr>
          ) : (
            rows.map((r, i) => (
              <tr
                key={r.code_id ?? `${r.content}-${i}`}
                className="border-b border-p-border last:border-0 hover:bg-p-bg-subtle/50 transition-colors duration-100"
              >
                <td className="px-4 py-2.5 text-p-text-faint text-xs">{i + 1}</td>
                <td className="px-4 py-2.5 text-p-text-faint text-xs whitespace-nowrap">
                  {r.code_number ?? "—"}
                </td>
                <td className="px-4 py-2.5 text-p-text font-medium max-w-xs">
                  <span className="block truncate">{r.label ?? "—"}</span>
                </td>
                <td className="px-4 py-2.5 text-p-text max-w-sm">
                  <div className="tooltip-trigger w-full">
                    <span className="block truncate">{r.content ?? "—"}</span>
                    {r.content && (
                      <div className="tooltip whitespace-normal break-words max-w-xl">
                        {r.content}
                      </div>
                    )}
                  </div>
                </td>
                <td className="px-4 py-2.5 text-p-text-muted text-xs text-right tabular-nums">
                  {r.frequency}
                </td>
                <td className="px-4 py-2.5 text-p-text-muted text-xs text-right tabular-nums">
                  {r.percentage}%
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
      {processingOverlay && (
        <ProcessingOverlay
          visible={processingOverlay.visible}
          status={processingOverlay.status}
          codedPct={processingOverlay.codedPct}
          autoCoded={processingOverlay.autoCoded}
          pendingReview={processingOverlay.pendingReview}
          anomalies={processingOverlay.anomalies}
          resolved={processingOverlay.resolved}
          pollCount={processingOverlay.pollCount}
        />
      )}
    </div>
  );
}
