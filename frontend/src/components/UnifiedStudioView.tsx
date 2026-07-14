import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ChevronLeft, ChevronRight, Keyboard, Search } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { getPreliminary, getResolutionSummary, getStudio, getVerbatims, processStudio } from "@/api/client";
import type { CodingStatus, PreliminarySummary, ResolutionSummary, StudioStatus, Verbatim } from "@/api/types";
import Breadcrumb from "./Breadcrumb";
import ResolutionSidebar from "./ResolutionSidebar";
import ResolutionCenter from "./ResolutionCenter";
import { PhaseCompleteChoice } from "./PhaseCompleteChoice";
import { studyDisplayName, studyKey } from "@/lib/projectTree";
import { useKeyboardShortcuts, registerShortcuts, modLabel } from "@/hooks/useKeyboardShortcuts";
import { useSidebarResize } from "@/hooks/useSidebarResize";
import { useVerbatixStore } from "@/store/useVerbatixStore";

// Decoupled components
import { AgentProcessingUI } from "./studio/AgentProcessingUI";
import { StudioHeader } from "./studio/StudioHeader";
import { StudioSummaryCards } from "./studio/StudioSummaryCards";
import { VerbatimsTable } from "./studio/VerbatimsTable";

function playProcessingFinishedSound() {
  try {
    const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new Ctx();
    const osc1 = ctx.createOscillator();
    const osc2 = ctx.createOscillator();
    const gainNode = ctx.createGain();
    
    osc1.connect(gainNode);
    osc2.connect(gainNode);
    gainNode.connect(ctx.destination);
    
    osc1.type = "sine";
    osc2.type = "triangle";
    
    const now = ctx.currentTime;
    
    osc1.frequency.setValueAtTime(523.25, now); // C5
    osc2.frequency.setValueAtTime(523.25, now);
    
    osc1.frequency.setValueAtTime(659.25, now + 0.1); // E5
    osc2.frequency.setValueAtTime(659.25, now + 0.1);
    
    osc1.frequency.setValueAtTime(783.99, now + 0.2); // G5
    osc2.frequency.setValueAtTime(783.99, now + 0.2);
    
    osc1.frequency.setValueAtTime(1046.50, now + 0.3); // C6
    osc2.frequency.setValueAtTime(1046.50, now + 0.3);
    
    gainNode.gain.setValueAtTime(0, now);
    gainNode.gain.linearRampToValueAtTime(0.1, now + 0.05);
    gainNode.gain.exponentialRampToValueAtTime(0.001, now + 0.6);
    
    osc1.start(now);
    osc2.start(now);
    osc1.stop(now + 0.65);
    osc2.stop(now + 0.65);
  } catch {
    // silent fallback
  }
}

const PAGE_SIZE = 50;

