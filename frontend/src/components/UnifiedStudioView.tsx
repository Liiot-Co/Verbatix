import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight,
  Keyboard, PartyPopper, RefreshCw, Search,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { getPreliminary, getStudio, getVerbatims, processStudio } from "@/api/client";
import type { CodingStatus, PreliminarySummary, StudioStatus, Verbatim } from "@/api/types";
import Breadcrumb from "./Breadcrumb";
import { useKeyboardShortcuts, registerShortcuts, modLabel } from "@/hooks/useKeyboardShortcuts";
import { useVerbatixStore } from "@/store/useVerbatixStore";

const PAGE_SIZE = 50;

const STATUS_BADGE: Record<string, string> = {
  pending: "badge-pending",
  auto_coded: "badge-auto",
  needs_review: "badge-warning",
  manually_coded: "badge-success",
  unknown: "badge-error",
};

const STATUS_LABELS: Record<CodingStatus, string> = {
  pending: "Pendiente",
  auto_coded: "Auto-codificado",
  needs_review: "Necesita revisión",
  manually_coded: "Codificado a mano",
  unknown: "Desconocida",
};

function isTypingTarget(el: EventTarget | null): boolean {
  return el instanceof HTMLInputElement || el instanceof HTMLSelectElement || el instanceof HTMLTextAreaElement;
}

