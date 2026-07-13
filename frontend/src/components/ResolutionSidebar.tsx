import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, Check, CheckCircle2, Maximize2, Plus, Sparkles } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
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
import { registerShortcuts, useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { useVerbatixStore } from "@/store/useVerbatixStore";

const PAGE_SIZE = 50;
const MAX_DOTS = 12;

const STATUS_CHIP: Record<MentionGroupStatus, { label: string; className: string }> = {
  anomaly: { label: "Confusa", className: "badge-error" },
  below_threshold: { label: "Bajo umbral", className: "badge-warning" },
  pending_review: { label: "Sin revisar", className: "badge-pending" },
  auto_coded: { label: "Sugerido", className: "badge-auto" },
  resolved: { label: "Resuelto", className: "badge-success" },
};

// Stable per-code color, same idea as the mockup's per-category hue.
function codeColor(codeNumber: number): string {
  const hue = (codeNumber * 47) % 360;
  return `oklch(0.55 0.14 ${hue})`;
}

// Chirp up for "classify", chirp down for "discard" — same trick as the mockup's gamified feel.
function playSound(type: "classify" | "discard") {
  try {
    const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = "sine";
    if (type === "classify") {
      osc.frequency.setValueAtTime(480, ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(920, ctx.currentTime + 0.13);
      gain.gain.setValueAtTime(0.1, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.28);
    } else {
      osc.frequency.setValueAtTime(340, ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(170, ctx.currentTime + 0.12);
      gain.gain.setValueAtTime(0.07, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.22);
    }
    osc.start();
    osc.stop(ctx.currentTime + 0.32);
  } catch {
    // Web Audio unavailable — silent is fine, this is a nice-to-have.
  }
}

/**
 * Gamified "one mention at a time" resolution sidebar — matches the mockup's
 * "Centro de Resolución" panel: dot progress, swipe/keyboard card resolution,
 * a keyboard-navigable code grid, sound feedback. Reused standalone (full-page
 * ResolutionCenter) and embedded (UnifiedStudioView's workspace column).
 */
export default function ResolutionSidebar({
  studioId,
  onResolved,
  onExpand,
}: {
  studioId: string;
  /** Called after each successful resolve — lets a parent (e.g. a queue list) refresh. */
  onResolved?: () => void;
  /** Shows a fullscreen-expand button in the header when provided. */
  onExpand?: () => void;
}) {
  const showToast = useVerbatixStore((s) => s.showToast);
  const newCodeInputRef = useRef<HTMLInputElement>(null);
  const discardBtnRef = useRef<HTMLButtonElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0 });

  const [queue, setQueue] = useState<ResolutionQueueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [, setSummary] = useState<ResolutionSummary | null>(null);
  const [codes, setCodes] = useState<StudioCode[]>([]);
  const [systemCodes, setSystemCodes] = useState<StudioCode[]>([]);
  const [detail, setDetail] = useState<MentionGroupDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [resolving, setResolving] = useState(false);
  const [resolvedThisSession, setResolvedThisSession] = useState(0);

  const [cardExiting, setCardExiting] = useState<"up" | "down" | null>(null);
  const [cardVisible, setCardVisible] = useState(true);
  const [navCodeIndex, setNavCodeIndex] = useState(0);
  const [showNewCodeInput, setShowNewCodeInput] = useState(false);
  const [showDiscardMenu, setShowDiscardMenu] = useState(false);
  const [navDiscardIndex, setNavDiscardIndex] = useState(0);
  const [newCodeLabel, setNewCodeLabel] = useState("");
  const [addAlias, setAddAlias] = useState(true);
  // Zonas de foco tipo Excel: "header" = tarjeta de la mención (←/→ descartan/crean),
  // "list" = grilla de marcas (las 4 flechas navegan). ↓ baja a la lista, ↑ desde la primera fila vuelve.
  const [zone, setZone] = useState<"header" | "list">("header");
  const [gridCols, setGridCols] = useState(() => {
    const saved = localStorage.getItem("resolution-grid-cols");
    return saved ? parseInt(saved, 10) : 2;
  });
  const [autoCols, setAutoCols] = useState(() => {
    const saved = localStorage.getItem("resolution-auto-cols");
    return saved !== "false";
  });
  const sidebarRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    localStorage.setItem("resolution-grid-cols", gridCols.toString());
  }, [gridCols]);

  useEffect(() => {
    localStorage.setItem("resolution-auto-cols", autoCols ? "true" : "false");
  }, [autoCols]);

  useEffect(() => {
    if (!autoCols || !sidebarRef.current) return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (!rect) return;
      const { width } = rect;
      let newCols = 2;
      if (width >= 650) newCols = 4;
      else if (width >= 480) newCols = 3;
      else if (width >= 350) newCols = 2;
      else newCols = 1;

      setGridCols((prev) => (prev !== newCols ? newCols : prev));
    });
    observer.observe(sidebarRef.current);
    return () => observer.disconnect();
  }, [autoCols]);

  const currentCard = queue[0] ?? null;

  const loadQueue = useCallback(() => {
    return getResolutionQueue(studioId, PAGE_SIZE, 0).then((res) => {
      setQueue(res.items);
      setTotal(res.total);
    });
  }, [studioId]);

  const loadSummary = useCallback(() => {
    return getResolutionSummary(studioId).then(setSummary);
  }, [studioId]);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      loadQueue(), 
      loadSummary(), 
      getStudioCodes(studioId, true).then((allCodes) => {
        setCodes(allCodes.filter(c => !c.is_system));
        setSystemCodes(allCodes.filter(c => c.is_system).sort((a, b) => a.code_number - b.code_number));
      })
    ]).finally(() => setLoading(false));
  }, [studioId, loadQueue, loadSummary]);

  useEffect(() => {
    if (!currentCard) {
      setDetail(null);
      return;
    }
    setShowDiscardMenu(false);
    setShowNewCodeInput(false);
    setNewCodeLabel("");
    setZone("header");
    getMentionGroup(currentCard.id).then(setDetail);
  }, [currentCard]);

  // Pre-highlight the engine's suggested code when a new card comes up.
  useEffect(() => {
    if (!detail?.suggested_code) {
      setNavCodeIndex(0);
      return;
    }
    const idx = codes.findIndex((c) => c.id === detail.suggested_code!.id);
    setNavCodeIndex(idx >= 0 ? idx : 0);
  }, [detail, codes]);

  // Como en Excel: el scroll de la grilla sigue a la celda seleccionada.
  useEffect(() => {
    gridRef.current?.children[navCodeIndex]?.scrollIntoView({ block: "nearest" });
  }, [navCodeIndex, zone]);

  const applyOptimisticRemoval = (groupId: string) => {
    const snapshot = queue;
    const next = snapshot.filter((g) => g.id !== groupId);
    setQueue(next);
    setTotal((t) => Math.max(0, t - 1));
    return () => {
      setQueue(snapshot);
      setTotal((t) => t + 1);
    };
  };

  const resolve = useCallback(
    async (groupId: string, decision: ResolveDecision) => {
      const rollback = applyOptimisticRemoval(groupId);
      setResolvedThisSession((n) => n + 1);
      try {
        const result = await resolveMentionGroup(groupId, decision);
        if (result.auto_resolved_groups && result.auto_resolved_groups.length > 0) {
          const autoIds = new Set(result.auto_resolved_groups.map((g) => g.id));
          setQueue((q) => q.filter((g) => !autoIds.has(g.id)));
          setTotal((t) => Math.max(0, t - result.auto_resolved_groups.length));
          setResolvedThisSession((n) => n + result.auto_resolved_groups.length);
          const codeLabel = result.codes_assigned[0]?.label;
          const texts = result.auto_resolved_groups.map((g) => `«${g.normalized_text}»`);
          const shown = texts.slice(0, 3).join(", ") + (texts.length > 3 ? ` y ${texts.length - 3} más` : "");
          showToast(
            codeLabel ? `Auto-clasificados como «${codeLabel}»: ${shown}` : `Auto-clasificados: ${shown}`,
            "success"
          );
        }
        loadSummary();
        onResolved?.();
      } catch {
        rollback();
        setResolvedThisSession((n) => Math.max(0, n - 1));
        showToast("No se pudo resolver el grupo. Intenta de nuevo.", "error");
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [queue, loadSummary, showToast, onResolved]
  );

  // Exit animation plays for 230ms while the (already-optimistic) resolve happens
  // underneath, then the new current card fades back in — same timing as the mockup.
  const playAndResolve = useCallback(
    (direction: "up" | "down", groupId: string, decision: ResolveDecision) => {
      if (cardExiting || resolving) return;
      setResolving(true);
      playSound(direction === "up" ? "discard" : "classify");
      setCardExiting(direction);
      setCardVisible(false);
      resolve(groupId, decision);
      setTimeout(() => {
        setCardExiting(null);
        setCardVisible(false);
        setResolving(false);
        setTimeout(() => setCardVisible(true), 20);
      }, 230);
    },
    [cardExiting, resolving, resolve]
  );

  const discardCurrent = useCallback(() => {
    if (!currentCard || cardExiting) return;
    if (!showDiscardMenu) {
      if (discardBtnRef.current) {
        const rect = discardBtnRef.current.getBoundingClientRect();
        setMenuPos({ top: rect.top + rect.height / 2, left: rect.left });
      }
      setShowDiscardMenu(true);
      setShowNewCodeInput(false);
    } else {
      setShowDiscardMenu(false);
    }
  }, [currentCard, cardExiting, showDiscardMenu]);

  const assignCode = useCallback(
    (codeId: string) => {
      if (!currentCard) return;
      playAndResolve("down", currentCard.id, {
        action: "approve",
        code_ids: [codeId],
        new_code: null,
        add_alias: addAlias,
      });
    },
    [currentCard, addAlias, playAndResolve]
  );

  const assignHighlighted = useCallback(() => {
    const code = codes[navCodeIndex];
    if (code) assignCode(code.id);
  }, [codes, navCodeIndex, assignCode]);

  const createAndAssign = useCallback(
    (label: string) => {
      if (!currentCard) return;
      const trimmed = label.trim() || currentCard.normalized_text;
      playAndResolve("down", currentCard.id, {
        action: "approve",
        code_ids: [],
        new_code: { label: trimmed },
        add_alias: addAlias,
      });
    },
    [currentCard, addAlias, playAndResolve]
  );

  const openNewCodeInput = useCallback(() => {
    if (!currentCard || cardExiting) return;
    setShowNewCodeInput(true);
    setShowDiscardMenu(false);
    setNewCodeLabel(currentCard.normalized_text);
    setTimeout(() => newCodeInputRef.current?.focus(), 60);
  }, [currentCard, cardExiting]);

  useEffect(() => {
    registerShortcuts("resolution-sidebar", [
      { 
        key: "Enter", 
        action: () => {
          if (showDiscardMenu) {
            const sc = systemCodes[navDiscardIndex];
            if (sc) assignCode(sc.id);
          } else {
            assignHighlighted();
          }
        }, 
        description: "Asignar código", 
        category: "Acciones" 
      },
      {
        key: "ArrowLeft",
        action: () => {
          if (showDiscardMenu) return;
          if (zone === "list") {
            setNavCodeIndex((i) => (i % gridCols > 0 ? i - 1 : i));
          } else {
            discardCurrent();
          }
        },
        description: "Descartar / Navegar izquierda",
        category: "Acciones",
      },
      { key: "d", action: discardCurrent, description: "Descartar", category: "Acciones" },
      {
        key: "ArrowRight",
        action: () => {
          if (showDiscardMenu) {
            setShowDiscardMenu(false);
          } else if (zone === "list") {
            setNavCodeIndex((i) => (i % gridCols < gridCols - 1 && i + 1 < codes.length ? i + 1 : i));
          } else {
            openNewCodeInput();
          }
        },
        description: "Nueva marca / Navegar derecha",
        category: "Acciones",
      },
      { key: "n", action: openNewCodeInput, description: "Nueva marca", category: "Acciones" },
      {
        key: "ArrowUp",
        action: () => {
          if (showDiscardMenu) {
            setNavDiscardIndex(i => Math.max(0, i - 1));
          } else if (zone === "list") {
            if (navCodeIndex < gridCols) {
              setZone("header");
            } else {
              setNavCodeIndex((i) => i - gridCols);
            }
          }
        },
        description: "Navegar arriba / Volver a la mención",
        category: "Navegación",
      },
      {
        key: "ArrowDown",
        action: () => {
          if (showDiscardMenu) {
            setNavDiscardIndex(i => Math.min(systemCodes.length - 1, i + 1));
          } else if (zone === "header") {
            setZone("list");
          } else {
            setNavCodeIndex((i) => Math.min(codes.length - 1, i + gridCols));
          }
        },
        description: "Navegar abajo / Ir a marcas",
        category: "Navegación",
      },
      ...Array.from({ length: 9 }, (_, i) => ({
        key: String(i + 1),
        action: () => {
          if (showDiscardMenu) {
            if (systemCodes[i]) assignCode(systemCodes[i].id);
          } else {
            if (codes[i]) assignCode(codes[i].id);
          }
        },
        description: `Asignar código #${i + 1}`,
        category: "Códigos rápidos",
      })),
      {
        key: "Escape",
        action: () => {
          setShowDiscardMenu(false);
          setShowNewCodeInput(false);
          setZone("header");
        },
        description: "Cerrar menús",
        category: "Acciones",
      },
    ]);
  }, [assignHighlighted, discardCurrent, openNewCodeInput, codes, systemCodes, assignCode, showDiscardMenu, zone, navCodeIndex, navDiscardIndex, gridCols]);

  useKeyboardShortcuts("resolution-sidebar");

  const dotStates = useMemo(() => {
    const totalDots = Math.min(MAX_DOTS, resolvedThisSession + queue.length);
    return Array.from({ length: totalDots }, (_, i) => {
      if (i < resolvedThisSession) return "done";
      if (i === resolvedThisSession && queue.length > 0) return "current";
      return "pending";
    });
  }, [resolvedThisSession, queue.length]);

  const cardMotion = useMemo(() => {
    if (cardExiting === "up") return { opacity: 0, y: -80, rotate: -8 };
    if (cardExiting === "down") return { opacity: 0, y: 80, rotate: 5 };
    if (cardVisible) return { opacity: 1, y: 0, rotate: 0, scale: 1 };
    return { opacity: 0, y: 12, scale: 0.97 };
  }, [cardExiting, cardVisible]);

  const allResolved = !loading && queue.length === 0;

  return (
    <div ref={sidebarRef} className="card overflow-hidden flex flex-col h-full">
      <div className="px-4 pt-3.5 pb-2.5 bg-p-surface border-b border-p-border shrink-0">
        <div className="flex items-center justify-between text-sm font-bold text-p-text mb-2.5">
          <span>Centro de Resolución</span>
          <div className="flex items-center gap-2">
            {onExpand && (
              <button
                onClick={onExpand}
                className="text-p-text-faint hover:text-p-text transition-colors"
                title="Abrir en pantalla completa"
                aria-label="Abrir en pantalla completa"
              >
                <Maximize2 className="w-3.5 h-3.5" />
              </button>
            )}
            <span className={total > 0 ? "badge-warning" : "badge-success"}>{total} RESTANTES</span>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {dotStates.map((st, i) => (
            <span
              key={i}
              className={[
                "w-2 h-2 rounded-full transition-colors",
                st === "done" ? "bg-p-success" : st === "current" ? "bg-p-warning ring-4 ring-p-warning/20" : "bg-p-bg-subtle",
              ].join(" ")}
            />
          ))}
          <span className="font-mono text-[11px] text-p-text-faint ml-1">
            {resolvedThisSession}/{resolvedThisSession + total}
          </span>
        </div>
      </div>

      {allResolved ? (
        <div className="flex-1 overflow-y-auto scrollbar-thin p-4 flex flex-col">
          <div className="flex-1 bg-p-surface border border-p-border rounded-2xl flex flex-col items-center justify-center gap-2.5 text-center">
            <div className="w-12 h-12 rounded-full bg-green-50 border border-green-200 flex items-center justify-center">
              <CheckCircle2 className="w-6 h-6 text-p-success" />
            </div>
            <div>
              <div className="font-semibold text-sm text-p-text mb-0.5">¡Todo clasificado!</div>
              <div className="text-sm text-p-text-muted">Podés finalizar el proceso.</div>
            </div>
          </div>
        </div>
      ) : currentCard && detail ? (
        <>
          {/* Top zone: mención actual — fixed in place, never scrolls out of view */}
          <div className="p-4 pb-0 shrink-0">
            <motion.div
              animate={cardMotion}
              transition={{ duration: 0.23, ease: cardExiting ? "easeIn" : ([0.22, 1.4, 0.36, 1] as const) }}
              className={[
                "bg-gradient-to-br from-orange-50 via-white to-purple-50 border border-p-border rounded-2xl p-4 transition-shadow",
                zone === "header" ? "ring-2 ring-p-accent/25" : "",
              ].join(" ")}
            >
              <div className="flex items-center justify-between mb-2.5">
                <span className="font-mono text-[10.5px] tracking-wide uppercase text-p-accent">
                  Revisar · mención #{resolvedThisSession + 1}
                </span>
                <span className={STATUS_CHIP[detail.status].className}>{STATUS_CHIP[detail.status].label}</span>
              </div>
              <div className="font-extrabold text-lg tracking-tight text-p-text mb-1.5">{detail.normalized_text}</div>
              <div className="font-mono text-[11px] text-p-text-faint mb-3">{detail.frequency_count} menciones</div>

              <div className="pt-2.5 border-t border-p-border/60">
                {showNewCodeInput ? (
                  <div className="flex flex-col gap-2">
                    <label className="font-mono text-[10.5px] tracking-wide uppercase text-blue-600">
                      Nombre de nueva marca
                    </label>
                    <input
                      ref={newCodeInputRef}
                      type="text"
                      value={newCodeLabel}
                      onChange={(e) => setNewCodeLabel(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          createAndAssign(newCodeLabel);
                        } else if (e.key === "Escape") {
                          setShowNewCodeInput(false);
                          setNewCodeLabel("");
                        }
                      }}
                      className="input text-sm font-semibold"
                    />
                    <div className="flex gap-1.5">
                      <button
                        onClick={() => {
                          setShowNewCodeInput(false);
                          setNewCodeLabel("");
                        }}
                        className="flex-1 inline-flex items-center justify-center px-3 py-2 rounded-lg border border-p-border bg-p-bg-subtle text-sm text-p-text-muted"
                      >
                        <kbd className="kbd-hint mr-1">Esc</kbd> Cancelar
                      </button>
                      <button
                        onClick={() => createAndAssign(newCodeLabel)}
                        disabled={resolving}
                        className="flex-[2] inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg border border-green-200 bg-green-50 text-sm font-bold text-green-700"
                      >
                        <Plus className="w-3.5 h-3.5" /> Crear <kbd className="kbd-hint ml-1">↵</kbd>
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex gap-1.5 relative">
                    <button
                      ref={discardBtnRef}
                      onClick={discardCurrent}
                      disabled={resolving}
                      className="flex-1 inline-flex items-center justify-center gap-1 px-2.5 py-2 rounded-lg border border-p-border bg-p-bg-subtle text-sm text-p-text-muted hover:bg-p-surface transition-colors"
                    >
                      <kbd className="kbd-hint">←</kbd>
                      <span>Descartar</span>
                    </button>
                    
                    {/* Radial Discard Menu (Game-like Popover via Portal) */}
                    {createPortal(
                      <>
                        {showDiscardMenu && (
                          <div 
                            className="fixed inset-0 z-[9998]"
                            onClick={(e) => {
                              e.stopPropagation();
                              setShowDiscardMenu(false);
                            }}
                          />
                        )}
                        <AnimatePresence>
                          {showDiscardMenu && (
                            <div className="fixed z-[9999]" style={{ top: menuPos.top, left: menuPos.left }}>
                              {systemCodes.map((sc, i) => {
                                // Ángulos de 255 (Arriba-Izquierda) a 105 (Abajo-Izquierda)
                                const degrees = 255 - (150 / Math.max(1, systemCodes.length - 1)) * i;
                                const angle = degrees * (Math.PI / 180);
                                const radius = 145; // Increased radius for more space
                                const tx = Math.cos(angle) * radius;
                                const ty = Math.sin(angle) * radius;

                                return (
                                  <motion.button
                                    key={sc.id}
                                    initial={{ opacity: 0, x: 0, y: 0, scale: 0.1 }}
                                    animate={{ opacity: 1, x: tx, y: ty, scale: 1 }}
                                    exit={{ opacity: 0, x: 0, y: 0, scale: 0.1, transition: { duration: 0.15 } }}
                                    transition={{ duration: 0.3, delay: i * 0.04, type: "spring", stiffness: 350, damping: 22 }}
                                    onClick={() => { assignCode(sc.id); setShowDiscardMenu(false); }}
                                    className={[
                                      "absolute -ml-[45px] -mt-[40px] flex flex-col items-center justify-center p-2 rounded-2xl border-2 shadow-xl bg-p-surface transition-colors cursor-pointer",
                                      navDiscardIndex === i ? "border-p-accent ring-4 ring-p-accent/20 z-10" : "border-p-border hover:border-p-accent/50 z-0",
                                    ].join(" ")}
                                    style={{ width: "90px", height: "80px" }}
                                  >
                                    <span className="text-[10px] font-mono text-p-text-muted mb-0.5">Cód {sc.code_number}</span>
                                    <span className="text-[11px] font-bold text-p-text text-center leading-[1.15] w-full px-0.5 line-clamp-3">{sc.label}</span>
                                    <kbd className="kbd-hint mt-1 scale-75 origin-top absolute -bottom-2 -right-2 bg-p-surface shadow-sm">{i + 1}</kbd>
                                  </motion.button>
                                );
                              })}
                            </div>
                          )}
                        </AnimatePresence>
                      </>,
                      document.body
                    )}

                    <button
                      onClick={openNewCodeInput}
                      disabled={resolving}
                      className="flex-[2] inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg border border-blue-200 bg-blue-50 text-sm font-bold text-blue-700 hover:bg-blue-100 transition-colors"
                    >
                      <Plus className="w-3.5 h-3.5" />
                      <span>Nueva</span>
                      <kbd className="kbd-hint">→</kbd>
                    </button>
                  </div>
                )}
              </div>
            </motion.div>
          </div>

          {/* Bottom zone: grid de códigos, navegable por teclado — this is the part that scrolls */}
          <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin p-4 pt-3 space-y-3">
            <div className="bg-p-surface border border-p-border rounded-2xl p-3.5">
              <div className="flex items-center gap-1.5 mb-2">
                <span className="text-[10.5px] tracking-wide uppercase text-p-text-faint whitespace-nowrap">
                  Asignar
                </span>
                <div className="flex-1 h-px bg-p-border" />
                <div className="flex items-center gap-0.5">
                  <button
                    onClick={() => setAutoCols(true)}
                    title="Ajustar columnas automáticamente"
                    className={`px-1.5 h-4 text-[9px] font-bold flex items-center justify-center rounded transition-colors ${autoCols ? 'bg-p-accent text-white' : 'text-p-text-muted hover:bg-p-bg-subtle'}`}
                  >
                    AUTO
                  </button>
                  {[1, 2, 3, 4].map(c => (
                    <button
                      key={c}
                      onClick={() => { setGridCols(c); setAutoCols(false); }}
                      title={`${c} ${c === 1 ? 'columna' : 'columnas'} fijas`}
                      className={`w-4 h-4 text-[9px] font-bold flex items-center justify-center rounded transition-colors ${!autoCols && gridCols === c ? 'bg-p-accent text-white' : 'text-p-text-muted hover:bg-p-bg-subtle'}`}
                    >
                      {c}
                    </button>
                  ))}
                </div>
                <span className="text-[10px] text-p-text-faint ml-1 font-mono">{codes.length}</span>
              </div>
              <div
                ref={gridRef}
                className="grid gap-1"
                style={{ gridTemplateColumns: `repeat(${gridCols}, minmax(0, 1fr))` }}
              >
                {codes.map((c, i) => {
                  const isSuggested = detail.suggested_code?.id === c.id;
                  const isNavSel = i === navCodeIndex;
                  return (
                    <button
                      key={c.id}
                      onClick={() => assignCode(c.id)}
                      disabled={resolving}
                      className={[
                        "flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-left transition-all",
                        isNavSel ? "border-2" : "border",
                        isNavSel ? "" : "border-p-border bg-p-surface",
                      ].join(" ")}
                      style={
                        isNavSel
                          ? {
                              borderColor: codeColor(c.code_number),
                              background: zone === "list" ? `${codeColor(c.code_number)}18` : undefined,
                              opacity: zone === "list" ? 1 : 0.6,
                            }
                          : undefined
                      }
                    >
                      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: codeColor(c.code_number) }} />
                      <span className="text-[13px] font-semibold text-p-text flex-1 min-w-0 truncate">{c.label}</span>
                      {isSuggested && <Sparkles className="w-3 h-3 text-p-accent shrink-0" />}
                    </button>
                  );
                })}
              </div>
            </div>

            <label className="flex items-center gap-2 text-xs text-p-text-muted px-1">
              <input
                type="checkbox"
                checked={addAlias}
                onChange={(e) => setAddAlias(e.target.checked)}
                className="rounded border-p-border"
              />
              Recordar como alias para futuras rondas
            </label>
          </div>
        </>
      ) : (
        <div className="flex-1 overflow-y-auto p-4">
          <div className="skeleton h-40 rounded-2xl" />
        </div>
      )}

      <div className="px-4 py-3 border-t border-p-border bg-p-surface shrink-0">
        {!allResolved && (
          <div className="flex justify-center gap-2.5 mb-2 flex-wrap">
            {zone === "header" ? (
              <>
                <span className="font-mono text-[10px] text-p-text-faint flex items-center gap-1">
                  <kbd className="kbd-hint">←</kbd>Descartar
                </span>
                <span className="font-mono text-[10px] text-p-text-faint flex items-center gap-1">
                  <kbd className="kbd-hint">→</kbd>Nueva marca
                </span>
                <span className="font-mono text-[10px] text-p-text-faint flex items-center gap-1">
                  <kbd className="kbd-hint">↓</kbd>Ir a marcas
                </span>
              </>
            ) : (
              <>
                <span className="font-mono text-[10px] text-p-text-faint flex items-center gap-1">
                  <kbd className="kbd-hint">←↑↓→</kbd>Navegar
                </span>
                <span className="font-mono text-[10px] text-p-text-faint flex items-center gap-1">
                  <kbd className="kbd-hint">↑</kbd>Volver a la mención
                </span>
              </>
            )}
            <span className="font-mono text-[10px] text-p-text-faint flex items-center gap-1">
              <kbd className="kbd-hint">↵</kbd>Asignar
            </span>
          </div>
        )}
        <div
          className={[
            "flex items-center justify-center gap-1.5 text-xs font-semibold",
            allResolved ? "text-p-success" : "text-p-text-faint",
          ].join(" ")}
        >
          {allResolved ? <Check className="w-3.5 h-3.5" /> : <AlertTriangle className="w-3.5 h-3.5" />}
          <span>{allResolved ? "Todo resuelto" : `${total} por resolver`}</span>
        </div>
      </div>
    </div>
  );
}
