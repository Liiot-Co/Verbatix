import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronLeft, ChevronRight, FolderOpen, Plus, Search, Sparkles } from "lucide-react";
import { createProject, getProjects } from "@/api/client";
import type { ProjectListItem } from "@/api/types";
import { useKeyboardShortcuts, registerShortcuts, type PageShortcut } from "@/hooks/useKeyboardShortcuts";
import GlowCard, { GlowCardGrid, glowVariantForIndex } from "@/components/GlowCard";
import AvatarStack from "@/components/AvatarStack";
import WaitingAssignmentsHome from "@/components/WaitingAssignmentsHome";
import { useVerbatixStore } from "@/store/useVerbatixStore";
import { can } from "@/lib/capabilities";
import { isWaitingForAssignments } from "@/lib/sessionRouting";
import MascotAvatar from "@/components/mascot/MascotAvatar";
import StatusPicker from "@/components/mascot/StatusPicker";
import { PRESENCE_CATALOG, type PresenceStatus } from "@/lib/presence";

const PAGE_SIZE = 10;
const RECENT_COUNT = 3;

const ANALYTIC_OPTIONS = [
  { value: "", label: "Todos" },
  { value: "brands", label: "Marcas" },
  { value: "reasons", label: "Razones" },
  { value: "both", label: "Marcas y Razones" },
  { value: "none", label: "Sin objetivo" },
];

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
  const user = useVerbatixStore((state) => state.user);
  const canManageProjects = can(user, "projects.manage");

  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [filterTarget, setFilterTarget] = useState("");
  const [page, setPage] = useState(1);
  const [presenceOpen, setPresenceOpen] = useState(false);
  const presenceStatus: PresenceStatus = user?.presence_status ?? "disponible";
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createExternalCode, setCreateExternalCode] = useState("");
  const [createName, setCreateName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  useEffect(() => {
    if (user && isWaitingForAssignments(user)) {
      setLoading(false);
      return;
    }
    getProjects()
      .then(setProjects)
      .finally(() => setLoading(false));
  }, [user]);

  useEffect(() => {
    setPage(1);
  }, [searchQuery, filterTarget]);

  const sortedByRecent = useMemo(
    () => [...projects].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()),
    [projects]
  );

  const recentProjects = sortedByRecent.slice(0, RECENT_COUNT);

  const filteredProjects = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    let result = sortedByRecent;
    if (filterTarget) {
      result = result.filter((p) => p.analytic_target === filterTarget);
    }
    if (q) {
      result = result.filter(
        (p) =>
          p.name.toLowerCase().includes(q) ||
          (p.external_code || "").toLowerCase().includes(q)
      );
    }
    return result;
  }, [sortedByRecent, searchQuery, filterTarget]);

  const totalPages = Math.max(1, Math.ceil(filteredProjects.length / PAGE_SIZE));
  const paginatedProjects = filteredProjects.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const handleSearchKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      setSearchQuery("");
      (e.target as HTMLInputElement).blur();
    }
  };

  const openCreateModal = () => {
    setCreateExternalCode("");
    setCreateName("");
    setCreateError(null);
    setShowCreateModal(true);
  };

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!createExternalCode.trim() || !createName.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      const project = await createProject(createExternalCode.trim(), createName.trim());
      setShowCreateModal(false);
      navigate(`/wizard?projectId=${project.id}`);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "No se pudo crear el proyecto");
    } finally {
      setCreating(false);
    }
  };

  useEffect(() => {
    const shortcuts: PageShortcut[] = [
    ];
    if (canManageProjects) shortcuts.splice(1, 0, {
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
        action: () => openCreateModal(),
        description: "Nuevo proyecto",
        category: "Acciones",
      });
    shortcuts.push({ key: "r", meta: true, action: () => window.location.reload(), description: "Recargar proyectos", category: "Acciones" });
    registerShortcuts("dashboard", shortcuts);
  }, [canManageProjects, navigate]);

  useKeyboardShortcuts("dashboard");

  if (user && isWaitingForAssignments(user)) {
    return <WaitingAssignmentsHome />;
  }

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
          <div className="flex items-start gap-3 shrink-0">
            {canManageProjects && <button type="button" onClick={openCreateModal} className="btn-primary text-xs py-1.5 px-3.5 rounded-full shrink-0">
              <Plus className="w-3.5 h-3.5" />
              Nuevo proyecto
            </button>}
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap w-full">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-p-text-faint pointer-events-none" />
            <input
              type="search"
              placeholder="Buscar proyectos…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={handleSearchKeyDown}
              className="input pl-9 text-sm rounded-xl w-full"
              aria-label="Buscar proyectos"
            />
          </div>
          <select
            value={filterTarget}
            onChange={(e) => setFilterTarget(e.target.value)}
            className="input text-sm rounded-xl py-2"
            aria-label="Filtrar por objetivo analítico"
          >
            {ANALYTIC_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      </div>

      <div className={`fixed bottom-5 right-5 z-40 transition-opacity duration-150 ${presenceOpen ? "pointer-events-none opacity-0" : ""}`}>
        <MascotAvatar
          status={presenceStatus}
          size="lg"
          onClick={() => setPresenceOpen(true)}
          title={`Cambiar estado — ${PRESENCE_CATALOG[presenceStatus].label}`}
        />
      </div>
      <AnimatePresence>
        {presenceOpen && <StatusPicker status={presenceStatus} onClose={() => setPresenceOpen(false)} variant="floating" />}
      </AnimatePresence>

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
            {canManageProjects && <button type="button" onClick={openCreateModal} className="btn-primary text-xs py-1.5 px-3.5 rounded-full mt-1">
              <Plus className="w-3.5 h-3.5" /> Nuevo proyecto
            </button>}
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
                        <AvatarStack projectId={project.id} users={project.assigned_users_preview} total={project.assigned_users_count} />
                        <span
                          className={[
                            "shrink-0 uppercase tracking-wide",
                            project.rounds_count > 0 ? "badge-success" : "badge-warning",
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

      {showCreateModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-p-text/20 backdrop-blur-[2px]"
          onMouseDown={() => !creating && setShowCreateModal(false)}
        >
          <motion.form
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            className="w-full max-w-md glow-card glow-card-3 p-5 sm:p-6 space-y-4"
            onMouseDown={(e) => e.stopPropagation()}
            onSubmit={handleCreateProject}
          >
            <div className="space-y-1">
              <h2 className="font-heading text-lg font-semibold text-p-text tracking-tight">
                Nuevo proyecto
              </h2>
              <p className="text-sm text-p-text-muted">Datos mínimos para crear el proyecto.</p>
            </div>

            <div className="space-y-3">
              <label className="block space-y-1">
                <span className="text-xs font-semibold text-p-text-muted">Código externo</span>
                <input
                  type="text"
                  className="input text-sm rounded-xl w-full"
                  value={createExternalCode}
                  onChange={(e) => setCreateExternalCode(e.target.value)}
                  autoFocus
                  required
                />
              </label>
              <label className="block space-y-1">
                <span className="text-xs font-semibold text-p-text-muted">Nombre</span>
                <input
                  type="text"
                  className="input text-sm rounded-xl w-full"
                  value={createName}
                  onChange={(e) => setCreateName(e.target.value)}
                  required
                />
              </label>
            </div>

            {createError && <p className="text-xs text-p-error">{createError}</p>}

            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                className="btn-ghost text-xs py-1.5 px-3.5 rounded-full"
                onClick={() => setShowCreateModal(false)}
                disabled={creating}
              >
                Cancelar
              </button>
              <button
                type="submit"
                className="btn-primary text-xs py-1.5 px-3.5 rounded-full"
                disabled={creating || !createExternalCode.trim() || !createName.trim()}
              >
                {creating ? "Creando..." : "Crear proyecto"}
              </button>
            </div>
          </motion.form>
        </div>
      )}
    </div>
  );
}
