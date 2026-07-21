import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowRight, Plus } from "lucide-react";
import { getProject } from "@/api/client";
import type { ProjectDetail as ProjectDetailType } from "@/api/types";
import Breadcrumb from "./Breadcrumb";
import { roundPhasePath } from "@/lib/projectTree";
import { useVerbatixStore } from "@/store/useVerbatixStore";
import { useKeyboardShortcuts, registerShortcuts } from "@/hooks/useKeyboardShortcuts";
import { can } from "@/lib/capabilities";
import ProjectTeamManager from "@/components/ProjectTeamManager";

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const setActiveProjectId = useVerbatixStore((s) => s.setActiveProjectId);
  const user = useVerbatixStore((s) => s.user);
  const canManageRounds = can(user, "rounds.manage");

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
    const shortcuts = [
    ];
    if (canManageRounds) shortcuts.push({
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
      });
    registerShortcuts("project-detail", shortcuts);
  }, [canManageRounds, navigate, projectId]);
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

  const rounds = project.rounds ?? [];

  return (
    <div className="max-w-4xl mx-auto py-4 space-y-5">
      <Breadcrumb items={[{ label: "Proyectos", to: "/" }, { label: project.name }]} />

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="space-y-1">
          <h1 className="font-heading text-xl font-semibold text-p-text tracking-tight">{project.name}</h1>
          <div className="flex items-center gap-1.5 text-xs font-subtitle text-p-text-faint">
            <span className="font-semibold text-p-text-muted">{project.external_code}</span>
            <span>
              {rounds.length} {rounds.length === 1 ? "ronda" : "rondas"}
            </span>
          </div>
        </div>

        <div className="flex gap-2">{can(user, "assignments.manage") && <ProjectTeamManager projectId={project.id} />}{canManageRounds && <Link
          to={`/wizard?projectId=${project.id}`}
          className="btn-primary text-xs py-1.5 px-3.5 rounded-full inline-flex items-center gap-1.5 shrink-0"
        >
          <Plus className="w-3.5 h-3.5" /> Nueva ronda
        </Link>}</div>
      </div>

      {rounds.length === 0 ? (
        <div className="card-subtle p-8 flex flex-col items-center justify-center gap-2.5 text-center">
          <div>
            <div className="text-sm font-semibold text-p-text">Sin rondas todavía</div>
            <p className="text-xs text-p-text-faint mt-1">
              Crea la primera ronda para cargar y clasificar tus archivos.
            </p>
          </div>
          {canManageRounds && <Link
            to={`/wizard?projectId=${project.id}`}
            className="btn-primary text-xs py-1.5 px-3.5 rounded-full inline-flex items-center gap-1.5 mt-1"
          >
            <Plus className="w-3.5 h-3.5" /> Nueva ronda
          </Link>}
        </div>
      ) : (
        <section className="space-y-2.5">
          <h2 className="text-[11px] font-semibold tracking-[0.08em] uppercase text-p-text-faint">
            Rondas
          </h2>
          <div className="space-y-2">
            {rounds.map((round) => {
              const totalVerbatims = round.subprojects.reduce((n, subproject) => n + subproject.verbatims_total, 0);
              const totalCoded = round.subprojects.reduce((n, subproject) => n + subproject.auto_coded, 0);
              const processed = !["created", "files_uploaded", "processing"].includes(round.status);
              const setupIncomplete = !!round.setup_incomplete;
              const target = setupIncomplete
                ? `/wizard?projectId=${project.id}&roundId=${round.id}`
                : can(user, "audit.view") && !can(user, "resolution.view")
                ? `/rounds/${round.id}/audit`
                : round.status === "audit_approved" ? `/rounds/${round.id}/report` : roundPhasePath(round.id, round.status);
              const content = <>
                  <div className="project-row-icon project-row-icon-1"><span className="text-xs font-bold">R</span></div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-p-text truncate group-hover:text-p-accent transition-colors">
                      R{round.round_number} · {round.name}
                    </div>
                    <div className="text-[11px] font-subtitle text-p-text-faint mt-0.5 truncate">{!processed && !canManageRounds ? "Esperando procesamiento" : `Marcas y razones · ${totalCoded}/${totalVerbatims} codificados`}</div>
                  </div>
                  {setupIncomplete && (
                    <div className="flex-1 flex justify-center px-2">
                      <span className="badge-warning shrink-0 whitespace-nowrap">
                        Configuración incompleta
                      </span>
                    </div>
                  )}
                  {processed || canManageRounds ? <ArrowRight className="w-4 h-4 text-p-text-faint group-hover:translate-x-0.5 transition-transform shrink-0" /> : null}
                </>;
              return processed || canManageRounds || setupIncomplete ? (
                <Link
                  key={round.id}
                  to={target}
                  className="project-row group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-p-accent/40"
                >
                  {content}
                </Link>
              ) : <div key={round.id} className="project-row opacity-75">{content}</div>;
            })}
          </div>
        </section>
      )}
    </div>
  );
}
