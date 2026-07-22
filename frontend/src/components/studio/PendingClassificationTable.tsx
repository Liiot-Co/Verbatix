import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Maximize2, Plus, Search, X, Trophy } from "lucide-react";
import {
  bulkResolve,
  createRoundCode,
  getResolutionQueue,
  getRoundCodes,
  resolveMentionGroup,
} from "@/api/client";
import type { CodingType, ResolutionQueueItem, RoundCode } from "@/api/types";
import { registerShortcuts, useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { useVerbatixStore } from "@/store/useVerbatixStore";
import { STATUS_CHIP } from "@/lib/resolutionStatus";
import { codingTypeLabel } from "@/lib/projectTree";

const PAGE_SIZE = 100;

interface CodePickerProps {
  codes: RoundCode[];
  /** System codes for rare/unrelated mentions (NS/NC, Otras menciones...) —
   *  shown as a separate section below the regular codes, in the same popup
   *  instead of a separate "Sin dato" picker. */
  systemCodes?: RoundCode[];
  onPick: (codeId: string) => void;
  /** Creates a brand-new code with this label and assigns it. Omit to disable. */
  onCreate?: (label: string) => void;
  onClose: () => void;
  anchorLabel: string;
}

/** Small searchable code list shared by the per-row and bulk "assign" actions. */
function CodePicker({
  codes,
  systemCodes = [],
  onPick,
  onCreate,
  onClose,
  anchorLabel,
}: CodePickerProps) {
  const [query, setQuery] = useState("");
  const [navIndex, setNavIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? codes.filter((c) => c.label.toLowerCase().includes(q)) : codes;
  }, [codes, query]);

  const filteredSystem = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? systemCodes.filter((c) => c.label.toLowerCase().includes(q)) : systemCodes;
  }, [systemCodes, query]);

  const combined = useMemo(() => [...filtered, ...filteredSystem], [filtered, filteredSystem]);

  const trimmedQuery = query.trim();
  const canCreate =
    !!onCreate &&
    trimmedQuery.length > 0 &&
    !combined.some((c) => c.label.toLowerCase() === trimmedQuery.toLowerCase());
  // "Crear" occupies the last nav slot, after every matched code.
  const createIndex = combined.length;

  useEffect(() => setNavIndex(0), [query]);
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const pickAt = (i: number) => {
    if (canCreate && i === createIndex) {
      onCreate!(trimmedQuery);
      return;
    }
    const c = combined[i];
    if (c) onPick(c.id);
  };

  return (
    <div
      className="absolute z-command-palette mt-1 w-72 max-h-96 overflow-hidden rounded-xl border border-p-border bg-p-surface shadow-xl flex flex-col"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="p-2 border-b border-p-border shrink-0">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-p-text-faint pointer-events-none" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={anchorLabel}
            className="input w-full h-7 pl-7 text-xs"
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                onClose();
                return;
              }
              const maxIndex = canCreate ? createIndex : combined.length - 1;
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setNavIndex((i) => Math.min(maxIndex, i + 1));
              }
              if (e.key === "ArrowUp") {
                e.preventDefault();
                setNavIndex((i) => Math.max(0, i - 1));
              }
              if (e.key === "Enter") {
                e.preventDefault();
                pickAt(navIndex);
              }
            }}
          />
        </div>
      </div>
      <div className="overflow-y-auto scrollbar-thin py-1">
        {combined.length === 0 && !canCreate ? (
          <div className="px-3 py-2 text-xs text-p-text-faint">Sin resultados.</div>
        ) : (
          <>
            {filtered.map((c, i) => (
              <button
                key={c.id}
                onClick={() => pickAt(i)}
                className={`w-full text-left px-3 py-1.5 text-sm flex items-center gap-2 transition-colors ${i === navIndex ? "bg-p-accent-soft text-p-accent" : "hover:bg-p-bg-subtle text-p-text"}`}
              >
                {i < 9 && <kbd className="kbd-hint shrink-0">{i + 1}</kbd>}
                <span className="truncate">{c.label}</span>
              </button>
            ))}
            {filteredSystem.length > 0 && (
              <div className="px-3 pt-2 pb-1 text-[10px] font-semibold text-p-text-faint uppercase tracking-wide">
                Sin dato / poco frecuentes
              </div>
            )}
            {filteredSystem.map((c, j) => {
              const i = filtered.length + j;
              return (
                <button
                  key={c.id}
                  onClick={() => pickAt(i)}
                  className={`w-full text-left px-3 py-1.5 text-sm flex items-center gap-2 transition-colors ${i === navIndex ? "bg-p-accent-soft text-p-accent" : "hover:bg-p-bg-subtle text-p-text"}`}
                >
                  <span className="truncate">{c.label}</span>
                </button>
              );
            })}
            {canCreate && (
              <button
                onClick={() => pickAt(createIndex)}
                className={`w-full text-left px-3 py-1.5 text-sm flex items-center gap-2 border-t border-p-border transition-colors ${navIndex === createIndex ? "bg-p-accent-soft text-p-accent" : "hover:bg-p-bg-subtle text-p-text"}`}
              >
                <Plus className="w-3.5 h-3.5 shrink-0" />
                <span className="truncate">Crear "{trimmedQuery}"</span>
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

interface PendingClassificationTableProps {
  subprojectId: string;
  codingType: CodingType;
  onResolved?: () => void;
  onFocusRow?: (groupId: string) => void;
}

/**
 * Batch-first pending-mentions table: replaces the old default of opening a
 * one-card-at-a-time ResolutionCenter. Every mention is a row you can select
 * (checkbox / shift-click / keyboard) and assign in bulk, or assign inline
 * from its own row — the 1x1 "focus" card (ResolutionSidebar) becomes an
 * opt-in escape hatch via the per-row expand button, not the default surface.
 */
export default function PendingClassificationTable({
  subprojectId,
  codingType,
  onResolved,
  onFocusRow,
}: PendingClassificationTableProps) {
  const showToast = useVerbatixStore((s) => s.showToast);

  const [queue, setQueue] = useState<ResolutionQueueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [codes, setCodes] = useState<RoundCode[]>([]);
  const [systemCodes, setSystemCodes] = useState<RoundCode[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // Excel-style range anchor: shift-click/shift-arrow always extends from here
  // until a plain click/arrow moves it to the new cursor position.
  const [anchorIndex, setAnchorIndex] = useState<number | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);

  // Which row/spot has an open code picker: "bulk" for the top toolbar,
  // or a group id for that row's inline "Asignar" button.
  const [picker, setPicker] = useState<"bulk" | string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  const loadQueue = useCallback(() => {
    if (!subprojectId) return Promise.resolve();
    return getResolutionQueue(subprojectId, PAGE_SIZE, 0, undefined, debouncedSearch).then(
      (res) => {
        setQueue(res.items);
        setTotal(res.total);
      },
    );
  }, [subprojectId, debouncedSearch]);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      loadQueue(),
      getRoundCodes(subprojectId, true).then((all) => {
        setCodes(all.filter((c) => !c.is_system));
        setSystemCodes(
          all.filter((c) => c.is_system).sort((a, b) => a.code_number - b.code_number),
        );
      }),
    ]).finally(() => setLoading(false));
  }, [subprojectId, loadQueue]);

  useEffect(() => {
    setActiveIndex((i) => Math.min(i, Math.max(0, queue.length - 1)));
  }, [queue.length]);

  const selectRange = useCallback(
    (from: number, to: number) => {
      const start = Math.min(from, to);
      const end = Math.max(from, to);
      const ids = new Set<string>();
      for (let i = start; i <= end; i++) {
        const id = queue[i]?.id;
        if (id) ids.add(id);
      }
      setSelected(ids);
    },
    [queue],
  );

  const toggleSelect = useCallback(
    (groupId: string, index: number, shiftKey: boolean) => {
      if (shiftKey) {
        const anchor = anchorIndex ?? index;
        setAnchorIndex(anchor);
        selectRange(anchor, index);
        return;
      }
      setSelected((prev) => {
        const next = new Set(prev);
        if (next.has(groupId)) next.delete(groupId);
        else next.add(groupId);
        return next;
      });
      setAnchorIndex(index);
    },
    [anchorIndex, selectRange],
  );

  const refresh = useCallback(async () => {
    await loadQueue();
    onResolved?.();
  }, [loadQueue, onResolved]);

  const assignRow = useCallback(
    async (groupId: string, codeId: string, addAlias = codingType === "brands") => {
      setBusy(true);
      try {
        await resolveMentionGroup(groupId, {
          action: "approve",
          code_ids: [codeId],
          add_alias: addAlias,
        });
        setSelected((prev) => {
          const n = new Set(prev);
          n.delete(groupId);
          return n;
        });
        setPicker(null);
        await refresh();
      } catch {
        showToast("No se pudo asignar el código.", "error");
      } finally {
        setBusy(false);
      }
    },
    [codingType, refresh, showToast],
  );

  const assignSelection = useCallback(
    async (codeId: string) => {
      if (selected.size === 0) return;
      setBusy(true);
      try {
        const result = await bulkResolve(subprojectId, Array.from(selected), {
          action: "approve",
          code_ids: [codeId],
          add_alias: codingType === "brands",
        });
        setSelected(new Set());
        setPicker(null);
        if (result.failed.length > 0) {
          showToast(
            `${result.resolved.length} resueltos, ${result.failed.length} fallaron`,
            "error",
          );
        } else {
          showToast(`${result.resolved.length} grupos resueltos`, "success");
        }
        await refresh();
      } catch {
        showToast("No se pudo resolver el lote.", "error");
      } finally {
        setBusy(false);
      }
    },
    [subprojectId, selected, codingType, refresh, showToast],
  );

  // Mints a code that doesn't exist yet (rare/one-off mention that doesn't
  // fit any existing code) and assigns it right away — no separate "create
  // codebook entry" trip needed.
  const createAndAssignRow = useCallback(
    async (groupId: string, label: string) => {
      setBusy(true);
      try {
        const created = await createRoundCode(subprojectId, { label });
        setCodes((prev) => [...prev, created]);
        await assignRow(groupId, created.id);
      } catch {
        showToast("No se pudo crear el código.", "error");
        setBusy(false);
      }
    },
    [subprojectId, assignRow, showToast],
  );

  const createAndAssignSelection = useCallback(
    async (label: string) => {
      setBusy(true);
      try {
        const created = await createRoundCode(subprojectId, { label });
        setCodes((prev) => [...prev, created]);
        await assignSelection(created.id);
      } catch {
        showToast("No se pudo crear el código.", "error");
        setBusy(false);
      }
    },
    [subprojectId, assignSelection, showToast],
  );

  const openAssignPopup = useCallback(() => {
    if (selected.size > 0) {
      setPicker((p) => (p === "bulk" ? null : "bulk"));
      return;
    }
    const g = queue[activeIndex];
    if (g) setPicker((p) => (p === g.id ? null : g.id));
  }, [selected, queue, activeIndex]);

  useEffect(() => {
    registerShortcuts("pending-classification-table", [
      {
        key: "ArrowDown",
        action: () =>
          setActiveIndex((i) => {
            const next = Math.min(queue.length - 1, i + 1);
            setAnchorIndex(next);
            return next;
          }),
        description: "Fila siguiente",
        category: "Navegación",
      },
      {
        key: "ArrowUp",
        action: () =>
          setActiveIndex((i) => {
            const next = Math.max(0, i - 1);
            setAnchorIndex(next);
            return next;
          }),
        description: "Fila anterior",
        category: "Navegación",
      },
      {
        key: "ArrowDown",
        shift: true,
        action: () =>
          setActiveIndex((i) => {
            const next = Math.min(queue.length - 1, i + 1);
            const anchor = anchorIndex ?? i;
            setAnchorIndex(anchor);
            selectRange(anchor, next);
            return next;
          }),
        description: "Extender selección hacia abajo (Excel)",
        category: "Navegación",
      },
      {
        key: "ArrowUp",
        shift: true,
        action: () =>
          setActiveIndex((i) => {
            const next = Math.max(0, i - 1);
            const anchor = anchorIndex ?? i;
            setAnchorIndex(anchor);
            selectRange(anchor, next);
            return next;
          }),
        description: "Extender selección hacia arriba (Excel)",
        category: "Navegación",
      },
      {
        key: " ",
        action: () => {
          const g = queue[activeIndex];
          if (g) toggleSelect(g.id, activeIndex, false);
        },
        description: "Seleccionar / deseleccionar fila activa",
        category: "Acciones",
      },
      {
        key: "ArrowRight",
        action: openAssignPopup,
        description: "Buscar y clasificar (selección o fila activa)",
        category: "Acciones",
      },
      {
        key: "Enter",
        action: openAssignPopup,
        description: "Buscar y clasificar (selección o fila activa)",
        category: "Acciones",
      },
      {
        key: "Escape",
        action: () => setPicker(null),
        description: "Cerrar selector de código",
        category: "Acciones",
      },
      ...Array.from({ length: 9 }, (_, i) => ({
        key: String(i + 1),
        action: () => {
          const code = codes[i];
          if (!code) return;
          if (selected.size > 0) void assignSelection(code.id);
          else {
            const g = queue[activeIndex];
            if (g) void assignRow(g.id, code.id);
          }
        },
        description: `Asignar código #${i + 1} (a selección o fila activa)`,
        category: "Códigos rápidos",
      })),
    ]);
  }, [
    queue,
    activeIndex,
    anchorIndex,
    codes,
    selected,
    toggleSelect,
    selectRange,
    assignSelection,
    assignRow,
    openAssignPopup,
  ]);

  useKeyboardShortcuts("pending-classification-table");

  const allResolved = !loading && queue.length === 0 && total === 0;

  return (
    <div className="card overflow-hidden flex flex-col h-full">
      <div className="px-4 py-2.5 border-b border-p-border shrink-0 space-y-2.5">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm font-bold text-p-text">
              {codingTypeLabel(codingType)} pendientes de clasificar
            </span>
            <span className={total > 0 ? "badge-warning" : "badge-success"}>{total}</span>
          </div>
          <div className="relative w-56 shrink-0">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-p-text-faint pointer-events-none" />
            <input
              type="search"
              placeholder="Buscar..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="input pl-8 py-1.5 h-8 text-xs rounded-lg w-full"
            />
          </div>
        </div>

        {/* Batch bar — always visible so mouse-first users see it immediately,
            not just after they happen to select rows. */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-xs text-p-text-muted shrink-0">
            {selected.size > 0
              ? `Asignar a ${selected.size} seleccionados:`
              : "Selecciona filas para asignar en lote, o usa Asignar por fila:"}
          </span>
          {codes.slice(0, 8).map((c) => (
            <button
              key={c.id}
              disabled={busy || selected.size === 0}
              onClick={() => assignSelection(c.id)}
              className="text-xs font-semibold px-2 py-1 rounded-md border border-p-border bg-p-surface hover:border-p-accent/50 transition-colors disabled:opacity-40"
            >
              {c.label}
            </button>
          ))}
          <div className="relative">
            <button
              disabled={busy || selected.size === 0}
              onClick={() => setPicker(picker === "bulk" ? null : "bulk")}
              className="text-xs font-semibold px-2 py-1 rounded-md border border-p-border bg-p-surface hover:border-p-accent/50 transition-colors disabled:opacity-40"
            >
              Más…
            </button>
            {picker === "bulk" && (
              <CodePicker
                codes={codes}
                systemCodes={systemCodes}
                anchorLabel={`Asignar a ${selected.size}...`}
                onPick={(codeId) => assignSelection(codeId)}
                onCreate={(label) => createAndAssignSelection(label)}
                onClose={() => setPicker(null)}
              />
            )}
          </div>
          {selected.size > 0 && (
            <button
              onClick={() => setSelected(new Set())}
              className="text-xs text-p-text-faint hover:text-p-text ml-1"
            >
              limpiar
            </button>
          )}
        </div>
      </div>

      <div className="overflow-y-auto scrollbar-thin flex-1">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-p-surface z-10">
            <tr className="border-b border-p-border text-left">
              <th className="px-3 py-2 w-8" />
              <th className="px-2 py-2 font-semibold text-p-text-muted text-xs uppercase tracking-wider">
                Mención
              </th>
              <th className="px-2 py-2 font-semibold text-p-text-muted text-xs uppercase tracking-wider text-right">
                Freq.
              </th>
              <th className="px-2 py-2 font-semibold text-p-text-muted text-xs uppercase tracking-wider">
                Estado
              </th>
              <th className="px-2 py-2 font-semibold text-p-text-muted text-xs uppercase tracking-wider">
                Asignar
              </th>
              <th className="px-2 py-2 w-8" />
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: 8 }).map((_, i) => (
                <tr key={`sk-${i}`} className="border-b border-p-border last:border-0">
                  <td className="px-3 py-2.5" colSpan={6}>
                    <div className="skeleton h-4 w-full rounded" />
                  </td>
                </tr>
              ))
            ) : allResolved ? (
              <tr>
                <td colSpan={6} className="px-4 py-16">
                  <motion.div
                    initial={{ opacity: 0, scale: 0.8, y: 10 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    className="flex flex-col items-center justify-center text-center space-y-3"
                  >
                    <div className="relative">
                      <motion.div
                        animate={{ rotate: 360 }}
                        transition={{ duration: 25, repeat: Infinity, ease: "linear" }}
                        className="absolute -inset-6 bg-gradient-to-r from-p-success/20 to-p-accent/20 rounded-full blur-xl"
                      />
                      <motion.div
                        whileHover={{ scale: 1.05, rotate: [-2, 2, -2, 0] }}
                        className="relative w-16 h-16 bg-gradient-to-tr from-p-success/10 to-p-success/30 border border-p-success/20 rounded-2xl flex items-center justify-center shadow-sm cursor-default"
                      >
                        <Trophy className="w-8 h-8 text-p-success drop-shadow-sm" />
                      </motion.div>
                    </div>
                    <div className="space-y-1">
                      <h3 className="font-heading text-xl font-bold bg-gradient-to-r from-p-success to-p-accent bg-clip-text text-transparent">
                        ¡Todo al día!
                      </h3>
                      <p className="text-sm text-p-text-muted">
                        No hay {codingTypeLabel(codingType).toLowerCase()} pendientes por
                        clasificar.
                      </p>
                    </div>
                  </motion.div>
                </td>
              </tr>
            ) : queue.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-p-text-faint text-sm">
                  Sin resultados para "{debouncedSearch}".
                </td>
              </tr>
            ) : (
              queue.map((g, i) => (
                <tr
                  key={g.id}
                  onClick={(e) => {
                    setActiveIndex(i);
                    toggleSelect(g.id, i, e.shiftKey);
                  }}
                  className={[
                    "border-b border-p-border last:border-0 cursor-pointer transition-colors",
                    selected.has(g.id)
                      ? "bg-p-accent/10"
                      : i === activeIndex
                        ? "bg-p-accent/5 ring-1 ring-inset ring-p-accent/20"
                        : "hover:bg-p-bg-subtle/50",
                  ].join(" ")}
                >
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      checked={selected.has(g.id)}
                      onChange={(e) => {
                        e.stopPropagation();
                        toggleSelect(g.id, i, false);
                        // Un checkbox enfocado cuenta como "input de texto" para el
                        // guard de atajos (useKeyboardShortcuts) — sin el blur, las
                        // flechas (sin modificador o con shift) quedan mudas hasta
                        // que el foco salga del checkbox.
                        e.currentTarget.blur();
                      }}
                      onClick={(e) => e.stopPropagation()}
                      className="rounded border-p-border focus-visible:ring-2 focus-visible:ring-p-accent/40"
                    />
                  </td>
                  <td className="px-2 py-2 max-w-xs">
                    <div className="tooltip-trigger w-full">
                      <span className="block truncate font-medium text-p-text">
                        {g.normalized_text}
                      </span>
                      {g.sample_text && (
                        <div className="tooltip whitespace-normal break-words max-w-xl">
                          "{g.sample_text}"
                        </div>
                      )}
                    </div>
                  </td>
                  <td className="px-2 py-2 text-right text-p-text-muted text-xs tabular-nums">
                    ×{g.frequency_count}
                  </td>
                  <td className="px-2 py-2">
                    <span
                      className={STATUS_CHIP[g.status].className}
                      title={STATUS_CHIP[g.status].hint}
                    >
                      {STATUS_CHIP[g.status].label}
                    </span>
                  </td>
                  <td className="px-2 py-2">
                    <div className="relative inline-block">
                      <button
                        disabled={busy}
                        onClick={(e) => {
                          e.stopPropagation();
                          setPicker(picker === g.id ? null : g.id);
                        }}
                        className="text-xs font-semibold px-2 py-1 rounded-md border border-p-border bg-p-surface hover:border-p-accent/50 transition-colors"
                      >
                        Asignar…
                      </button>
                      {picker === g.id && (
                        <CodePicker
                          codes={codes}
                          systemCodes={systemCodes}
                          anchorLabel="Asignar código..."
                          onPick={(codeId) => assignRow(g.id, codeId)}
                          onCreate={(label) => createAndAssignRow(g.id, label)}
                          onClose={() => setPicker(null)}
                        />
                      )}
                    </div>
                  </td>
                  <td className="px-2 py-2">
                    {onFocusRow && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onFocusRow(g.id);
                        }}
                        className="text-p-text-faint hover:text-p-text"
                        title="Abrir en modo enfoque (una por una)"
                        aria-label="Modo enfoque"
                      >
                        <Maximize2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="px-4 py-2 border-t border-p-border bg-p-surface shrink-0 flex items-center justify-center gap-2.5 flex-wrap">
        <span className="font-mono text-[10px] text-p-text-faint flex items-center gap-1">
          <kbd className="kbd-hint">↑↓</kbd>Navegar
        </span>
        <span className="font-mono text-[10px] text-p-text-faint flex items-center gap-1">
          <kbd className="kbd-hint">⇧+↑↓</kbd>Extender selección
        </span>
        <span className="font-mono text-[10px] text-p-text-faint flex items-center gap-1">
          <kbd className="kbd-hint">Espacio</kbd>Seleccionar
        </span>
        <span className="font-mono text-[10px] text-p-text-faint flex items-center gap-1">
          <kbd className="kbd-hint">1-9</kbd>Código rápido
        </span>
        <span className="font-mono text-[10px] text-p-text-faint flex items-center gap-1">
          <kbd className="kbd-hint">→ / ↵</kbd>Buscar y clasificar
        </span>
        {picker && (
          <button
            onClick={() => setPicker(null)}
            className="text-p-text-faint hover:text-p-text ml-1"
            title="Cerrar selector"
          >
            <X className="w-3 h-3 inline" /> cerrar selector
          </button>
        )}
      </div>
    </div>
  );
}
