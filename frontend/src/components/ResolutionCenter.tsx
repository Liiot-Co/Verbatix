import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { AlertTriangle, Check, Plus, Search, Sparkles, X } from "lucide-react";
import { motion } from "framer-motion";
import {
  getMentionGroup,
  getResolutionQueue,
  getResolutionSummary,
  getStudioCodes,
  resolveMentionGroup,
} from "@/api/client";
import type {
  MentionGroupDetail,
  MentionGroupStatus,
  ResolutionQueueItem,
  ResolutionSummary,
  ResolveDecision,
  StudioCode,
} from "@/api/types";
import Breadcrumb from "./Breadcrumb";
import { registerShortcuts, useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { useVerbatixStore } from "@/store/useVerbatixStore";

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
  const searchRef = useRef<HTMLInputElement>(null);

  const [queue, setQueue] = useState<ResolutionQueueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<ResolutionSummary | null>(null);
  const [codes, setCodes] = useState<StudioCode[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<MentionGroupDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [resolving, setResolving] = useState(false);
  const [selectedCodeIds, setSelectedCodeIds] = useState<string[]>([]);
  const [pendingNewLabel, setPendingNewLabel] = useState<string | null>(null);
  const [addAlias, setAddAlias] = useState(true);
  const [codeSearch, setCodeSearch] = useState("");

  const loadQueue = useCallback(() => {
    if (!studioId) return Promise.resolve();
    return getResolutionQueue(studioId, PAGE_SIZE, 0).then((res) => {
      setQueue(res.items);
      setTotal(res.total);
    });
  }, [studioId]);

  const loadSummary = useCallback(() => {
    if (!studioId) return Promise.resolve();
    return getResolutionSummary(studioId).then(setSummary);
  }, [studioId]);

  useEffect(() => {
    if (!studioId) return;
    setLoading(true);
    Promise.all([loadQueue(), loadSummary(), getStudioCodes(studioId).then(setCodes)]).finally(() =>
      setLoading(false)
    );
  }, [studioId, loadQueue, loadSummary]);

  // Keep the selection valid and pull the first group into view whenever the queue changes.
  useEffect(() => {
    if (queue.length === 0) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !queue.some((g) => g.id === selectedId)) {
      setSelectedId(queue[0]!.id);
    }
  }, [queue, selectedId]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    setSelectedCodeIds([]);
    setPendingNewLabel(null);
    setCodeSearch("");
    getMentionGroup(selectedId).then(setDetail);
  }, [selectedId]);

  const selectedIndex = useMemo(() => queue.findIndex((g) => g.id === selectedId), [queue, selectedId]);

  const filteredCodes = useMemo(() => {
    const q = codeSearch.trim().toLowerCase();
    if (!q) return codes;
    return codes.filter(
      (c) => c.label.toLowerCase().includes(q) || String(c.code_number).includes(q)
    );
  }, [codes, codeSearch]);

  const quickCodes = useMemo(() => codes.slice(0, 9), [codes]);

  const toggleCode = (id: string) => {
    setSelectedCodeIds((prev) => (prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]));
  };

  const applyOptimisticRemoval = (groupId: string) => {
    const snapshot = queue;
    const idx = snapshot.findIndex((g) => g.id === groupId);
    const next = snapshot.filter((g) => g.id !== groupId);
    setQueue(next);
    setTotal((t) => Math.max(0, t - 1));
    if (next.length) setSelectedId(next[Math.min(idx, next.length - 1)]!.id);
    return () => {
      setQueue(snapshot);
      setTotal((t) => t + 1);
      setSelectedId(groupId);
    };
  };

  const resolve = useCallback(
    async (groupId: string, decision: ResolveDecision) => {
      if (resolving) return;
      setResolving(true);
      const rollback = applyOptimisticRemoval(groupId);
      try {
        const result = await resolveMentionGroup(groupId, decision);
        showToast(
          decision.action === "discard"
            ? "Grupo descartado."
            : `${result.verbatims_updated} verbatims codificados.`,
          "success"
        );
        loadSummary();
      } catch {
        rollback();
        showToast("No se pudo resolver el grupo. Intenta de nuevo.", "error");
      } finally {
        setResolving(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [queue, resolving, loadSummary, showToast]
  );

  const approveCurrent = useCallback(() => {
    if (!detail) return;
    const codeIds = selectedCodeIds;
    const useSuggested = codeIds.length === 0 && !pendingNewLabel && detail.suggested_code;
    if (codeIds.length === 0 && !pendingNewLabel && !useSuggested) {
      showToast("Selecciona al menos un código o crea uno nuevo.", "info");
      return;
    }
    resolve(detail.id, {
      action: "approve",
      code_ids: useSuggested ? [detail.suggested_code!.id] : codeIds,
      new_code: pendingNewLabel ? { label: pendingNewLabel } : null,
      add_alias: addAlias,
    });
  }, [detail, selectedCodeIds, pendingNewLabel, addAlias, resolve, showToast]);

  const discardCurrent = useCallback(() => {
    if (!detail) return;
    resolve(detail.id, { action: "discard", code_ids: [], add_alias: false });
  }, [detail, resolve]);

  const navigateQueue = useCallback(
    (delta: number) => {
      if (queue.length === 0) return;
      const idx = selectedIndex < 0 ? 0 : selectedIndex;
      const next = Math.min(queue.length - 1, Math.max(0, idx + delta));
      setSelectedId(queue[next]!.id);
    },
    [queue, selectedIndex]
  );

  useEffect(() => {
    registerShortcuts("resolution-center", [
      { key: "Enter", action: approveCurrent, description: "Aprobar sugerencia/selección", category: "Acciones" },
      { key: "d", action: discardCurrent, description: "Descartar", category: "Acciones" },
      { key: "n", action: () => searchRef.current?.focus(), description: "Crear código nuevo", category: "Acciones" },
      { key: "ArrowUp", action: () => navigateQueue(-1), description: "Grupo anterior", category: "Navegación" },
      { key: "ArrowDown", action: () => navigateQueue(1), description: "Grupo siguiente", category: "Navegación" },
      ...Array.from({ length: 9 }, (_, i) => ({
        key: String(i + 1),
        action: () => quickCodes[i] && toggleCode(quickCodes[i].id),
        description: `Alternar código #${i + 1}`,
        category: "Códigos rápidos",
      })),
    ]);
  }, [approveCurrent, discardCurrent, navigateQueue, quickCodes]);

  useKeyboardShortcuts("resolution-center");

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
          <div className="flex items-center gap-3 text-xs text-p-text-muted">
            <span>
              {summary.resolved} / {summary.resolved + summary.pending + summary.auto_coded} resueltos
            </span>
            <span
              className={summary.can_close ? "badge-success" : "badge-pending"}
              title={summary.can_close ? "Todo resuelto: el estudio puede cerrarse" : "Aún hay grupos pendientes"}
            >
              {summary.can_close ? "Listo para cerrar" : `${summary.pending} pendientes`}
            </span>
          </div>
        )}
      </div>

      {summary && (
        <div className="h-2 rounded-full bg-p-bg-subtle overflow-hidden">
          <motion.div
            className="h-full bg-gradient-to-r from-p-accent to-p-accent-mid"
            initial={{ width: 0 }}
            animate={{ width: `${summary.progress_pct}%` }}
            transition={{ duration: 0.5, ease: [0.19, 1, 0.22, 1] as const }}
          />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[380px_1fr] gap-4">
        {/* Panel izquierdo: cola de trabajo */}
        <div className="card overflow-hidden flex flex-col max-h-[70vh]">
          <div className="px-4 py-2.5 border-b border-p-border text-xs font-semibold text-p-text-muted uppercase tracking-wide flex items-center justify-between">
            <span>Cola ({total})</span>
            <kbd className="kbd-hint">↑ ↓</kbd>
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
              queue.map((g) => (
                <button
                  key={g.id}
                  onClick={() => setSelectedId(g.id)}
                  className={[
                    "w-full text-left px-4 py-3 border-b border-p-border last:border-0 transition-colors",
                    g.id === selectedId ? "bg-p-accent/10" : "hover:bg-p-bg-subtle/60",
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
                </button>
              ))
            )}
          </div>
        </div>

        {/* Panel derecho: área de decisión */}
        <div className="card p-5 space-y-4">
          {!detail ? (
            <p className="text-sm text-p-text-faint">Selecciona un grupo de la cola.</p>
          ) : (
            <>
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <h2 className="font-heading text-lg font-semibold text-p-text">{detail.normalized_text}</h2>
                  <span className={STATUS_CHIP[detail.status].className}>{STATUS_CHIP[detail.status].label}</span>
                </div>
                <p className="text-xs text-p-text-muted">
                  {detail.verbatims_count} verbatim{detail.verbatims_count === 1 ? "" : "s"} afectado
                  {detail.verbatims_count === 1 ? "" : "s"}
                </p>
              </div>

              {detail.suggested_code && (
                <div className="flex items-center gap-2 text-sm bg-p-accent/10 border border-p-accent/30 rounded-lg px-3 py-2">
                  <Sparkles className="w-4 h-4 text-p-accent shrink-0" />
                  <span className="text-p-text">
                    Sugerencia del motor: <strong>{detail.suggested_code.label}</strong>
                  </span>
                </div>
              )}

              <div className="space-y-1.5">
                <span className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Muestras</span>
                <ul className="space-y-1 max-h-32 overflow-y-auto scrollbar-thin">
                  {detail.samples.map((s, i) => (
                    <li key={i} className="text-sm text-p-text bg-p-bg-subtle/60 rounded-md px-2.5 py-1.5">
                      "{s}"
                    </li>
                  ))}
                </ul>
              </div>

              <div className="space-y-2">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-p-text-faint pointer-events-none" />
                  <input
                    ref={searchRef}
                    className="input pl-10 text-sm"
                    placeholder="Buscar código o crear uno nuevo..."
                    value={codeSearch}
                    onChange={(e) => setCodeSearch(e.target.value)}
                  />
                </div>

                <div className="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto scrollbar-thin">
                  {filteredCodes.map((c) => {
                    const active = selectedCodeIds.includes(c.id);
                    return (
                      <button
                        key={c.id}
                        onClick={() => toggleCode(c.id)}
                        className={[
                          "inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full border transition-colors",
                          active
                            ? "bg-p-accent text-white border-p-accent"
                            : "bg-p-surface text-p-text-muted border-p-border hover:border-p-accent/50",
                        ].join(" ")}
                      >
                        {active && <Check className="w-3 h-3" />}
                        {c.label}
                      </button>
                    );
                  })}
                  {codeSearch.trim() && !filteredCodes.some((c) => c.label.toLowerCase() === codeSearch.trim().toLowerCase()) && (
                    <button
                      onClick={() => {
                        setPendingNewLabel(codeSearch.trim());
                        setCodeSearch("");
                      }}
                      className="inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full border border-dashed border-p-accent text-p-accent hover:bg-p-accent/10"
                    >
                      <Plus className="w-3 h-3" /> Crear "{codeSearch.trim()}"
                    </button>
                  )}
                </div>

                {pendingNewLabel && (
                  <div className="flex items-center gap-1.5 text-xs bg-p-accent/10 border border-p-accent/30 rounded-full px-2.5 py-1 w-fit">
                    <Plus className="w-3 h-3 text-p-accent" />
                    <span className="text-p-text">Nuevo: {pendingNewLabel}</span>
                    <button onClick={() => setPendingNewLabel(null)} aria-label="Quitar código nuevo">
                      <X className="w-3 h-3 text-p-text-faint hover:text-p-text" />
                    </button>
                  </div>
                )}

                <label className="flex items-center gap-2 text-xs text-p-text-muted">
                  <input
                    type="checkbox"
                    checked={addAlias}
                    onChange={(e) => setAddAlias(e.target.checked)}
                    className="rounded border-p-border"
                  />
                  Recordar como alias para futuras rondas
                </label>
              </div>

              <div className="flex items-center gap-2 pt-2">
                <motion.button
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  className="btn-primary text-sm py-2 flex-1 justify-center"
                  disabled={resolving}
                  onClick={approveCurrent}
                >
                  <Check className="w-4 h-4" /> Aprobar <kbd className="kbd-hint ml-1">Enter</kbd>
                </motion.button>
                <motion.button
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm text-p-error border border-p-border hover:bg-red-50 transition-all duration-150 ease-out-expo active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400"
                  disabled={resolving}
                  onClick={discardCurrent}
                >
                  <AlertTriangle className="w-4 h-4" /> Descartar <kbd className="kbd-hint ml-1">D</kbd>
                </motion.button>
              </div>
            </>
          )}
        </div>
      </div>

      <div className="fixed bottom-4 left-1/2 -translate-x-1/2 hidden sm:flex items-center gap-3 text-xs text-p-text-faint bg-p-surface/90 backdrop-blur-glass border border-p-border rounded-xl px-4 py-2 shadow-lg">
        <span className="flex items-center gap-1"><kbd className="kbd-hint">Enter</kbd> Aprobar</span>
        <span className="flex items-center gap-1"><kbd className="kbd-hint">D</kbd> Descartar</span>
        <span className="flex items-center gap-1"><kbd className="kbd-hint">N</kbd> Nuevo código</span>
        <span className="flex items-center gap-1"><kbd className="kbd-hint">1-9</kbd> Códigos rápidos</span>
        <span className="flex items-center gap-1"><kbd className="kbd-hint">↑ ↓</kbd> Navegar</span>
      </div>
    </div>
  );
}
