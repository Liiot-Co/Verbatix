import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useDropzone } from "react-dropzone";
import { AnimatePresence, motion } from "framer-motion";
import { Check, ChevronLeft, FileSpreadsheet, UploadCloud, AlertCircle } from "lucide-react";
import { useVerbatixStore } from "@/store/useVerbatixStore";
import { playSuccess, playTick } from "@/lib/sound";
import Breadcrumb, { type Crumb } from "./Breadcrumb";
import {
  createProject,
  createRound,
  createStudy,
  getProject,
  importFile,
  uploadFile,
} from "@/api/client";
import type {
  ColumnMap,
  CodingType,
  DetectedSheet,
  OriginMode,
  ProjectDetail,
  Round,
  RoundSummary,
  Study,
  StudySummary,
  UploadedFile,
} from "@/api/types";
import { useKeyboardShortcuts, registerShortcuts, modLabel } from "@/hooks/useKeyboardShortcuts";

type WizardStep = "project" | "study" | "round" | "upload";

const STEPS: { key: WizardStep; label: string; icon: string }[] = [
  { key: "project", label: "Proyecto", icon: "📁" },
  { key: "study", label: "Estudio", icon: "🏷️" },
  { key: "round", label: "Ronda", icon: "🔄" },
  { key: "upload", label: "Excel", icon: "📊" },
];

function ToggleGroup<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div role="radiogroup" className="grid grid-cols-2 gap-1.5">
      {options.map((opt) => (
        <motion.button
          key={opt.value}
          type="button"
          role="radio"
          aria-checked={value === opt.value}
          onClick={() => {
            onChange(opt.value);
            playTick();
          }}
          whileHover={{ scale: 1.01 }}
          whileTap={{ scale: 0.98 }}
          className={[
            "relative text-sm font-medium py-2 rounded-lg border transition-all duration-150 ease-out-expo",
            value === opt.value
              ? "border-p-accent/50 bg-p-accent-soft text-p-accent shadow-sm"
              : "border-p-border text-p-text-muted hover:bg-p-bg-subtle hover:text-p-text",
          ].join(" ")}
        >
          {opt.label}
          <motion.div
            layoutId="toggle-indicator"
            className="absolute inset-0 rounded-lg bg-p-accent/10"
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
          />
        </motion.button>
      ))}
    </div>
  );
}

function useEnterToSubmit(onSubmit: () => void) {
  return (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Enter") return;
    if (e.target instanceof HTMLSelectElement || e.target instanceof HTMLButtonElement) return;
    e.preventDefault();
    onSubmit();
  };
}

const stepVariants = {
  enter: (dir: number) => ({ opacity: 0, x: dir > 0 ? 24 : -24, filter: "blur(4px)" }),
  center: { opacity: 1, x: 0, filter: "blur(0px)" },
  exit: (dir: number) => ({ opacity: 0, x: dir > 0 ? -24 : 24, filter: "blur(4px)" }),
};

