import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowRight, FastForward, Plus, Tag, Trash2 } from "lucide-react";
import { deleteRound, deleteStudio, getProject } from "@/api/client";
import type { ProjectDetail as ProjectDetailType, RoundSummary, StudioSummary } from "@/api/types";
import Breadcrumb from "./Breadcrumb";
import { useVerbatixStore } from "@/store/useVerbatixStore";
import { useKeyboardShortcuts, registerShortcuts } from "@/hooks/useKeyboardShortcuts";

const STATUS_TONE: Record<string, string> = {
  created: "text-p-text-faint bg-p-bg-subtle border-p-border",
  files_uploaded: "text-p-accent bg-p-accent-soft border-p-accent/20",
  preliminary_ready: "text-p-accent bg-p-accent-soft border-p-accent/20",
  draft: "text-p-text-faint bg-p-bg-subtle border-p-border",
  completed: "text-p-success bg-p-success/10 border-p-success/20",
};

function latestStudioOf(project: ProjectDetailType): StudioSummary | null {
  for (const round of project.rounds) {
    if (round.studios[0]) return round.studios[0];
  }
  return null;
}

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const setActiveProjectId = useVerbatixStore((s) => s.setActiveProjectId);

  const [project, setProject] = useState<ProjectDetailType | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!projectId) return;
    setLoading(true);
    getProject(projectId)
      .then((p) => {
        setProject(p);
        setActiveProjectId(p.id);
      })
      .finally(() => setLoading(false));
  }, [projectId, setActiveProjectId]);

  useEffect(() => {
    registerShortcuts("project-detail", [
      {
        key: "Escape",
        meta: false,
        action: () => navigate("/"),
        description: "Volver a proyectos",
        category: "Navegación",
      },
      {
        key: "n",
        meta: true,
        shift: true,
        action: () => navigate(`/wizard?projectId=${projectId ?? ""}`),
        description: "Nueva ronda",
        category: "Acciones",
      },
    ]);
  }, [navigate, projectId]);
  useKeyboardShortcuts("project-detail");

  const handleDeleteRound = async (e: React.MouseEvent, round: RoundSummary) => {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm(`¿Eliminar la ronda "${round.name}"? Esto borra todos sus estudios.`)) return;
    await deleteRound(round.id);
    setProject((p) => (p ? { ...p, rounds: p.rounds.filter((r) => r.id !== round.id) } : p));
  };

  const handleDeleteStudio = async (e: React.MouseEvent, roundId: string, studio: StudioSummary) => {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm(`¿Eliminar el estudio "${studio.name}"?`)) return;
    await deleteStudio(studio.id);
    setProject((p) =>
      p
        ? {
            ...p,
            rounds: p.rounds.map((r) =>
              r.id === roundId ? { ...r, studios: r.studios.filter((s) => s.id !== studio.id) } : r
            ),
          }
        : p
    );
  };

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto py-4 space-y-4">
        <div className="skeleton h-6 w-40 rounded" />
        <div className="skeleton h-24 rounded-2xl" />
        <div className="skeleton h-40 rounded-2xl" />
      </div>
    );
  }

  if (!project) {
    return (
      <div className="max-w-4xl mx-auto py-4">
        <p className="text-sm text-p-text-faint">Proyecto no encontrado.</p>
      </div>
    );
  }

  const latestStudio = latestStudioOf(project);

  return (
    <div className="max-w-4xl mx-auto py-4 space-y-6">
      <Breadcrumb items={[{ label: "Proyectos", to: "/" }, { label: project.name }]} />

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="space-y-1">
          <h1 className="font-heading text-2xl font-semibold text-p-text tracking-tight">{project.name}</h1>
          <div className="flex items-center gap-1.5 text-xs font-subtitle text-p-text-faint">
            <span className="font-semibold text-p-text-muted">{project.external_code}</span>
            <span>{project.rounds.length} {project.rounds.length === 1 ? "ronda" : "rondas"}</span>
          </div>
        </div>

        {/* General actions */}
        <div className="flex items-center gap-2">
          {latestStudio && (
            <Link
              to={`/studios/${latestStudio.id}`}
              className="btn-ghost text-sm py-2 inline-flex items-center gap-1.5"
              title="Atajo directo al último estudio"
            >
              <FastForward className="w-4 h-4" /> Continuar último estudio
            </Link>
          )}
          <Link to={`/wizard?projectId=${project.id}`} className="btn-primary text-sm py-2 inline-flex items-center gap-1.5">
            <Plus className="w-4 h-4" /> Nueva ronda
          </Link>
        </div>
      </div>

      {project.rounds.length === 0 ? (
        <div className="card-subtle p-10 flex flex-col items-center justify-center gap-3 text-center">
          <Tag className="w-8 h-8 text-p-text-faint" />
          <div>
            <div className="text-sm font-semibold text-p-text">Sin rondas todavía</div>
            <p className="text-xs text-p-text-faint mt-1">Crea la primera ronda para empezar.</p>
          </div>
          <Link to={`/wizard?projectId=${project.id}`} className="btn-primary text-sm mt-2 inline-flex items-center gap-1.5">
            <Plus className="w-4 h-4" /> Nueva ronda
          </Link>
        </div>
      ) : (
        <div className="space-y-4">
          {project.rounds.map((round: RoundSummary) => (
            <div
              key={round.id}
              className="card p-4 space-y-3"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-p-text-faint">R{round.round_number}</span>
                  <span className="text-sm font-bold text-p-text">{round.name}</span>
                </div>
                <div className="flex items-center gap-1">
                  <Link
                    to={`/wizard?projectId=${project.id}&roundId=${round.id}`}
                    className="btn-ghost text-xs py-1 px-2 inline-flex items-center gap-1"
                  >
                    <Plus className="w-3.5 h-3.5" /> Nuevo estudio
                  </Link>
                  <button
                    type="button"
                    onClick={(e) => handleDeleteRound(e, round)}
                    className="w-6 h-6 flex items-center justify-center rounded-md text-p-text-faint hover:text-p-error hover:bg-p-error/10 transition-colors"
                    title="Eliminar ronda"
                    aria-label={`Eliminar ronda ${round.name}`}
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {round.studios.length === 0 ? (
                <p className="text-xs text-p-text-faint">Sin estudios todavía.</p>
              ) : (
                <div className="space-y-1.5">
                  {round.studios.map((studio) => (
                    <Link
                      key={studio.id}
                      to={`/studios/${studio.id}`}
                      className="w-full flex items-center justify-between gap-3 px-3 py-2 rounded-lg border border-p-border hover:border-p-accent/40 hover:bg-p-bg-subtle/60 transition-colors text-left group"
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full border border-p-border bg-p-bg-subtle uppercase tracking-wide text-p-text-muted shrink-0">
                          {studio.coding_type === "brands" ? "Marcas" : "Razones"}
                        </span>
                        <span className="text-sm text-p-text truncate">{studio.name}</span>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <span className="text-xs text-p-text-faint">
                          {studio.auto_coded}/{studio.verbatims_total}
                        </span>
                        <span
                          className={[
                            "text-[11px] font-semibold px-2 py-0.5 rounded-full border",
                            STATUS_TONE[studio.status] ?? STATUS_TONE.created,
                          ].join(" ")}
                        >
                          {studio.status}
                        </span>
                        <ArrowRight className="w-3.5 h-3.5 text-p-text-faint group-hover:translate-x-0.5 transition-transform" />
                        <button
                          type="button"
                          onClick={(e) => handleDeleteStudio(e, round.id, studio)}
                          className="w-6 h-6 flex items-center justify-center rounded-md text-p-text-faint opacity-0 group-hover:opacity-100 hover:text-p-error hover:bg-p-error/10 transition-all"
                          title="Eliminar estudio"
                          aria-label={`Eliminar estudio ${studio.name}`}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </Link>
                  ))}
                </div>
              )}
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
