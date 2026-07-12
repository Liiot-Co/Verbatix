import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowRight, FolderOpen, Plus, Search } from "lucide-react";
import { getProjects } from "@/api/client";
import type { ProjectListItem } from "@/api/types";
import { useKeyboardShortcuts, registerShortcuts, modLabel } from "@/hooks/useKeyboardShortcuts";

const GRID_COLS = 2;

const GRADIENT_CLASSES = ["card-gradient-morph-1", "card-gradient-morph-2", "card-gradient-morph-3", "card-gradient-morph-4", "card-gradient-morph-5"];

export default function ProjectDashboard() {
  const navigate = useNavigate();

  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const cardRefs = useRef<(HTMLAnchorElement | null)[]>([]);
  const [focusedIndex, setFocusedIndex] = useState(-1);

  useEffect(() => {
    getProjects()
      .then(setProjects)
      .finally(() => setLoading(false));
  }, []);

  const filteredProjects = projects.filter((p) =>
    p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    p.external_code.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const totalTiles = filteredProjects.length + 1;

  const onGridKeyDown = (e: React.KeyboardEvent, idx: number) => {
    const deltas: Record<string, number> = {
      ArrowRight: 1,
      ArrowLeft: -1,
      ArrowDown: GRID_COLS,
      ArrowUp: -GRID_COLS,
    };
    const delta = deltas[e.key];
    if (delta === undefined) return;
    e.preventDefault();
    const next = Math.max(0, Math.min(totalTiles - 1, idx + delta));
    cardRefs.current[next]?.focus();
    setFocusedIndex(next);
  };

  const handleSearchKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      setSearchQuery("");
      (e.target as HTMLInputElement).blur();
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      cardRefs.current[0]?.focus();
      setFocusedIndex(0);
    }
  };

  useEffect(() => {
    registerShortcuts("dashboard", [
      {
        key: "f",
        meta: true,
        action: () => {
          const input = document.querySelector('input[placeholder*="Buscar"]') as HTMLInputElement;
          input?.focus();
        },
        description: "Buscar proyectos",
        category: "Navegación",
        allowInInput: false,
      },
      {
        key: "n",
        meta: true,
        shift: true,
        action: () => navigate("/wizard"),
        description: "Nuevo proyecto",
        category: "Acciones",
      },
      {
        key: "r",
        meta: true,
        action: () => window.location.reload(),
        description: "Recargar proyectos",
        category: "Acciones",
      },
    ]);
  }, [navigate]);

  useKeyboardShortcuts("dashboard");

  return (
    <div className="max-w-4xl mx-auto py-4 space-y-6">
      {/* Header with search */}
      <div className="space-y-1"
      >
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 className="font-heading text-2xl font-semibold text-p-text tracking-tight">Proyectos</h1>
            <p className="font-subtitle text-sm text-p-text-muted mt-0.5">
              Cada proyecto agrupa rondas y estudios de codificación de verbatims.
            </p>
          </div>
          <div className="relative w-full sm:w-64">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-p-text-faint pointer-events-none" />
            <input
              type="search"
              placeholder="Buscar proyectos…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={handleSearchKeyDown}
              className="input pl-10 pr-10 text-sm"
              aria-label="Buscar proyectos"
            />
            <kbd className="hidden sm:flex items-center absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-mono text-p-text-faint border border-p-border rounded px-1.5 py-0.5 pointer-events-none">
              {modLabel()}F
            </kbd>
          </div>
        </div>
      </div>

      <AnimatePresence mode="wait">
        {loading ? (
          <div
            key="loading"
            className="grid grid-cols-1 sm:grid-cols-2 gap-3"
          >
            {[0, 1].map((i) => (
              <div key={i} className="skeleton h-28 rounded-2xl" />
            ))}
          </div>
        ) : filteredProjects.length === 0 ? (
          <motion.div
            key="empty"
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.25 }}
            className="card-subtle p-10 flex flex-col items-center justify-center gap-3 text-center"
          >
            <FolderOpen className="w-10 h-10 text-p-text-faint animate-pulse-soft" />
            <div>
              <div className="text-sm font-semibold text-p-text">No hay proyectos{searchQuery ? ` para "${searchQuery}"` : ""}</div>
              <p className="text-xs text-p-text-faint mt-1">
                {searchQuery ? "Intenta con otra búsqueda." : "Crea el primero para empezar a codificar verbatims."}
              </p>
            </div>
            {!searchQuery && (
              <Link to="/wizard" className="btn-primary text-sm mt-2 inline-flex items-center gap-1.5">
                <Plus className="w-4 h-4" /> Nuevo proyecto
              </Link>
            )}
          </motion.div>
        ) : (
          <motion.div
            key="grid"
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            role="grid"
            aria-label="Proyectos"
          >
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {filteredProjects.map((project, idx) => {
                return (
                  <motion.div
                    key={project.id}
                    layout
                    exit={{ opacity: 0, scale: 0.95, transition: { duration: 0.15 } }}
                  >
                    <Link
                      to={`/projects/${project.id}`}
                      ref={(el) => { cardRefs.current[idx] = el; }}
                      onKeyDown={(e) => onGridKeyDown(e, idx)}
                      onFocus={() => setFocusedIndex(idx)}
                      className={[
                        `relative ${GRADIENT_CLASSES[idx % GRADIENT_CLASSES.length]} p-4 text-left space-y-3 overflow-hidden group block`,
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-p-accent/40",
                        "hover:-translate-y-0.5 hover:shadow-lg active:scale-[0.98] transition-all duration-200",
                        focusedIndex === idx ? "ring-2 ring-p-accent/50" : "",
                      ].join(" ")}
                    >
                    {/* Ambient glow on hover/focus */}
                    <motion.div
                      aria-hidden
                      className="pointer-events-none absolute inset-0"
                      initial={{ opacity: 0 }}
                      whileHover={{ opacity: 1 }}
                      transition={{ duration: 0.3 }}
                      style={{
                        background: "radial-gradient(140px circle at 100% 0%, oklch(var(--p-accent-l) var(--p-accent-c) var(--p-accent-h) / 0.08), transparent 70%)",
                      }}
                    />

                    <div className="relative flex items-start justify-between gap-2">
                      <motion.div
                        layout
                        className="text-base font-bold text-p-text leading-snug pr-8"
                      >
                        {project.name}
                      </motion.div>
                      <motion.div
                        layout
                        className="w-4 h-4 text-p-text-faint shrink-0 mt-1 group-hover:translate-x-0.5 transition-transform duration-200"
                      >
                        <ArrowRight />
                      </motion.div>
                    </div>

                    {project.rounds_count > 0 && (
                      <motion.div
                        layout
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        className="relative inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border w-fit text-p-text-faint bg-p-bg-subtle border-p-border"
                      >
                        <span className="font-semibold text-p-text-muted">{project.rounds_count}</span> {project.rounds_count === 1 ? "ronda" : "rondas"}
                      </motion.div>
                    )}

                    <motion.div
                      layout
                      className="relative text-[11px] font-subtitle text-p-text-faint"
                    >
                      <span className="font-semibold text-p-text-muted">{project.external_code}</span>
                    </motion.div>
                  </Link>
                  </motion.div>
                );
              })}

              {/* New Project Card */}
              <motion.div
                layout
                exit={{ opacity: 0, scale: 0.95, transition: { duration: 0.15 } }}
              >
                <Link
                  to="/wizard"
                  ref={(el) => { cardRefs.current[filteredProjects.length] = el; }}
                  onKeyDown={(e) => onGridKeyDown(e, filteredProjects.length)}
                  onFocus={() => setFocusedIndex(filteredProjects.length)}
                  className={[
                    "card-subtle p-4 flex flex-col items-center justify-center gap-2 text-p-text-muted block",
                    "hover:text-p-text hover:border-p-accent/40 active:scale-[0.99] transition-all duration-200",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-p-accent/40",
                    "min-h-[104px] group",
                  ].join(" ")}
                >
                <motion.div
                  whileHover={{ rotate: 90, scale: 1.1 }}
                  transition={{ type: "spring", stiffness: 300, damping: 20 }}
                  className="w-5 h-5 text-p-text-faint group-hover:text-p-accent transition-colors"
                >
                  <Plus />
                </motion.div>
                <span className="text-sm font-medium">Nuevo proyecto</span>
                   <span className="text-xs text-p-text-faint hidden sm:block">{modLabel()}⇧N</span>
                </Link>
              </motion.div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Keyboard hint bar */}
      <div className="flex items-center justify-center gap-4 text-xs text-p-text-faint px-4 py-2 border-t border-p-border"
      >
        <span className="flex items-center gap-1">
          <kbd className="kbd-hint">{modLabel()}F</kbd> Buscar
        </span>
        <span className="flex items-center gap-1">
          <kbd className="kbd-hint">{modLabel()}K</kbd> Comandos
        </span>
        <span className="flex items-center gap-1">
          <kbd className="kbd-hint">← → ↑ ↓</kbd> Navegar
        </span>
        <span className="flex items-center gap-1">
          <kbd className="kbd-hint">Enter</kbd> Abrir
        </span>
      </div>
    </div>
  );
}