export default function UnifiedStudioView() {
  const { studioId } = useParams<{ studioId: string }>();
  const navigate = useNavigate();
  const searchRef = useRef<HTMLInputElement>(null);
  const showToast = useVerbatixStore((s) => s.showToast);

  const [studio, setStudio] = useState<StudioStatus | null>(null);
  const [preliminary, setPreliminary] = useState<PreliminarySummary | null>(null);
  const [resolution, setResolution] = useState<ResolutionSummary | null>(null);
  const [verbatims, setVerbatims] = useState<Verbatim[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [statusFilter, setStatusFilter] = useState<CodingStatus | "">("");
  const [search, setSearch] = useState("");
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [fullscreenResolution, setFullscreenResolution] = useState(false);
  const [phaseChoiceOpen, setPhaseChoiceOpen] = useState(false);
  const { width: sidebarWidth, startResizing } = useSidebarResize(460, 320, 800);

  const loadData = useCallback(() => {
    if (!studioId) return Promise.resolve();
    return Promise.all([
      getStudio(studioId).then(setStudio),
      getPreliminary(studioId).then(setPreliminary),
      getResolutionSummary(studioId).then(setResolution),
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
      getResolutionSummary(studioId!).then(setResolution),
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

  const autoProcessing = studio?.status === "processing" || studio?.status === "files_uploaded";
  const wasProcessing = useRef(false);

  useEffect(() => {
    if (autoProcessing) {
      wasProcessing.current = true;
      return;
    }
    if (wasProcessing.current && studio?.status === "preliminary_ready") {
      wasProcessing.current = false;
      showToast("Procesamiento terminado", "success");
      playProcessingFinishedSound();
      loadVerbatims();
    }
  }, [autoProcessing, studio?.status, showToast, loadVerbatims]);

  useEffect(() => {
    if (!autoProcessing) return;
    const id = setInterval(() => {
      Promise.all([loadData(), loadVerbatims()]);
    }, 8000);
    return () => clearInterval(id);
  }, [autoProcessing, loadData, loadVerbatims]);

  // Tras cerrar resolución: elegir reporte o auditoría. Si ya estaba cerrada al entrar, ir al reporte.
  const wasCloseable = useRef<boolean | null>(null);
  useEffect(() => {
    if (!studioId || resolution == null) return;
    const canClose = resolution.can_close;

    if (canClose && wasCloseable.current === null) {
      navigate(`/studios/${studioId}/report`, { replace: true });
      return;
    }
    if (canClose && wasCloseable.current === false) {
      setPhaseChoiceOpen(true);
    }
    wasCloseable.current = canClose;
  }, [studioId, resolution, navigate]);

  const handleProcess = async () => {
    if (!studioId) return;
    setProcessing(true);
    try {
      await processStudio(studioId);
      showToast("Procesamiento encolado — el motor está trabajando", "info");
      setStudio((s) => (s ? { ...s, status: "processing" } : s));
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
    <div className="max-w-[1400px] mx-auto py-4 space-y-4">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => navigate(`/projects/${studio.project_id}/studies/${studyKey(studio.coding_type, studio.name)}`)}
          className="shrink-0 w-6 h-6 flex items-center justify-center rounded-md text-p-text-faint hover:text-p-text hover:bg-p-bg-subtle transition-colors"
          title="Volver"
          aria-label="Volver"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
        </button>
        <Breadcrumb
          items={[
            { label: "Proyectos", to: "/" },
            { label: studio.project_name, to: `/projects/${studio.project_id}` },
            {
              label: studyDisplayName(studio.name, studio.coding_type),
              to: `/projects/${studio.project_id}/studies/${studyKey(studio.coding_type, studio.name)}`,
            },
            { label: "Procesamiento" },
          ]}
        />
      </div>

      <div 
        className={`grid grid-cols-1 gap-4 items-start ${preliminary && !isProcessingNow && !fullscreenResolution ? "xl:[grid-template-columns:1fr_var(--sidebar-w)]" : ""}`}
        style={{ "--sidebar-w": `${sidebarWidth}px` } as React.CSSProperties}
      >
      <div className="space-y-4 min-w-0 order-2 xl:order-none">

      <StudioHeader
        studio={studio}
        autoProcessing={autoProcessing}
        neverProcessed={neverProcessed}
        isProcessingNow={isProcessingNow}
        onProcess={handleProcess}
      />

      {preliminary && (
        <StudioSummaryCards
          summary={summary}
          momentum={momentum}
          codedPct={codedPct}
          justFinished={justFinished}
          onOpenResolution={() => setFullscreenResolution(true)}
        />
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
        <motion.button
          type="button"
          onClick={() => setShowShortcuts(true)}
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
          title="Ver atajos de teclado"
          aria-label="Ver atajos de teclado"
          className="hidden sm:flex items-center gap-1.5 px-3 text-xs text-p-text-faint hover:text-p-text border border-p-border rounded-lg hover:border-p-accent/40 transition-colors shrink-0"
        >
          <Keyboard className="w-3.5 h-3.5" />
          <kbd className="kbd-hint">?</kbd>
        </motion.button>
      </div>

      {isProcessingNow && (
        <div className="card p-4 border border-p-accent/20 bg-p-surface/40 mb-4">
          <AgentProcessingUI />
        </div>
      )}

      <VerbatimsTable
        loading={loading}
        verbatims={visible}
        search={search}
        startIndex={(page - 1) * PAGE_SIZE}
      />

      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-p-text-muted">
          <span>Página {page} de {totalPages} · {total} verbatims</span>
          <div className="flex items-center gap-1.5">
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

      </div>

      {preliminary && !isProcessingNow && !fullscreenResolution && (
        <motion.div
          initial={{ opacity: 0, x: 40, scale: 0.95 }}
          animate={{ opacity: 1, x: 0, scale: 1 }}
          transition={{ type: "spring", stiffness: 350, damping: 25, delay: 0.1 }}
          className="order-1 xl:order-none xl:sticky xl:top-4 h-auto xl:h-[calc(100vh-5rem)] relative"
        >
          <div
            className="hidden xl:flex absolute -left-4 top-0 w-4 h-full cursor-col-resize items-center justify-center z-10 opacity-0 hover:opacity-100 transition-opacity group"
            onMouseDown={startResizing}
            title="Ajustar ancho"
          >
            <div className="w-1 h-12 bg-p-text-muted/30 group-hover:bg-p-accent rounded-full transition-colors" />
          </div>
          <ResolutionSidebar
            studioId={studioId}
            onResolved={() => { loadData(); loadVerbatims(); }}
            onExpand={() => setFullscreenResolution(true)}
          />
        </motion.div>
      )}
      </div>

      {fullscreenResolution && !isProcessingNow && (
        <ResolutionCenter studioId={studioId} onClose={() => setFullscreenResolution(false)} />
      )}

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
                  <div className="flex justify-between"><span>Esc</span><span className="text-p-text-muted">Limpiar filtros</span></div>
                  <div className="flex justify-between"><span>{modLabel()}K</span><span className="text-p-text-muted">Comandos</span></div>
                </div>
                <div className="text-xs font-semibold text-p-text-muted uppercase tracking-wide mt-2">Acciones</div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="flex justify-between"><span>{modLabel()}R</span><span className="text-p-text-muted">Recargar</span></div>
                  <div className="flex justify-between"><span>{modLabel()}E</span><span className="text-p-text-muted">Exportar</span></div>
                </div>
                <div className="text-xs font-semibold text-p-text-muted uppercase tracking-wide mt-2">Centro de Resolución</div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="flex justify-between"><span>←↑↓→</span><span className="text-p-text-muted">Navegar códigos</span></div>
                  <div className="flex justify-between"><span>↵</span><span className="text-p-text-muted">Asignar</span></div>
                  <div className="flex justify-between"><span>d</span><span className="text-p-text-muted">Sin dato</span></div>
                  <div className="flex justify-between"><span>n</span><span className="text-p-text-muted">Nueva marca</span></div>
                  <div className="flex justify-between"><span>1-9</span><span className="text-p-text-muted">Código rápido</span></div>
                  <div className="flex justify-between"><span>a-z</span><span className="text-p-text-muted">Filtrar códigos</span></div>
                </div>
              </div>
              <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }} onClick={() => setShowShortcuts(false)} className="btn-primary w-full mt-4 justify-center">
                Entendido
              </motion.button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {phaseChoiceOpen && studioId && (
        <PhaseCompleteChoice
          studioId={studioId}
          variant="modal"
          onDismiss={() => setPhaseChoiceOpen(false)}
        />
      )}
    </div>
  );
}


