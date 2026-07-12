import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowRight, Plus, Trash2 } from "lucide-react";
import { deleteStudio, getProject } from "@/api/client";
import type { ProjectDetail as ProjectDetailType } from "@/api/types";
import Breadcrumb from "./Breadcrumb";
import { findStudyGroup, parseStudyKey } from "@/lib/projectTree";
import { useVerbatixStore } from "@/store/useVerbatixStore";

const STATUS_TONE: Record<string, string> = {
  created: "text-p-text-faint bg-p-bg-subtle border-p-border",
  files_uploaded: "text-p-accent bg-p-accent-soft border-p-accent/20",
  processing: "text-p-accent bg-p-accent-soft border-p-accent/20",
  preliminary_ready: "text-p-accent bg-p-accent-soft border-p-accent/20",
  draft: "text-p-text-faint bg-p-bg-subtle border-p-border",
  completed: "text-p-success bg-p-success/10 border-p-success/20",
};

export default function StudyDetail() {
  const { projectId, studyKey } = useParams<{ projectId: string; studyKey: string }>();
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

  const parsed = studyKey ? parseStudyKey(studyKey) : null;
  const study = project && studyKey ? findStudyGroup(project, studyKey) : undefined;

  const handleDeleteRoundStudio = async (studioId: string, roundName: string) => {
    if (!confirm(`¿Eliminar la ronda "${roundName}" de este estudio?`)) return;
    await deleteStudio(studioId);
    if (!projectId) return;
    const p = await getProject(projectId);
    setProject(p);
    if (!findStudyGroup(p, studyKey!)) navigate(`/projects/${projectId}`);
  };

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto py-4 space-y-4">
        <div className="skeleton h-6 w-48 rounded" />
        <div className="skeleton h-32 rounded-2xl" />
      </div>
    );
  }

  if (!project || !parsed || !study) {
    return (
      <div className="max-w-4xl mx-auto py-4">
        <p className="text-sm text-p-text-faint">Estudio no encontrado.</p>
        <Link to={projectId ? `/projects/${projectId}` : "/"} className="text-sm text-p-accent mt-2 inline-block">
          Volver al proyecto
        </Link>
      </div>
    );
  }

  const typeLabel = study.coding_type === "brands" ? "Marcas" : "Razones";

  return (
    <div className="max-w-4xl mx-auto py-4 space-y-5">
      <Breadcrumb
        items={[
          { label: "Proyectos", to: "/" },
          { label: project.name, to: `/projects/${project.id}` },
          { label: study.name },
        ]}
      />

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full border border-p-border bg-p-bg-subtle uppercase tracking-wide text-p-text-muted">
              {typeLabel}
            </span>
            <h1 className="font-heading text-xl font-semibold text-p-text tracking-tight">{study.name}</h1>
          </div>
          <p className="font-subtitle text-xs text-p-text-muted">
            {study.rounds.length} {study.rounds.length === 1 ? "ronda" : "rondas"} en {project.external_code}
          </p>
        </div>
        <Link
          to={`/wizard?projectId=${project.id}&study=${study.key}`}
          className="btn-primary text-xs py-1.5 px-3.5 rounded-full inline-flex items-center gap-1.5 shrink-0"
        >
          <Plus className="w-3.5 h-3.5" /> Nueva ronda
        </Link>
      </div>

      {study.rounds.length === 0 ? (
        <div className="card-subtle p-8 text-center space-y-2">
          <p className="text-sm font-semibold text-p-text">Sin rondas todavía</p>
          <p className="text-xs text-p-text-faint">Crea la primera ronda para subir verbatims.</p>
          <Link
            to={`/wizard?projectId=${project.id}&study=${study.key}`}
            className="btn-primary text-xs py-1.5 px-3.5 rounded-full inline-flex items-center gap-1.5 mt-2"
          >
            <Plus className="w-3.5 h-3.5" /> Nueva ronda
          </Link>
        </div>
      ) : (
        <div className="space-y-2">
          {study.rounds.map((entry) => (
            <Link
              key={entry.studio.id}
              to={`/studios/${entry.studio.id}`}
              className="project-row group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-p-accent/40"
            >
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-p-text group-hover:text-p-accent transition-colors">
                  R{entry.round_number} · {entry.round_name}
                </div>
                <div className="text-[11px] font-subtitle text-p-text-faint mt-0.5">
                  {entry.studio.auto_coded}/{entry.studio.verbatims_total} codificados
                </div>
              </div>
              <span
                className={[
                  "shrink-0 text-[10px] font-semibold tracking-wide uppercase px-2.5 py-1 rounded-full border",
                  STATUS_TONE[entry.studio.status] ?? STATUS_TONE.created,
                ].join(" ")}
              >
                {entry.studio.status}
              </span>
              <ArrowRight className="w-4 h-4 text-p-text-faint group-hover:translate-x-0.5 transition-transform shrink-0" />
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  void handleDeleteRoundStudio(entry.studio.id, entry.round_name);
                }}
                className="w-7 h-7 flex items-center justify-center rounded-md text-p-text-faint opacity-0 group-hover:opacity-100 hover:text-p-error hover:bg-p-error/10 transition-all shrink-0"
                title="Eliminar ronda"
                aria-label={`Eliminar ronda ${entry.round_name}`}
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
