import { useCallback, useEffect, useRef } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { useWizardStore } from "@/store/useWizardStore";
import { resolveAnomaly, reopenResponse } from "@/api/client";
import { playSound } from "@/lib/sound";
import EntityCard from "@/components/EntityCard";
import CodePicker from "@/components/CodePicker";
import SessionSummary from "@/components/SessionSummary";
import type { SurveyItem } from "@/api/types";

interface Props {
  onAdvance: () => void;
}

export default function ReviewStage({ onAdvance }: Props) {
  const files               = useWizardStore((s) => s.files);
  const activeFileId        = useWizardStore((s) => s.activeFileId);
  const activeStudyMode     = useWizardStore((s) => s.activeStudyMode);
  const resolveItemsForFile = useWizardStore((s) => s.resolveItemsForFile);
  const reopenItemForFile   = useWizardStore((s) => s.reopenItemForFile);
  const showToast           = useWizardStore((s) => s.showToast);
  const focusedIdx          = useWizardStore((s) => s.focusedItemIdx);
  const setFocusedIdx       = useWizardStore((s) => s.setFocusedItemIdx);
  const session             = useWizardStore((s) => s.session);
  const startSession        = useWizardStore((s) => s.startSession);
  const recordResolution    = useWizardStore((s) => s.recordResolution);

  const [resolving, setResolving] = useState<number | null>(null);
  const [exitDir, setExitDir] = useState<"left" | "right">("right");
  const reducedMotion = useReducedMotion();

  const autoAdvancedRef = useRef<Set<string>>(new Set());

  const activeEntry   = files.find((f) => f.id === activeFileId);
  const currentIdx    = files.findIndex((f) => f.id === activeFileId) + 1;
  const totalFiles    = files.length;
  const items         = activeEntry?.items ?? [];
  const uploadResult  = activeEntry?.uploadResult;
  const pending       = items.filter((i) => i.status === "requires_human");
  const total         = uploadResult?.requires_human ?? pending.length;
  const done          = total - pending.length;
  const progress      = total > 0 ? done / total : 1;

  // Auto-advance when queue empties (once per file)
  useEffect(() => {
    if (!activeFileId || !activeEntry) return;
    if (pending.length > 0) return;
    if (autoAdvancedRef.current.has(activeFileId)) return;
    autoAdvancedRef.current.add(activeFileId);
    const timer = setTimeout(onAdvance, 1500);
    return () => clearTimeout(timer);
  }, [activeFileId, pending.length]);

  useEffect(() => {
    if (total > 0) startSession();
  }, [total, startSession]);

  // Arrow key navigation
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setFocusedIdx(Math.min(focusedIdx + 1, pending.length - 1));
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setFocusedIdx(Math.max(focusedIdx - 1, 0));
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [focusedIdx, pending.length, setFocusedIdx]);

  const undo = useCallback(
    async (responseId: number) => {
      if (!activeFileId) return;
      try {
        const reopened = await reopenResponse(responseId);
        reopenItemForFile(activeFileId, reopened);
      } catch {
        showToast("No se pudo deshacer", "error");
      }
    },
    [activeFileId, reopenItemForFile, showToast]
  );

  const resolve = useCallback(
    async (responseId: number, brand: string) => {
      if (!activeFileId) return;
      playSound("classify");
      setExitDir("right");
      setResolving(responseId);
      try {
        const result = await resolveAnomaly({
          response_id: responseId,
          resolved_brand: brand,
        });
        resolveItemsForFile(activeFileId, result.resolved, result.cascade_resolved);
        recordResolution(result.cascade_resolved.length);

        const undoAction = { label: "Deshacer", onAction: () => undo(responseId) };
        if (result.cascade_resolved.length > 0) {
          showToast(
            `"${brand}" guardado · +${result.cascade_resolved.length} resueltos en cascada`,
            "success",
            undoAction
          );
        } else {
          showToast(`"${brand}" guardado`, "success", undoAction);
        }
        setFocusedIdx(Math.max(0, Math.min(focusedIdx, pending.length - 2)));
      } catch (e) {
        showToast(
          e instanceof Error ? e.message : "Error al resolver",
          "error"
        );
      } finally {
        setResolving(null);
      }
    },
    [activeFileId, resolveItemsForFile, recordResolution, showToast, setFocusedIdx, pending.length, undo]
  );

  const handleApprove = useCallback(
    (item: SurveyItem) => {
      if (!item.suggested_brand) return;
      resolve(item.id, item.suggested_brand);
    },
    [resolve]
  );

  const handleReject = useCallback(
    async (responseId: number) => {
      if (!activeFileId) return;
      playSound("discard");
      setExitDir("left");
      setResolving(responseId);
      try {
        const result = await resolveAnomaly({
          response_id: responseId,
          resolved_brand: "__rejected__",
        });
        resolveItemsForFile(activeFileId, result.resolved, []);
        recordResolution();
        showToast("Rechazado", "info", { label: "Deshacer", onAction: () => undo(responseId) });
      } catch {
        showToast("Error al rechazar", "error");
      } finally {
        setResolving(null);
      }
    },
    [activeFileId, resolveItemsForFile, recordResolution, showToast, undo]
  );

  if (!activeEntry) return null;

  const focusedItem = pending[focusedIdx] ?? null;

  return (
    <div className="flex flex-col h-full gap-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-heading text-2xl font-semibold text-p-text tracking-tight">
            Centro de Resolución
          </h1>
          <p className="font-subtitle text-sm text-p-text-muted">
            Archivo {currentIdx} de {totalFiles} ·{" "}
            <span className="font-medium text-p-text">{activeEntry.name}</span>
            {" · "}
            {pending.length}{" "}
            {pending.length === 1
              ? "respuesta requiere"
              : "respuestas requieren"}{" "}
            validación
          </p>
          <p className="text-[11px] text-p-text-faint font-subtitle mt-1">
            {activeStudyMode === "codebook"
              ? "↑↓ navegar cola · ← rechazar · 1–9 alternar código · Enter guardar y avanzar"
              : "↑↓ navegar cola · ← rechazar · → o Enter aprobar · E editar"}
          </p>
        </div>
        <button onClick={onAdvance} className="btn-ghost shrink-0 text-sm">
          {currentIdx < totalFiles ? "Siguiente →" : "Ver Dashboard →"}
        </button>
      </div>

      {/* Progress bar */}
      <div className="card-subtle px-4 py-3 space-y-2 shrink-0">
        <div className="flex justify-between text-xs text-p-text-muted">
          <span>
            {done} de {total} resueltos
          </span>
          <span className="font-subtitle">{Math.round(progress * 100)}%</span>
        </div>
        <div className="h-1 rounded-full bg-p-bg-subtle overflow-hidden">
          <motion.div
            className="h-full rounded-full bg-gradient-to-r from-p-accent to-p-accent-mid"
            animate={{ width: `${progress * 100}%` }}
            transition={{ duration: 0.4, ease: "easeOut" }}
          />
        </div>
      </div>

      {pending.length > 0 && focusedItem ? (
        <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[1fr_380px] gap-4">
          {/* LEFT: pending queue */}
          <div className="card overflow-hidden flex flex-col min-h-0">
            <div className="px-4 py-2.5 border-b border-p-border shrink-0 flex items-center justify-between">
              <span className="text-xs font-subtitle uppercase tracking-wider text-p-text-faint">
                Cola pendiente
              </span>
              <span className="text-xs font-subtitle text-p-text-faint">{pending.length}</span>
            </div>
            <div className="flex-1 overflow-y-auto">
              {pending.map((item, idx) => (
                <button
                  key={item.id}
                  onClick={() => setFocusedIdx(idx)}
                  className={[
                    "w-full text-left px-4 py-2.5 flex items-center gap-3 border-b border-p-border last:border-0 transition-colors",
                    idx === focusedIdx ? "bg-p-accent-soft" : "hover:bg-p-bg-subtle",
                  ].join(" ")}
                >
                  <span className="text-[10px] font-subtitle text-p-text-faint w-5 shrink-0">
                    {idx + 1}
                  </span>
                  <span className="text-sm text-p-text truncate flex-1">
                    {item.original_text}
                  </span>
                  <span className="text-xs font-subtitle text-p-text-faint shrink-0">
                    {Math.round(item.confidence * 100)}%
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* RIGHT: single primary surface — which one depends on the study's mode.
              Exit slides toward whichever action just fired (← reject, → approve/save),
              like a swipe-to-classify card game. */}
          <div className="min-h-0 overflow-y-auto">
            <AnimatePresence mode="wait">
              <motion.div
                key={focusedItem.id}
                initial={reducedMotion ? { opacity: 0 } : { opacity: 0, y: 10, scale: 0.98 }}
                animate={reducedMotion ? { opacity: 1 } : { opacity: 1, y: 0, scale: 1 }}
                exit={
                  reducedMotion
                    ? { opacity: 0 }
                    : exitDir === "left"
                    ? { opacity: 0, x: -140, rotate: -6 }
                    : { opacity: 0, x: 140, rotate: 6 }
                }
                transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
              >
                {activeStudyMode === "codebook" ? (
                  <>
                    <EntityCard
                      item={focusedItem}
                      readOnly
                      focused={false}
                      onFocus={() => {}}
                      onApprove={() => {}}
                      onReject={() => {}}
                      onEdit={() => {}}
                    />
                    <div className="card p-5 mt-3 space-y-3">
                      <CodePicker
                        item={focusedItem}
                        fileId={activeEntry.id}
                        onSaved={() => setFocusedIdx(Math.max(0, Math.min(focusedIdx, pending.length - 2)))}
                        onReject={() => handleReject(focusedItem.id)}
                      />
                      <button
                        onClick={() => handleReject(focusedItem.id)}
                        className="text-xs text-p-text-faint hover:text-p-error transition-colors w-full text-center"
                      >
                        Rechazar esta respuesta
                      </button>
                    </div>
                  </>
                ) : (
                  <EntityCard
                    item={focusedItem}
                    focused={resolving === null}
                    onFocus={() => {}}
                    onApprove={() => handleApprove(focusedItem)}
                    onReject={() => handleReject(focusedItem.id)}
                    onEdit={(brand) => resolve(focusedItem.id, brand)}
                  />
                )}
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      ) : (
        <motion.div
          key="done"
          initial={{ opacity: 0, scale: 0.97 }}
          animate={{ opacity: 1, scale: 1 }}
          className="card p-10 text-center space-y-3"
        >
          <p className="text-2xl">✓</p>
          <p className="font-semibold text-p-text">Cola completada</p>
          <p className="text-sm text-p-text-muted">
            {currentIdx < totalFiles
              ? `Avanzando al archivo ${currentIdx + 1} de ${totalFiles}...`
              : "Todas las respuestas fueron resueltas."}
          </p>
          <SessionSummary session={session} />
          <button
            onClick={onAdvance}
            className="btn-primary text-sm mx-auto"
          >
            {currentIdx < totalFiles
              ? `Ir al archivo ${currentIdx + 1} →`
              : "Ir al Dashboard →"}
          </button>
        </motion.div>
      )}

      {resolving !== null && (
        <div className="fixed bottom-6 right-6 card px-4 py-2 flex items-center gap-2 text-sm shadow-lg">
          <Loader2 className="w-4 h-4 animate-spin text-p-accent" />
          <span className="text-p-text-muted">
            Guardando y verificando cascada...
          </span>
        </div>
      )}
    </div>
  );
}
