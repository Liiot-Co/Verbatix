import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowRight, Plus } from "lucide-react";
import { getProject } from "@/api/client";
import type { ProjectDetail as ProjectDetailType } from "@/api/types";
import Breadcrumb from "./Breadcrumb";
import { codingTypeLabel, studyDisplayName } from "@/lib/projectTree";
import { useVerbatixStore } from "@/store/useVerbatixStore";
import { useKeyboardShortcuts, registerShortcuts } from "@/hooks/useKeyboardShortcuts";

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
        description: "Nuevo estudio",
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

  const studies = project.studies;
  const studiesCount = studies.length;
  const totalRounds = studies.reduce((n, s) => n + s.rounds.length, 0);

  return (
    <div className="max-w-4xl mx-auto py-4 space-y-5">
      <Breadcrumb items={[{ label: "Proyectos", to: "/" }, { label: project.name }]} />

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="space-y-1">
          <h1 className="font-heading text-xl font-semibold text-p-text tracking-tight">{project.name}</h1>
          <div className="flex items-center gap-1.5 text-xs font-subtitle text-p-text-faint">
            <span className="font-semibold text-p-text-muted">{project.external_code}</span>
            <span>
              {studiesCount} {studiesCount === 1 ? "estudio" : "estudios"}
              · {totalRounds} {totalRounds === 1 ? "ronda" : "rondas"}
            </span>
          </div>
        </div>

        <Link
          to={`/wizard?projectId=${project.id}`}
          className="btn-primary text-xs py-1.5 px-3.5 rounded-full inline-flex items-center gap-1.5 shrink-0"
        >
          <Plus className="w-3.5 h-3.5" /> Nuevo estudio
        </Link>
      </div>

      {studies.length === 0 ? (
        <div className="card-subtle p-8 flex flex-col items-center justify-center gap-2.5 text-center">
          <div>
            <div className="text-sm font-semibold text-p-text">Sin estudios todavía</div>
            <p className="text-xs text-p-text-faint mt-1">
              Crea un estudio de Marcas o Razones; luego añade rondas con tus archivos Excel.
            </p>
          </div>
          <Link
            to={`/wizard?projectId=${project.id}`}
            className="btn-primary text-xs py-1.5 px-3.5 rounded-full inline-flex items-center gap-1.5 mt-1"
          >
            <Plus className="w-3.5 h-3.5" /> Nuevo estudio
          </Link>
        </div>
      ) : (
        <section className="space-y-2.5">
          <h2 className="text-[11px] font-semibold tracking-[0.08em] uppercase text-p-text-faint">
            Estudios
          </h2>
          <div className="space-y-2">
            {studies.map((study) => {
              const totalVerbatims = study.rounds.reduce((n, r) => n + r.verbatims_total, 0);
              const totalCoded = study.rounds.reduce((n, r) => n + r.auto_coded, 0);
              const typeLabel = codingTypeLabel(study.coding_type);
              return (
                <Link
                  key={study.id}
                  to={`/projects/${project.id}/studies/${study.id}`}
                  className="project-row group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-p-accent/40"
                >
                  <div className={`project-row-icon project-row-icon-${study.coding_type === "brands" ? "1" : "2"}`}>
                    <span className="text-xs font-bold">{study.coding_type === "brands" ? "M" : "R"}</span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-p-text truncate group-hover:text-p-accent transition-colors">
                      {studyDisplayName(study.name, study.coding_type)}
                    </div>
                    <div className="text-[11px] font-subtitle text-p-text-faint mt-0.5 truncate">
                      {typeLabel}
                      <span className="mx-1.5 text-p-border-mid">·</span>
                      {study.rounds.length} {study.rounds.length === 1 ? "ronda" : "rondas"}
                      <span className="mx-1.5 text-p-border-mid">·</span>
                      {totalCoded}/{totalVerbatims} codificados
                    </div>
                  </div>
                  <ArrowRight className="w-4 h-4 text-p-text-faint group-hover:translate-x-0.5 transition-transform shrink-0" />
                </Link>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
