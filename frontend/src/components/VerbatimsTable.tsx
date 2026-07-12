import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, Search, Keyboard } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { getRound, getVerbatims } from "@/api/client";
import type { CodingStatus, RoundStatus, Verbatim } from "@/api/types";
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

export default function VerbatimsTable() {
  const { roundId } = useParams<{ roundId: string }>();
  const searchRef = useRef<HTMLInputElement>(null);
  const showToast = useVerbatixStore((s) => s.showToast);

  const [round, setRound] = useState<RoundStatus | null>(null);
  const [verbatims, setVerbatims] = useState<Verbatim[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<CodingStatus | "">("");
  const [search, setSearch] = useState("");
  const [showShortcuts, setShowShortcuts] = useState(false);

  useEffect(() => {
    if (!roundId) return;
    getRound(roundId).then(setRound);
  }, [roundId]);

  useEffect(() => {
    setPage(1);
  }, [statusFilter]);

  useEffect(() => {
    if (!roundId) return;
    setLoading(true);
    getVerbatims(roundId, page, PAGE_SIZE, statusFilter || undefined)
      .then((res) => {
        setVerbatims(res.items);
        setTotal(res.total);
      })
      .finally(() => setLoading(false));
  }, [roundId, page, statusFilter]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const visible = useMemo(() => {
    if (!search.trim()) return verbatims;
    const q = search.trim().toLowerCase();
    return verbatims.filter((v) => v.original_text.toLowerCase().includes(q));
  }, [verbatims, search]);

  // Register keyboard shortcuts for this page
  useEffect(() => {
    registerShortcuts("verbatims", [
      {
        key: "f",
        meta: true,
        action: () => {
          searchRef.current?.focus();
          searchRef.current?.select();
        },
        description: "Enfocar búsqueda",
        category: "Navegación",
        allowInInput: false,
      },
      {
        key: "ArrowRight",
        meta: false,
        action: () => setPage((p) => Math.min(totalPages, p + 1)),
        description: "Página siguiente",
        category: "Navegación",
        allowInInput: false,
      },
      {
        key: "ArrowLeft",
        meta: false,
        action: () => setPage((p) => Math.max(1, p - 1)),
        description: "Página anterior",
        category: "Navegación",
        allowInInput: false,
      },
      {
        key: "r",
        meta: true,
        action: () => window.location.reload(),
        description: "Recargar verbatims",
        category: "Acciones",
      },
      {
        key: "e",
        meta: true,
        action: () => showToast("Exportar en desarrollo", "info"),
        description: "Exportar resultados",
        category: "Acciones",
      },
      {
        key: "Escape",
        meta: false,
        action: () => {
          setSearch("");
          setStatusFilter("");
          setShowShortcuts(false);
          searchRef.current?.blur();
        },
        description: "Limpiar filtros / Cerrar",
        category: "Navegación",
      },
      {
        key: "?",
        meta: false,
        action: () => setShowShortcuts((v) => !v),
        description: "Mostrar atajos de teclado",
        category: "Navegación",
      },
    ]);
  }, [totalPages, showToast]);

  useKeyboardShortcuts("verbatims");

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target)) return;
      if (e.key === "ArrowRight") setPage((p) => Math.min(totalPages, p + 1));
      if (e.key === "ArrowLeft") setPage((p) => Math.max(1, p - 1));
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [totalPages]);

  return (
    <div className="max-w-4xl mx-auto py-4 space-y-4">
      <Breadcrumb
        items={[
          { label: "Proyectos", to: "/" },
          ...(round?.project_name ? [{ label: round.project_name }] : []),
          ...(round?.study_name ? [{ label: round.study_name }] : []),
          { label: round?.name ?? "Verbatims" },
        ]}
      />

      <div className="space-y-1"
      >
        <h1 className="font-heading text-2xl font-semibold text-p-text tracking-tight">
          {round?.name ?? "Verbatims"}
        </h1>
        {round && (
          <p className="font-subtitle text-sm text-p-text-muted">
            {round.counters.verbatims_total} verbatims · {round.counters.codes_total} códigos en el libro
          </p>
        )}
      </div>

      {/* Search and filter bar */}
      <div className="flex flex-col sm:flex-row gap-2"
      >
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

      {/* Table */}
      <div className="card overflow-hidden"
      >
        <motion.table className="w-full text-sm" layout>
          <thead>
            <tr className="border-b border-p-border text-left">
              <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">Respondent</th>
              <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">Verbatim</th>
              <th className="px-4 py-2.5 font-semibold text-p-text-muted text-xs uppercase tracking-wider">Estado</th>
            </tr>
          </thead>
          <tbody>
            <AnimatePresence mode="popLayout">
              {loading ? (
                Array.from({ length: 6 }).map((_, i) => (
                  <tr key={`skeleton-${i}`} className="border-b border-p-border last:border-0">
                    <td className="px-4 py-2.5"><div className="skeleton h-3 w-10 rounded" /></td>
                    <td className="px-4 py-2.5"><div className="skeleton h-3 w-3/4 rounded" /></td>
                    <td className="px-4 py-2.5"><div className="skeleton h-3 w-16 rounded-full" /></td>
                  </tr>
                ))
              ) : visible.length === 0 ? (
                <motion.tr
                  exit={{ opacity: 0 }}
                >
                  <td colSpan={3} className="px-4 py-8 text-center text-p-text-faint text-sm">
                    {search ? `Sin resultados para "${search}" en esta página.` : "Sin verbatims todavía."}
                  </td>
                </motion.tr>
              ) : (
                visible.map((v) => (
                  <motion.tr
                    key={v.id}
                    layout
                    exit={{ opacity: 0, y: -8, x: 10, transition: { duration: 0.15 } }}
                    className="border-b border-p-border last:border-0 hover:bg-p-bg-subtle/50 transition-colors duration-100"
                  >
                    <td className="px-4 py-2.5 text-p-text-faint text-xs">{v.respondent_external_id ?? "—"}</td>
                    <td className="px-4 py-2.5 text-p-text max-w-2xl truncate">{v.original_text}</td>
                    <td className="px-4 py-2.5">
                      <motion.span
                        whileHover={{ scale: 1.05 }}
                        className={["inline-flex items-center text-[11px] font-semibold px-2 py-0.5 rounded-full border", STATUS_BADGE[v.coding_status] ?? STATUS_BADGE.pending].join(" ")}
                      >
                        {STATUS_LABELS[v.coding_status as CodingStatus] ?? v.coding_status}
                      </motion.span>
                    </td>
                  </motion.tr>
                ))
              )}
            </AnimatePresence>
          </tbody>
        </motion.table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-p-text-muted"
        >
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

      {/* Keyboard shortcuts hint — click or press ? to open the full list */}
      <motion.button
        type="button"
        onClick={() => setShowShortcuts(true)}
        aria-label="Mostrar atajos de teclado"
        whileHover={{ y: -2 }}
        className="fixed bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-3 text-xs text-p-text-faint bg-p-surface/90 backdrop-blur-glass border border-p-border rounded-xl px-4 py-2 shadow-lg hidden sm:flex hover:text-p-text hover:border-p-accent/40 transition-colors"
      >
        <span className="flex items-center gap-1">
          <kbd className="kbd-hint">{modLabel()}F</kbd> Buscar
        </span>
        <span className="flex items-center gap-1">
          <kbd className="kbd-hint">← →</kbd> Páginas
        </span>
        <span className="flex items-center gap-1">
          <kbd className="kbd-hint">{modLabel()}K</kbd> Comandos
        </span>
        <span className="flex items-center gap-1">
          <kbd className="kbd-hint">?</kbd> Ver todos
        </span>
      </motion.button>

      {/* Shortcuts modal */}
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
                <motion.button
                  whileTap={{ scale: 0.9 }}
                  onClick={() => setShowShortcuts(false)}
                  className="text-p-text-faint hover:text-p-text"
                  aria-label="Cerrar"
                >
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
              <motion.button
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                onClick={() => setShowShortcuts(false)}
                className="btn-primary w-full mt-4 justify-center"
              >
                Entendido
              </motion.button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}