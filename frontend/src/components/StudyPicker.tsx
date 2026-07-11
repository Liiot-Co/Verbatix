import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Plus, ArrowRight, AlertCircle, Tags, Fingerprint } from "lucide-react";
import { useWizardStore } from "@/store/useWizardStore";
import { getStudies, getRounds, createStudy } from "@/api/client";
import type { MarketStudy, Round, StudyMode } from "@/api/types";

const MODES: { value: StudyMode; label: string; hint: string; icon: typeof Tags }[] = [
  { value: "brands", label: "Marcas", hint: "Aprobar/corregir la marca cierra cada respuesta", icon: Fingerprint },
  { value: "codebook", label: "Codebook", hint: "Asignar códigos cierra cada respuesta", icon: Tags },
];

export default function StudyPicker() {
  const setActiveStudyId = useWizardStore((s) => s.setActiveStudyId);
  const setActiveStudyName = useWizardStore((s) => s.setActiveStudyName);
  const setActiveStudyMode = useWizardStore((s) => s.setActiveStudyMode);

  const [studies, setStudies] = useState<MarketStudy[]>([]);
  const [rounds, setRounds] = useState<Round[]>([]);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newMode, setNewMode] = useState<StudyMode>("brands");

  useEffect(() => {
    getStudies().then(setStudies).catch(() => {});
    getRounds().then(setRounds).catch(() => {});
  }, []);

  const pendingFor = (studyId: number) =>
    rounds
      .filter((r) => r.study_id === studyId)
      .reduce((sum, r) => sum + (r.requires_human ?? 0), 0);

  // Stage detail per study — the picker's whole job is to orient the user,
  // so each card states outright where its work stands, not just a count.
  const stageFor = (study: MarketStudy): { label: string; tone: "warning" | "success" | "faint" } => {
    const pending = pendingFor(study.id);
    if (pending > 0) return { label: `${pending} ${pending === 1 ? "pendiente" : "pendientes"}`, tone: "warning" };
    if (study.round_count > 0) return { label: "Completado", tone: "success" };
    return { label: "Sin cargas", tone: "faint" };
  };

  const STAGE_TONE = {
    warning: "text-p-warning bg-p-warning/10 border-p-warning/20",
    success: "text-p-success bg-p-success/10 border-p-success/20",
    faint:   "text-p-text-faint bg-p-bg-subtle border-p-border",
  };

  const enter = (study: MarketStudy) => {
    setActiveStudyId(study.id);
    setActiveStudyName(study.name);
    setActiveStudyMode(study.mode);
  };

  const handleCreate = async () => {
    if (!newName.trim()) return;
    const study = await createStudy(newName.trim(), undefined, newMode);
    setNewName("");
    setCreating(false);
    enter(study);
  };

  return (
    <div className="max-w-4xl mx-auto py-4 space-y-6">
      <div className="space-y-1">
        <h1 className="font-heading text-2xl font-semibold text-p-text tracking-tight">
          Elige un estudio
        </h1>
        <p className="font-subtitle text-sm text-p-text-muted">
          Todo lo que hagas — cargas, revisión, codebook — vive dentro de un estudio.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {studies.map((study) => {
          const stage = stageFor(study);
          return (
            <motion.button
              key={study.id}
              onClick={() => enter(study)}
              className="card p-4 text-left space-y-3 hover:border-p-accent/40 transition-colors"
            >
              {/* Primary: name is what identifies the project, given the most weight */}
              <div className="flex items-start justify-between gap-2">
                <div className="text-base font-bold text-p-text leading-snug">
                  {study.name}
                </div>
                <ArrowRight className="w-4 h-4 text-p-text-faint shrink-0 mt-1" />
              </div>

              {/* Secondary: stage detail — where this project's work actually stands */}
              <div
                className={[
                  "inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border w-fit",
                  STAGE_TONE[stage.tone],
                ].join(" ")}
              >
                {stage.tone === "warning" && <AlertCircle className="w-3.5 h-3.5" />}
                {stage.label}
              </div>

              {/* Tertiary: metadata — quiet, small, last in the reading order */}
              <div className="flex items-center gap-1.5 text-[11px] font-subtitle text-p-text-faint">
                <span className="font-semibold text-p-text-muted">
                  EST-{String(study.id).padStart(4, "0")}
                </span>
                <span className="px-1.5 py-0.5 rounded border border-p-border uppercase tracking-wide">
                  {study.mode === "codebook" ? "Codebook" : "Marcas"}
                </span>
                {study.codebook_size} códigos · {study.round_count} rondas
              </div>
            </motion.button>
          );
        })}

        {creating ? (
          <div className="card p-4 space-y-2.5">
            <label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
              Nombre del estudio
            </label>
            <input
              autoFocus
              className="input w-full text-sm"
              placeholder='ej. "Q3 2024 Latam"'
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleCreate();
                if (e.key === "Escape") setCreating(false);
              }}
            />
            <label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
              Qué cierra una respuesta
            </label>
            <div className="grid grid-cols-2 gap-1.5">
              {MODES.map((m) => (
                <button
                  key={m.value}
                  type="button"
                  onClick={() => setNewMode(m.value)}
                  className={[
                    "text-left p-2.5 rounded-lg border space-y-0.5 transition-colors",
                    newMode === m.value
                      ? "border-p-accent/50 bg-p-accent-soft"
                      : "border-p-border hover:bg-p-bg-subtle",
                  ].join(" ")}
                >
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-p-text">
                    <m.icon className="w-3.5 h-3.5" />
                    {m.label}
                  </div>
                  <p className="text-[10.5px] text-p-text-faint leading-snug">{m.hint}</p>
                </button>
              ))}
            </div>
            <div className="flex gap-1.5">
              <button className="btn-primary text-xs py-1.5 flex-1 justify-center" onClick={handleCreate}>
                Crear y entrar
              </button>
              <button className="btn-ghost text-xs py-1.5 px-3" onClick={() => setCreating(false)}>
                Cancelar
              </button>
            </div>
          </div>
        ) : (
          <button
            onClick={() => setCreating(true)}
            className="card-subtle p-4 flex flex-col items-center justify-center gap-2 text-p-text-muted hover:text-p-text hover:border-p-accent/40 transition-colors min-h-[104px]"
          >
            <Plus className="w-5 h-5" />
            <span className="text-sm font-medium">Nuevo estudio</span>
          </button>
        )}
      </div>
    </div>
  );
}
