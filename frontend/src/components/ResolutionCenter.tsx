import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Sparkles } from "lucide-react";
import { getResolutionQueue, getResolutionSummary } from "@/api/client";
import type { MentionGroupStatus, ResolutionQueueItem, ResolutionSummary } from "@/api/types";
import Breadcrumb from "./Breadcrumb";
import ResolutionSidebar from "./ResolutionSidebar";

const PAGE_SIZE = 50;

const STATUS_CHIP: Record<MentionGroupStatus, { label: string; className: string }> = {
  anomaly: { label: "Confusa", className: "badge-error" },
  below_threshold: { label: "Bajo umbral", className: "badge-warning" },
  pending_review: { label: "Sin revisar", className: "badge-pending" },
  auto_coded: { label: "Sugerido", className: "badge-auto" },
  resolved: { label: "Resuelto", className: "badge-success" },
};

export default function ResolutionCenter() {
  const { studioId } = useParams<{ studioId: string }>();

  const [queue, setQueue] = useState<ResolutionQueueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<ResolutionSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const loadQueue = useCallback(() => {
    if (!studioId) return;
    Promise.all([
      getResolutionQueue(studioId, PAGE_SIZE, 0).then((res) => {
        setQueue(res.items);
        setTotal(res.total);
      }),
      getResolutionSummary(studioId).then(setSummary),
    ]).finally(() => setLoading(false));
  }, [studioId]);

  useEffect(() => {
    setLoading(true);
    loadQueue();
  }, [loadQueue]);

  if (!studioId) return null;

  return (
    <div className="max-w-6xl mx-auto py-4 space-y-4">
      <Breadcrumb
        items={[
          { label: "Proyectos", to: "/" },
          { label: "Estudio", to: `/studios/${studioId}` },
          { label: "Centro de Resolución" },
        ]}
      />

      <div className="flex items-center justify-between gap-4 flex-wrap">
        <h1 className="font-heading text-2xl font-semibold text-p-text tracking-tight">Centro de Resolución</h1>
        {summary && (
          <span
            className={summary.can_close ? "badge-success" : "badge-pending"}
            title={summary.can_close ? "Todo resuelto: el estudio puede cerrarse" : "Aún hay grupos pendientes"}
          >
            {summary.can_close ? "Listo para cerrar" : `${summary.pending} pendientes`}
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_348px] gap-4 items-start">
        {/* Cola: contexto de lo que sigue (orden por impacto, ya viene ordenado del backend) */}
        <div className="card overflow-hidden flex flex-col max-h-[70vh]">
          <div className="px-4 py-2.5 border-b border-p-border text-xs font-semibold text-p-text-muted uppercase tracking-wide">
            Cola ({total})
          </div>
          <div className="overflow-y-auto scrollbar-thin flex-1">
            {loading ? (
              Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="px-4 py-3 border-b border-p-border last:border-0">
                  <div className="skeleton h-3 w-3/4 rounded mb-2" />
                  <div className="skeleton h-3 w-1/3 rounded" />
                </div>
              ))
            ) : queue.length === 0 ? (
              <div className="px-4 py-10 text-center text-sm text-p-text-faint">
                No hay grupos pendientes. ¡Todo al día!
              </div>
            ) : (
              queue.map((g, i) => (
                <div
                  key={g.id}
                  className={["px-4 py-3 border-b border-p-border last:border-0", i === 0 ? "bg-p-accent/10" : ""].join(
                    " "
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm text-p-text font-medium truncate">{g.normalized_text}</span>
                    <span className="text-xs text-p-text-faint shrink-0">×{g.frequency_count}</span>
                  </div>
                  <div className="flex items-center gap-1.5 mt-1">
                    <span className={STATUS_CHIP[g.status].className}>{STATUS_CHIP[g.status].label}</span>
                    {g.suggested_code && (
                      <span className="text-[10px] text-p-text-faint flex items-center gap-1">
                        <Sparkles className="w-3 h-3" /> {g.suggested_code.label}
                      </span>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        <ResolutionSidebar studioId={studioId} onResolved={loadQueue} />
      </div>
    </div>
  );
}
