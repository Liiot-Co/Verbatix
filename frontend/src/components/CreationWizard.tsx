import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useDropzone } from "react-dropzone";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronLeft,
  FileSpreadsheet,
  Files,
  UploadCloud,
  Users,
} from "lucide-react";
import { useVerbatixStore } from "@/store/useVerbatixStore";
import { playSuccess, playTick } from "@/lib/sound";
import Breadcrumb, { type Crumb } from "./Breadcrumb";
import FieldSelectionTable, { initialFieldSelections } from "./FieldSelectionTable";
import ProfileReviewPanel from "./ProfileReviewPanel";
import RoundCodingControls, {
  detectedMaxFromFields,
  hasPendingRoundMentionDecision,
  type RoundCodingControlsValue,
} from "./RoundCodingControls";
import {
  createProject,
  createRound,
  classifyQuestion,
  getCodebookSources,
  getProject,
  importFile,
  importClientCatalog,
  previewClientCatalog,
  previewFields,
  resolveImportFlag,
  uploadFile,
  uploadRoundProfile,
} from "@/api/client";
import type {
  CatalogOriginSelection,
  CatalogPreview,
  CodebookSource,
  ColumnMap,
  CodingType,
  DetectedSheet,
  DuplicateFlag,
  FieldPreview,
  FieldSelection,
  ProfileCandidateFlag,
  ProfileReviewSummary,
  ProjectDetail,
  Round,
  RoundProfileSummary,
  UploadedFile,
} from "@/api/types";
import { useKeyboardShortcuts, registerShortcuts } from "@/hooks/useKeyboardShortcuts";
import { nextRoundNumber } from "@/lib/projectTree";
import { guessExcelColumnMap } from "@/lib/excelColumns";

type WizardStep = "project" | "studio" | "round" | "fields" | "review";

type BatchFileStatus = "pending" | "uploading" | "importing" | "done" | "error";

interface BatchItem {
  file: File;
  status: BatchFileStatus;
  error?: string;
  roundName?: string;
}

const STEPS: { key: WizardStep; label: string; icon: string }[] = [
  { key: "project", label: "Proyecto", icon: "📁" },
  { key: "studio", label: "Libro de códigos", icon: "📚" },
  { key: "round", label: "Ronda y Excel", icon: "🔄" },
  { key: "fields", label: "Campos", icon: "🧩" },
];

const CODING_LABELS: Record<CodingType, string> = {
  brands: "Marcas",
  reasons: "Razones",
};

type CodingScope = "brands" | "reasons" | "both";

const SCOPE_OPTIONS: { value: CodingScope; label: string; hint: string }[] = [
  { value: "brands", label: "Solo Marcas", hint: "Respuestas de marcas conocidas / mencionadas" },
  { value: "reasons", label: "Solo Razones", hint: "Respuestas de motivos o atributos" },
  { value: "both", label: "Ambas", hint: "Marcas y razones en la misma ronda" },
];

const SCOPE_CODING_TYPES: Record<CodingScope, CodingType[]> = {
  brands: ["brands"],
  reasons: ["reasons"],
  both: ["brands", "reasons"],
};

