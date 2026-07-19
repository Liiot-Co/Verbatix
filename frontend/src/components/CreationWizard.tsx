import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useDropzone } from "react-dropzone";
import { AnimatePresence, motion } from "framer-motion";
import { Check, ChevronDown, ChevronLeft, FileSpreadsheet, UploadCloud, AlertCircle, Files } from "lucide-react";
import { useVerbatixStore } from "@/store/useVerbatixStore";
import { playSuccess, playTick } from "@/lib/sound";
import Breadcrumb, { type Crumb } from "./Breadcrumb";
import {
  createProject,
  createRound,
  classifyQuestion,
  getCodebookSources,
  getProject,
  importFile,
  importClientCatalog,
  previewClientCatalog,
  uploadFile,
} from "@/api/client";
import type {
  CatalogOriginSelection,
  CatalogPreview,
  CodebookSource,
  ColumnMap,
  CodingType,
  DetectedSheet,
  ProjectDetail,
  Round,
  UploadedFile,
} from "@/api/types";
import { useKeyboardShortcuts, registerShortcuts } from "@/hooks/useKeyboardShortcuts";
import { nextRoundNumber } from "@/lib/projectTree";

type WizardStep = "project" | "studio" | "round";

type BatchFileStatus = "pending" | "uploading" | "importing" | "done" | "error";

interface BatchItem {
  file: File;
  status: BatchFileStatus;
  error?: string;
  roundName?: string;
}

const STEPS: { key: WizardStep; label: string; icon: string }[] = [
  { key: "project", label: "Proyecto", icon: "📁" },
  { key: "studio", label: "Configuración", icon: "🏷️" },
  { key: "round", label: "Ronda y Excel", icon: "🔄" },
];

const CODING_LABELS: Record<CodingType, string> = {
  brands: "Marcas",
  reasons: "Razones",
};

