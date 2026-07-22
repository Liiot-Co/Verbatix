import { useState, useEffect } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowRight, Plus, Search, X } from "lucide-react";
import { getProject } from "@/api/client";
import type { ProjectDetail as ProjectDetailType } from "@/api/types";
import Breadcrumb from "./Breadcrumb";
import { roundPhasePath } from "@/lib/projectTree";
import { useVerbatixStore } from "@/store/useVerbatixStore";
import { useKeyboardShortcuts, registerShortcuts } from "@/hooks/useKeyboardShortcuts";
import ProjectTeamManager from "./ProjectTeamManager";
import { can } from "@/lib/capabilities";

export default function StudyDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const setActiveProjectId = useVerbatixStore((s) => s.setActiveProjectId);
  const user = useVerbatixStore((s) => s.user);
  const canManageRounds = can(user, "rounds.manage");

  const [project, setProject] = useState<ProjectDetailType | null>(null);
  const [loading, setLoading] = useState(true);

  const [roundSearchQuery, setRoundSearchQuery] = useState("");

  useEffect(() => {
    if (!projectId) return;
    setLoading(true);
    getProject(projectId).then((p) => {
      setActiveProjectId(p.id);
      setProject(p);
    }).finally(() => setLoading(false));
  }, [projectId, setActiveProjectId]);

  useEffect(() => {
    if (!project) return;
    const shortcuts = [];
    if (canManageRounds) shortcuts.push(
      { key: "Escape", meta: false, action: () => navigate("/"), description: "Volver a proyectos", category: "Navegación" },
      { key: "n", meta: true, shift: true, action: () => navigate(`/wizard?projectId=${projectId ?? ""}`), description: "Nueva ronda", category: "Acciones" },
    );
    registerShortcuts("project-detail", shortcuts);
  }, [canManageRounds, navigate, projectId, project]);
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
        <p className="text-sm text-p-text-faint">Estudio no encontrado.</p>
      </div>
    );
  }

  const rounds = project.rounds ?? [];
  const filteredRounds = rounds.filter((r) => {
    if (!roundSearchQuery) return true;
    const q = roundSearchQuery.toLowerCase().trim();
    return r.name.toLowerCase().includes(q) || `r${r.round_number}`.includes(q);
  });

  return (
    <div className="max-w-4xl mx-auto py-4 space-y-5">
      <Breadcrumb
        items={[
          { label: "Proyectos", to: "/" },
          ...(project.project_name ? [{ label: project.project_name, to: `/projects/${project.project_id}` }] : []),
          { label: project.name },
        ]}
      />
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h1 className="font-heading text-xl font-semibold text-p-text tracking-tight">
              {project.name}
            </h1>
            {project.external_code && (
              <span className="badge-info text-[11px] px-2 py-0.5">
                {project.external_code}
              </span>
            )}
          </div>
          <p className="text-xs font-subtitle text-p-text-faint">
            {rounds.length} {rounds.length === 1 ? "ronda" : "rondas"}
          </p>
        </div>
        <div className="flex items-start gap-3 shrink-0">
          <ProjectTeamManager
            projectId={project.id}
          />
          {can(user, "rounds.manage") && (
            <button
              type="button"
              onClick={() => navigate(`/wizard?projectId=${project.id}`)}
              className="btn-primary text-xs py-1.5 px-3.5 rounded-full shrink-0"
            >
              <Plus className="w-3.5 h-3.5" />
              Nueva ronda
            </button>
          )}
        </div>
      </div>

      <div className="relative max-w-xs">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-p-text-faint pointer-events-none" />
        <input
          type="search"
          placeholder="Buscar ronda…"
          value={roundSearchQuery}
          onChange={(e) => setRoundSearchQuery(e.target.value)}
          className="input pl-9 pr-8 text-sm rounded-xl w-full"
        />
        {roundSearchQuery && (
          <button
            onClick={() => setRoundSearchQuery("")}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-p-text-faint hover:text-p-text"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {filteredRounds.length === 0 ? (
        <div className="card-subtle p-8 flex flex-col items-center justify-center gap-2.5 text-center">
          <div className="text-sm font-semibold text-p-text">
            {roundSearchQuery ? "Sin resultados" : "Sin rondas"}
          </div>
          <p className="text-xs text-p-text-faint mt-1">
            {roundSearchQuery
              ? "Ninguna ronda coincide con tu búsqueda."
              : "Este estudio aún no tiene rondas configuradas."}
          </p>
          {!roundSearchQuery && can(user, "rounds.manage") && (
            <button
              type="button"
              onClick={() => navigate(`/wizard?projectId=${project.id}`)}
              className="btn-primary text-xs py-1.5 px-3.5 rounded-full mt-1"
            >
              <Plus className="w-3.5 h-3.5" /> Nueva ronda
            </button>
          )}
        </div>
      ) : (
        <section className="space-y-2.5">
          <div className="flex items-center justify-between">
            <h2 className="text-[11px] font-semibold tracking-[0.08em] uppercase text-p-text-faint">
              Rondas
            </h2>
            <span className="text-[11px] text-p-text-faint">
              {filteredRounds.length} {filteredRounds.length === 1 ? "ronda" : "rondas"}
            </span>
          </div>
          <div className="space-y-2">
            {filteredRounds.map((round) => {
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
                  <div className="project-row-icon project-row-icon-2"><span className="text-xs font-bold">R</span></div>
                  <div className="flex-1 min-w-0 flex items-center gap-3">
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-p-text truncate group-hover:text-p-accent transition-colors flex items-center gap-2">
                        R{round.round_number} · {round.name}
                      </div>
                      <div className="text-[11px] font-subtitle text-p-text-faint mt-0.5 truncate">{!processed && !canManageRounds ? "Esperando procesamiento" : `Marcas y razones · ${totalCoded}/${totalVerbatims} codificados`}</div>
                    </div>
                  </div>
                  {setupIncomplete && (
                    <div className="flex-1 flex justify-center px-2">
                      <span className="badge-warning shrink-0 whitespace-nowrap">Configuración incompleta</span>
                    </div>
                  )}
                  {processed || canManageRounds ? <ArrowRight className="w-4 h-4 text-p-text-faint group-hover:translate-x-0.5 transition-transform shrink-0" /> : null}
                </>;
              return processed || canManageRounds || setupIncomplete ? (
                <Link key={round.id} to={target} className="project-row group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-p-accent/40">
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