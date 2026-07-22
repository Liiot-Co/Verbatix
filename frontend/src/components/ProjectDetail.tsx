import React, { useState, useEffect, useMemo } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowRight, FolderOpen, Plus, Search, X } from "lucide-react";
import { getProyecto, createProject } from "@/api/client";
import type { ProyectoDetail } from "@/api/types";
import Breadcrumb from "./Breadcrumb";
import { useVerbatixStore } from "@/store/useVerbatixStore";
import { useKeyboardShortcuts, registerShortcuts } from "@/hooks/useKeyboardShortcuts";
import { can } from "@/lib/capabilities";

const ANALYTIC_OPTIONS = [
  { value: "", label: "Todos los objetivos" },
  { value: "brands", label: "Marcas (Brands)" },
  { value: "reasons", label: "Razones (Reasons)" },
  { value: "both", label: "Mixto (Marcas + Razones)" },
  { value: "none", label: "Sin objetivo" },
];

const ANALYTIC_LABELS: Record<string, string> = {
  brands: "Marcas",
  reasons: "Razones",
  both: "Mixto",
  none: "Sin objetivo",
};

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const setActiveProjectId = useVerbatixStore((s) => s.setActiveProjectId);
  const user = useVerbatixStore((s) => s.user);

  const [proyecto, setProyecto] = useState<ProyectoDetail | null>(null);
  const [loading, setLoading] = useState(true);

  const [searchQuery, setSearchQuery] = useState("");
  const [filterTarget, setFilterTarget] = useState("");

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createExternalCode, setCreateExternalCode] = useState("");
  const [createName, setCreateName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const showToast = useVerbatixStore((s) => s.showToast);

  const openCreateModal = () => {
    setShowCreateModal(true);
    setCreateExternalCode("");
    setCreateName("");
    setCreateError("");
  };

  const handleCreateStudy = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!proyecto) return;
    setCreateError("");
    setCreating(true);
    try {
      const newStudy = await createProject(createExternalCode, createName, proyecto.id);
      setProyecto({
        ...proyecto,
        studies: [
          {
            id: newStudy.id,
            external_code: newStudy.external_code,
            name: newStudy.name,
            analytic_target: "none",
            rounds_count: 0,
            created_at: newStudy.created_at,
            project_id: proyecto.id
          },
          ...proyecto.studies
        ]
      });
      setShowCreateModal(false);
      showToast("Estudio creado exitosamente", "success");
      navigate(`/wizard?projectId=${newStudy.id}`);
    } catch (err: any) {
      setCreateError(err.message || "Error al crear estudio");
    } finally {
      setCreating(false);
    }
  };

  useEffect(() => {
    if (!projectId) return;
    setLoading(true);
    getProyecto(projectId).then((p) => {
      setActiveProjectId(p.id);
      setProyecto(p);
    }).finally(() => setLoading(false));
  }, [projectId, setActiveProjectId]);

  useEffect(() => {
    if (!proyecto) return;
    const shortcuts = [];
    shortcuts.push(
      { key: "Escape", meta: false, action: () => navigate("/"), description: "Volver a proyectos", category: "Navegación" }
    );
    registerShortcuts("project-detail", shortcuts);
  }, [navigate, proyecto]);
  useKeyboardShortcuts("project-detail");

  const filteredStudies = useMemo(() => {
    if (!proyecto) return [];
    const q = searchQuery.toLowerCase().trim();
    return proyecto.studies.filter((s) => {
      if (q && !s.name.toLowerCase().includes(q) && !(s.external_code ?? "").toLowerCase().includes(q)) return false;
      if (filterTarget && s.analytic_target !== filterTarget) return false;
      return true;
    });
  }, [proyecto, searchQuery, filterTarget]);

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto py-4 space-y-4">
        <div className="skeleton h-6 w-40 rounded" />
        <div className="skeleton h-24 rounded-2xl" />
        <div className="skeleton h-40 rounded-2xl" />
      </div>
    );
  }

  if (!proyecto) {
    return (
      <div className="max-w-4xl mx-auto py-4">
        <p className="text-sm text-p-text-faint">Proyecto no encontrado.</p>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto py-4 space-y-5">
      <Breadcrumb items={[{ label: "Proyectos", to: "/" }, { label: proyecto.name }]} />
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="space-y-1">
          <h1 className="font-heading text-xl font-semibold text-p-text tracking-tight">{proyecto.name}</h1>
          <p className="text-xs font-subtitle text-p-text-faint">
            {proyecto.studies.length} {proyecto.studies.length === 1 ? "estudio" : "estudios"}
          </p>
        </div>
        <div className="flex items-start gap-3 shrink-0">
          {can(user, "projects.manage") && (
            <button type="button" onClick={openCreateModal} className="btn-primary text-xs py-1.5 px-3.5 rounded-full shrink-0">
              <Plus className="w-3.5 h-3.5" />
              Nuevo estudio
            </button>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-p-text-faint pointer-events-none" />
          <input
            type="search"
            placeholder="Buscar estudio…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="input pl-9 pr-8 text-sm rounded-xl w-full"
          />
          {searchQuery && (
            <button onClick={() => setSearchQuery("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-p-text-faint hover:text-p-text">
              <X className="w-3.5 h-3.5" />
            </button>
          )}
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

      {filteredStudies.length === 0 ? (
        <div className="card-subtle p-8 flex flex-col items-center justify-center gap-2.5 text-center">
          <FolderOpen className="w-8 h-8 text-p-text-faint animate-pulse-soft" />
          <div>
            <div className="text-sm font-semibold text-p-text">
              {searchQuery || filterTarget ? "Sin resultados" : "Sin estudios"}
            </div>
            <p className="text-xs text-p-text-faint mt-1">
              {searchQuery || filterTarget
                ? "Ningún estudio coincide con los filtros."
                : "Este proyecto no tiene estudios asignados."}
            </p>
          </div>
          {!searchQuery && !filterTarget && can(user, "projects.manage") && (
            <button type="button" onClick={openCreateModal} className="btn-primary text-xs py-1.5 px-3.5 rounded-full mt-1">
              <Plus className="w-3.5 h-3.5" /> Nuevo estudio
            </button>
          )}
        </div>
      ) : (
        <section className="space-y-2.5">
          <div className="flex items-center justify-between">
            <h2 className="text-[11px] font-semibold tracking-[0.08em] uppercase text-p-text-faint">Estudios</h2>
            <span className="text-[11px] text-p-text-faint">
              {filteredStudies.length} {filteredStudies.length === 1 ? "estudio" : "estudios"}
            </span>
          </div>
          <div className="space-y-2">
            {filteredStudies.map((study) => (
              <Link
                key={study.id}
                to={`/studies/${study.id}`}
                className="project-row group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-p-accent/40"
              >
                <div className="project-row-icon project-row-icon-1">
                  <FolderOpen className="w-4 h-4" />
                </div>
                <div className="flex-1 min-w-0 flex items-center gap-3">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-p-text truncate group-hover:text-p-accent transition-colors">
                      {study.name}
                    </div>
                    <div className="text-[11px] font-subtitle text-p-text-faint mt-0.5 truncate">
                      {study.external_code && <><span className="font-semibold text-p-text-muted">{study.external_code}</span><span className="mx-1.5 text-p-border-mid">·</span></>}
                      {study.rounds_count} {study.rounds_count === 1 ? "ronda" : "rondas"}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="badge-info">
                    {ANALYTIC_LABELS[study.analytic_target] ?? study.analytic_target}
                  </span>
                </div>
                <ArrowRight className="w-4 h-4 text-p-text-faint group-hover:translate-x-0.5 transition-transform shrink-0 ml-2" />
              </Link>
            ))}
          </div>
        </section>
      )}

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
            onSubmit={handleCreateStudy}
          >
            <div className="space-y-1">
              <h2 className="font-heading text-lg font-semibold text-p-text tracking-tight">
                Nuevo estudio
              </h2>
              <p className="text-sm text-p-text-muted">Datos mínimos para crear el estudio.</p>
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
                {creating ? "Creando..." : "Crear estudio"}
              </button>
            </div>
          </motion.form>
        </div>
      )}
    </div>
  );
}