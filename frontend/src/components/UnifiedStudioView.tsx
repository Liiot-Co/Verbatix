import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Keyboard, Search, X } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { getPreliminary, getResolutionSummary, getRound, getVerbatimsSummary, isProcessingRequired, processRound } from "@/api/client";
import { isResolutionPhase } from "@/lib/studioStatus";
import type { CodingType, PreliminarySummary, ResolutionSummary, RoundStatus, VerbatimSummaryRow } from "@/api/types";
import Breadcrumb from "./Breadcrumb";
import ResolutionSidebar from "./ResolutionSidebar";
import ResolutionCenter from "./ResolutionCenter";
import { useKeyboardShortcuts, registerShortcuts, modLabel } from "@/hooks/useKeyboardShortcuts";
import { useSidebarResize } from "@/hooks/useSidebarResize";
import { useVerbatixStore } from "@/store/useVerbatixStore";
import { can } from "@/lib/capabilities";

// Decoupled components
import { StudioHeader } from "./studio/StudioHeader";
import { StudioSummaryCards } from "./studio/StudioSummaryCards";
import { VerbatimsTable } from "./studio/VerbatimsTable";
import PendingClassificationTable from "./studio/PendingClassificationTable";
import CodebookDraftReview from "./CodebookDraftReview";

/** Fullscreen shell for PendingClassificationTable as the "detailed" resolution view — opened from ResolutionSidebar's expand button, keeping the sidebar as the default surface. */
function DetailedResolutionView({
  subprojectId,
  codingType,
  onClose,
  onResolved,
  onFocusRow,
}: {
  subprojectId: string;
  codingType: CodingType;
  onClose: () => void;
  onResolved: () => void;
  onFocusRow: (groupId: string) => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 bg-p-bg flex flex-col">
      <div className="flex items-center justify-between gap-4 flex-wrap px-6 py-4 border-b border-p-border shrink-0">
        <h1 className="font-heading text-2xl font-semibold text-p-text tracking-tight">Centro de Resolución Detallada</h1>
        <button
          onClick={onClose}
          className="btn-ghost text-xs py-1.5 px-2"
          title="Cerrar (Esc)"
          aria-label="Cerrar"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="flex-1 min-h-0 px-6 py-4">
        <PendingClassificationTable
          subprojectId={subprojectId}
          codingType={codingType}
          onResolved={onResolved}
          onFocusRow={onFocusRow}
        />
      </div>
    </div>
  );
}

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

