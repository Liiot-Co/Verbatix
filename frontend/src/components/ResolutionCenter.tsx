import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { Ban, Sparkles } from "lucide-react";
import { bulkResolve, getResolutionQueue, getResolutionSummary, getStudio, getStudioCodes } from "@/api/client";
import type { CodingType, MentionGroupStatus, ResolutionQueueItem, ResolutionSummary, StudioCode } from "@/api/types";
import { useVerbatixStore } from "@/store/useVerbatixStore";
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
  const showToast = useVerbatixStore((s) => s.showToast);

  const [queue, setQueue] = useState<ResolutionQueueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<ResolutionSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [codes, setCodes] = useState<StudioCode[]>([]);
  const [codingType, setCodingType] = useState<CodingType>("brands");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [lastClickedIndex, setLastClickedIndex] = useState<number | null>(null);
  const [bulkAssignCodeId, setBulkAssignCodeId] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const noun = codingType === "reasons" ? "razón" : "marca";

  const loadQueue = useCallback(() => {
    if (!studioId) return;
    Promise.all([
      getResolutionQueue(studioId, PAGE_SIZE, 0).then((res) => {
        setQueue(res.items);
        setTotal(res.total);
      }),
      getResolutionSummary(studioId).then(setSummary),
      getStudioCodes(studioId).then(setCodes),
      getStudio(studioId).then((s) => setCodingType(s.coding_type)),
    ]).finally(() => setLoading(false));
  }, [studioId]);

  useEffect(() => {
    setLoading(true);
    loadQueue();
  }, [loadQueue]);

  // Selection clears whenever the underlying queue changes shape (e.g. after a resolve).
  useEffect(() => {
    setSelected((prev) => {
      const ids = new Set(queue.map((g) => g.id));
      const next = new Set([...prev].filter((id) => ids.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [queue]);

  const toggleSelect = useCallback(
    (index: number, event: React.MouseEvent) => {
      const id = queue[index]?.id;
      if (!id) return;
      setSelected((prev) => {
        const next = new Set(prev);
        if (event.shiftKey && lastClickedIndex !== null) {
          const from = Math.min(lastClickedIndex, index);
          const to = Math.max(lastClickedIndex, index);
          for (let i = from; i <= to; i++) {
            const groupId = queue[i]?.id;
            if (groupId) next.add(groupId);
          }
        } else if (next.has(id)) {
          next.delete(id);
        } else {
          next.add(id);
        }
        return next;
      });
      setLastClickedIndex(index);
    },
    [queue, lastClickedIndex]
  );

  const clearSelection = useCallback(() => {
    setSelected(new Set());
    setLastClickedIndex(null);
  }, []);

  const runBulk = useCallback(
    async (decision: { action: "approve" | "discard"; code_ids: string[] }) => {
      if (!studioId || selected.size === 0) return;
      setBulkBusy(true);
      try {
        const result = await bulkResolve(studioId, [...selected], { ...decision, add_alias: false });
        if (result.failed.length > 0) {
          showToast(`${result.failed.length} grupo(s) no se pudieron resolver.`, "error");
        }
        clearSelection();
        setBulkAssignCodeId("");
        loadQueue();
      } catch {
        showToast("No se pudo aplicar la acción en lote.", "error");
      } finally {
        setBulkBusy(false);
      }
    },
    [studioId, selected, showToast, clearSelection, loadQueue]
  );

  const selectedCount = selected.size;
  const selectedFrequency = useMemo(
    () => queue.filter((g) => selected.has(g.id)).reduce((sum, g) => sum + g.frequency_count, 0),
    [queue, selected]
  );

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
        <div className="card overflow-hidden flex flex-col h-[calc(100vh-7rem)]">
          <div className="px-4 py-2.5 border-b border-p-border text-xs font-semibold text-p-text-muted uppercase tracking-wide flex items-center justify-between gap-2">
            <span>Cola ({total})</span>
            {selectedCount > 0 && (
              <span className="normal-case font-normal text-p-text-faint">
                {selectedCount} seleccionados · {selectedFrequency} menciones
              </span>
            )}
          </div>

          {selectedCount > 0 && (
            <div className="px-4 py-2 border-b border-p-border bg-p-bg-subtle flex items-center gap-2 flex-wrap">
              <select
                value={bulkAssignCodeId}
                onChange={(e) => setBulkAssignCodeId(e.target.value)}
                className="input text-xs py-1 max-w-[180px]"
                disabled={bulkBusy}
              >
                <option value="">Asignar a {noun}…</option>
                {codes.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </select>
              <button
                onClick={() => bulkAssignCodeId && runBulk({ action: "approve", code_ids: [bulkAssignCodeId] })}
                disabled={bulkBusy || !bulkAssignCodeId}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-blue-200 bg-blue-50 text-xs font-bold text-blue-700 disabled:opacity-50"
              >
                Asignar {selectedCount}
              </button>
              <button
                onClick={() => runBulk({ action: "discard", code_ids: [] })}
                disabled={bulkBusy}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-p-border bg-p-surface text-xs text-p-text-muted disabled:opacity-50"
              >
                <Ban className="w-3 h-3" /> Descartar {selectedCount}
              </button>
              <button
                onClick={clearSelection}
                disabled={bulkBusy}
                className="ml-auto text-xs text-p-text-faint underline underline-offset-2"
              >
                Limpiar
              </button>
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
                  className={[
                    "px-4 py-3 border-b border-p-border last:border-0 flex items-start gap-2.5 cursor-pointer select-none",
                    selected.has(g.id) ? "bg-p-accent/10" : i === 0 ? "bg-p-accent/5" : "",
                  ].join(" ")}
                  onClick={(e) => toggleSelect(i, e)}
                >
                  <input
                    type="checkbox"
                    checked={selected.has(g.id)}
                    onChange={() => {}}
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleSelect(i, e);
                    }}
                    aria-label={`Seleccionar ${g.normalized_text}`}
                    className="mt-1 rounded border-p-border shrink-0"
                  />
                  <div className="flex-1 min-w-0">
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
                </div>
              ))
            )}
          </div>
        </div>

        <ResolutionSidebar studioId={studioId} codingType={codingType} onResolved={loadQueue} />
      </div>
    </div>
  );
}
