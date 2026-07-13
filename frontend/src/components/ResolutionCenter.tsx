import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Sparkles, X } from "lucide-react";
import { getResolutionQueue, getResolutionSummary } from "@/api/client";
import type { MentionGroupStatus, ResolutionQueueItem, ResolutionSummary } from "@/api/types";
import ResolutionSidebar from "./ResolutionSidebar";
import { useSidebarResize } from "@/hooks/useSidebarResize";

const PAGE_SIZE = 50;

const STATUS_CHIP: Record<MentionGroupStatus, { label: string; className: string }> = {
  anomaly: { label: "Confusa", className: "badge-error" },
  below_threshold: { label: "Bajo umbral", className: "badge-warning" },
  pending_review: { label: "Sin revisar", className: "badge-pending" },
  auto_coded: { label: "Sugerido", className: "badge-auto" },
  resolved: { label: "Resuelto", className: "badge-success" },
};

/** Fullscreen advanced resolution editor — opened from ResolutionSidebar's expand button. */
export default function ResolutionCenter({ studioId, onClose }: { studioId: string; onClose: () => void }) {
  const [queue, setQueue] = useState<ResolutionQueueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<ResolutionSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const { width: sidebarWidth, startResizing } = useSidebarResize(460, 320, 800);

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

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div className="fixed inset-0 z-50 bg-p-bg flex flex-col">
      <div className="flex items-center justify-between gap-4 flex-wrap px-6 py-4 border-b border-p-border shrink-0">
        <h1 className="font-heading text-2xl font-semibold text-p-text tracking-tight">Centro de Resolución</h1>
        <div className="flex items-center gap-3">
          {summary && (
            <span
              className={summary.can_close ? "badge-success" : "badge-pending"}
              title={summary.can_close ? "Todo resuelto: el estudio puede cerrarse" : "Aún hay grupos pendientes"}
            >
              {summary.can_close ? "Listo para cerrar" : `${summary.pending} pendientes`}
            </span>
          )}
          <button
            onClick={onClose}
            className="btn-ghost text-xs py-1.5 px-2"
            title="Cerrar (Esc)"
            aria-label="Cerrar"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div 
        className="grid grid-cols-1 gap-4 items-start flex-1 min-h-0 px-6 py-4 overflow-y-auto lg:[grid-template-columns:1fr_var(--sidebar-w)]"
        style={{ "--sidebar-w": `${sidebarWidth}px` } as React.CSSProperties}
      >
        {/* Cola: contexto de lo que sigue (orden por impacto, ya viene ordenado del backend) */}
        <div className="card overflow-hidden flex flex-col max-h-[calc(100vh-8rem)]">
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

        <div className="h-[calc(100vh-8rem)] relative">
          <div 
            className="hidden lg:flex absolute -left-4 top-0 w-4 h-full cursor-col-resize items-center justify-center z-10 opacity-0 hover:opacity-100 transition-opacity group"
            onMouseDown={startResizing}
            title="Ajustar ancho"
          >
            <div className="w-1 h-12 bg-p-text-muted/30 group-hover:bg-p-accent rounded-full transition-colors" />
          </div>
          <ResolutionSidebar studioId={studioId} onResolved={loadQueue} />
        </div>
      </div>
    </div>,
    document.body
  );
}