export default function UnifiedStudioView() {
  const { roundId } = useParams<{ roundId: string }>();
  const navigate = useNavigate();
  const searchRef = useRef<HTMLInputElement>(null);
  const showToast = useVerbatixStore((s) => s.showToast);
  const user = useVerbatixStore((s) => s.user);
  const canManageRound = can(user, "rounds.manage");
  const canViewResolution = can(user, "resolution.view");
  const hasReportCapability = can(user, "reports.view");

  const [round, setRound] = useState<RoundStatus | null>(null);
  const [activeSubprojectId, setActiveSubprojectId] = useState<string | null>(null);
  const [preliminary, setPreliminary] = useState<PreliminarySummary | null>(null);
  const [, setResolution] = useState<ResolutionSummary | null>(null);
  const [summaryView, setSummaryView] = useState<"pending" | "coded">("coded");
  const [summaryRows, setSummaryRows] = useState<VerbatimSummaryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [search, setSearch] = useState("");
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [fullscreenResolution, setFullscreenResolution] = useState(false);
  const [showDetailedResolution, setShowDetailedResolution] = useState(false);
  const [focusGroupId, setFocusGroupId] = useState<string | null>(null);
  const [pollCount, setPollCount] = useState(0);
  const { width: sidebarWidth, startResizing } = useSidebarResize(460, 320, 800);

  const loadData = useCallback(async () => {
    if (!roundId) return Promise.resolve();
    const currentRound = await getRound(roundId);
    setRound(currentRound);
    const subprojectId = activeSubprojectId
      ?? currentRound.subprojects.find((subproject) => subproject.coding_type === "brands")?.id
      ?? currentRound.subprojects[0]?.id;
    if (!subprojectId) return;
    if (!activeSubprojectId) setActiveSubprojectId(subprojectId);
    // Resolución/Preliminar solo responden una vez que la ronda alcanzó una fase
    // de resolución (ver require_resolution_phase en backend). Antes de eso el
    // motor sigue trabajando: no llamamos esos endpoints para no provocar 403
    // processing_required — la UI muestra el estado de procesamiento.
    const resolutionReady = isResolutionPhase(currentRound.status);
    const requests: Promise<unknown>[] = [];
    if (resolutionReady && (canManageRound || canViewResolution)) {
      requests.push(getPreliminary(roundId).then(setPreliminary));
    } else {
      setPreliminary(null);
    }
    if (resolutionReady && canViewResolution) {
      requests.push(getResolutionSummary(subprojectId).then(setResolution));
    } else {
      setResolution(null);
    }
    await Promise.allSettled(requests);
  }, [roundId, activeSubprojectId, canManageRound, canViewResolution]);

  const loadVerbatims = useCallback(() => {
    if (!activeSubprojectId || !isResolutionPhase(round?.status)) return;
    getVerbatimsSummary(activeSubprojectId, summaryView)
      .then((res) => setSummaryRows(res.items))
      .catch((err) => {
        if (!isProcessingRequired(err)) throw err;
      });
  }, [activeSubprojectId, summaryView, round?.status]);

  useEffect(() => {
    setLoading(true);
    void loadData().finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roundId, loadData]);

  useEffect(() => {
    if (!activeSubprojectId) return;
    if (!isResolutionPhase(round?.status)) {
      setSummaryRows([]);
      return;
    }
    setLoading(true);
    getVerbatimsSummary(activeSubprojectId, summaryView)
      .then((res) => setSummaryRows(res.items))
      .catch((err) => {
        if (!isProcessingRequired(err)) throw err;
      })
      .finally(() => setLoading(false));
  }, [activeSubprojectId, summaryView, round?.status]);

  const autoProcessing = round?.status === "processing" || round?.status === "files_uploaded";
  const wasProcessing = useRef(false);

  useEffect(() => {
    if (autoProcessing) {
      wasProcessing.current = true;
      return;
    }
    if (wasProcessing.current && round?.status === "preliminary_ready") {
      wasProcessing.current = false;
      setPollCount(0);
      showToast("Procesamiento terminado", "success");
      playProcessingFinishedSound();
      loadVerbatims();
    }
  }, [autoProcessing, round?.status, showToast, loadVerbatims]);

  useEffect(() => {
    if (!autoProcessing) return;
    const id = setInterval(() => {
      setPollCount((c) => c + 1);
      Promise.all([loadData(), loadVerbatims()]);
    }, 8000);
    return () => clearInterval(id);
  }, [autoProcessing, loadData, loadVerbatims]);

  const handleProcess = async () => {
    if (!roundId || !canManageRound) return;
    setProcessing(true);
    try {
      await processRound(roundId);
      showToast("Procesamiento encolado — el motor está trabajando", "info");
      setRound((r) => (r ? { ...r, status: "processing" } : r));
      await Promise.all([loadData(), loadVerbatims()]);
    } catch {
      showToast("No se pudo procesar la ronda", "error");
    } finally {
      setProcessing(false);
    }
  };

  const visible = useMemo(() => {
    if (!search.trim()) return summaryRows;
    const q = search.trim().toLowerCase();
    return summaryRows.filter(
      (r) => r.content?.toLowerCase().includes(q) || r.label?.toLowerCase().includes(q)
    );
  }, [summaryRows, search]);

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
          setSearch(""); setShowShortcuts(false);
          searchRef.current?.blur();
        },
        description: "Limpiar filtros / Cerrar", category: "Navegación" },
      { key: "?", meta: false, action: () => setShowShortcuts((v) => !v),
        description: "Mostrar atajos de teclado", category: "Navegación" },
    ]);
  }, [showToast]);

  useKeyboardShortcuts("unified-studio");

  if (loading && !round) {
    return (
      <div className="max-w-4xl mx-auto py-4 space-y-4">
        <div className="skeleton h-6 w-40 rounded" />
        <div className="skeleton h-40 rounded-2xl" />
        <div className="skeleton h-64 rounded-2xl" />
      </div>
    );
  }

  if (!roundId || !round) {
    return (
      <div className="max-w-4xl mx-auto py-4">
        <p className="text-sm text-p-text-faint">Ronda no encontrada.</p>
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
  const showOverlay = isProcessingNow || (autoProcessing && !isResolutionPhase(round?.status));
  const activeSubproject = round.subprojects.find((subproject) => subproject.id === activeSubprojectId)
    ?? round.subprojects[0];

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
          onClick={() => navigate(`/studies/${round.study_id}`)}
          className="shrink-0 w-6 h-6 flex items-center justify-center rounded-md text-p-text-faint hover:text-p-text hover:bg-p-bg-subtle transition-colors"
          title="Volver"
          aria-label="Volver"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
        </button>
        <Breadcrumb
          items={[
            { label: "Proyectos", to: "/" },
            ...(round.project_name ? [{ label: round.project_name, to: `/projects/${round.project_id}` }] : []),
            { label: round.study_name, to: `/studies/${round.study_id}` },
            { label: "Procesamiento" },
          ]}
        />
      </div>

      <div
        className={`grid grid-cols-1 gap-4 items-start ${canViewResolution && preliminary && !isProcessingNow && !fullscreenResolution ? "xl:[grid-template-columns:1fr_var(--sidebar-w)]" : ""}`}
        style={{ "--sidebar-w": `${sidebarWidth}px` } as React.CSSProperties}
      >
      <div className="space-y-4 min-w-0 order-2 xl:order-none">

      <StudioHeader
        studio={round}
        canManageRound={canManageRound}
        canViewReport={hasReportCapability && (canManageRound || round.audit.status === "approved")}
        autoProcessing={autoProcessing}
        neverProcessed={neverProcessed}
        isProcessingNow={isProcessingNow}
        onProcess={handleProcess}
      />

      {round.status === "codebook_review" && activeSubproject?.status === "codebook_review" && canManageRound ? (
        <CodebookDraftReview
          subprojectId={activeSubproject.id}
          onApproved={async () => {
            await loadData();
            await loadVerbatims();
          }}
        />
      ) : null}

      <div className="flex items-center gap-2 self-start">
        <span className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Clasificando:</span>
        <div className="inline-flex rounded-lg border border-p-border p-0.5">
        {round.subprojects.map((subproject) => (
          <button
            key={subproject.id}
            type="button"
            onClick={() => setActiveSubprojectId(subproject.id)}
            className={`px-5 py-2 text-sm rounded-md transition-colors ${activeSubproject?.id === subproject.id ? "bg-p-accent-mid/15 text-p-accent-mid font-medium" : "text-p-text-muted hover:text-p-text"}`}
          >
            {subproject.coding_type === "brands" ? "Marcas" : "Razones"}
          </button>
        ))}
        </div>
      </div>

      {canViewResolution && preliminary && (
        <StudioSummaryCards
          summary={summary}
          momentum={momentum}
          codedPct={codedPct}
          justFinished={justFinished}
          onOpenResolution={() => setShowDetailedResolution(true)}
        />
      )}

      <div className="flex flex-col sm:flex-row gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-p-text-faint pointer-events-none" />
          <input
            ref={searchRef}
            className="input w-full text-sm pl-10 pr-12"
            placeholder="Buscar..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <kbd className="hidden sm:flex items-center absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-mono text-p-text-faint border border-p-border rounded px-1.5 py-0.5 pointer-events-none">
            {modLabel()}F
          </kbd>
        </div>
        <div className="inline-flex rounded-lg border border-p-border p-0.5 shrink-0">
          <button
            type="button"
            onClick={() => setSummaryView("coded")}
            className={`px-5 py-2 text-sm rounded-md transition-colors ${summaryView === "coded" ? "bg-p-accent-mid/15 text-p-accent-mid font-medium" : "text-p-text-muted hover:text-p-text"}`}
          >
            Codificados
          </button>
          <button
            type="button"
            onClick={() => setSummaryView("pending")}
            className={`px-5 py-2 text-sm rounded-md transition-colors ${summaryView === "pending" ? "bg-p-accent-mid/15 text-p-accent-mid font-medium" : "text-p-text-muted hover:text-p-text"}`}
          >
            Pendientes
          </button>
        </div>
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

      <VerbatimsTable
        loading={loading && !round}
        rows={visible}
        search={search}
        processingOverlay={showOverlay ? {
          visible: true,
          status: round?.status,
          codedPct,
          autoCoded,
          pendingReview,
          anomalies,
          resolved,
          pollCount,
        } : null}
      />

      </div>

      {canViewResolution && preliminary && !isProcessingNow && !fullscreenResolution && (
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
            subprojectId={activeSubproject?.id ?? ""}
            codingType={activeSubproject?.coding_type ?? "brands"}
            auditRoundId={roundId}
            roundFullyResolved={!hasPending}
            onResolved={() => { loadData(); loadVerbatims(); }}
            onExpand={() => setShowDetailedResolution(true)}
          />
        </motion.div>
      )}
      </div>

      {canViewResolution && fullscreenResolution && !isProcessingNow && activeSubproject && (
        <ResolutionCenter
          subprojectId={activeSubproject.id}
          codingType={activeSubproject.coding_type}
          roundId={roundId}
          roundFullyResolved={!hasPending}
          onClose={() => { setFullscreenResolution(false); setFocusGroupId(null); }}
          onResolved={() => { loadData(); loadVerbatims(); }}
          initialFocusGroupId={focusGroupId}
        />
      )}

      {canViewResolution && showDetailedResolution && !isProcessingNow && activeSubproject && (
        <DetailedResolutionView
          subprojectId={activeSubproject.id}
          codingType={activeSubproject.coding_type}
          onClose={() => setShowDetailedResolution(false)}
          onResolved={() => { loadData(); loadVerbatims(); }}
          onFocusRow={(groupId) => { setFocusGroupId(groupId); setFullscreenResolution(true); }}
        />
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

    </div>
  );
}