export default function UnifiedStudioView() {
  const { studioId } = useParams<{ studioId: string }>();
  const searchRef = useRef<HTMLInputElement>(null);
  const showToast = useVerbatixStore((s) => s.showToast);

  const [studio, setStudio] = useState<StudioStatus | null>(null);
  const [preliminary, setPreliminary] = useState<PreliminarySummary | null>(null);
  const [verbatims, setVerbatims] = useState<Verbatim[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [statusFilter, setStatusFilter] = useState<CodingStatus | "">("");
  const [search, setSearch] = useState("");
  const [showShortcuts, setShowShortcuts] = useState(false);

  const loadData = useCallback(() => {
    if (!studioId) return Promise.resolve();
    return Promise.all([
      getStudio(studioId).then(setStudio),
      getPreliminary(studioId).then(setPreliminary),
    ]);
  }, [studioId]);

  const loadVerbatims = useCallback(() => {
    if (!studioId) return;
    getVerbatims(studioId, PAGE_SIZE, (page - 1) * PAGE_SIZE, statusFilter || undefined)
      .then((res) => {
        setVerbatims(res.items);
        setTotal(res.total);
      });
  }, [studioId, page, statusFilter]);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      getStudio(studioId!).then(setStudio),
      getPreliminary(studioId!).then(setPreliminary),
    ]).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studioId]);

  useEffect(() => {
    if (!studioId) return;
    setLoading(true);
    getVerbatims(studioId, PAGE_SIZE, (page - 1) * PAGE_SIZE, statusFilter || undefined)
      .then((res) => {
        setVerbatims(res.items);
        setTotal(res.total);
      })
      .finally(() => setLoading(false));
  }, [studioId, page, statusFilter]);

  const autoProcessing = studio?.status === "files_uploaded";

  useEffect(() => {
    if (!autoProcessing) return;
    const id = setInterval(() => {
      Promise.all([loadData(), loadVerbatims()]);
    }, 8000);
    return () => clearInterval(id);
  }, [autoProcessing, loadData, loadVerbatims]);

  const handleProcess = async () => {
    if (!studioId) return;
    setProcessing(true);
    try {
      const result = await processStudio(studioId);
      showToast(
        `${result.groups_classified} grupos codificados solos, ${result.anomalies} necesitan revisión`,
        "success"
      );
      await Promise.all([loadData(), loadVerbatims()]);
    } catch {
      showToast("No se pudo procesar el estudio", "error");
    } finally {
      setProcessing(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const visible = useMemo(() => {
    if (!search.trim()) return verbatims;
    const q = search.trim().toLowerCase();
    return verbatims.filter((v) => v.original_text.toLowerCase().includes(q));
  }, [verbatims, search]);

  useEffect(() => { setPage(1); }, [statusFilter]);

  useEffect(() => {
    registerShortcuts("unified-studio", [
      { key: "f", meta: true,
        action: () => { searchRef.current?.focus(); searchRef.current?.select(); },
        description: "Enfocar búsqueda", category: "Navegación", allowInInput: false },
      { key: "ArrowRight", meta: false, action: () => setPage((p) => Math.min(totalPages, p + 1)),
        description: "Página siguiente", category: "Navegación", allowInInput: false },
      { key: "ArrowLeft", meta: false, action: () => setPage((p) => Math.max(1, p - 1)),
        description: "Página anterior", category: "Navegación", allowInInput: false },
      { key: "r", meta: true, action: () => window.location.reload(),
        description: "Recargar", category: "Acciones" },
      { key: "e", meta: true, action: () => showToast("Exportar en desarrollo", "info"),
        description: "Exportar resultados", category: "Acciones" },
      { key: "Escape", meta: false, action: () => {
          setSearch(""); setStatusFilter(""); setShowShortcuts(false);
          searchRef.current?.blur();
        },
        description: "Limpiar filtros / Cerrar", category: "Navegación" },
      { key: "?", meta: false, action: () => setShowShortcuts((v) => !v),
        description: "Mostrar atajos de teclado", category: "Navegación" },
    ]);
  }, [totalPages, showToast]);

  useKeyboardShortcuts("unified-studio");

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target)) return;
      if (e.key === "ArrowRight") setPage((p) => Math.min(totalPages, p + 1));
      if (e.key === "ArrowLeft") setPage((p) => Math.max(1, p - 1));
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [totalPages]);

  if (loading && !studio) {
    return (
      <div className="max-w-4xl mx-auto py-4 space-y-4">
        <div className="skeleton h-6 w-40 rounded" />
        <div className="skeleton h-40 rounded-2xl" />
        <div className="skeleton h-64 rounded-2xl" />
      </div>
    );
  }

  if (!studioId || !studio) {
    return (
      <div className="max-w-4xl mx-auto py-4">
        <p className="text-sm text-p-text-faint">Estudio no encontrado.</p>
      </div>
    );
  }

  const summary = preliminary?.summary;
  const autoCoded = summary?.auto_coded ?? 0;
  const pendingReview = summary?.pending_review ?? 0;
  const anomalies = summary?.anomalies ?? 0;
  const resolved = summary?.resolved ?? 0;
  const totalGroups = autoCoded + pendingReview + anomalies + resolved;
  const codedPct = totalGroups ? Math.round(((autoCoded + resolved) / totalGroups) * 100) : 0;
  const hasPending = pendingReview > 0;
  const neverProcessed = hasPending && autoCoded + resolved === 0;
  const justFinished = totalGroups > 0 && codedPct === 100;

  const isProcessingNow = autoProcessing || processing;

  const momentum = autoProcessing
    ? "Procesando en el motor — esto puede tardar unos minutos."
    : codedPct === 100
    ? "¡Todo codificado! El motor resolvió el 100% solo."
    : codedPct >= 75
    ? "Casi listo — el motor va muy bien."
    : codedPct >= 40
    ? "Buen avance, sigue así."
    : codedPct > 0
    ? "Arrancando — el motor ya empezó a codificar."
    : "Sin codificar todavía.";

  return (
    <div className="max-w-5xl mx-auto py-4 space-y-4">
      <Breadcrumb items={[{ label: "Proyectos", to: "/" }, { label: studio.name }]} />

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="space-y-1">
          <h1 className="font-heading text-2xl font-semibold text-p-text tracking-tight">{studio.name}</h1>
          <p className="font-subtitle text-sm text-p-text-muted">
            {studio.coding_type === "brands" ? "Marcas" : "Razones"} · {studio.counters.verbatims_total} verbatims · estado: {studio.status}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {autoProcessing && (
            <span className="flex items-center gap-1.5 text-xs text-p-accent">
              <motion.span
                animate={{ opacity: [1, 0.3, 1] }}
                transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
                className="w-2 h-2 rounded-full bg-p-accent"
              />
              En vivo
            </span>
          )}
          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            className={neverProcessed ? "btn-primary text-sm py-2" : "btn-ghost text-sm py-2"}
            disabled={isProcessingNow}
            onClick={handleProcess}
            title={
              autoProcessing
                ? "El motor ya está codificando en segundo plano"
                : neverProcessed
                ? "Codificar automáticamente"
                : "Volver a correr el motor sobre lo pendiente"
            }
          >
            {isProcessingNow ? (
              <motion.span
                animate={{ rotate: 360 }}
                transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                className="w-4 h-4 border-2 border-current/30 border-t-current rounded-full"
              />
            ) : (
              <RefreshCw className="w-4 h-4" />
            )}
            {isProcessingNow ? "Procesando..." : neverProcessed ? "Procesar" : "Reprocesar"}
          </motion.button>
        </div>
      </div>

      {preliminary && (
        <>
          <div className="card p-4 space-y-2">
            <div className="flex items-center justify-between text-xs text-p-text-muted">
              <span className="flex items-center gap-1.5">
                <AnimatePresence mode="wait">
                  {justFinished && (
                    <motion.span
                      key="party"
                      initial={{ scale: 0, rotate: -20 }}
                      animate={{ scale: 1, rotate: 0 }}
                      transition={{ type: "spring", stiffness: 400, damping: 15 }}
                    >
                      <PartyPopper className="w-3.5 h-3.5 text-p-success" />
                    </motion.span>
                  )}
                </AnimatePresence>
                {momentum}
              </span>
              <span className="font-semibold text-p-text">{codedPct}%</span>
            </div>
            <div className="h-2 rounded-full bg-p-bg-subtle overflow-hidden">
              <motion.div
                className={[
                  "h-full bg-gradient-to-r",
                  justFinished ? "from-p-success to-p-success" : "from-p-accent to-p-accent-mid",
                ].join(" ")}
                initial={{ width: 0 }}
                animate={{ width: `${codedPct}%` }}
                transition={{ duration: 0.6, ease: [0.19, 1, 0.22, 1] as const }}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="card p-4 space-y-2">
              <div className="flex items-center gap-2 text-p-success">
                <CheckCircle2 className="w-4 h-4" />
                <span className="text-xs font-semibold uppercase tracking-wide">Codificado</span>
              </div>
              <div className="text-2xl font-bold text-p-text">{autoCoded + resolved}</div>
              <p className="text-xs text-p-text-faint">Grupos que el motor resolvió solo (o ya fueron revisados).</p>
            </div>
            <div className="card p-4 space-y-2">
              <div className="flex items-center gap-2 text-p-warning">
                <AlertTriangle className="w-4 h-4" />
                <span className="text-xs font-semibold uppercase tracking-wide">Pendiente</span>
              </div>
              <div className="text-2xl font-bold text-p-text">{pendingReview + anomalies}</div>
              <p className="text-xs text-p-text-faint">
                {pendingReview} sin procesar todavía · {anomalies} menciones confusas
              </p>
            </div>
          </div>
        </>
      )}

      <div className="flex flex-col sm:flex-row gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-p-text-faint pointer-events-none" />
          <input
            ref={searchRef}
            className="input w-full text-sm pl-10 pr-12"
            placeholder="Buscar en esta página..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <kbd className="hidden sm:flex items-center absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-mono text-p-text-faint border border-p-border rounded px-1.5 py-0.5 pointer-events-none">
            {modLabel()}F
          </kbd>
        </div>
        <motion.select
          whileHover={{ scale: 1.01 }}
          whileFocus={{ scale: 1.01 }}
          className="input w-full sm:w-52 text-sm"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as CodingStatus | "")}
        >
          <option value="">Todos los estados</option>
          <option value="pending">Pendiente</option>
          <option value="auto_coded">Auto-codificado</option>
          <option value="needs_review">Necesita revisión</option>
          <option value="manually_coded">Codificado a mano</option>
          <option value="unknown">Desconocida</option>
        </motion.select>
      </div>

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-p-border text-left">
              <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">#</th>
              <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">Respondiente</th>
              <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">Respuesta</th>
              <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">Código</th>
              <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">Estado</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: 6 }).map((_, i) => (
                <tr key={`skeleton-${i}`} className="border-b border-p-border last:border-0">
                  <td className="px-4 py-2.5"><div className="skeleton h-3 w-6 rounded" /></td>
                  <td className="px-4 py-2.5"><div className="skeleton h-3 w-10 rounded" /></td>
                  <td className="px-4 py-2.5"><div className="skeleton h-3 w-3/4 rounded" /></td>
                  <td className="px-4 py-2.5"><div className="skeleton h-3 w-24 rounded" /></td>
                  <td className="px-4 py-2.5"><div className="skeleton h-3 w-16 rounded-full" /></td>
                </tr>
              ))
            ) : visible.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-p-text-faint text-sm">
                  {search ? `Sin resultados para "${search}" en esta página.` : "Sin verbatims todavía."}
                </td>
              </tr>
            ) : (
              visible.map((v, rowIndex) => (
                <tr
                  key={v.id}
                  className="border-b border-p-border last:border-0 hover:bg-p-bg-subtle/50 transition-colors duration-100"
                >
                  <td className="px-4 py-2.5 text-p-text-faint text-xs">{(page - 1) * PAGE_SIZE + rowIndex + 1}</td>
                  <td className="px-4 py-2.5 text-p-text-faint text-xs">{v.respondent_external_id ?? "—"}</td>
                  <td className="px-4 py-2.5 text-p-text max-w-2xl truncate">{v.original_text}</td>
                  <td className="px-4 py-2.5">
                    {v.codes.length === 0 ? (
                      <span className="text-xs text-p-text-faint">—</span>
                    ) : (
                      <div className="flex flex-col gap-1">
                        {v.codes.map((code, i) => (
                          <div key={i} className="flex items-center gap-1.5" title={code.matched_alias ? `Matcheó con "${code.matched_alias}"` : undefined}>
                            <span className="inline-flex items-center justify-center text-[10px] font-semibold w-5 h-5 rounded-full border border-p-border bg-p-bg-subtle text-p-text-muted shrink-0">
                              {code.code_number}
                            </span>
                            <span className="text-xs font-medium text-p-text">{code.label}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={["inline-flex items-center text-[11px] font-semibold px-2 py-0.5 rounded-full border", STATUS_BADGE[v.coding_status] ?? STATUS_BADGE.pending].join(" ")}
                    >
                      {STATUS_LABELS[v.coding_status as CodingStatus] ?? v.coding_status}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-p-text-muted">
          <span>Página {page} de {totalPages} · {total} verbatims</span>
          <div className="flex items-center gap-1.5">
            <kbd className="hidden sm:inline text-[10px] font-mono text-p-text-faint border border-p-border rounded px-1.5 py-0.5 mr-1">← →</kbd>
            <motion.button
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              className="btn-ghost text-xs py-1 px-2"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              aria-label="Página anterior"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
            </motion.button>
            <motion.button
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              className="btn-ghost text-xs py-1 px-2"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              aria-label="Página siguiente"
            >
              <ChevronRight className="w-3.5 h-3.5" />
            </motion.button>
          </div>
        </div>
      )}

      <motion.button
        type="button"
        onClick={() => setShowShortcuts(true)}
        aria-label="Mostrar atajos de teclado"
        whileHover={{ y: -2 }}
        className="fixed bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-3 text-xs text-p-text-faint bg-p-surface/90 backdrop-blur-glass border border-p-border rounded-xl px-4 py-2 shadow-lg hidden sm:flex hover:text-p-text hover:border-p-accent/40 transition-colors"
      >
        <span className="flex items-center gap-1"><kbd className="kbd-hint">{modLabel()}F</kbd> Buscar</span>
        <span className="flex items-center gap-1"><kbd className="kbd-hint">← →</kbd> Páginas</span>
        <span className="flex items-center gap-1"><kbd className="kbd-hint">{modLabel()}K</kbd> Comandos</span>
        <span className="flex items-center gap-1"><kbd className="kbd-hint">?</kbd> Ver todos</span>
      </motion.button>

      <AnimatePresence>
        {showShortcuts && (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setShowShortcuts(false)}
          >
            <motion.div
              className="card w-full max-w-md p-6"
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              transition={{ type: "spring", stiffness: 300, damping: 25 }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-heading text-lg font-semibold text-p-text">Atajos de teclado</h3>
                <motion.button whileTap={{ scale: 0.9 }} onClick={() => setShowShortcuts(false)} className="text-p-text-faint hover:text-p-text" aria-label="Cerrar">
                  <Keyboard className="w-5 h-5" />
                </motion.button>
              </div>
              <div className="space-y-3 text-sm">
                <div className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Navegación</div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="flex justify-between"><span>{modLabel()}F</span><span className="text-p-text-muted">Buscar</span></div>
                  <div className="flex justify-between"><span>← →</span><span className="text-p-text-muted">Páginas</span></div>
                  <div className="flex justify-between"><span>Esc</span><span className="text-p-text-muted">Limpiar filtros</span></div>
                  <div className="flex justify-between"><span>{modLabel()}K</span><span className="text-p-text-muted">Comandos</span></div>
                </div>
                <div className="text-xs font-semibold text-p-text-muted uppercase tracking-wide mt-2">Acciones</div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="flex justify-between"><span>{modLabel()}R</span><span className="text-p-text-muted">Recargar</span></div>
                  <div className="flex justify-between"><span>{modLabel()}E</span><span className="text-p-text-muted">Exportar</span></div>
                </div>
              </div>
              <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }} onClick={() => setShowShortcuts(false)} className="btn-primary w-full mt-4 justify-center">
                Entendido
              </motion.button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
