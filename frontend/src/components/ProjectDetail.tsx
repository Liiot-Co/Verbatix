import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowRight, FastForward, Plus, Tag } from "lucide-react";
import { getProject } from "@/api/client";
import type { ProjectDetail as ProjectDetailType, RoundSummary, StudySummary } from "@/api/types";
import Breadcrumb from "./Breadcrumb";
import { useVerbatixStore } from "@/store/useVerbatixStore";
import { useKeyboardShortcuts, registerShortcuts } from "@/hooks/useKeyboardShortcuts";

const STATUS_TONE: Record<string, string> = {
  created: "text-p-text-faint bg-p-bg-subtle border-p-border",
  files_uploaded: "text-p-accent bg-p-accent-soft border-p-accent/20",
  draft: "text-p-text-faint bg-p-bg-subtle border-p-border",
  completed: "text-p-success bg-p-success/10 border-p-success/20",
};

function latestRoundOf(project: ProjectDetailType): RoundSummary | null {
  for (const study of project.studies) {
    if (study.rounds[0]) return study.rounds[0];
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
        description: "Nuevo study",
        category: "Acciones",
      },
    ]);
  }, [navigate, projectId]);
  useKeyboardShortcuts("project-detail");

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

  const latestRound = latestRoundOf(project);

  return (
    <div className="max-w-4xl mx-auto py-4 space-y-6">
      <Breadcrumb items={[{ label: "Proyectos", to: "/" }, { label: project.name }]} />

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="space-y-1">
          <h1 className="font-heading text-2xl font-semibold text-p-text tracking-tight">{project.name}</h1>
          <div className="flex items-center gap-1.5 text-xs font-subtitle text-p-text-faint">
            <span className="font-semibold text-p-text-muted">{project.external_code}</span>
            {project.client_name && (
              <span className="px-1.5 py-0.5 rounded border border-p-border uppercase tracking-wide bg-p-bg-subtle">
                {project.client_name}
              </span>
            )}
            <span>{project.studies_count} {project.studies_count === 1 ? "estudio" : "estudios"}</span>
          </div>
        </div>

        {/* General actions */}
        <div className="flex items-center gap-2">
          {latestRound && (
            <button
              onClick={() => navigate(`/rounds/${latestRound.id}/verbatims`)}
              className="btn-ghost text-sm py-2"
              title="Atajo directo a la última ronda"
            >
              <FastForward className="w-4 h-4" /> Continuar última ronda
            </button>
          )}
          <button onClick={() => navigate(`/wizard?projectId=${project.id}`)} className="btn-primary text-sm py-2">
            <Plus className="w-4 h-4" /> Nuevo study
          </button>
        </div>
      </div>

      {project.studies.length === 0 ? (
        <div className="card-subtle p-10 flex flex-col items-center justify-center gap-3 text-center">
          <Tag className="w-8 h-8 text-p-text-faint" />
          <div>
            <div className="text-sm font-semibold text-p-text">Sin studies todavía</div>
            <p className="text-xs text-p-text-faint mt-1">Crea el primero (marcas o razones) para empezar.</p>
          </div>
          <button onClick={() => navigate(`/wizard?projectId=${project.id}`)} className="btn-primary text-sm mt-2">
            <Plus className="w-4 h-4" /> Nuevo study
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          {project.studies.map((study: StudySummary) => (
            <div
              key={study.id}
              className="card p-4 space-y-3"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-p-text">{study.name}</span>
                  <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full border border-p-border bg-p-bg-subtle uppercase tracking-wide text-p-text-muted">
                    {study.coding_type === "brands" ? "Marcas" : "Razones"}
                  </span>
                </div>
                <button
                  onClick={() => navigate(`/wizard?projectId=${project.id}&studyId=${study.id}`)}
                  className="btn-ghost text-xs py-1 px-2"
                >
                  <Plus className="w-3.5 h-3.5" /> Nueva ronda
                </button>
              </div>

              {study.rounds.length === 0 ? (
                <p className="text-xs text-p-text-faint">Sin rondas todavía.</p>
              ) : (
                <div className="space-y-1.5">
                  {study.rounds.map((round) => (
                    <button
                      key={round.id}
                      onClick={() => navigate(`/rounds/${round.id}/verbatims`)}
                      className="w-full flex items-center justify-between gap-3 px-3 py-2 rounded-lg border border-p-border hover:border-p-accent/40 hover:bg-p-bg-subtle/60 transition-colors text-left group"
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-xs font-semibold text-p-text-faint shrink-0">R{round.round_number}</span>
                        <span className="text-sm text-p-text truncate">{round.name}</span>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <span className="text-xs text-p-text-faint">
                          {round.progress.coded}/{round.progress.total}
                        </span>
                        <span
                          className={[
                            "text-[11px] font-semibold px-2 py-0.5 rounded-full border",
                            STATUS_TONE[round.status] ?? STATUS_TONE.created,
                          ].join(" ")}
                        >
                          {round.status}
                        </span>
                        <ArrowRight className="w-3.5 h-3.5 text-p-text-faint group-hover:translate-x-0.5 transition-transform" />
                      </div>
                    </button>
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