function codingTypesForScope(scope: CodingScope): CodingType[] {
  return SCOPE_CODING_TYPES[scope];
}

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

  // REQ-07: la persona elige qué tipos codifica (Marcas / Razones / Ambas) y,
  // de forma obligatoria, el origen del libro de cada tipo elegido.
  const [round, setRound] = useState<Round | null>(null);
  const [codingScope, setCodingScope] = useState<CodingScope>("both");
  const activeCodingTypes = codingTypesForScope(codingScope);
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
  // Acordeón del paso Configuración: arranca cerrado para que la pantalla
  // no se vea larga; la persona abre el tipo que quiera configurar.
  const [expandedCodingType, setExpandedCodingType] = useState<CodingType | null>(null);

  // Step 2: ronda (wave de datos dentro del estudio) + Excel. min_mentions/
  // % auditoría se capturan acá, al soltar el archivo, y viajan con el import
  // — no se pueden editar después: cambiarlas mientras el motor ya procesó con
  // el valor viejo deja el catálogo por frecuencia y el muestreo de auditoría
  // inconsistentes (bug real reportado en producción).
  const [rName, setRName] = useState("Ronda 1 - 2026");
  const [rRoundNumber, setRRoundNumber] = useState(1);
  const [rThreshold, setRThreshold] = useState(3);
  const [rAudit, setRAudit] = useState(10);

  const [uploaded, setUploaded] = useState<UploadedFile | null>(null);
  const [verbatimsSheet, setVerbatimsSheet] = useState("");
  const [columnMap, setColumnMap] = useState<Partial<ColumnMap>>({});
  const [fieldPreviews, setFieldPreviews] = useState<FieldPreview[]>([]);
  const [fieldSelections, setFieldSelections] = useState<FieldSelection[]>([]);
  const [roundControls, setRoundControls] = useState<RoundCodingControlsValue>({
    singleCodeByType: {},
    expectedMaxMentions: null,
    mentionsDecision: null,
  });
  const [roundProfile, setRoundProfile] = useState<RoundProfileSummary | null>(null);
  const [profileUploading, setProfileUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [sheetError, setSheetError] = useState<string | null>(null);
  const [pendingQuestions, setPendingQuestions] = useState<string[]>([]);
  const [questionTypes, setQuestionTypes] = useState<Record<string, CodingType>>({});
  const [importedCount, setImportedCount] = useState(0);
  const [duplicates, setDuplicates] = useState<DuplicateFlag[]>([]);
  const [profileCandidates, setProfileCandidates] = useState<ProfileCandidateFlag[]>([]);
  const [profileSummary, setProfileSummary] = useState<ProfileReviewSummary | null>(null);
  const [editNotes, setEditNotes] = useState<Record<string, string>>({});
  const [resolvingFlagId, setResolvingFlagId] = useState<string | null>(null);

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

      const nextNum = nextRoundNumber(detail.rounds ?? []);
      setRRoundNumber(nextNum);
      setRName(`Ronda ${nextNum} - ${new Date().getFullYear()}`);
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

  // Si el alcance deja fuera el tipo que estaba abierto, cierra el acordeón
  // (no abre otro solo: la persona lo despliega cuando quiera).
  useEffect(() => {
    if (expandedCodingType && !activeCodingTypes.includes(expandedCodingType)) {
      setExpandedCodingType(null);
    }
  }, [activeCodingTypes, expandedCodingType]);

  const goToStep = (next: WizardStep) => {
    const nextIndex = STEPS.findIndex((s) => s.key === next);
    setDirection(nextIndex >= prevStepIndexRef.current ? 1 : -1);
    prevStepIndexRef.current = nextIndex;
    setStep(next);
  };

  const handleCreateProject = async () => {
    if (!newExternalCode.trim() || !newProjectName.trim()) return;
    try {
      let detail = projectDetail;
      if (!project) {
        const created = await createProject(newExternalCode.trim(), newProjectName.trim());
        setProject(created);
        setActiveProjectId(created.id);
        detail = {
          ...created,
          rounds: [],
          categories: [],
          proyecto_id: created.proyecto_id ?? null,
          created_at: new Date().toISOString(),
        };
        setProjectDetail(detail);
      }
      const nextNum = nextRoundNumber(detail?.rounds ?? []);
      setRRoundNumber(nextNum);
      setRName(`Ronda ${nextNum} - ${new Date().getFullYear()}`);
      playSuccess();
      goToStep("studio");
    } catch {
      showToast("Error al crear el proyecto", "error");
    }
  };

  const handleContinueFromStudio = () => {
    const missingSource = activeCodingTypes.find(
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

  // La ronda se crea con SOLO los tipos elegidos (Marcas / Razones / ambas)
  // y el origen de catálogo obligatorio de cada uno.
  const ensureRound = async (): Promise<Round | null> => {
    if (round) return round;
    if (!project || !rName.trim()) return null;
    try {
      const selectedOrigins = Object.fromEntries(
        activeCodingTypes.map((codingType) => [codingType, catalogOrigins[codingType]])
      ) as Partial<Record<CodingType, CatalogOriginSelection>>;
      const reasonsSource = activeCodingTypes.includes("reasons")
        ? codebookSources.reasons.find(
          (source) => source.source_subproject_id === catalogOrigins.reasons.source_subproject_id
        )
        : undefined;
      const created = await createRound(project.id, {
        name: rName.trim(),
        round_number: rRoundNumber,
        min_mentions_threshold: rThreshold,
        audit_percentage: rAudit,
        origin_mode: reasonsSource ? "homologated" : "from_scratch",
        source_round_id: reasonsSource?.round_id ?? null,
        catalog_origins: selectedOrigins,
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

  const handleProfileUpload = async (file: File) => {
    setProfileUploading(true);
    try {
      const r = await ensureRound();
      if (!r) {
        showToast("Escribe el nombre de la ronda antes de subir el perfil.", "error");
        return;
      }
      const result = await uploadRoundProfile(r.id, file);
      setRoundProfile({
        profile_file_id: result.profile_file_id,
        original_filename: result.original_filename,
        total_rows: result.total_rows,
        expected_respondents: result.expected_respondents,
        created_at: null,
      });
      showToast(`Perfil: ${result.expected_respondents} Respondent ID esperados`, "success");
      playTick();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Perfil inválido", "error");
    } finally {
      setProfileUploading(false);
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
      const sheetName = verbatimGuess?.name ?? result.detected_sheets[0]?.name ?? "";
      setVerbatimsSheet(sheetName);
      if (result.file_type !== "dau") {
        const sheet = result.detected_sheets.find((s) => s.name === sheetName);
        setColumnMap(guessExcelColumnMap(sheet?.columns ?? []));
      } else {
        setColumnMap({});
      }
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

  // Selección de campos: para .dau se dispara apenas se sube el archivo (no
  // depende de elegir hoja); para Excel espera a que haya una hoja elegida.
  // Depende de ids/scope estables — NO de arrays recreados por render, o el
  // preview se re-dispara en bucle y resetea roundControls (Sí → No).
  useEffect(() => {
    if (!round || !uploaded) {
      setFieldPreviews([]);
      setFieldSelections([]);
      return;
    }
    if (!isDau && !verbatimsSheet) return;
    const types = codingTypesForScope(codingScope);
    const roundId = round.id;
    const fileId = uploaded.file_id;
    const expectedFromRound = round.expected_max_mentions ?? null;
    const singleFromSp = Object.fromEntries(
      round.subprojects.map((s) => [s.coding_type, !!s.single_code_per_response])
    ) as Partial<Record<CodingType, boolean>>;

    let cancelled = false;
    void previewFields(roundId, fileId, isDau ? undefined : verbatimsSheet).then(({ fields }) => {
      if (cancelled) return;
      setFieldPreviews(fields);
      setFieldSelections(initialFieldSelections(fields));
      const singleCodeByType: Partial<Record<CodingType, boolean>> = {};
      for (const ct of types) {
        // Valor ya guardado en el subproyecto, si no → No (multi); sugerencia
        // DAU también es multi (false). El analista puede cambiar a Sí.
        singleCodeByType[ct] = singleFromSp[ct] ?? false;
      }
      setRoundControls({
        singleCodeByType,
        expectedMaxMentions: expectedFromRound,
        mentionsDecision: null,
      });
    });
    return () => {
      cancelled = true;
    };
  }, [round?.id, uploaded?.file_id, verbatimsSheet, isDau, codingScope]); // round/uploaded por id a propósito

  const importedCatalogTypes = activeCodingTypes.filter(
    (codingType) => catalogOrigins[codingType].origin === "imported_client_catalog"
  );
  const catalogsReady = importedCatalogTypes.every((codingType) => catalogConfirmed[codingType]);
  const detectedMaxMentions = detectedMaxFromFields(fieldPreviews);
  const mentionDecisionsReady = !hasPendingRoundMentionDecision(
    roundControls, detectedMaxMentions, activeCodingTypes
  );
  const canImport = !!(
    round
    && uploaded
    && verbatimsSheet
    && (isDau || (columnMap.verbatim && columnMap.respondent_id))
    && catalogsReady
    && mentionDecisionsReady
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
          catalog_origins: Object.fromEntries(
            activeCodingTypes.map((codingType) => [codingType, catalogOrigins[codingType]])
          ),
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
    if (!round || !uploaded || !verbatimsSheet || !(isDau || (columnMap.verbatim && columnMap.respondent_id))) return;
    setSubmitting(true);
    try {
      const result = await importFile(
        round.id,
        uploaded.file_id,
        verbatimsSheet,
        columnMap as ColumnMap,
        // El wizard de selección de campos solo controla el import para .dau
        // (ver Task 8): en Excel, "field" es la columna del sheet, que no
        // corresponde al question_key real de cada fila (viene de la columna
        // "Question ID"), así que field_selections no aplicaría a nada real.
        isDau
          ? {
            fieldSelections: fieldSelections.map((fs) => ({
              ...fs,
              coding_type: codingScope === "both"
                ? fs.coding_type
                : (activeCodingTypes[0] ?? fs.coding_type),
            })),
            singleCodeByType: Object.fromEntries(
              activeCodingTypes.map((ct) => [ct, roundControls.singleCodeByType[ct] ?? false])
            ),
            expectedMaxMentions: roundControls.expectedMaxMentions,
            mentionsDecision: roundControls.mentionsDecision,
          }
          : {
            singleCodeByType: Object.fromEntries(
              activeCodingTypes.map((ct) => [ct, roundControls.singleCodeByType[ct] ?? false])
            ),
            expectedMaxMentions: roundControls.expectedMaxMentions,
            mentionsDecision: roundControls.mentionsDecision,
          }
      );
      if (result.pending_questions.length > 0) {
        const defaultType = activeCodingTypes[0] ?? "brands";
        setPendingQuestions(result.pending_questions);
        setQuestionTypes(Object.fromEntries(result.pending_questions.map((question) => [question, defaultType])));
        showToast(
          isDau
            ? "Este .dau tiene variables fuera de la plantilla conocida — revisa el detalle antes de continuar."
            : "Clasifica las nuevas variables antes de procesar la ronda.",
          "info"
        );
        return;
      }
      for (const warning of result.warnings ?? []) {
        showToast(warning, "info");
      }
      setImportedCount(result.imported.verbatims);
      setDuplicates(result.review.duplicates ?? []);
      setProfileCandidates(result.review.profile_candidates ?? []);
      setProfileSummary(result.review.profile ?? null);
      playSuccess();

      const pendingFlags = result.review.pending_flags ?? 0;
      const hasProfileReview =
        Boolean(result.review.profile?.has_profile)
        || (result.review.profile_candidates?.length ?? 0) > 0;

      if (pendingFlags > 0 || hasProfileReview) {
        setStep("review");
        showToast(
          pendingFlags > 0
            ? `Importados ${result.imported.verbatims} verbatims · ${pendingFlags} pendientes de revisión (perfil / duplicados).`
            : `Importados ${result.imported.verbatims} verbatims · cruce con perfil OK.`,
          pendingFlags > 0 ? "info" : "success",
        );
        if (pendingFlags === 0 && batchItems.length > 0 && project) {
          await runBatch(project.id);
        }
        return;
      }

      showToast(
        `Importados ${result.imported.verbatims} verbatims${result.imported.codes ? ` y ${result.imported.codes} códigos` : ""} · codificando en el motor...`,
        "success"
      );

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

  const handleResolveReviewFlag = async (
    flag: { flag_id: string },
    action: "keep" | "remove" | "edit",
    kind: "duplicate" | "profile" = "duplicate",
  ) => {
    if (resolvingFlagId || !round) return;
    setResolvingFlagId(flag.flag_id);
    try {
      const result = await resolveImportFlag(
        flag.flag_id,
        action,
        action === "edit" ? editNotes[flag.flag_id] : undefined,
      );
      if (kind === "duplicate") {
        setDuplicates((current) =>
          current.map((d) => (d.flag_id === flag.flag_id ? { ...d, status: result.status } : d))
        );
      } else {
        setProfileCandidates((current) =>
          current.map((c) => (c.flag_id === flag.flag_id ? { ...c, status: result.status } : c))
        );
      }
      playTick();
      if (result.pending_flags === 0) {
        playSuccess();
        showToast("Revisión resuelta · codificando en el motor...", "success");
        if (batchItems.length > 0 && project) {
          await runBatch(project.id);
        } else {
          navigate(`/rounds/${round.id}/preliminary`);
        }
      }
    } catch {
      showToast("No se pudo resolver la decisión.", "error");
    } finally {
      setResolvingFlagId(null);
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
            coding_type: questionTypes[questionKey] ?? activeCodingTypes[0] ?? "brands",
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
      if (step === "round" || step === "studio" || step === "fields" || step === "review") return goToStep("project");
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

  // El paso "fields" (revisión de campos) necesita más ancho que el resto
  // del wizard para que la tabla no quede apretada — el contenedor exterior
  // ya no fija max-width; cada paso lo declara por su cuenta.
  const stepContentWidth = step === "fields" || step === "review" ? "max-w-4xl" : "max-w-2xl";

  return (
    <div className="relative mx-auto py-4 space-y-6 px-4">
      {/* Ambient wash — drifts warmer as the wizard progresses */}
      <motion.div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10"
        animate={{
          background: `radial-gradient(60vw 60vh circle at ${20 + stepIndex * 20}% -10%, oklch(var(--p-accent-l) var(--p-accent-c) var(--p-accent-h) / 0.05), transparent 60%), radial-gradient(50vw 50vh circle at ${80 - stepIndex * 15}% 100%, oklch(var(--p-accent-mid-l) var(--p-accent-mid-c) var(--p-accent-mid-h) / 0.05), transparent 55%)`,
        }}
        transition={{ duration: 0.7, ease: "easeInOut" }}
      />

      <div className="max-w-2xl mx-auto space-y-6">
        <Breadcrumb items={crumbs} />

        <div className="space-y-1">
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
      </div>

      <AnimatePresence mode="wait" custom={direction}>
        <motion.div
          key={step}
          custom={direction}
          variants={stepVariants}
          initial="enter"
          animate="center"
          exit="exit"
          transition={{ duration: 0.25, ease: [0.19, 1, 0.22, 1] as const }}
          className={`${stepContentWidth} mx-auto`}
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
                  <h2 className="text-sm font-semibold text-p-text">¿Qué vas a codificar?</h2>
                  <p className="text-xs text-p-text-muted mt-0.5">
                    Elige Marcas, Razones o ambas. Luego defines el origen del libro solo para lo seleccionado.
                  </p>
                </div>
                <div role="radiogroup" aria-label="Alcance de la ronda" className="grid grid-cols-3 gap-1.5">
                  {SCOPE_OPTIONS.map((option) => {
                    const active = codingScope === option.value;
                    return (
                      <button
                        key={option.value}
                        type="button"
                        role="radio"
                        aria-checked={active}
                        disabled={!!round}
                        onClick={() => {
                          setCodingScope(option.value);
                          playTick();
                        }}
                        className={[
                          "rounded-lg border px-2 py-2.5 text-center transition-all duration-150 disabled:opacity-60 disabled:cursor-not-allowed",
                          active
                            ? "border-p-accent/50 bg-p-accent-soft shadow-sm"
                            : "border-p-border hover:bg-p-bg-subtle",
                        ].join(" ")}
                      >
                        <span className={["block text-sm font-medium", active ? "text-p-accent" : "text-p-text"].join(" ")}>
                          {option.label}
                        </span>
                        <span className="block text-[11px] text-p-text-muted mt-0.5 leading-snug">
                          {option.hint}
                        </span>
                      </button>
                    );
                  })}
                </div>

                <div className="pt-1">
                  <h2 className="text-sm font-semibold text-p-text">Origen del libro de códigos</h2>
                  <p className="text-xs text-p-text-muted mt-0.5">
                    Obligatorio para cada tipo elegido. Los números de código existentes nunca se reordenan.
                  </p>
                </div>
                {activeCodingTypes.map((codingType) => {
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
                onClick={() => goToStep("project")}
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

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <div className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Mínimo de menciones</div>
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
                  <div>
                    <div className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">% de auditoría</div>
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
                </div>
                <p className="text-xs text-p-text-faint">
                  Se fijan al soltar el archivo — no se pueden cambiar después de importar.
                </p>
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

              {/* REQ-05: perfil siempre visible (antes o después del Excel de respuestas) */}
              <div className="rounded-lg border border-p-accent/30 bg-p-accent/5 p-3 space-y-2">
                <div className="text-xs font-semibold text-p-text uppercase tracking-wide">
                  Perfil de referencia (opcional)
                </div>
                <p className="text-[11px] text-p-text-muted">
                  Excel pactado con el cliente (columna <span className="font-medium">Respondent ID</span>).
                  Al importar las respuestas se compara quién llegó vs quién se esperaba.
                  Si no subes perfil, la ronda funciona igual que siempre.
                </p>
                {roundProfile ? (
                  <p className="text-xs text-p-text">
                    Activo: <span className="font-medium">{roundProfile.original_filename}</span>
                    {" · "}
                    {roundProfile.expected_respondents} Respondent ID esperados
                  </p>
                ) : (
                  <p className="text-xs text-p-text-faint">Sin perfil cargado todavía.</p>
                )}
                <label className={[
                  "btn-secondary text-xs py-1.5 px-2.5 inline-flex cursor-pointer",
                  profileUploading ? "opacity-50 pointer-events-none" : "",
                ].join(" ")}>
                  <input
                    type="file"
                    accept=".xlsx,.xls"
                    className="sr-only"
                    disabled={profileUploading}
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      e.target.value = "";
                      if (f) void handleProfileUpload(f);
                    }}
                  />
                  {profileUploading
                    ? "Subiendo…"
                    : roundProfile
                      ? "Cambiar perfil .xlsx"
                      : "Subir perfil .xlsx"}
                </label>
              </div>

              {!uploaded ? (
                <div className="space-y-3">
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
                        onChange={(e) => {
                          setVerbatimsSheet(e.target.value);
                          setSheetError(null);
                          if (uploaded && uploaded.file_type !== "dau") {
                            const sheet = uploaded.detected_sheets.find((s) => s.name === e.target.value);
                            setColumnMap(guessExcelColumnMap(sheet?.columns ?? []));
                          } else {
                            setColumnMap({});
                          }
                        }}
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
                        className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1"
                      >
                        <div>
                          <motion.label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
                            Columna Respondent ID
                          </motion.label>
                          <p className="text-[10px] text-p-text-faint mt-0.5 mb-1">
                            Se cruza con el perfil de referencia
                          </p>
                          <motion.select
                            className="input w-full text-sm"
                            value={columnMap.respondent_id ?? ""}
                            onChange={(e) => setColumnMap((m) => ({ ...m, respondent_id: e.target.value }))}
                            whileFocus={{ scale: 1.002 }}
                          >
                            <option value="">Elegir columna...</option>
                            {activeSheet.columns.map((c) => (
                              <option key={c} value={c}>{c}</option>
                            ))}
                          </motion.select>
                        </div>
                        <div>
                          <motion.label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
                            Columna de verbatim
                          </motion.label>
                          <p className="text-[10px] text-p-text-faint mt-0.5 mb-1">
                            Texto abierto a clasificar
                          </p>
                          <motion.select
                            className="input w-full text-sm"
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

                    {fieldPreviews.length > 0 && (
                      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="pt-1">
                        <motion.button
                          whileHover={{ scale: 1.02 }}
                          whileTap={{ scale: 0.98 }}
                          className="btn-primary text-sm py-2 w-full justify-center"
                          onClick={() => goToStep("fields")}
                        >
                          Continuar · revisar campos ({fieldPreviews.length})
                        </motion.button>
                      </motion.div>
                    )}
                  </motion.div>
                </motion.div>
              )}
            </div>
          )}

          {/* Step 4: Campos — revisión de la selección de campos, en su propio
              paso porque con .dau (20+ campos) necesita más ancho que el
              resto del wizard para no quedar apretada (ver stepContentWidth). */}
          {step === "fields" && project && (
            <div className="space-y-3">
              <motion.button
                onClick={() => goToStep("round")}
                whileHover={{ x: -2 }}
                whileTap={{ scale: 0.98 }}
                className="flex items-center gap-1 text-xs text-p-text-muted hover:text-p-text mb-1 transition-colors"
              >
                <ChevronLeft className="w-3.5 h-3.5" /> {uploaded?.original_filename ?? project.name}
              </motion.button>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
                  {isDau ? "Campos a clasificar" : "Muestra de valores"}
                </label>
                <RoundCodingControls
                  codingTypes={activeCodingTypes}
                  value={roundControls}
                  onChange={setRoundControls}
                  detectedMaxMentions={detectedMaxMentions}
                />
                <FieldSelectionTable
                  fields={fieldPreviews}
                  value={fieldSelections}
                  onChange={setFieldSelections}
                  showCodingType={codingScope === "both"}
                  readOnly={!isDau}
                />
              </div>

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

              {pendingQuestions.length > 0 && isDau && (
                <div className="flex items-start gap-2 text-sm text-p-warning bg-p-warning/10 border border-p-warning/30 rounded-lg p-3">
                  <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    <p>
                      Este .dau tiene variables fuera de la plantilla conocida (NBS_UNAID*), por lo que
                      no se pueden clasificar como Marcas o Razones automáticamente. Contacta a
                      ingeniería para clasificarlas antes de continuar la importación:
                    </p>
                    <ul className="text-xs font-mono space-y-0.5 pl-1">
                      {pendingQuestions.map((questionKey) => (
                        <li key={questionKey} className="truncate">{questionKey}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}

              {pendingQuestions.length > 0 && !isDau && (
                <div className="space-y-3 rounded-lg border border-p-warning/40 bg-p-warning/10 p-3">
                  <div className="text-sm font-semibold text-p-text">Clasifica las variables nuevas</div>
                  <p className="text-xs text-p-text-muted">
                    Cada variable se envía a {activeCodingTypes.map((t) => CODING_LABELS[t]).join(" o ")} antes de reintentar la importación.
                  </p>
                  {pendingQuestions.map((questionKey) => (
                    <div key={questionKey} className="grid grid-cols-[1fr_150px] gap-2 items-center">
                      <code className="truncate text-xs text-p-text">{questionKey}</code>
                      {activeCodingTypes.length === 1 ? (
                        <span className="text-sm font-medium text-p-text text-right">
                          {CODING_LABELS[activeCodingTypes[0]!]}
                        </span>
                      ) : (
                        <select
                          className="input text-sm"
                          aria-label={`Tipo de ${questionKey}`}
                          value={questionTypes[questionKey] ?? activeCodingTypes[0] ?? "brands"}
                          onChange={(event) => setQuestionTypes((current) => ({
                            ...current,
                            [questionKey]: event.target.value as CodingType,
                          }))}
                        >
                          {activeCodingTypes.map((codingType) => (
                            <option key={codingType} value={codingType}>
                              {CODING_LABELS[codingType]}
                            </option>
                          ))}
                        </select>
                      )}
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
                <motion.div className="space-y-2 pt-1">
                  <div className="rounded-lg border border-p-border bg-p-bg-subtle p-3 space-y-2">
                    <div className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
                      Perfil de referencia
                    </div>
                    {roundProfile ? (
                      <p className="text-xs text-p-text">
                        Se cruzará al importar: <span className="font-medium">{roundProfile.original_filename}</span>
                        {" · "}
                        {roundProfile.expected_respondents} esperados
                      </p>
                    ) : (
                      <p className="text-[11px] text-p-text-muted">
                        Opcional. Si subes el Excel de perfiles ahora, al importar verás esperados / llegaron / sobran.
                      </p>
                    )}
                    <label className={[
                      "btn-secondary text-xs py-1.5 px-2.5 inline-flex cursor-pointer",
                      profileUploading ? "opacity-50 pointer-events-none" : "",
                    ].join(" ")}>
                      <input
                        type="file"
                        accept=".xlsx,.xls"
                        className="sr-only"
                        disabled={profileUploading}
                        onChange={(e) => {
                          const f = e.target.files?.[0];
                          e.target.value = "";
                          if (f) void handleProfileUpload(f);
                        }}
                      />
                      {profileUploading
                        ? "Subiendo…"
                        : roundProfile
                          ? "Cambiar perfil"
                          : "Subir perfil .xlsx"}
                    </label>
                  </div>
                  <div className="flex gap-1.5">
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
                    onClick={() => {
                      setUploaded(null);
                      setColumnMap({});
                      setSheetError(null);
                      setBatchItems([]);
                      goToStep("round");
                    }}
                  >
                    Cambiar archivo{batchItems.length > 0 ? "s" : ""}
                  </motion.button>
                  </div>
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
            </div>
          )}

          {step === "review" && project && round && (
            <div className="space-y-4">
              <div className="card p-4 space-y-1">
                <div className="flex items-center gap-2 text-sm font-semibold text-p-text">
                  <Check className="w-4 h-4 text-p-success" />
                  {importedCount} verbatims importados
                </div>
                <p className="text-xs text-p-text-muted">
                  Aquí se ve el cruce con el perfil. El motor arranca cuando no queden pendientes
                  (candidatos a exclusión y/o duplicados).
                </p>
              </div>

              {profileSummary?.has_profile || profileCandidates.length > 0 ? (
                <ProfileReviewPanel
                  roundId={round.id}
                  fileId={uploaded!.file_id}
                  summary={profileSummary}
                  candidates={profileCandidates}
                  onCandidatesChange={setProfileCandidates}
                  showToast={showToast}
                  onAllResolved={() => {
                    playSuccess();
                    showToast("Revisión resuelta · codificando en el motor...", "success");
                    if (batchItems.length > 0 && project) {
                      void runBatch(project.id);
                    } else {
                      navigate(`/rounds/${round.id}/preliminary`);
                    }
                  }}
                />
              ) : (
                <div className="card p-4 text-xs text-p-text-muted">
                  No hay perfil de referencia en esta ronda — no hubo cruce por Respondent ID.
                  Vuelve a la ronda y súbelo antes de importar si lo necesitas.
                </div>
              )}

              {duplicates.length > 0 && (
                <section className="card p-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <Users className="w-4 h-4 text-p-warning" />
                    <h2 className="text-sm font-bold uppercase tracking-wide text-p-text">
                      Posibles duplicados reales
                    </h2>
                  </div>
                  <div className="space-y-2">
                    {duplicates.map((flag) => (
                      <div key={flag.flag_id} className="rounded-lg border border-p-border bg-p-bg-subtle p-3 space-y-2">
                        <div className="flex items-center justify-between gap-2 flex-wrap">
                          <div className="text-xs text-p-text">
                            <span className="font-semibold">Serial {flag.serial ?? "—"}</span>
                            <span className="text-p-text-muted"> · ID real </span>
                            <code className="text-[11px]">{flag.realid ?? "—"}</code>
                          </div>
                          {flag.status !== "pending" ? (
                            <span className="badge-success">{flag.status}</span>
                          ) : (
                            <div className="flex items-center gap-1.5">
                              <button
                                type="button"
                                className="btn-primary text-xs py-1.5 px-2.5"
                                disabled={resolvingFlagId === flag.flag_id}
                                onClick={() => void handleResolveReviewFlag(flag, "keep", "duplicate")}
                              >
                                Mantener ambos
                              </button>
                              <button
                                type="button"
                                className="btn-ghost text-xs py-1.5 px-2.5 text-p-error"
                                disabled={resolvingFlagId === flag.flag_id}
                                onClick={() => void handleResolveReviewFlag(flag, "remove", "duplicate")}
                              >
                                Quitar de esta carga
                              </button>
                            </div>
                          )}
                        </div>
                        {flag.status === "pending" && (
                          <input
                            className="input w-full text-xs"
                            placeholder="Nota opcional"
                            value={editNotes[flag.flag_id] ?? ""}
                            onChange={(e) =>
                              setEditNotes((current) => ({ ...current, [flag.flag_id]: e.target.value }))
                            }
                          />
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {profileSummary?.has_profile
                && profileCandidates.every((c) => c.status !== "pending")
                && duplicates.every((d) => d.status !== "pending") && (
                <button
                  type="button"
                  className="btn-primary text-sm py-2 w-full justify-center"
                  onClick={() => navigate(`/rounds/${round.id}/preliminary`)}
                >
                  Ir al procesamiento
                </button>
              )}
            </div>
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
