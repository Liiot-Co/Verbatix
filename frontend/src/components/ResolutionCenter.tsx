import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Sparkles, X } from "lucide-react";
import { bulkResolve, getResolutionQueue, getResolutionSummary, getStudioCodes } from "@/api/client";
import type { MentionGroupStatus, ResolutionQueueItem, ResolutionSummary, StudioCode } from "@/api/types";
import ResolutionSidebar from "./ResolutionSidebar";
import { useSidebarResize } from "@/hooks/useSidebarResize";
import { useVerbatixStore } from "@/store/useVerbatixStore";

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
  const showToast = useVerbatixStore((s) => s.showToast);
  const [queue, setQueue] = useState<ResolutionQueueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<ResolutionSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [codes, setCodes] = useState<StudioCode[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [lastClickedIndex, setLastClickedIndex] = useState<number | null>(null);
  const [bulkAssigning, setBulkAssigning] = useState(false);
  const [focusGroupId, setFocusGroupId] = useState<string | null>(null);
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
    getStudioCodes(studioId, false).then(setCodes);
  }, [loadQueue, studioId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const toggleSelect = useCallback(
    (groupId: string, index: number, shiftKey: boolean) => {
      setSelected((prev) => {
        const next = new Set(prev);
        if (shiftKey && lastClickedIndex !== null) {
          const from = Math.min(lastClickedIndex, index);
          const to = Math.max(lastClickedIndex, index);
          for (let i = from; i <= to; i++) {
            const id = queue[i]?.id;
            if (id) next.add(id);
          }
        } else if (next.has(groupId)) {
          next.delete(groupId);
        } else {
          next.add(groupId);
        }
        return next;
      });
      setLastClickedIndex(index);
    },
    [lastClickedIndex, queue]
  );

  const assignBulk = useCallback(
    async (codeId: string) => {
      if (selected.size === 0) return;
      setBulkAssigning(true);
      try {
        const result = await bulkResolve(studioId, Array.from(selected), {
          action: "approve",
          code_ids: [codeId],
          new_code: null,
          add_alias: false,
        });
        setSelected(new Set());
        if (result.failed.length > 0) {
          showToast(
            `${result.resolved.length} resueltos, ${result.failed.length} fallaron: ${result.failed
              .map((f) => f.error)
              .slice(0, 2)
              .join("; ")}`,
            "error"
          );
        } else {
          showToast(`${result.resolved.length} grupos resueltos`, "success");
        }
        loadQueue();
      } catch {
        showToast("No se pudo resolver el lote. Intenta de nuevo.", "error");
      } finally {
        setBulkAssigning(false);
      }
    },
    [selected, studioId, showToast, loadQueue]
  );

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
        {/* Cola: contexto de lo que sigue (orden por impacto, ya viene ordenado del backend).
            Click trae al frente; shift-click selecciona un rango para resolver en lote. */}
        <div className="card overflow-hidden flex flex-col max-h-[calc(100vh-8rem)]">
          <div className="px-4 py-2.5 border-b border-p-border text-xs font-semibold text-p-text-muted uppercase tracking-wide flex items-center justify-between">
            <span>Cola ({total})</span>
            {selected.size > 0 && (
              <button
                onClick={() => setSelected(new Set())}
                className="normal-case font-normal text-p-text-faint hover:text-p-text"
              >
                {selected.size} seleccionados · limpiar
              </button>
            )}
          </div>
          {selected.size > 0 && (
            <div className="px-4 py-2 border-b border-p-border bg-p-bg-subtle flex items-center gap-1.5 flex-wrap">
              <span className="text-xs text-p-text-muted shrink-0">Asignar a {selected.size}:</span>
              {codes.slice(0, 12).map((c) => (
                <button
                  key={c.id}
                  disabled={bulkAssigning}
                  onClick={() => assignBulk(c.id)}
                  className="text-xs font-semibold px-2 py-1 rounded-md border border-p-border bg-p-surface hover:border-p-accent/50 transition-colors"
                >
                  {c.label}
                </button>
              ))}
            </div>
          )}
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
                  onClick={(e) => {
                    if (e.shiftKey || e.metaKey || e.ctrlKey) {
                      toggleSelect(g.id, i, e.shiftKey);
                    } else {
                      setFocusGroupId(g.id);
                    }
                  }}
                  role="button"
                  tabIndex={0}
                  className={[
                    "px-4 py-3 border-b border-p-border last:border-0 cursor-pointer transition-colors",
                    selected.has(g.id) ? "bg-p-accent/15" : i === 0 ? "bg-p-accent/10" : "hover:bg-p-bg-subtle",
                  ].join(" ")}
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
          <ResolutionSidebar
            studioId={studioId}
            onResolved={loadQueue}
            focusGroupId={focusGroupId}
            onFocusHandled={() => setFocusGroupId(null)}
          />
        </div>
      </div>
    </div>,
    document.body
  );
}
