import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronLeft, ChevronRight, FolderOpen, Plus, Search, Sparkles } from "lucide-react";
import { getProjects } from "@/api/client";
import type { ProjectListItem } from "@/api/types";
import { useKeyboardShortcuts, registerShortcuts } from "@/hooks/useKeyboardShortcuts";
import GlowCard, { GlowCardGrid, glowVariantForIndex } from "@/components/GlowCard";

const PAGE_SIZE = 10;
const RECENT_COUNT = 3;

const ICON_CLASSES = [
  "project-row-icon-1",
  "project-row-icon-2",
  "project-row-icon-3",
  "project-row-icon-4",
  "project-row-icon-5",
];

function formatRelativeDate(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays <= 0) return "Hoy";
  if (diffDays === 1) return "Ayer";
  if (diffDays < 7) return `Hace ${diffDays} días`;
  return date.toLocaleDateString("es", { day: "numeric", month: "short", year: "numeric" });
}

function studySummaryLabel(studies: number, rounds: number): string {
  const s = studies === 1 ? "1 estudio" : `${studies} estudios`;
  const r = rounds === 1 ? "1 ronda" : `${rounds} rondas`;
  return `${s} · ${r}`;
}

export default function ProjectDashboard() {
  const navigate = useNavigate();

  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [page, setPage] = useState(1);

  useEffect(() => {
    getProjects()
      .then(setProjects)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    setPage(1);
  }, [searchQuery]);

  const sortedByRecent = useMemo(
    () => [...projects].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()),
    [projects]
  );

  const recentProjects = sortedByRecent.slice(0, RECENT_COUNT);

  const filteredProjects = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    if (!q) return sortedByRecent;
    return sortedByRecent.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.external_code.toLowerCase().includes(q)
    );
  }, [sortedByRecent, searchQuery]);

  const totalPages = Math.max(1, Math.ceil(filteredProjects.length / PAGE_SIZE));
  const paginatedProjects = filteredProjects.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const handleSearchKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      setSearchQuery("");
      (e.target as HTMLInputElement).blur();
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
    <div className="max-w-4xl mx-auto py-4 space-y-5">
      {/* Header */}
      <div className="space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="font-heading text-xl font-semibold text-p-text tracking-tight">Proyectos</h1>
            <p className="font-subtitle text-xs text-p-text-muted mt-0.5">
              Cada proyecto agrupa estudios (Marcas, Razones) con sus rondas de codificación.
            </p>
          </div>
          <Link to="/wizard" className="btn-primary text-xs py-1.5 px-3.5 rounded-full shrink-0">
            <Plus className="w-3.5 h-3.5" />
            Nuevo proyecto
          </Link>
        </div>

        <div className="relative w-full">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-p-text-faint pointer-events-none" />
          <input
            type="search"
            placeholder="Buscar proyectos…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={handleSearchKeyDown}
            className="input pl-9 text-sm rounded-xl"
            aria-label="Buscar proyectos"
          />
        </div>
      </div>

      <AnimatePresence mode="wait">
        {loading ? (
          <div key="loading" className="space-y-5">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
              {[0, 1, 2].map((i) => (
                <div key={i} className="skeleton h-[72px] rounded-2xl" />
              ))}
            </div>
            <div className="space-y-2">
              {[0, 1, 2].map((i) => (
                <div key={i} className="skeleton h-14 rounded-xl" />
              ))}
            </div>
          </div>
        ) : projects.length === 0 ? (
          <motion.div
            key="empty"
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.25 }}
            className="card-subtle p-8 flex flex-col items-center justify-center gap-2.5 text-center"
          >
            <FolderOpen className="w-8 h-8 text-p-text-faint animate-pulse-soft" />
            <div>
              <div className="text-sm font-semibold text-p-text">No hay proyectos</div>
              <p className="text-xs text-p-text-faint mt-1">
                Crea el primero para empezar a codificar verbatims.
              </p>
            </div>
            <Link to="/wizard" className="btn-primary text-xs py-1.5 px-3.5 rounded-full mt-1">
              <Plus className="w-3.5 h-3.5" /> Nuevo proyecto
            </Link>
          </motion.div>
        ) : (
          <motion.div
            key="content"
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="space-y-6"
          >
            {/* Recent projects — 3 cards */}
            {!searchQuery && recentProjects.length > 0 && (
              <section className="space-y-2.5">
                <h2 className="text-[11px] font-semibold tracking-[0.08em] uppercase text-p-text-faint">
                  Proyectos recientes
                </h2>
                <GlowCardGrid>
                  {recentProjects.map((project, idx) => (
                    <GlowCard
                      key={project.id}
                      to={`/projects/${project.id}`}
                      variant={glowVariantForIndex(idx)}
                      label={project.external_code}
                      title={project.name}
                      footer={studySummaryLabel(project.studies_count, project.rounds_count)}
                    />
                  ))}
                </GlowCardGrid>
              </section>
            )}

            {/* All projects — list */}
            <section className="space-y-2.5">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-[11px] font-semibold tracking-[0.08em] uppercase text-p-text-faint">
                  {searchQuery ? "Resultados" : "Todos los proyectos"}
                </h2>
                <span className="text-[11px] text-p-text-faint">
                  {filteredProjects.length} {filteredProjects.length === 1 ? "proyecto" : "proyectos"}
                </span>
              </div>

              {filteredProjects.length === 0 ? (
                <div className="card-subtle p-6 text-center">
                  <p className="text-sm font-semibold text-p-text">
                    No hay proyectos para &ldquo;{searchQuery}&rdquo;
                  </p>
                  <p className="text-xs text-p-text-faint mt-1">Intenta con otra búsqueda.</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {paginatedProjects.map((project, idx) => {
                    const absoluteIdx = (page - 1) * PAGE_SIZE + idx;
                    return (
                      <Link
                        key={project.id}
                        to={`/projects/${project.id}`}
                        className="project-row group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-p-accent/40"
                      >
                        <div className={`project-row-icon ${ICON_CLASSES[absoluteIdx % ICON_CLASSES.length]}`}>
                          <Sparkles className="w-4 h-4" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-semibold text-p-text truncate group-hover:text-p-accent transition-colors">
                            {project.name}
                          </div>
                          <div className="text-[11px] font-subtitle text-p-text-faint mt-0.5 truncate">
                            {project.external_code}
                            <span className="mx-1.5 text-p-border-mid">·</span>
                            {studySummaryLabel(project.studies_count, project.rounds_count)}
                            <span className="mx-1.5 text-p-border-mid">·</span>
                            {formatRelativeDate(project.created_at)}
                          </div>
                        </div>
                        <span
                          className={[
                            "shrink-0 text-[10px] font-semibold tracking-wide uppercase px-2.5 py-1 rounded-full border",
                            project.rounds_count > 0
                              ? "text-emerald-700 bg-emerald-50 border-emerald-200"
                              : "text-amber-700 bg-amber-50 border-amber-200",
                          ].join(" ")}
                        >
                          {project.studies_count > 0 ? "Activo" : "Sin estudios"}
                        </span>
                      </Link>
                    );
                  })}
                </div>
              )}

              {filteredProjects.length > PAGE_SIZE && (
                <div className="pagination pt-1">
                  <span className="pagination-info">
                    Página {page} de {totalPages} · {filteredProjects.length} proyectos
                  </span>
                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      className="pagination-btn"
                      disabled={page <= 1}
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      aria-label="Página anterior"
                    >
                      <ChevronLeft className="w-3.5 h-3.5" />
                    </button>
                    <button
                      type="button"
                      className="pagination-btn"
                      disabled={page >= totalPages}
                      onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                      aria-label="Página siguiente"
                    >
                      <ChevronRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              )}
            </section>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