const ORIGIN_OPTIONS: {
  value: CatalogOriginSelection["origin"];
  label: string;
  description: string;
}[] = [
  {
    value: "scratch",
    label: "Crear desde cero",
    description: "Los códigos se crean durante la codificación. El libro queda oficial al cerrar la ronda.",
  },
  {
    value: "inherited_round",
    label: "Heredar libro del proyecto",
    description: "Reusa un libro oficial de una ronda anterior o de otro estudio del mismo cliente.",
  },
  {
    value: "imported_client_catalog",
    label: "Homologar libro de códigos",
    description: "Sube el libro oficial del cliente. Cada número de código se respeta tal cual viene.",
  },
];

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
  const isNewRoundFlow = Boolean(searchParams.get("projectId"));
  const setActiveProjectId = useVerbatixStore((s) => s.setActiveProjectId);
  const showToast = useVerbatixStore((s) => s.showToast);

  const [step, setStep] = useState<WizardStep>("project");
  const prevStepIndexRef = useRef(0);
  const [direction, setDirection] = useState(1);

  // Step 1: proyecto
  type WizardProject = Pick<ProjectDetail, "id" | "name" | "external_code">;
  const [project, setProject] = useState<WizardProject | null>(null);
  const [projectDetail, setProjectDetail] = useState<ProjectDetail | null>(null);
  const [newExternalCode, setNewExternalCode] = useState("");
  const [newProjectName, setNewProjectName] = useState("");

  // REQ-07: cada subproyecto elige obligatoriamente su origen de catálogo.
  const [round, setRound] = useState<Round | null>(null);
  const newStudyCodingType: CodingType = "brands";
  const [catalogOrigins, setCatalogOrigins] = useState<Record<CodingType, CatalogOriginSelection>>({
    brands: { origin: "scratch", source_subproject_id: null },
    reasons: { origin: "scratch", source_subproject_id: null },
  });
  const [codebookSources, setCodebookSources] = useState<Record<CodingType, CodebookSource[]>>({
    brands: [],
    reasons: [],
  });
  const [catalogUploads, setCatalogUploads] = useState<Partial<Record<CodingType, UploadedFile>>>({});
  const [catalogSheets, setCatalogSheets] = useState<Partial<Record<CodingType, string>>>({});
  const [catalogPreviews, setCatalogPreviews] = useState<Partial<Record<CodingType, CatalogPreview>>>({});
  const [catalogConfirmed, setCatalogConfirmed] = useState<Partial<Record<CodingType, boolean>>>({});
  // Acordeón del paso Configuración: solo una sección (Marcas/Razones) abierta
  // a la vez para que la pantalla no se alargue.
  const [expandedCodingType, setExpandedCodingType] = useState<CodingType | null>("brands");

  // Step 3: ronda (wave de datos dentro del estudio) + Excel — umbrales de
  // clasificación se configuran por ronda, no por estudio: todos los estudios
  // de una misma ola comparten el mismo mínimo de menciones y % de auditoría.
  const [rName, setRName] = useState("Ronda 1 - 2026");
  const [rRoundNumber, setRRoundNumber] = useState(1);
  const [rThreshold, setRThreshold] = useState(3);
  const [rAudit, setRAudit] = useState(10);

  const [uploaded, setUploaded] = useState<UploadedFile | null>(null);
  const [verbatimsSheet, setVerbatimsSheet] = useState("");
  const [columnMap, setColumnMap] = useState<Partial<ColumnMap>>({});
  const [submitting, setSubmitting] = useState(false);
  const [sheetError, setSheetError] = useState<string | null>(null);
  const [pendingQuestions, setPendingQuestions] = useState<string[]>([]);
  const [questionTypes, setQuestionTypes] = useState<Record<string, CodingType>>({});

  // Archivos adicionales soltados junto al primero: cada uno se convierte en
  // una ronda nueva del mismo estudio (mismo min_mentions/auditoría que la
  // ronda 1), reusando el mapeo de columnas del primer archivo — se asume que
  // todas las rondas de un estudio comparten la misma plantilla de Excel.
  const [batchItems, setBatchItems] = useState<BatchItem[]>([]);
  const [batchRunning, setBatchRunning] = useState(false);

  const projectRef = useRef<HTMLInputElement>(null);
  const roundRef = useRef<HTMLInputElement>(null);

  // Deep-link: /wizard?projectId=... crea una ronda en el Estudio existente.
  useEffect(() => {
    const projectId = searchParams.get("projectId");
    if (!projectId) return;
    getProject(projectId).then((detail) => {
      setProject(detail);
      setProjectDetail(detail);
      setActiveProjectId(detail.id);
      setNewExternalCode(detail.external_code);
      setNewProjectName(detail.name);

      goToStep("studio");
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if ((step !== "studio" && step !== "round") || !project) return;
    getProject(project.id).then((detail) => {
      setProjectDetail(detail);
    });
    Promise.all([
      getCodebookSources(project.id, "brands"),
      getCodebookSources(project.id, "reasons"),
    ]).then(([brands, reasons]) => setCodebookSources({ brands, reasons }));
  }, [step, project]);

  const goToStep = (next: WizardStep) => {
    const nextIndex = STEPS.findIndex((s) => s.key === next);
    setDirection(nextIndex >= prevStepIndexRef.current ? 1 : -1);
    prevStepIndexRef.current = nextIndex;
    setStep(next);
  };

  const handleCreateProject = async () => {
    if (!newExternalCode.trim() || !newProjectName.trim()) return;
    try {
      if (!project) {
        const created = await createProject(newExternalCode.trim(), newProjectName.trim());
        setProject(created);
        setActiveProjectId(created.id);
        setProjectDetail({
          ...created,
          rounds: [],
          categories: [],
          proyecto_id: created.proyecto_id ?? null,
          created_at: new Date().toISOString(),
        });
      }
      playSuccess();
      goToStep("studio");
    } catch {
      showToast("Error al crear el proyecto", "error");
    }
  };

  const handleContinueFromStudio = () => {
    const missingSource = (["brands", "reasons"] as CodingType[]).find(
      (codingType) =>
        catalogOrigins[codingType].origin === "inherited_round"
        && !catalogOrigins[codingType].source_subproject_id
    );
    if (missingSource) {
      setExpandedCodingType(missingSource);
      showToast(`Elige el libro a heredar para ${CODING_LABELS[missingSource]}`, "error");
      return;
    }
    if (projectDetail) {
      const nextNum = nextRoundNumber(projectDetail.rounds ?? []);
      setRRoundNumber(nextNum);
      setRName(`Ronda ${nextNum} - ${new Date().getFullYear()}`);
    }
    playSuccess();
    goToStep("round");
  };

  // La ronda se crea directamente dentro del Estudio (`projects` en schema v8).
  const ensureRound = async (): Promise<Round | null> => {
    if (round) return round;
    if (!project || !rName.trim()) return null;
    try {
      const reasonsSource = codebookSources.reasons.find(
        (source) => source.source_subproject_id === catalogOrigins.reasons.source_subproject_id
      );
      const created = await createRound(project.id, {
        name: rName.trim(),
        round_number: rRoundNumber,
        min_mentions_threshold: rThreshold,
        audit_percentage: rAudit,
        origin_mode: reasonsSource ? "homologated" : "from_scratch",
        source_round_id: reasonsSource?.round_id ?? null,
        catalog_origins: catalogOrigins,
      });
      setRound(created);
      const inheritedCodes = created.subprojects.reduce((sum, subproject) => sum + (subproject.inherited_codes ?? 0), 0);
      const inheritedAliases = created.subprojects.reduce((sum, subproject) => sum + (subproject.inherited_aliases ?? 0), 0);
      if (inheritedCodes > 0) {
        const inheritedNets = created.subprojects.reduce((sum, subproject) => sum + (subproject.inherited_nets ?? 0), 0);
        showToast(`Se heredaron ${inheritedCodes} códigos, ${inheritedAliases} alias y ${inheritedNets} netos`, "success");
      }
      playSuccess();
      return created;
    } catch {
      showToast("Error al crear la ronda", "error");
      return null;
    }
  };

  const onDrop = useCallback(
    async (accepted: File[]) => {
      const [file, ...rest] = accepted;
      if (!file) return;
      const r = await ensureRound();
      if (!r) return;
      setSheetError(null);
      const result = await uploadFile(r.id, file);
      setUploaded(result);
      const verbatimGuess = result.detected_sheets.find((s) => s.guessed_as === "verbatims");
      setVerbatimsSheet(verbatimGuess?.name ?? result.detected_sheets[0]?.name ?? "");
      setBatchItems(rest.map((f) => ({ file: f, status: "pending" as const })));
      playTick();
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [round, project, rName, rRoundNumber, rThreshold, rAudit, catalogOrigins]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    multiple: true,
    accept: {
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/vnd.ms-excel": [".xls"],
      "application/octet-stream": [".dau"],
    },
  });

  const activeSheet: DetectedSheet | undefined = uploaded?.detected_sheets.find((s) => s.name === verbatimsSheet);
  // Un .dau no tiene columna de verbatim que elegir — el backend
  // auto-selecciona las respuestas abiertas del registro y descarta la
  // infraestructura conocida (id, fechas, URLs, metadata) — ver
  // dau._NON_RESPONSE_FIELDS / dau.parse_verbatims.
  const isDau = uploaded?.file_type === "dau";

  const importedCatalogTypes = (["brands", "reasons"] as CodingType[]).filter(
    (codingType) => catalogOrigins[codingType].origin === "imported_client_catalog"
  );
  const catalogsReady = importedCatalogTypes.every((codingType) => catalogConfirmed[codingType]);
  const canImport = !!(
    round
    && uploaded
    && verbatimsSheet
    && (isDau || columnMap.verbatim)
    && catalogsReady
  );

  const loadCatalogPreview = async (
    codingType: CodingType,
    catalogFile: UploadedFile,
    sheet: string
  ) => {
    if (!round || !sheet) return;
    const preview = await previewClientCatalog(round.id, catalogFile.file_id, sheet, codingType);
    setCatalogSheets((current) => ({ ...current, [codingType]: sheet }));
    setCatalogPreviews((current) => ({ ...current, [codingType]: preview }));
    setCatalogConfirmed((current) => ({ ...current, [codingType]: false }));
  };

  const handleCatalogUpload = async (codingType: CodingType, file: File) => {
    const targetRound = await ensureRound();
    if (!targetRound) return;
    try {
      const result = await uploadFile(targetRound.id, file);
      setCatalogUploads((current) => ({ ...current, [codingType]: result }));
      const guessed = result.detected_sheets.find((sheet) => sheet.guessed_as === "codebook")
        ?? result.detected_sheets[0];
      if (!guessed) throw new Error("El archivo no contiene hojas");
      const preview = await previewClientCatalog(
        targetRound.id, result.file_id, guessed.name, codingType
      );
      setCatalogSheets((current) => ({ ...current, [codingType]: guessed.name }));
      setCatalogPreviews((current) => ({ ...current, [codingType]: preview }));
    } catch {
      showToast("No se pudo leer el libro de códigos del cliente", "error");
    }
  };

  const handleConfirmCatalog = async (codingType: CodingType) => {
    const catalogFile = catalogUploads[codingType];
    const sheet = catalogSheets[codingType];
    if (!round || !catalogFile || !sheet) return;
    setSubmitting(true);
    try {
      await importClientCatalog(round.id, catalogFile.file_id, sheet, codingType);
      setCatalogConfirmed((current) => ({ ...current, [codingType]: true }));
      showToast(`Libro de códigos de ${CODING_LABELS[codingType]} homologado`, "success");
    } catch {
      showToast("No se pudo homologar el libro de códigos", "error");
    } finally {
      setSubmitting(false);
    }
  };

  // Cada archivo adicional del lote se convierte en su propia ronda nueva del
  // mismo estudio: crea la ronda, sube el archivo, adivina sus hojas (mismo
  // criterio que el primer archivo) y reusa el columnMap del primero. Un
  // archivo sin hoja de verbatims detectable (o cualquier otro fallo) queda
  // marcado con error y no bloquea al resto del lote.
  const runBatch = async (projectId: string) => {
    setBatchRunning(true);
    const year = new Date().getFullYear();
    let nextNumber = rRoundNumber + 1;

    for (const [i, item] of batchItems.entries()) {
      setBatchItems((items) => items.map((it, idx) => (idx === i ? { ...it, status: "uploading" } : it)));
      const roundName = `Ronda ${nextNumber} - ${year}`;
      try {
        const newRound = await createRound(projectId, {
          name: roundName,
          round_number: nextNumber,
          min_mentions_threshold: rThreshold,
          audit_percentage: rAudit,
          origin_mode: "from_scratch",
          source_round_id: null,
          catalog_origins: {
            brands: { origin: "scratch", source_subproject_id: null },
            reasons: { origin: "scratch", source_subproject_id: null },
          },
          reuse_catalogs_from_round_id: round?.id ?? null,
        });
        const uploadedBatch = await uploadFile(newRound.id, item.file);
        setBatchItems((items) =>
          items.map((it, idx) => (idx === i ? { ...it, status: "importing", roundName: newRound.name } : it))
        );

        const verbatimGuess = uploadedBatch.detected_sheets.find((s) => s.guessed_as === "verbatims");
        if (!verbatimGuess) {
          throw new Error("No se detectó una hoja de verbatims en este archivo");
        }
        await importFile(
          newRound.id,
          uploadedBatch.file_id,
          verbatimGuess.name,
          columnMap as ColumnMap
        );
        setBatchItems((items) => items.map((it, idx) => (idx === i ? { ...it, status: "done" } : it)));
      } catch (err) {
        const message = err instanceof Error ? err.message : "Error desconocido";
        setBatchItems((items) => items.map((it, idx) => (idx === i ? { ...it, status: "error", error: message } : it)));
      }
      nextNumber += 1;
    }
    setBatchRunning(false);
  };

  const handleImport = async () => {
    if (!round || !uploaded || !verbatimsSheet || !(isDau || columnMap.verbatim)) return;
    setSubmitting(true);
    try {
      const result = await importFile(
        round.id,
        uploaded.file_id,
        verbatimsSheet,
        columnMap as ColumnMap
      );
      if (result.pending_questions.length > 0) {
        setPendingQuestions(result.pending_questions);
        setQuestionTypes(Object.fromEntries(result.pending_questions.map((question) => [question, newStudyCodingType])));
        showToast("Clasifica las nuevas variables antes de procesar la ronda.", "info");
        return;
      }
      showToast(
        `Importados ${result.imported.verbatims} verbatims${result.imported.codes ? ` y ${result.imported.codes} códigos` : ""} · codificando en el motor...`,
        "success"
      );
      playSuccess();

      if (batchItems.length > 0 && project) {
        await runBatch(project.id);
      } else {
        navigate(`/rounds/${round.id}/preliminary`);
      }
    } catch {
      showToast("No se pudo importar el archivo", "error");
    } finally {
      setSubmitting(false);
    }
  };

  const handleClassifyQuestions = async () => {
    if (!project || pendingQuestions.length === 0) return;
    setSubmitting(true);
    try {
      await Promise.all(
        pendingQuestions.map((questionKey) =>
          classifyQuestion(project.id, {
            question_key: questionKey,
            coding_type: questionTypes[questionKey] ?? "brands",
          })
        )
      );
      setPendingQuestions([]);
      await handleImport();
    } catch {
      showToast("No se pudieron clasificar las variables nuevas", "error");
    } finally {
      setSubmitting(false);
    }
  };

  const goToStudy = () => {
    if (project) navigate(`/projects/${project.id}`);
  };

  const batchDone = batchItems.length > 0 && !batchRunning && batchItems.every((it) => it.status === "done" || it.status === "error");

  const stepIndex = STEPS.findIndex((s) => s.key === step);

  const activeStudyName = project?.name;
  const crumbs: Crumb[] = [
    { label: "Proyectos", to: "/" },
    {
      label: project?.name ?? "Nuevo proyecto",
      ...(project && step !== "project" ? { onClick: () => goToStep("project") } : {}),
    },
  ];
  if (activeStudyName) crumbs.push({ label: activeStudyName });

  const projectPanelKeyDown = useEnterToSubmit(handleCreateProject);
  const studioPanelKeyDown = useEnterToSubmit(handleContinueFromStudio);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (step === "round") return goToStep("studio");
      if (step === "studio") return goToStep("project");
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [step, uploaded]);

  // Register shortcuts for this context
  useEffect(() => {
    registerShortcuts("wizard", [
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
      if (step === "round") roundRef.current?.focus();
    }, 100);
  }, [step]);

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
        <h1 className="font-heading text-2xl font-semibold text-p-text tracking-tight">
          {isNewRoundFlow || project ? "Nueva ronda" : "Nuevo estudio"}
        </h1>
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
          {/* Step 1: Proyecto */}
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
              <div className="flex gap-1.5 pt-1">
                <motion.button
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  className="btn-primary text-sm py-2 flex-1 justify-center"
                  onClick={handleCreateProject}
                >
                  {project ? "Continuar" : "Crear proyecto"}
                </motion.button>
              </div>
            </div>
          )}

          {/* Step 2: configuración de la ronda */}
          {step === "studio" && project && (
            <div
              className="card p-4 space-y-2.5"
              onKeyDown={studioPanelKeyDown}
            >
              <motion.button
                onClick={() => goToStep("project")}
                whileHover={{ x: -2 }}
                whileTap={{ scale: 0.98 }}
                className="flex items-center gap-1 text-xs text-p-text-muted hover:text-p-text mb-1 transition-colors"
              >
                <ChevronLeft className="w-3.5 h-3.5" /> {project.name}
              </motion.button>

              <motion.div className="space-y-3">
                <div>
                  <h2 className="text-sm font-semibold text-p-text">Origen del libro de códigos</h2>
                  <p className="text-xs text-p-text-muted mt-0.5">
                    Define de dónde parte el libro de códigos de cada tipo. Los números de código existentes nunca se reordenan.
                  </p>
                </div>
                {(["brands", "reasons"] as CodingType[]).map((codingType) => {
                  const selection = catalogOrigins[codingType];
                  const expanded = expandedCodingType === codingType;
                  const selectedOption = ORIGIN_OPTIONS.find((option) => option.value === selection.origin);
                  const source = codebookSources[codingType].find(
                    (candidate) => candidate.source_subproject_id === selection.source_subproject_id
                  );
                  const needsSource = selection.origin === "inherited_round" && !selection.source_subproject_id;
                  return (
                    <div key={codingType} className="rounded-xl border border-p-border overflow-hidden">
                      <button
                        type="button"
                        aria-expanded={expanded}
                        onClick={() => {
                          setExpandedCodingType(expanded ? null : codingType);
                          playTick();
                        }}
                        className="w-full flex items-center justify-between gap-2 px-3 py-2.5 hover:bg-p-bg-subtle transition-colors"
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="text-sm font-semibold text-p-text">{CODING_LABELS[codingType]}</span>
                          <span
                            className={[
                              "text-[11px] font-medium px-2 py-0.5 rounded-full truncate",
                              needsSource
                                ? "bg-p-warning/15 text-p-text-muted"
                                : "bg-p-accent-soft text-p-accent",
                            ].join(" ")}
                          >
                            {needsSource
                              ? "Heredar · falta elegir el libro"
                              : selection.origin === "inherited_round" && source
                                ? `Heredar · ${source.project_name} R${source.round_number}`
                                : selectedOption?.label}
                          </span>
                        </div>
                        <ChevronDown
                          className={[
                            "w-4 h-4 shrink-0 text-p-text-muted transition-transform duration-200",
                            expanded ? "rotate-180" : "",
                          ].join(" ")}
                        />
                      </button>
                      <AnimatePresence initial={false}>
                        {expanded && (
                          <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: "auto", opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            transition={{ duration: 0.2, ease: [0.19, 1, 0.22, 1] as const }}
                          >
                            <div role="radiogroup" className="px-3 pb-3 pt-1 space-y-1.5">
                              {ORIGIN_OPTIONS.map((option) => {
                                const active = selection.origin === option.value;
                                return (
                                  <button
                                    key={option.value}
                                    type="button"
                                    role="radio"
                                    aria-checked={active}
                                    disabled={!!round}
                                    onClick={() => {
                                      setCatalogOrigins((current) => ({
                                        ...current,
                                        [codingType]: { origin: option.value, source_subproject_id: null },
                                      }));
                                      playTick();
                                    }}
                                    className={[
                                      "w-full flex items-start gap-2.5 text-left rounded-lg border p-2.5 transition-all duration-150 disabled:opacity-60 disabled:cursor-not-allowed",
                                      active
                                        ? "border-p-accent/50 bg-p-accent-soft shadow-sm"
                                        : "border-p-border hover:bg-p-bg-subtle",
                                    ].join(" ")}
                                  >
                                    <span
                                      className={[
                                        "mt-0.5 w-3.5 h-3.5 shrink-0 rounded-full border flex items-center justify-center",
                                        active ? "border-p-accent" : "border-p-border-mid",
                                      ].join(" ")}
                                    >
                                      {active && <span className="w-2 h-2 rounded-full bg-p-accent" />}
                                    </span>
                                    <span className="min-w-0">
                                      <span className={["block text-sm font-medium", active ? "text-p-accent" : "text-p-text"].join(" ")}>
                                        {option.label}
                                      </span>
                                      <span className="block text-xs text-p-text-muted mt-0.5">
                                        {option.description}
                                      </span>
                                    </span>
                                  </button>
                                );
                              })}

                              {selection.origin === "inherited_round" && (
                                <div className="pt-1.5">
                                  <label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
                                    Libro oficial a heredar
                                  </label>
                                  {codebookSources[codingType].length === 0 ? (
                                    <p className="mt-1.5 text-xs text-p-text-muted rounded-lg bg-p-bg-subtle p-2.5">
                                      Aún no hay libros oficiales de {CODING_LABELS[codingType]} disponibles.
                                      Un libro queda oficial cuando su ronda cierra la auditoría, o cuando se homologa
                                      el libro de códigos del cliente.
                                    </p>
                                  ) : (
                                    <select
                                      className="input w-full text-sm mt-1"
                                      aria-label={`Libro oficial a heredar para ${CODING_LABELS[codingType]}`}
                                      value={selection.source_subproject_id ?? ""}
                                      disabled={!!round}
                                      onChange={(event) => setCatalogOrigins((current) => ({
                                        ...current,
                                        [codingType]: {
                                          origin: "inherited_round",
                                          source_subproject_id: event.target.value || null,
                                        },
                                      }))}
                                    >
                                      <option value="">Elegir libro...</option>
                                      {codebookSources[codingType].map((candidate) => (
                                        <option
                                          key={candidate.source_subproject_id}
                                          value={candidate.source_subproject_id}
                                        >
                                          {candidate.project_name} · R{candidate.round_number} ({candidate.round_name})
                                        </option>
                                      ))}
                                    </select>
                                  )}
                                  {source && (
                                    <p className="mt-2 text-xs text-p-text-muted">
                                      Vas a heredar {source.codes} códigos, {source.aliases} alias y {source.nets} netos.
                                    </p>
                                  )}
                                </div>
                              )}
                              {selection.origin === "imported_client_catalog" && (
                                <p className="text-xs text-p-text-muted pt-1">
                                  En el siguiente paso subirás el archivo del cliente y revisarás códigos, alias y netos antes de confirmarlo.
                                </p>
                              )}
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>
                  );
                })}

                <motion.button
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  className="btn-primary text-sm py-2 w-full justify-center mt-1"
                  onClick={handleContinueFromStudio}
                >
                  Continuar a ronda <span className="opacity-60 font-normal">(Enter)</span>
                </motion.button>
              </motion.div>
            </div>
          )}

          {/* Step 3: Ronda (wave de datos del estudio) + Excel, en un solo paso */}
          {step === "round" && project && (
            <div className="space-y-3">
              <motion.button
                onClick={() => goToStep("studio")}
                whileHover={{ x: -2 }}
                whileTap={{ scale: 0.98 }}
                className="flex items-center gap-1 text-xs text-p-text-muted hover:text-p-text mb-1 transition-colors"
              >
                <ChevronLeft className="w-3.5 h-3.5" /> {project.name}
              </motion.button>

              <div className="card p-4 space-y-2.5">
                <p className="text-xs text-p-text-faint">
                  Estudio <span className="font-semibold text-p-text-muted">{project.name}</span>
                </p>

                <div className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Nombre de la ronda</div>
                <motion.input
                  ref={roundRef}
                  autoFocus
                  disabled={!!round}
                  className="input w-full text-sm"
                  value={rName}
                  onChange={(e) => setRName(e.target.value)}
                  whileFocus={{ scale: 1.002 }}
                />
                <div className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Número de ronda</div>
                <motion.input
                  type="number"
                  min={1}
                  disabled={!!round}
                  className="input w-full text-sm"
                  value={rRoundNumber}
                  onChange={(e) => setRRoundNumber(Number(e.target.value))}
                  whileFocus={{ scale: 1.002 }}
                />

                <motion.div className={newStudyCodingType === "brands" ? "grid grid-cols-2 gap-3" : "grid grid-cols-1 gap-3"}>
                  {newStudyCodingType === "brands" && (
                    <div>
                      <motion.label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Mínimo de menciones</motion.label>
                      <motion.input
                        type="number"
                        min={1}
                        disabled={!!round}
                        className="input w-full text-sm mt-1"
                        value={rThreshold}
                        onChange={(e) => setRThreshold(Number(e.target.value))}
                        whileFocus={{ scale: 1.002 }}
                      />
                    </div>
                  )}
                  <div>
                    <motion.label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">% de auditoría</motion.label>
                    <motion.input
                      type="number"
                      min={0}
                      max={100}
                      disabled={!!round}
                      className="input w-full text-sm mt-1"
                      value={rAudit}
                      onChange={(e) => setRAudit(Number(e.target.value))}
                      whileFocus={{ scale: 1.002 }}
                    />
                  </div>
                </motion.div>
              </div>

              {importedCatalogTypes.length > 0 && (
                <div className="card p-4 space-y-3">
                  <div>
                    <h2 className="text-sm font-semibold text-p-text">Homologación · Libro de códigos del cliente</h2>
                    <p className="text-xs text-p-text-muted">
                      Sube el libro del cliente, revisa el resumen y confírmalo antes de importar las respuestas.
                    </p>
                  </div>
                  {!round && (
                    <button
                      type="button"
                      className="btn-primary text-sm w-full justify-center"
                      onClick={() => void ensureRound()}
                    >
                      Preparar ronda para cargar los libros
                    </button>
                  )}
                  {round && importedCatalogTypes.map((codingType) => {
                    const catalogFile = catalogUploads[codingType];
                    const preview = catalogPreviews[codingType];
                    const confirmed = catalogConfirmed[codingType];
                    return (
                      <div key={codingType} className="rounded-xl border border-p-border p-3 space-y-2.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-semibold text-p-text">
                            {CODING_LABELS[codingType]}
                          </span>
                          {confirmed && (
                            <span className="flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full bg-p-success/10 text-p-success">
                              <Check className="w-3 h-3" /> Homologado
                            </span>
                          )}
                        </div>
                        {!catalogFile ? (
                          <label
                            className={[
                              "flex items-center justify-center gap-2 rounded-lg border border-dashed border-p-border-mid",
                              "px-3 py-4 text-sm text-p-text-muted cursor-pointer",
                              "hover:border-p-accent/50 hover:bg-p-accent-soft/50 hover:text-p-text",
                              "transition-all duration-200",
                            ].join(" ")}
                          >
                            <UploadCloud className="w-4 h-4 text-p-text-faint" />
                            <span>
                              Subir el libro de códigos{" "}
                              <span className="text-p-text-faint">(.xlsx, .xls)</span>
                            </span>
                            <input
                              type="file"
                              accept=".xlsx,.xls"
                              aria-label={`Libro de códigos de ${CODING_LABELS[codingType]}`}
                              className="sr-only"
                              onChange={(event) => {
                                const file = event.target.files?.[0];
                                if (file) void handleCatalogUpload(codingType, file);
                              }}
                            />
                          </label>
                        ) : (
                          <>
                            <div className="flex items-center gap-2 text-sm font-medium text-p-text">
                              <FileSpreadsheet className="w-4 h-4 shrink-0 text-p-accent" />
                              <span className="truncate">{catalogFile.original_filename}</span>
                            </div>
                            <select
                              className="input w-full text-sm"
                              aria-label={`Hoja del libro de códigos de ${CODING_LABELS[codingType]}`}
                              value={catalogSheets[codingType] ?? ""}
                              disabled={confirmed}
                              onChange={(event) => void loadCatalogPreview(
                                codingType, catalogFile, event.target.value
                              )}
                            >
                              {catalogFile.detected_sheets.map((sheet) => (
                                <option key={sheet.name} value={sheet.name}>
                                  {sheet.name} ({sheet.rows} filas)
                                </option>
                              ))}
                            </select>
                            {preview && (
                              <div className="rounded-lg bg-p-bg-subtle p-2.5 text-xs text-p-text-muted">
                                Vas a homologar {preview.codes} códigos, {preview.aliases} alias y {preview.nets} netos.
                                {preview.system_codes_overflow && (
                                  <span className="block mt-1">
                                    El cliente ocupa 95–99: los códigos de sistema nacerán como 995–999.
                                  </span>
                                )}
                              </div>
                            )}
                            {!confirmed && (
                              <button
                                type="button"
                                className="btn-primary text-sm py-2 w-full justify-center"
                                disabled={!preview || submitting}
                                onClick={() => void handleConfirmCatalog(codingType)}
                              >
                                Confirmar libro de códigos
                              </button>
                            )}
                          </>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {!catalogsReady && (
                <div className="rounded-lg border border-p-warning/40 bg-p-warning/10 p-3 text-xs text-p-text-muted">
                  Confirma los libros de códigos del cliente para habilitar la importación de respuestas.
                </div>
              )}

              {!uploaded ? (
                <div className="space-y-1.5">
                  <div className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
                    Archivo de respuestas (verbatims)
                  </div>
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
                      Arrastra aquí el archivo con las respuestas, o haz clic para elegirlo
                    </motion.span>
                    <span className="text-xs text-p-text-faint">.xlsx, .xls o .dau</span>
                  </div>
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

                  {batchItems.length > 0 && !batchRunning && !batchDone && (
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      className="flex items-start gap-2 text-xs text-p-text-muted bg-p-bg-subtle rounded-lg p-2.5"
                    >
                      <Files className="w-3.5 h-3.5 shrink-0 mt-0.5 text-p-accent" />
                      <span>
                        +{batchItems.length} archivo{batchItems.length > 1 ? "s" : ""} más se importará
                        {batchItems.length > 1 ? "n" : ""} como ronda{batchItems.length > 1 ? "s" : ""} nueva
                        {batchItems.length > 1 ? "s" : ""} al confirmar, reusando el mapeo de columnas de abajo:{" "}
                        {batchItems.map((it) => it.file.name).join(", ")}
                      </span>
                    </motion.div>
                  )}

                  <motion.div className="space-y-3">
                    <div>
                      <motion.label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Hoja de respuestas (verbatims)</motion.label>
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

                    {isDau && activeSheet && (
                      <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        className="text-xs text-p-text-muted bg-p-bg-subtle rounded-lg p-2.5"
                      >
                        Se importarán las respuestas abiertas detectadas en cada registro (
                        {activeSheet.columns.length} campos, excluyendo id/fechas/metadata de la plataforma).
                      </motion.div>
                    )}

                    {!isDau && activeSheet && (
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
                      </motion.div>
                    )}

                    {sheetError && (
                      <motion.div
                        initial={{ opacity: 0, y: -10 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="flex items-center gap-2 text-sm text-p-error bg-p-error/10 border border-p-error/30 rounded-lg p-3"
                      >
                        <AlertCircle className="w-4 h-4 shrink-0" />
                        {sheetError}
                      </motion.div>
                    )}

                    {pendingQuestions.length > 0 && (
                      <div className="space-y-3 rounded-lg border border-p-warning/40 bg-p-warning/10 p-3">
                        <div className="text-sm font-semibold text-p-text">Clasifica las variables nuevas</div>
                        <p className="text-xs text-p-text-muted">
                          Cada variable se envía al subproyecto de Marcas o Razones antes de reintentar la importación.
                        </p>
                        {pendingQuestions.map((questionKey) => (
                          <div key={questionKey} className="grid grid-cols-[1fr_150px] gap-2 items-center">
                            <code className="truncate text-xs text-p-text">{questionKey}</code>
                            <select
                              className="input text-sm"
                              value={questionTypes[questionKey] ?? "brands"}
                              onChange={(event) => setQuestionTypes((current) => ({
                                ...current,
                                [questionKey]: event.target.value as CodingType,
                              }))}
                            >
                              <option value="brands">Marcas</option>
                              <option value="reasons">Razones</option>
                            </select>
                          </div>
                        ))}
                        <button
                          type="button"
                          className="btn-primary text-sm py-2 w-full justify-center"
                          disabled={submitting}
                          onClick={handleClassifyQuestions}
                        >
                          Clasificar y continuar
                        </button>
                      </div>
                    )}

                    {!batchRunning && !batchDone && pendingQuestions.length === 0 && (
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
                          ) : batchItems.length > 0 ? (
                            `Importar (+${batchItems.length} ronda${batchItems.length > 1 ? "s" : ""})`
                          ) : (
                            "Importar"
                          )}
                        </motion.button>
                        <motion.button
                          whileHover={{ scale: 1.02 }}
                          whileTap={{ scale: 0.98 }}
                          className="btn-ghost text-sm py-2 px-3"
                          onClick={() => { setUploaded(null); setColumnMap({}); setSheetError(null); setBatchItems([]); }}
                        >
                          Cambiar archivo{batchItems.length > 0 ? "s" : ""}
                        </motion.button>
                      </motion.div>
                    )}

                    {batchItems.length > 0 && (batchRunning || batchDone) && (
                      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-2 pt-1">
                        <div className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
                          Rondas adicionales
                        </div>
                        {batchItems.map((item, idx) => (
                          <div
                            key={idx}
                            className="flex items-center gap-2 text-xs bg-p-bg-subtle rounded-lg p-2"
                          >
                            {item.status === "done" ? (
                              <Check className="w-3.5 h-3.5 shrink-0 text-p-success" />
                            ) : item.status === "error" ? (
                              <AlertCircle className="w-3.5 h-3.5 shrink-0 text-p-error" />
                            ) : item.status === "pending" ? (
                              <FileSpreadsheet className="w-3.5 h-3.5 shrink-0 text-p-text-faint" />
                            ) : (
                              <motion.span
                                animate={{ rotate: 360 }}
                                transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                                className="w-3 h-3 shrink-0 border-2 border-p-accent/30 border-t-p-accent rounded-full"
                              />
                            )}
                            <span className="flex-1 truncate text-p-text">
                              {item.roundName ?? item.file.name}
                            </span>
                            <span className="text-p-text-faint shrink-0">
                              {item.error ?? (item.status === "pending" ? "En espera" : item.status === "uploading" ? "Subiendo..." : item.status === "importing" ? "Importando..." : "Listo")}
                            </span>
                          </div>
                        ))}

                        {batchDone && (
                          <motion.button
                            whileHover={{ scale: 1.02 }}
                            whileTap={{ scale: 0.98 }}
                            className="btn-primary text-sm py-2 w-full justify-center mt-1"
                            onClick={goToStudy}
                          >
                            Ir al estudio
                          </motion.button>
                        )}
                      </motion.div>
                    )}
                  </motion.div>
                </motion.div>
              )}
            </div>
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