export default function CreationWizard() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const setActiveProjectId = useVerbatixStore((s) => s.setActiveProjectId);
  const showToast = useVerbatixStore((s) => s.showToast);

  const [step, setStep] = useState<WizardStep>("project");
  const prevStepIndexRef = useRef(0);
  const [direction, setDirection] = useState(1);

  // Step 1: proyecto
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [newExternalCode, setNewExternalCode] = useState("");
  const [newProjectName, setNewProjectName] = useState("");
  const [newClientName, setNewClientName] = useState("");

  // Step 2: study
  const [study, setStudy] = useState<StudySummary | Study | null>(null);
  const [newStudyName, setNewStudyName] = useState("Marcas");
  const [newStudyCodingType, setNewStudyCodingType] = useState<CodingType>("brands");
  const [newStudyQuestion, setNewStudyQuestion] = useState("");

  // Step 3: ronda
  const [rName, setRName] = useState("Ronda 1 - 2026");
  const [rRoundNumber, setRRoundNumber] = useState(1);
  const [rOriginMode, setROriginMode] = useState<OriginMode>("from_scratch");
  const [rSourceId, setRSourceId] = useState<string>("");
  const [rThreshold, setRThreshold] = useState(3);
  const [rAudit, setRAudit] = useState(10);
  const [round, setRound] = useState<Round | null>(null);

  // Step 4: excel
  const [uploaded, setUploaded] = useState<UploadedFile | null>(null);
  const [verbatimsSheet, setVerbatimsSheet] = useState("");
  const [codebookSheet, setCodebookSheet] = useState("");
  const [columnMap, setColumnMap] = useState<Partial<ColumnMap>>({});
  const [submitting, setSubmitting] = useState(false);
  const [sheetError, setSheetError] = useState<string | null>(null);

  const projectRef = useRef<HTMLInputElement>(null);
  const studyRef = useRef<HTMLInputElement>(null);
  const roundRef = useRef<HTMLInputElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  // Deep-link support: /wizard?projectId=...&studyId=... skips the steps
  // already decided elsewhere (e.g. "Nueva ronda" from a study's detail card).
  useEffect(() => {
    const projectId = searchParams.get("projectId");
    if (!projectId) return;
    getProject(projectId).then((detail) => {
      setProject(detail);
      setActiveProjectId(detail.id);
      const studyId = searchParams.get("studyId");
      const preselectedStudy = studyId ? detail.studies.find((s) => s.id === studyId) : undefined;
      if (preselectedStudy) {
        setStudy(preselectedStudy);
        goToStep("round");
      } else {
        goToStep("study");
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const homologationCandidates: RoundSummary[] = useMemo(() => {
    if (!project || !study) return [];
    return project.studies
      .filter((s) => s.coding_type === study.coding_type)
      .flatMap((s) => s.rounds);
  }, [project, study]);

  const goToStep = (next: WizardStep) => {
    const nextIndex = STEPS.findIndex((s) => s.key === next);
    setDirection(nextIndex >= prevStepIndexRef.current ? 1 : -1);
    prevStepIndexRef.current = nextIndex;
    setStep(next);
  };

  const handleCreateProject = async () => {
    if (!newExternalCode.trim() || !newProjectName.trim()) return;
    const created = await createProject(newExternalCode.trim(), newProjectName.trim(), newClientName.trim() || undefined);
    const detail = await getProject(created.id);
    setProject(detail);
    setActiveProjectId(detail.id);
    playSuccess();
    goToStep("study");
  };

  const handleCreateStudy = async () => {
    if (!project || !newStudyName.trim()) return;
    const created = await createStudy(project.id, {
      name: newStudyName.trim(),
      coding_type: newStudyCodingType,
      survey_question: newStudyQuestion.trim() || undefined,
    });
    setStudy(created);
    playSuccess();
    goToStep("round");
  };

  const handleCreateRound = async () => {
    if (!study || !rName.trim()) return;
    const created = await createRound(study.id, {
      name: rName.trim(),
      round_number: rRoundNumber,
      origin_mode: rOriginMode,
      source_round_id: rOriginMode === "homologated" && rSourceId ? rSourceId : null,
      min_mentions_threshold: rThreshold,
      audit_percentage: rAudit,
    });
    setRound(created);
    if (created.codebook.inherited_codes > 0) {
      showToast(`Se heredaron ${created.codebook.inherited_codes} códigos y ${created.codebook.inherited_aliases} alias`, "success");
    }
    playSuccess();
    goToStep("upload");
  };

  const onDrop = useCallback(
    async (accepted: File[]) => {
      const file = accepted[0];
      if (!file || !round) return;
      setSheetError(null);
      const result = await uploadFile(round.id, file);
      setUploaded(result);
      const verbatimGuess = result.detected_sheets.find((s) => s.guessed_as === "verbatims");
      const codebookGuess = result.detected_sheets.find((s) => s.guessed_as === "codebook");
      setVerbatimsSheet(verbatimGuess?.name ?? result.detected_sheets[0]?.name ?? "");
      setCodebookSheet(codebookGuess?.name ?? "");
      playTick();
    },
    [round]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    multiple: false,
    accept: {
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/vnd.ms-excel": [".xls"],
    },
  });

  const activeSheet: DetectedSheet | undefined = uploaded?.detected_sheets.find((s) => s.name === verbatimsSheet);

  const canImport = !!(round && uploaded && verbatimsSheet && columnMap.verbatim);

  const handleImport = async () => {
    if (!round || !uploaded || !verbatimsSheet || !columnMap.verbatim) return;
    setSubmitting(true);
    try {
      const result = await importFile(
        round.id,
        uploaded.file_id,
        verbatimsSheet,
        columnMap as ColumnMap,
        codebookSheet || undefined
      );
      showToast(
        `Importados ${result.imported.verbatims} verbatims${result.imported.codes ? ` y ${result.imported.codes} códigos` : ""}`,
        "success"
      );
      playSuccess();
      navigate(`/rounds/${round.id}/verbatims`);
    } catch {
      showToast("No se pudo importar el archivo", "error");
    } finally {
      setSubmitting(false);
    }
  };

  const stepIndex = STEPS.findIndex((s) => s.key === step);

  const crumbs: Crumb[] = [
    { label: "Proyectos", to: "/" },
    {
      label: project?.name ?? "Nuevo proyecto",
      ...(project && step !== "project" ? { onClick: () => goToStep("project") } : {}),
    },
  ];
  if (study) crumbs.push({ label: study.name, ...(step !== "study" ? { onClick: () => goToStep("study") } : {}) });
  if (round) crumbs.push({ label: round.name });

  const projectPanelKeyDown = useEnterToSubmit(handleCreateProject);
  const studyPanelKeyDown = useEnterToSubmit(handleCreateStudy);
  const roundPanelKeyDown = useEnterToSubmit(handleCreateRound);

  // Global Escape handling
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (step === "study") return goToStep("project");
      if (step === "round") return goToStep("study");
      if (step === "upload" && !uploaded) return goToStep("round");
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [step, uploaded]);

  // Register shortcuts for this context
  useEffect(() => {
    registerShortcuts("wizard", [
      {
        key: "ArrowRight",
        meta: true,
        action: () => {
          if (step === "project") goToStep("study");
          else if (step === "study") goToStep("round");
          else if (step === "round") goToStep("upload");
        },
        description: "Siguiente paso",
        category: "Navegación",
      },
      {
        key: "ArrowLeft",
        meta: true,
        action: () => {
          if (step === "upload") goToStep("round");
          else if (step === "round") goToStep("study");
          else if (step === "study") goToStep("project");
        },
        description: "Paso anterior",
        category: "Navegación",
      },
      {
        key: "s",
        meta: true,
        action: handleImport,
        description: "Importar (cuando esté listo)",
        category: "Acciones",
      },
    ]);
  }, [step, uploaded, round, handleImport]);

  useKeyboardShortcuts("wizard");

  // Focus refs when step changes
  useEffect(() => {
    setTimeout(() => {
      if (step === "project") projectRef.current?.focus();
      if (step === "study") studyRef.current?.focus();
      if (step === "round") roundRef.current?.focus();
      if (step === "upload" && !uploaded) searchRef.current?.focus();
    }, 100);
  }, [step, uploaded]);

  return (
    <div className="relative max-w-2xl mx-auto py-4 space-y-6">
      {/* Ambient wash — drifts warmer as the wizard progresses */}
      <motion.div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10"
        animate={{
          background: `radial-gradient(60vw 60vh circle at ${20 + stepIndex * 20}% -10%, oklch(var(--p-accent-l) var(--p-accent-c) var(--p-accent-h) / 0.05), transparent 60%), radial-gradient(50vw 50vh circle at ${80 - stepIndex * 15}% 100%, oklch(var(--p-accent-mid-l) var(--p-accent-mid-c) var(--p-accent-mid-h) / 0.05), transparent 55%)`,
        }}
        transition={{ duration: 0.7, ease: "easeInOut" }}
      />

      <Breadcrumb items={crumbs} />

      <div className="space-y-1"
      >
        <h1 className="font-heading text-2xl font-semibold text-p-text tracking-tight">Nuevo proyecto</h1>
      </div>

      {/* Stepper */}
      <nav className="flex items-center"
        aria-label="Progreso del asistente"
      >
        {STEPS.map((s, i) => {
          const done = i < stepIndex;
          const active = i === stepIndex;
          const clickable = done;
          return (
            <motion.div
              key={s.key}
              layout
              className="flex items-center flex-1 last:flex-none"
            >
              <motion.button
                type="button"
                disabled={!clickable}
                onClick={() => clickable && goToStep(s.key)}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                className={[
                  "flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all duration-200 shrink-0",
                  active ? "bg-p-accent text-white shadow-sm" : done ? "bg-p-accent-soft text-p-accent hover:bg-p-accent-soft/70 cursor-pointer" : "text-p-text-faint",
                ].join(" ")}
              >
                <motion.span
                  layoutId={`step-indicator-${i}`}
                  className={[
                    "w-4 h-4 rounded-full flex items-center justify-center text-[10px] shrink-0",
                    active ? "bg-white/25" : done ? "bg-p-accent text-white" : "border border-p-border-mid",
                  ].join(" ")}
                  transition={{ type: "spring", stiffness: 400, damping: 30 }}
                >
                  {done ? <Check className="w-2.5 h-2.5" /> : i + 1}
                </motion.span>
                <span>{s.label}</span>
              </motion.button>
              {i < STEPS.length - 1 && (
                <motion.div className="flex-1 h-px mx-1.5 bg-p-border overflow-hidden rounded-full">
                  <motion.div
                    layout
                    className="h-full bg-gradient-to-r from-p-accent to-p-accent-mid"
                    initial={{ width: done ? "100%" : "0%" }}
                    animate={{ width: done ? "100%" : "0%" }}
                    transition={{ duration: 0.5, ease: [0.19, 1, 0.22, 1] as const }}
                  />
                </motion.div>
              )}
            </motion.div>
          );
        })}
      </nav>

      <AnimatePresence mode="wait" custom={direction}>
        <motion.div
          key={step}
          custom={direction}
          variants={stepVariants}
          initial="enter"
          animate="center"
          exit="exit"
          transition={{ duration: 0.25, ease: [0.19, 1, 0.22, 1] as const }}
        >
          {/* Step 1: Project (creation form always visible) */}
          {step === "project" && (
            <div className="card p-4 space-y-2.5" onKeyDown={projectPanelKeyDown}>
              <div className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Código externo</div>
              <motion.input
                ref={projectRef}
                autoFocus
                className="input w-full text-sm"
                placeholder="32406432"
                value={newExternalCode}
                onChange={(e) => setNewExternalCode(e.target.value)}
                whileFocus={{ scale: 1.002 }}
              />
              <div className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Nombre del proyecto</div>
              <motion.input
                className="input w-full text-sm"
                placeholder="TRACK MULTICATEGORY..."
                value={newProjectName}
                onChange={(e) => setNewProjectName(e.target.value)}
                whileFocus={{ scale: 1.002 }}
              />
              <div className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Cliente</div>
              <motion.input
                className="input w-full text-sm"
                placeholder="Gloria"
                value={newClientName}
                onChange={(e) => setNewClientName(e.target.value)}
                whileFocus={{ scale: 1.002 }}
              />
              <div className="flex gap-1.5 pt-1">
                <motion.button
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  className="btn-primary text-sm py-2 flex-1 justify-center"
                  onClick={handleCreateProject}
                >
                  Crear y continuar
                </motion.button>
              </div>
            </div>
          )}

          {/* Step 2: Study (creation form always visible) */}
          {step === "study" && project && (
            <div className="space-y-3">
              <motion.button
                onClick={() => goToStep("project")}
                whileHover={{ x: -2 }}
                whileTap={{ scale: 0.98 }}
                className="flex items-center gap-1 text-xs text-p-text-muted hover:text-p-text transition-colors"
              >
                <ChevronLeft className="w-3.5 h-3.5" /> {project.name}
              </motion.button>

              <div className="card p-4 space-y-2.5" onKeyDown={studyPanelKeyDown}>
                <div className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Nombre</div>
                <motion.input
                  ref={studyRef}
                  autoFocus
                  className="input w-full text-sm"
                  value={newStudyName}
                  onChange={(e) => setNewStudyName(e.target.value)}
                  whileFocus={{ scale: 1.002 }}
                />

                <div className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Tipo de codificación</div>
                <ToggleGroup
                  options={[
                    { value: "brands" as CodingType, label: "Marcas" },
                    { value: "reasons" as CodingType, label: "Razones" },
                  ]}
                  value={newStudyCodingType}
                  onChange={setNewStudyCodingType}
                />

                <div className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Pregunta de la encuesta</div>
                <motion.input
                  className="input w-full text-sm"
                  placeholder="Q030 - BE1: ¿Qué marcas...?"
                  value={newStudyQuestion}
                  onChange={(e) => setNewStudyQuestion(e.target.value)}
                  whileFocus={{ scale: 1.002 }}
                />

                <div className="flex gap-1.5 pt-1">
                  <motion.button
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.98 }}
                    className="btn-primary text-sm py-2 flex-1 justify-center"
                    onClick={handleCreateStudy}
                  >
                    Crear y continuar
                  </motion.button>
                </div>
              </div>
            </div>
          )}

          {/* Step 3: Round */}
          {step === "round" && study && (
            <div
              className="card p-4 space-y-2.5"
              onKeyDown={roundPanelKeyDown}
            >
              <motion.button
                onClick={() => goToStep("study")}
                whileHover={{ x: -2 }}
                whileTap={{ scale: 0.98 }}
                className="flex items-center gap-1 text-xs text-p-text-muted hover:text-p-text mb-1 transition-colors"
              >
                <ChevronLeft className="w-3.5 h-3.5" /> {study.name}
              </motion.button>

              <motion.div className="space-y-4">
                <div>
                  <motion.label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Nombre</motion.label>
                  <motion.input
                    ref={roundRef}
                    autoFocus
                    className="input w-full text-sm mt-1"
                    value={rName}
                    onChange={(e) => setRName(e.target.value)}
                    whileFocus={{ scale: 1.002 }}
                  />
                </div>

                <div>
                  <motion.label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Número de ronda</motion.label>
                  <motion.input
                    type="number"
                    min={1}
                    className="input w-full text-sm mt-1"
                    value={rRoundNumber}
                    onChange={(e) => setRRoundNumber(Number(e.target.value))}
                    whileFocus={{ scale: 1.002 }}
                  />
                </div>

                <div>
                  <motion.label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Origen</motion.label>
                  <ToggleGroup
                    options={[
                      { value: "from_scratch" as OriginMode, label: "Desde cero" },
                      { value: "homologated" as OriginMode, label: "Homologar" },
                    ]}
                    value={rOriginMode}
                    onChange={setROriginMode}
                  />
                </div>

                {rOriginMode === "homologated" && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                  >
                    <motion.label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Ronda origen</motion.label>
                    <motion.select
                      className="input w-full text-sm mt-1"
                      value={rSourceId}
                      onChange={(e) => setRSourceId(e.target.value)}
                      whileFocus={{ scale: 1.002 }}
                    >
                      <option value="">Sin origen (libro de códigos externo)</option>
                      {homologationCandidates.map((c) => (
                        <option key={c.id} value={c.id}>{c.name}</option>
                      ))}
                    </motion.select>
                  </motion.div>
                )}

                <motion.div className="grid grid-cols-2 gap-3">
                  <div>
                    <motion.label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Mínimo de menciones</motion.label>
                    <motion.input
                      type="number"
                      min={1}
                      className="input w-full text-sm mt-1"
                      value={rThreshold}
                      onChange={(e) => setRThreshold(Number(e.target.value))}
                      whileFocus={{ scale: 1.002 }}
                    />
                  </div>
                  <div>
                    <motion.label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">% de auditoría</motion.label>
                    <motion.input
                      type="number"
                      min={0}
                      max={100}
                      className="input w-full text-sm mt-1"
                      value={rAudit}
                      onChange={(e) => setRAudit(Number(e.target.value))}
                      whileFocus={{ scale: 1.002 }}
                    />
                  </div>
                </motion.div>

                <motion.button
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  className="btn-primary text-sm py-2 w-full justify-center mt-1"
                  onClick={handleCreateRound}
                >
                  Crear ronda <span className="opacity-60 font-normal">(Enter)</span>
                </motion.button>
              </motion.div>
            </div>
          )}

          {/* Step 4: Upload */}
          {step === "upload" && round && (
            <div className="space-y-3">
              <motion.button
                onClick={() => goToStep("round")}
                whileHover={{ x: -2 }}
                whileTap={{ scale: 0.98 }}
                className="flex items-center gap-1 text-xs text-p-text-muted hover:text-p-text"
              >
                <ChevronLeft className="w-3.5 h-3.5" /> {round.name}
              </motion.button>

              {!uploaded ? (
                <div
                  {...getRootProps()}
                  className={[
                    "dropzone",
                    isDragActive ? "dropzone-active" : "hover:border-p-accent/40",
                  ].join(" ")}
                >
                  <input {...getInputProps()} />
                  <motion.div
                    initial={{ opacity: 0, scale: 0.98 }}
                    animate={isDragActive ? { opacity: 1, scale: 1.05, rotate: [0, -2, 2, -2, 0] } : { opacity: 1, scale: 1 }}
                    transition={{ duration: 0.5 }}
                    className="dropzone-icon"
                  >
                    <UploadCloud />
                  </motion.div>
                  <motion.span
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="text-sm font-medium text-p-text"
                  >
                    Arrastra el Excel aquí, o haz clic para elegirlo
                  </motion.span>
                  <span className="text-xs text-p-text-faint">.xlsx o .xls</span>
                </div>
              ) : (
                <motion.div
                  initial={{ opacity: 0, y: 8, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  transition={{ duration: 0.25, ease: [0.19, 1, 0.22, 1] as const }}
                  className="file-preview"
                >
                  <motion.div
                    initial={{ opacity: 0, scale: 0.8 }}
                    animate={{ opacity: 1, scale: 1 }}
                    className="flex items-center gap-2 text-sm font-semibold text-p-text"
                  >
                    <FileSpreadsheet className="w-4 h-4 text-p-accent" />
                    {uploaded.original_filename}
                  </motion.div>

                  <motion.div className="space-y-3">
                    <div>
                      <motion.label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Hoja de verbatims</motion.label>
                      <motion.select
                        className="input w-full text-sm mt-1"
                        value={verbatimsSheet}
                        onChange={(e) => { setVerbatimsSheet(e.target.value); setColumnMap({}); setSheetError(null); }}
                        whileFocus={{ scale: 1.002 }}
                      >
                        {uploaded.detected_sheets.map((s) => (
                          <option key={s.name} value={s.name}>{s.name} ({s.rows} filas)</option>
                        ))}
                      </motion.select>
                    </div>

                    <div>
                      <motion.label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Hoja de libro de códigos (opcional)</motion.label>
                      <motion.select
                        className="input w-full text-sm mt-1"
                        value={codebookSheet}
                        onChange={(e) => setCodebookSheet(e.target.value)}
                        whileFocus={{ scale: 1.002 }}
                      >
                        <option value="">Ninguna</option>
                        {uploaded.detected_sheets.map((s) => (
                          <option key={s.name} value={s.name}>{s.name} ({s.rows} filas)</option>
                        ))}
                      </motion.select>
                    </div>

                    {activeSheet && (
                      <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="grid grid-cols-2 gap-3 pt-1"
                      >
                        <div className="col-span-2">
                          <motion.label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Columna de verbatim</motion.label>
                          <motion.select
                            className="input w-full text-sm mt-1"
                            value={columnMap.verbatim ?? ""}
                            onChange={(e) => setColumnMap((m) => ({ ...m, verbatim: e.target.value }))}
                            whileFocus={{ scale: 1.002 }}
                          >
                            <option value="">Elegir columna...</option>
                            {activeSheet.columns.map((c) => (
                              <option key={c} value={c}>{c}</option>
                            ))}
                          </motion.select>
                        </div>
                        <div>
                          <motion.label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Respondent ID</motion.label>
                          <motion.select
                            className="input w-full text-sm mt-1"
                            value={columnMap.respondent_id ?? ""}
                            onChange={(e) => setColumnMap((m) => ({ ...m, respondent_id: e.target.value }))}
                            whileFocus={{ scale: 1.002 }}
                          >
                            <option value="">(ninguna)</option>
                            {activeSheet.columns.map((c) => (
                              <option key={c} value={c}>{c}</option>
                            ))}
                          </motion.select>
                        </div>
                        <div>
                          <motion.label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Question key</motion.label>
                          <motion.select
                            className="input w-full text-sm mt-1"
                            value={columnMap.question_key ?? ""}
                            onChange={(e) => setColumnMap((m) => ({ ...m, question_key: e.target.value }))}
                            whileFocus={{ scale: 1.002 }}
                          >
                            <option value="">(ninguna)</option>
                            {activeSheet.columns.map((c) => (
                              <option key={c} value={c}>{c}</option>
                            ))}
                          </motion.select>
                        </div>
                      </motion.div>
                    )}

                    {sheetError && (
                      <motion.div
                        initial={{ opacity: 0, y: -10 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="flex items-center gap-2 text-sm text-p-error bg-red-50 border border-red-200 rounded-lg p-3"
                      >
                        <AlertCircle className="w-4 h-4 shrink-0" />
                        {sheetError}
                      </motion.div>
                    )}

                    <motion.div className="flex gap-1.5 pt-1">
                      <motion.button
                        whileHover={{ scale: 1.02 }}
                        whileTap={{ scale: 0.98 }}
                        disabled={!canImport || submitting}
                        className="btn-primary text-sm py-2 flex-1 justify-center"
                        onClick={handleImport}
                      >
                        {submitting ? (
                          <>
                            <motion.span
                              animate={{ rotate: 360 }}
                              transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                              className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full"
                            />
                            Importando...
                          </>
                        ) : (
                          "Importar"
                        )}
                      </motion.button>
                      <motion.button
                        whileHover={{ scale: 1.02 }}
                        whileTap={{ scale: 0.98 }}
                        className="btn-ghost text-sm py-2 px-3"
                        onClick={() => { setUploaded(null); setColumnMap({}); setSheetError(null); }}
                      >
                        Cambiar archivo
                      </motion.button>
                    </motion.div>
                  </motion.div>
                </motion.div>
              )}
            </div>
          )}
        </motion.div>
      </AnimatePresence>

      {/* Keyboard hints */}
      <div className="fixed bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-3 text-xs text-p-text-faint bg-p-surface/90 backdrop-blur-glass border border-p-border rounded-xl px-4 py-2 shadow-lg hidden sm:flex"
      >
        <span className="flex items-center gap-1">
          <kbd className="kbd-hint">{modLabel()}→</kbd> Siguiente
        </span>
        <span className="flex items-center gap-1">
          <kbd className="kbd-hint">{modLabel()}←</kbd> Anterior
        </span>
        <span className="flex items-center gap-1">
          <kbd className="kbd-hint">Enter</kbd> Crear/Continuar
        </span>
        <span className="flex items-center gap-1">
          <kbd className="kbd-hint">Esc</kbd> Cancelar/Volver
        </span>
        <span className="flex items-center gap-1">
          <kbd className="kbd-hint">{modLabel()}S</kbd> Importar
        </span>
        <span className="flex items-center gap-1">
          <kbd className="kbd-hint">{modLabel()}K</kbd> Comandos
        </span>
      </div>
    </div>
  );
}
