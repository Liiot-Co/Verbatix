import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useDropzone } from "react-dropzone";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertCircle,
  AlertTriangle,
  BookOpen,
  Check,
  ChevronDown,
  ChevronLeft,
  FileSpreadsheet,
  Files,
  Info,
  Settings2,
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
  createRound,
  createRoundSubprojects,
  classifyQuestion,
  getCodebookSources,
  getNextRoundNumber,
  getProject,
  getRound,
  getRoundLoads,
  importFile,
  importClientCatalog,
  matchProfile,
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
  RoundStatus,
  RoundProfileSummary,
  SerialCollision,
  UploadedFile,
} from "@/api/types";
import { useKeyboardShortcuts, registerShortcuts } from "@/hooks/useKeyboardShortcuts";
import { nextRoundNumber } from "@/lib/projectTree";
import { guessExcelColumnMap } from "@/lib/excelColumns";

// REQ-07 (3 pasos, reducidos de 6 tras la encuesta UX): Configuración (ronda +
// archivo + libro de códigos) -> Datos (campos a codificar) -> Revisión
// (perfil de referencia opcional, cruce de duplicados/perfil y resumen).
// Perfil y "revisar perfil" se fusionaron en un solo paso: subir/cambiar el
// perfil ahí mismo re-dispara el cruce sin volver a un paso aparte. Cada
// paso agrupa sub-secciones verticalmente apiladas en vez de pantallas
// separadas, para bajar la carga cognitiva de navegar entre pasos. El
// proyecto ya existe al entrar acá (modal en ProjectDashboard / deep-link
// ?projectId=). Cuando entra por /rounds/:roundId/add-load la ronda YA
// existe con sus subprojects — el paso "setup" solo pide el archivo.
type WizardStep = "setup" | "data" | "profile" | "review";

type BatchFileStatus = "pending" | "uploading" | "importing" | "done" | "error";

interface BatchItem {
  file: File;
  status: BatchFileStatus;
  error?: string;
  roundName?: string;
}

const WIZARD_STEPS: { key: WizardStep; label: string; hint: string }[] = [
  { key: "setup", label: "Configuración", hint: "Ronda, archivo y libro de códigos" },
  { key: "data", label: "Datos", hint: "Campos a codificar" },
  { key: "profile", label: "Perfil", hint: "Perfil de referencia (opcional)" },
  { key: "review", label: "Revisión", hint: "Cruce de duplicados y resumen" },
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

// localStorage: recuerda la última config usada para prellenar el wizard
// (Task 9) — nunca fuerza el valor, el usuario siempre puede editarlo.
const WIZARD_PREFS_KEY = "verbatix:wizard-prefs";

interface WizardPrefs {
  threshold?: number;
  audit?: number;
  scope?: CodingScope;
  originByType?: Partial<Record<CodingType, CatalogOriginSelection["origin"]>>;
}

function loadWizardPrefs(): WizardPrefs {
  try {
    const raw = localStorage.getItem(WIZARD_PREFS_KEY);
    return raw ? (JSON.parse(raw) as WizardPrefs) : {};
  } catch {
    return {};
  }
}

function saveWizardPrefs(prefs: WizardPrefs) {
  try {
    localStorage.setItem(WIZARD_PREFS_KEY, JSON.stringify(prefs));
  } catch {
    // localStorage puede fallar en modo privado — no es crítico, se ignora.
  }
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
  enter: (dir: number) => ({ opacity: 0, y: dir > 0 ? 16 : -16, filter: "blur(4px)" }),
  center: { opacity: 1, y: 0, filter: "blur(0px)" },
  exit: (dir: number) => ({ opacity: 0, y: dir > 0 ? -16 : 16, filter: "blur(4px)" }),
};

export default function CreationWizard() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { step: urlStep, roundId: pathRoundId } = useParams<{ roundId: string; step?: string }>();
  const isAddLoadMode = Boolean(pathRoundId) || searchParams.get("addLoad") === "true";
  const existingRoundId = isAddLoadMode ? (pathRoundId ?? searchParams.get("roundId")) : null;
  // round-sequence-and-homologation (Task 11/12): /wizard?projectId=&roundId=
  // reanuda una ronda YA creada pero con configuración incompleta — distinto
  // de isAddLoadMode (que asume subproyectos ya listos para sumar una carga).
  const resumeRoundId = !isAddLoadMode ? searchParams.get("roundId") : null;
  const setActiveProjectId = useVerbatixStore((s) => s.setActiveProjectId);
  const showToast = useVerbatixStore((s) => s.showToast);

  const wizardPrefsRef = useRef<WizardPrefs>(loadWizardPrefs());

  const initialStep = urlStep && WIZARD_STEPS.some((s) => s.key === urlStep) ? (urlStep as WizardStep) : "setup";
  const [step, setStep] = useState<WizardStep>(initialStep);
  const prevStepIndexRef = useRef(WIZARD_STEPS.findIndex((s) => s.key === initialStep));
  const [direction, setDirection] = useState(1);

  // Proyecto: ya existe al entrar acá (modal del dashboard crea el proyecto
  // antes de navegar a /wizard?projectId=...).
  type WizardProject = Pick<ProjectDetail, "id" | "name" | "external_code">;
  const [project, setProject] = useState<WizardProject | null>(null);

  // Modo "agregar carga" a una ronda existente (antes AddLoadView).
  const [existingRound, setExistingRound] = useState<RoundStatus | null>(null);

  const [round, setRound] = useState<Round | null>(null);
  const [codingScope, setCodingScope] = useState<CodingScope>(
    wizardPrefsRef.current.scope ?? "both"
  );
  const activeCodingTypes = isAddLoadMode
    ? ((existingRound?.subprojects ?? []).map((s) => s.coding_type) as CodingType[])
    : round && round.subprojects.length > 0
    // round-sequence-and-homologation (Task 12): reanudando una ronda que ya
    // tiene subproyectos creados, el alcance real es el ya persistido — no
    // el que el wizard calcularía desde codingScope (que arranca en "both").
    ? (round.subprojects.map((s) => s.coding_type) as CodingType[])
    : codingTypesForScope(codingScope);
  const [catalogOrigins, setCatalogOrigins] = useState<Record<CodingType, CatalogOriginSelection>>({
    brands: {
      origin: wizardPrefsRef.current.originByType?.brands ?? "scratch",
      source_subproject_id: null,
    },
    reasons: {
      origin: wizardPrefsRef.current.originByType?.reasons ?? "scratch",
      source_subproject_id: null,
    },
  });
  const [codebookSources, setCodebookSources] = useState<Record<CodingType, CodebookSource[]>>({
    brands: [],
    reasons: [],
  });
  const [catalogUploads, setCatalogUploads] = useState<Partial<Record<CodingType, UploadedFile>>>({});
  const [catalogSheets, setCatalogSheets] = useState<Partial<Record<CodingType, string>>>({});
  const [catalogPreviews, setCatalogPreviews] = useState<Partial<Record<CodingType, CatalogPreview>>>({});
  const [catalogConfirmed, setCatalogConfirmed] = useState<Partial<Record<CodingType, boolean>>>({});
  // Acordeón del libro de códigos: arranca cerrado para que la pantalla no se
  // vea larga; la persona abre el tipo que quiera configurar.
  const [expandedCodingType, setExpandedCodingType] = useState<CodingType | null>(null);
  const [subprojectsCreated, setSubprojectsCreated] = useState(false);

  // Ronda (wave de datos dentro del estudio) + Excel. min_mentions/% auditoría
  // se capturan al soltar el archivo — no se pueden editar después: cambiarlas
  // mientras el motor ya procesó con el valor viejo deja el catálogo por
  // frecuencia y el muestreo de auditoría inconsistentes.
  const [rName, setRName] = useState("Ronda 1 - 2026");
  const [rRoundNumber, setRRoundNumber] = useState(1);
  const [rThreshold, setRThreshold] = useState(wizardPrefsRef.current.threshold ?? 3);
  const [rAudit, setRAudit] = useState(wizardPrefsRef.current.audit ?? 10);

  const [uploaded, setUploaded] = useState<UploadedFile | null>(null);
  const [sourceLabel, setSourceLabel] = useState("");
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
  const [matchingProfile, setMatchingProfile] = useState(false);
  const [pendingQuestions, setPendingQuestions] = useState<string[]>([]);
  const [questionTypes, setQuestionTypes] = useState<Record<string, CodingType>>({});
  const [importedCount, setImportedCount] = useState(0);
  const [importedFileId, setImportedFileId] = useState<string | null>(null);
  const [duplicates, setDuplicates] = useState<DuplicateFlag[]>([]);
  const [serialCollisions, setSerialCollisions] = useState<SerialCollision[]>([]);
  const [profileCandidates, setProfileCandidates] = useState<ProfileCandidateFlag[]>([]);
  const [profileSummary, setProfileSummary] = useState<ProfileReviewSummary | null>(null);
  const [editNotes, setEditNotes] = useState<Record<string, string>>({});
  const [resolvingFlagId, setResolvingFlagId] = useState<string | null>(null);

  // Archivos adicionales soltados junto al primero: cada uno se convierte en
  // una ronda nueva del mismo estudio (mismo min_mentions/auditoría y libro de
  // códigos que la ronda 1), reusando el mapeo de columnas del primer archivo.
  const [batchItems, setBatchItems] = useState<BatchItem[]>([]);
  const [batchRunning, setBatchRunning] = useState(false);

  // round-sequence-and-homologation (Task 8/9): true si el proyecto ya tiene
  // rondas previas — bloquea el número de ronda y fuerza homologar el libro
  // (el backend rechaza scratch/inherited_round en rondas no-primeras).
  const [hasExistingRounds, setHasExistingRounds] = useState(false);

  // Paso "Perfil" — oculto por defecto: solo aparece en el stepper y en el
  // flujo cuando la persona elige configurar el perfil de referencia
  // explícitamente desde "Datos". Sin esa elección, "Datos" avanza directo
  // a "Revisión" como si el paso no existiera.
  const [showProfileStep, setShowProfileStep] = useState(false);

  // Pasos realmente visibles en el stepper y en la navegación secuencial —
  // "profile" solo entra en la lista una vez que la persona elige
  // configurarlo, para no mostrar un paso vacío/irrelevante por defecto.
  const visibleSteps = showProfileStep
    ? WIZARD_STEPS
    : WIZARD_STEPS.filter((s) => s.key !== "profile");

  const roundRef = useRef<HTMLInputElement>(null);

  const effectiveRoundId = existingRoundId ?? round?.id ?? null;

  // Modo "agregar carga": carga la ronda existente (y su perfil, si tiene).
  useEffect(() => {
    if (!existingRoundId) return;
    getRound(existingRoundId)
      .then((detail) => {
        setExistingRound(detail);
        setActiveProjectId(detail.project_id);
      })
      .catch(() => showToast("No se pudo cargar la ronda.", "error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existingRoundId]);

  // round-sequence-and-homologation (Task 12): modo reanudación — la ronda ya
  // existe (algún paso del wizard se abandonó a medio camino) pero no está
  // lista para procesar. Carga su estado persistido en vez de arrancar de
  // cero, y nunca vuelve a crear la ronda ni duplica subproyectos: `round` ya
  // queda seteado acá, así que `ensureRound()` lo reusa tal cual.
  useEffect(() => {
    if (!resumeRoundId) return;
    getRound(resumeRoundId)
      .then((detail) => {
        setProject({
          id: detail.project_id,
          name: detail.project_name,
          external_code: detail.project_external_code ?? "",
        });
        setActiveProjectId(detail.project_id);
        setRound(detail);
        setRName(detail.name);
        setRRoundNumber(detail.round_number);
        setRThreshold(detail.min_mentions_threshold);
        setRAudit(detail.audit_percentage);
        // Mismo criterio que Task 8/9: round_number == 1 => primera ronda
        // del proyecto, cualquier otro valor => solo homologar.
        setHasExistingRounds(detail.round_number !== 1);

        const hasSubprojects = detail.subprojects.length > 0;
        setSubprojectsCreated(hasSubprojects);
        if (hasSubprojects) {
          setCatalogOrigins((current) => {
            const next = { ...current };
            for (const sp of detail.subprojects) {
              if (sp.catalog_origin) {
                next[sp.coding_type] = {
                  origin: sp.catalog_origin,
                  source_subproject_id: sp.source_subproject_id ?? null,
                };
              }
            }
            return next;
          });
          const pendingCatalogType = detail.subprojects.find(
            (sp) => sp.catalog_origin === "imported_client_catalog"
          )?.coding_type;
          if (pendingCatalogType) setExpandedCodingType(pendingCatalogType);
        }

        // Si ya hay archivo(s) subidos pero la ronda sigue sin cerrar el
        // import (created/files_uploaded), el paso de entrada es "Datos".
        if (hasSubprojects && ["created", "files_uploaded"].includes(detail.status)) {
          getRoundLoads(resumeRoundId).then((loads) => {
            if (loads.length > 0) goToStep("data");
          });
        }
      })
      .catch(() => showToast("No se pudo cargar la ronda a reanudar.", "error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resumeRoundId]);

  // Deep-link: /wizard?projectId=... crea una ronda en el Estudio existente.
  useEffect(() => {
    if (isAddLoadMode) return;
    const projectId = searchParams.get("projectId");
    const roundId = searchParams.get("roundId");
    if (!projectId || roundId) return;
    getProject(projectId).then((detail) => {
      setProject(detail);
      setActiveProjectId(detail.id);

      const existingRounds = detail.rounds ?? [];
      // Valor inmediato para no bloquear el render mientras llega la
      // respuesta del backend — round-sequence-and-homologation (Task 1/8):
      // el backend es la fuente de verdad, se sobreescribe apenas resuelve.
      const nextNum = nextRoundNumber(existingRounds);
      setRRoundNumber(nextNum);
      setRName(`Ronda ${nextNum} - ${new Date().getFullYear()}`);
      setHasExistingRounds(existingRounds.length > 0);

      getNextRoundNumber(projectId).then((expected) => {
        setRRoundNumber(expected);
        setRName((current) =>
          current === `Ronda ${nextNum} - ${new Date().getFullYear()}`
            ? `Ronda ${expected} - ${new Date().getFullYear()}`
            : current
        );
      }).catch(() => {
        // Si falla, se mantiene el valor calculado en el cliente.
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // round-sequence-and-homologation (Task 9, ajustado): si el proyecto ya
  // tiene rondas, la ronda nueva NO es la primera del proyecto — el backend
  // permite heredar u homologar, pero nunca crear desde cero. Si el origen
  // preseleccionado (desde localStorage) era "scratch", cambia al primero
  // disponible sin forzar uno en particular.
  useEffect(() => {
    setCatalogOrigins((current) => {
      const next = { ...current };
      let changed = false;
      (Object.keys(next) as CodingType[]).forEach((codingType) => {
        if (hasExistingRounds && next[codingType].origin === "scratch") {
          next[codingType] = { origin: "inherited_round", source_subproject_id: null };
          changed = true;
        } else if (!hasExistingRounds && next[codingType].origin === "inherited_round") {
          next[codingType] = { origin: "scratch", source_subproject_id: null };
          changed = true;
        }
      });
      return changed ? next : current;
    });
  }, [hasExistingRounds]);

  useEffect(() => {
    if (isAddLoadMode || step !== "setup" || !project) return;
    Promise.all([
      getCodebookSources(project.id, "brands"),
      getCodebookSources(project.id, "reasons"),
    ]).then(([brands, reasons]) => {
      setCodebookSources({ brands, reasons });
      setCatalogOrigins((current) => {
        const next = { ...current };
        if (next.brands.origin === "inherited_round" && !next.brands.source_subproject_id && brands.length > 0) {
          next.brands = { ...next.brands, source_subproject_id: brands[0]?.source_subproject_id ?? null };
        }
        if (next.reasons.origin === "inherited_round" && !next.reasons.source_subproject_id && reasons.length > 0) {
          next.reasons = { ...next.reasons, source_subproject_id: reasons[0]?.source_subproject_id ?? null };
        }
        return next;
      });
    });
  }, [step, project, isAddLoadMode]);

  // Si el alcance deja fuera el tipo que estaba abierto, cierra el acordeón
  // (no abre otro solo: la persona lo despliega cuando quiera).
  useEffect(() => {
    if (expandedCodingType && !activeCodingTypes.includes(expandedCodingType)) {
      setExpandedCodingType(null);
    }
  }, [activeCodingTypes, expandedCodingType]);

  const goToStep = (next: WizardStep) => {
    const nextIndex = visibleSteps.findIndex((s) => s.key === next);
    setDirection(nextIndex >= prevStepIndexRef.current ? 1 : -1);
    prevStepIndexRef.current = nextIndex;
    setStep(next);
    const params = new URLSearchParams(searchParams.toString());
    const qs = params.toString();
    navigate(`/wizard/${next}${qs ? `?${qs}` : ""}`);
  };

  // Normmalize URL on mount — if no step segment, redirect to /wizard/setup
  useEffect(() => {
    if (!urlStep) {
      const params = new URLSearchParams(searchParams.toString());
      if (pathRoundId) {
        params.set("roundId", pathRoundId);
        params.set("addLoad", "true");
      }
      const qs = params.toString();
      navigate(`/wizard/setup${qs ? `?${qs}` : ""}`, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync URL → step when URL changes externally (browser back/forward)
  useEffect(() => {
    const validated =
      urlStep && WIZARD_STEPS.some((s) => s.key === urlStep) ? (urlStep as WizardStep) : "setup";
    if (validated !== step) {
      const nextIndex = WIZARD_STEPS.findIndex((s) => s.key === validated);
      setDirection(nextIndex >= prevStepIndexRef.current ? 1 : -1);
      prevStepIndexRef.current = nextIndex;
      setStep(validated);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlStep]);

  // La ronda se crea sola (sin subprojects) al soltar el primer archivo —
  // Tarea 1/2: la sección "Libro de códigos" (dentro de Configuración) crea
  // los subprojects vía POST /rounds/{id}/subprojects, después de elegir el
  // origen.
  const ensureRound = async (): Promise<Round | null> => {
    if (round) return round;
    if (!project || !rName.trim()) return null;
    try {
      const created = await createRound(project.id, {
        name: rName.trim(),
        round_number: rRoundNumber,
        min_mentions_threshold: rThreshold,
        audit_percentage: rAudit,
      });
      setRound(created);
      return created;
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Error al crear la ronda", "error");
      return null;
    }
  };

  // Cierra el paso "Configuración": en modo agregar-carga solo avanza; en
  // modo ronda nueva valida el origen del libro y crea los subproyectos
  // (una sola vez) antes de avanzar a "Datos".
  const handleContinueToData = async () => {
    if (isAddLoadMode) {
      goToStep("data");
      return;
    }
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
    if (!round) return;
    if (subprojectsCreated) {
      goToStep("data");
      return;
    }
    setSubmitting(true);
    try {
      const selectedOrigins = Object.fromEntries(
        activeCodingTypes.map((codingType) => [codingType, catalogOrigins[codingType]])
      ) as Partial<Record<CodingType, CatalogOriginSelection>>;
      const result = await createRoundSubprojects(round.id, { catalog_origins: selectedOrigins });
      const inheritedCodes = result.subprojects.reduce((sum, sp) => sum + (sp.inherited_codes ?? 0), 0);
      const inheritedAliases = result.subprojects.reduce((sum, sp) => sum + (sp.inherited_aliases ?? 0), 0);
      const inheritedNets = result.subprojects.reduce((sum, sp) => sum + (sp.inherited_nets ?? 0), 0);
      if (inheritedCodes > 0) {
        showToast(`Se heredaron ${inheritedCodes} códigos, ${inheritedAliases} alias y ${inheritedNets} netos`, "success");
      }
      setRound((current) => (current ? { ...current, subprojects: result.subprojects } : current));
      setSubprojectsCreated(true);

      // Task 9: recordar la config de esta ronda para prellenar la próxima.
      saveWizardPrefs({
        threshold: rThreshold,
        audit: rAudit,
        scope: codingScope,
        originByType: {
          brands: catalogOrigins.brands.origin,
          reasons: catalogOrigins.reasons.origin,
        },
      });

      playSuccess();
      goToStep("data");
    } catch (err) {
      showToast(
        err instanceof Error ? err.message : "No se pudo crear el libro de códigos de la ronda",
        "error"
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleProfileUpload = async (file: File) => {
    if (!effectiveRoundId) return;
    setProfileUploading(true);
    try {
      const result = await uploadRoundProfile(effectiveRoundId, file);
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
      let targetRoundId: string;
      if (isAddLoadMode) {
        if (!existingRoundId) return;
        targetRoundId = existingRoundId;
      } else {
        const r = await ensureRound();
        if (!r) return;
        targetRoundId = r.id;
      }
      const result = await uploadFile(targetRoundId, file);
      setUploaded(result);
      setSourceLabel(result.suggested_source_label ?? file.name);
      const verbatimGuess = result.detected_sheets.find((s) => s.guessed_as === "verbatims");
      const sheetName = verbatimGuess?.name ?? result.detected_sheets[0]?.name ?? "";
      setVerbatimsSheet(sheetName);
      if (result.file_type !== "dau") {
        const sheet = result.detected_sheets.find((s) => s.name === sheetName);
        setColumnMap(guessExcelColumnMap(sheet?.columns ?? []));
      } else {
        setColumnMap({});
      }
      if (!isAddLoadMode) {
        setBatchItems(rest.map((f) => ({ file: f, status: "pending" as const })));
      }
      playTick();
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [round, project, rName, rRoundNumber, rThreshold, rAudit, isAddLoadMode, existingRoundId]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    multiple: !isAddLoadMode,
    accept: {
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/vnd.ms-excel": [".xls"],
      "application/octet-stream": [".dau"],
    },
  });

  const activeSheet: DetectedSheet | undefined = uploaded?.detected_sheets.find((s) => s.name === verbatimsSheet);
  // Un .dau no tiene columna de verbatim que elegir — el backend
  // auto-selecciona las respuestas abiertas del registro y descarta la
  // infraestructura conocida (id, fechas, URLs, metadata).
  const isDau = uploaded?.file_type === "dau";

  // Selección de campos: para .dau se dispara apenas se sube el archivo; para
  // Excel espera a que haya una hoja elegida. Depende de ids/scope estables —
  // NO de arrays recreados por render, o el preview se re-dispara en bucle.
  useEffect(() => {
    const roundId = effectiveRoundId;
    const subprojects = isAddLoadMode ? existingRound?.subprojects : round?.subprojects;
    if (!roundId || !uploaded || !subprojects || subprojects.length === 0) {
      setFieldPreviews([]);
      setFieldSelections([]);
      return;
    }
    if (!isDau && !verbatimsSheet) return;
    const types = activeCodingTypes;
    const fileId = uploaded.file_id;
    const expectedFromRound = (isAddLoadMode ? existingRound?.expected_max_mentions : round?.expected_max_mentions) ?? null;
    const singleFromSp = Object.fromEntries(
      subprojects.map((s) => [s.coding_type, !!s.single_code_per_response])
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveRoundId, uploaded?.file_id, verbatimsSheet, isDau, subprojectsCreated, isAddLoadMode]);

  const importedCatalogTypes = activeCodingTypes.filter(
    (codingType) => catalogOrigins[codingType].origin === "imported_client_catalog"
  );
  const catalogsReady = importedCatalogTypes.every((codingType) => catalogConfirmed[codingType]);
  const detectedMaxMentions = detectedMaxFromFields(fieldPreviews);
  const mentionDecisionsReady = !hasPendingRoundMentionDecision(
    roundControls, detectedMaxMentions, activeCodingTypes
  );
  const canImport = !!(
    effectiveRoundId
    && uploaded
    && verbatimsSheet
    && (isDau || (columnMap.verbatim && columnMap.respondent_id))
    && catalogsReady
    && mentionDecisionsReady
  );

  const hasUnsavedChanges = (!!uploaded && !importedCount) || !!roundProfile;

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
    if (!round) return;
    try {
      const result = await uploadFile(round.id, file);
      setCatalogUploads((current) => ({ ...current, [codingType]: result }));
      const guessed = result.detected_sheets.find((sheet) => sheet.guessed_as === "codebook")
        ?? result.detected_sheets[0];
      if (!guessed) throw new Error("El archivo no contiene hojas");
      const preview = await previewClientCatalog(
        round.id, result.file_id, guessed.name, codingType
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
  // mismo estudio: crea la ronda, crea sus subprojects reusando el catálogo
  // de la ronda 1, sube el archivo y lo importa. Un archivo sin hoja de
  // verbatims detectable (o cualquier otro fallo) queda marcado con error y
  // no bloquea al resto del lote.
  const runBatch = async (projectId: string) => {
    if (!round) return;
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
        });
        await createRoundSubprojects(newRound.id, {
          catalog_origins: Object.fromEntries(
            activeCodingTypes.map((codingType) => [codingType, catalogOrigins[codingType]])
          ),
          reuse_catalogs_from_round_id: round.id,
        });
        const uploadedBatch = await uploadFile(newRound.id, item.file);
        setBatchItems((items) =>
          items.map((it, idx) => (idx === i ? { ...it, status: "importing", roundName } : it))
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

  // Importa la carga de verbatims. Ya NO ejecuta el cruce de perfil ni la
  // detección de duplicados (Task 3/4) — eso corre aparte, explícitamente,
  // desde el paso "Revisión" vía matchProfile().
  const handleImport = async (): Promise<boolean> => {
    if (!effectiveRoundId || !uploaded || !verbatimsSheet || !(isDau || (columnMap.verbatim && columnMap.respondent_id))) {
      return false;
    }
    setSubmitting(true);
    try {
      const result = await importFile(
        effectiveRoundId,
        uploaded.file_id,
        verbatimsSheet,
        columnMap as ColumnMap,
        {
          sourceLabel: sourceLabel.trim() || undefined,
          // Solo .dau: en Excel "field" es la columna del sheet, que no
          // corresponde al question_key real de cada fila (viene de la
          // columna "Question ID"), así que field_selections no aplicaría.
          ...(isDau
            ? {
              fieldSelections: fieldSelections.map((fs) => ({
                ...fs,
                coding_type: activeCodingTypes.length === 1
                  ? (activeCodingTypes[0] ?? fs.coding_type)
                  : fs.coding_type,
              })),
            }
            : {}),
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
        setQuestionTypes(Object.fromEntries(result.pending_questions.map((q) => [q, defaultType])));
        showToast("Clasifica las variables nuevas antes de continuar.", "info");
        return false;
      }
      for (const warning of result.warnings ?? []) {
        showToast(warning, "info");
      }
      setImportedCount(result.imported.verbatims);
      setImportedFileId(uploaded.file_id);
      playSuccess();
      showToast(
        `Importados ${result.imported.verbatims} verbatims${result.imported.codes ? ` y ${result.imported.codes} códigos` : ""} · codificando en el motor...`,
        "success"
      );
      return true;
    } catch {
      showToast("No se pudo importar el archivo", "error");
      return false;
    } finally {
      setSubmitting(false);
    }
  };

  const handleClassifyQuestions = async () => {
    const projectIdForClassify = isAddLoadMode ? existingRound?.project_id : project?.id;
    if (!projectIdForClassify || pendingQuestions.length === 0) return;
    setSubmitting(true);
    try {
      await Promise.all(
        pendingQuestions.map((questionKey) =>
          classifyQuestion(projectIdForClassify, {
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

  // Cierra el paso "Datos": importa si hace falta, corre el lote de rondas
  // adicionales si las hay, y aterriza en "Perfil" (si se eligió
  // configurarlo) o directo en "Revisión" — el cruce de duplicados/perfil
  // se dispara ahí mismo, ya no hace falta ramificar "sin perfil" / "comparar
  // perfil" en dos botones.
  const handleContinueToReview = async (withProfile: boolean = showProfileStep) => {
    if (!importedFileId) {
      const ok = await handleImport();
      if (!ok) return;
    }
    if (batchItems.length > 0 && !isAddLoadMode) {
      const projectId = project?.id ?? existingRound?.project_id;
      if (projectId) await runBatch(projectId);
    }
    goToStep(withProfile ? "profile" : "review");
  };

  // Task 3: dispara el cruce explícito (duplicados + perfil) sobre la carga
  // ya importada — se dispara solo al entrar a "Revisión" (ver useEffect) y
  // de nuevo cada vez que se sube/cambia el perfil desde ese mismo paso.
  const handleMatchProfile = useCallback(async () => {
    if (!effectiveRoundId || !importedFileId) return;
    setMatchingProfile(true);
    try {
      const result = await matchProfile(effectiveRoundId, importedFileId);
      setDuplicates(result.duplicates);
      setSerialCollisions(result.serial_collisions);
      setProfileCandidates(result.profile_candidates);
      setProfileSummary({
        has_profile: result.has_profile,
        expected: result.expected,
        arrived: result.arrived,
        extra: result.extra,
        ...(result.summary !== undefined ? { summary: result.summary } : {}),
      });
    } catch {
      showToast("No se pudo cruzar con el perfil.", "error");
    } finally {
      setMatchingProfile(false);
    }
  }, [effectiveRoundId, importedFileId, showToast]);

  // Al entrar a "Revisión" con una carga ya importada, corre el cruce una
  // vez automáticamente (con o sin perfil — sin perfil solo trae duplicados).
  useEffect(() => {
    if (step !== "review" || !importedFileId) return;
    void handleMatchProfile();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, importedFileId]);


  const pendingFlags = useMemo(
    () =>
      duplicates.filter((d) => d.status === "pending").length
      + profileCandidates.filter((c) => c.status === "pending").length,
    [duplicates, profileCandidates]
  );

  const handleResolve = useCallback(
    async (
      flag: { flag_id: string },
      action: "keep" | "remove" | "edit",
      kind: "duplicate" | "profile" = "duplicate",
    ) => {
      if (resolvingFlagId) return;
      setResolvingFlagId(flag.flag_id);
      try {
        const result = await resolveImportFlag(
          flag.flag_id,
          action,
          action === "edit" ? editNotes[flag.flag_id] : undefined
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
      } catch {
        showToast("No se pudo resolver la decisión.", "error");
      } finally {
        setResolvingFlagId(null);
      }
    },
    [resolvingFlagId, editNotes, showToast]
  );

  const goToRoundOutcome = () => {
    if (effectiveRoundId) navigate(`/rounds/${effectiveRoundId}/preliminary`);
  };

  const batchDone = batchItems.length > 0 && !batchRunning && batchItems.every((it) => it.status === "done" || it.status === "error");

  const stepIndex = visibleSteps.findIndex((s) => s.key === step);

  const activeStudyName = isAddLoadMode ? existingRound?.project_name : project?.name;
  const crumbs: Crumb[] = [{ label: "Proyectos", to: "/" }];
  if (activeStudyName) {
    crumbs.push({
      label: activeStudyName,
      to: isAddLoadMode ? `/projects/${existingRound?.project_id}` : `/projects/${project?.id}`,
    });
  }
  crumbs.push({ label: isAddLoadMode ? (existingRound?.name ?? "Ronda") : "Nueva ronda" });

  const setupPanelKeyDown = useEnterToSubmit(() => void handleContinueToData());

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (step === "data" || step === "profile" || step === "review") return goToStep("setup");
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, uploaded]);

  // Register shortcuts for this context
  useEffect(() => {
    registerShortcuts("wizard", [
      {
        key: "s",
        meta: true,
        action: () => void handleImport(),
        description: "Importar (cuando esté listo)",
        category: "Acciones",
      },
    ]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, uploaded, round]);

  useKeyboardShortcuts("wizard");

  useEffect(() => {
    if (!hasUnsavedChanges) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [hasUnsavedChanges]);

  // Focus refs when step changes
  useEffect(() => {
    setTimeout(() => {
      if (step === "setup") roundRef.current?.focus();
    }, 100);
  }, [step]);

  // Los pasos "Datos" y "Revisión" necesitan más ancho que "Configuración"
  // para que la tabla de campos y los paneles de revisión no queden
  // apretados — el contenedor exterior ya no fija max-width; cada paso lo
  // declara por su cuenta.
  const stepContentWidth = step === "data" || step === "review" ? "max-w-4xl" : "max-w-2xl";

  const roundName = isAddLoadMode ? existingRound?.name : round?.name;

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

      <div className={`${stepContentWidth} mx-auto space-y-6`}>
        <Breadcrumb items={crumbs} />

        <div className="space-y-1">
          <h1 className="font-heading text-2xl font-semibold text-p-text tracking-tight">
            {isAddLoadMode ? "Agregar nueva carga" : "Nueva ronda"}
          </h1>
          {isAddLoadMode && (
            <p className="text-sm text-p-text-muted">
              Los datos nuevos se suman a <span className="font-semibold text-p-text">{roundName ?? "la ronda"}</span> sin
              tocar lo ya codificado. El Serial y el ID real del encuestado nunca se modifican.
            </p>
          )}
        </div>

        {/* Stepper horizontal — 3 pasos en fila, cada burbuja conecta con la
            siguiente por una barra de progreso; siempre visible arriba del
            contenido en vez de un riel lateral. */}
        <nav className="flex items-center" aria-label="Progreso del asistente">
          {visibleSteps.map((s, i) => {
            const done = i < stepIndex;
            const active = i === stepIndex;
            const clickable = done;
            const isLast = i === visibleSteps.length - 1;
            return (
              <div key={s.key} className="flex items-center flex-1 last:flex-none">
                <motion.button
                  type="button"
                  disabled={!clickable}
                  onClick={() => clickable && goToStep(s.key)}
                  whileHover={{ scale: clickable ? 1.02 : 1 }}
                  whileTap={{ scale: clickable ? 0.98 : 1 }}
                  className={[
                    "flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all duration-200 shrink-0",
                    active
                      ? "bg-p-accent text-white shadow-sm"
                      : done
                        ? "bg-p-accent-soft text-p-accent hover:bg-p-accent-soft/70 cursor-pointer"
                        : "text-p-text-faint",
                  ].join(" ")}
                >
                  <span
                    className={[
                      "w-5 h-5 rounded-full flex items-center justify-center text-[11px] font-semibold shrink-0",
                      active ? "bg-white/25" : done ? "bg-p-accent text-white" : "border border-p-border-mid",
                    ].join(" ")}
                  >
                    {done ? <Check className="w-3 h-3" /> : i + 1}
                  </span>
                  <span className="hidden sm:inline">{s.label}</span>
                </motion.button>
                {!isLast && (
                  <div className="flex-1 h-px mx-1.5 bg-p-border overflow-hidden rounded-full">
                    <motion.div
                      className="h-full bg-p-accent"
                      initial={{ width: done ? "100%" : "0%" }}
                      animate={{ width: done ? "100%" : "0%" }}
                      transition={{ duration: 0.4, ease: [0.19, 1, 0.22, 1] as const }}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        <div>
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
                {/* Paso 1: Configuración — ronda + archivo + libro de códigos,
                    apilados verticalmente en una sola pantalla. */}
                {step === "setup" && (isAddLoadMode || project) && (
                  <div className="space-y-3">
                    {!isAddLoadMode && project && (
                      <p className="text-xs text-p-text-faint">
                        Estudio <span className="font-semibold text-p-text-muted">{project.name}</span>
                      </p>
                    )}

                    {!isAddLoadMode && (
                      <div className="card p-4 space-y-2.5" onKeyDown={setupPanelKeyDown}>
                        <div className="flex items-center gap-1.5 text-xs font-semibold text-p-text uppercase tracking-wide pb-1 border-b border-p-border">
                          <Settings2 className="w-3.5 h-3.5 text-p-accent" /> Ronda
                        </div>
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
                          disabled={!!round || hasExistingRounds}
                          className="input w-full text-sm"
                          value={rRoundNumber}
                          onChange={(e) => setRRoundNumber(Number(e.target.value))}
                          whileFocus={{ scale: 1.002 }}
                        />
                        {hasExistingRounds && (
                          <p className="text-xs text-p-text-faint">
                            El proyecto ya tiene rondas — el número sigue la secuencia y no se puede editar.
                          </p>
                        )}


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
                    )}

                    {!uploaded ? (
                      <div className="space-y-1.5">
                        <div className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
                          Archivo de respuestas (verbatims)
                        </div>
                        <div
                          {...getRootProps()}
                          className={["dropzone", isDragActive ? "dropzone-active" : "hover:border-p-accent/40"].join(" ")}
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
                          <span className="text-sm font-medium text-p-text">
                            Arrastra el archivo con las respuestas, o haz clic para elegirlo
                          </span>
                          <span className="text-xs text-p-text-faint">.xlsx, .xls o .dau</span>
                        </div>
                      </div>
                    ) : (
                      <motion.div
                        initial={{ opacity: 0, y: 8, scale: 0.98 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        transition={{ duration: 0.25, ease: [0.19, 1, 0.22, 1] as const }}
                        className="file-preview space-y-3"
                      >
                        <div className="flex items-center gap-2 text-sm font-semibold text-p-text">
                          <FileSpreadsheet className="w-4 h-4 text-p-accent" />
                          {uploaded.original_filename}
                        </div>

                        {uploaded.duplicate_of && (
                          <div className="flex items-start gap-2 text-xs text-p-warning bg-p-warning/10 border border-p-warning/30 rounded-lg p-2.5">
                            <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                            <span>
                              Este archivo ya se subió a esta ronda como{" "}
                              <span className="font-semibold">
                                {uploaded.duplicate_of.source_label ?? uploaded.duplicate_of.original_filename}
                              </span>
                              . Si continúas, todos sus encuestados aparecerán como posibles duplicados en el paso "Revisión".
                            </span>
                          </div>
                        )}

                        {isAddLoadMode && (
                          <div>
                            <label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
                              Etiqueta de la carga
                            </label>
                            <input
                              className="input w-full text-sm mt-1"
                              value={sourceLabel}
                              onChange={(e) => setSourceLabel(e.target.value)}
                              placeholder="Dimension Parte 1"
                            />
                            <p className="text-[11px] text-p-text-faint mt-1">
                              Distingue esta carga de las anteriores cuando un Serial se repite.
                            </p>
                          </div>
                        )}

                        {batchItems.length > 0 && (
                          <div className="flex items-start gap-2 text-xs text-p-text-muted bg-p-bg-subtle rounded-lg p-2.5">
                            <Files className="w-3.5 h-3.5 shrink-0 mt-0.5 text-p-accent" />
                            <span>
                              +{batchItems.length} archivo{batchItems.length > 1 ? "s" : ""} más se importará
                              {batchItems.length > 1 ? "n" : ""} como ronda{batchItems.length > 1 ? "s" : ""} nueva
                              {batchItems.length > 1 ? "s" : ""} al confirmar, reusando el mapeo de columnas de abajo:{" "}
                              {batchItems.map((it) => it.file.name).join(", ")}
                            </span>
                          </div>
                        )}

                        <div>
                          <label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">Hoja de respuestas (verbatims)</label>
                          <select
                            className="input w-full text-sm mt-1"
                            value={verbatimsSheet}
                            onChange={(e) => {
                              setVerbatimsSheet(e.target.value);
                              if (uploaded && uploaded.file_type !== "dau") {
                                const sheet = uploaded.detected_sheets.find((s) => s.name === e.target.value);
                                setColumnMap(guessExcelColumnMap(sheet?.columns ?? []));
                              } else {
                                setColumnMap({});
                              }
                            }}
                          >
                            {uploaded.detected_sheets.map((s) => (
                              <option key={s.name} value={s.name}>{s.name} ({s.rows} filas)</option>
                            ))}
                          </select>
                        </div>

                        {isDau && activeSheet && (
                          <div className="text-xs text-p-text-muted bg-p-bg-subtle rounded-lg p-2.5">
                            Se importarán las respuestas abiertas detectadas en cada registro (
                            {activeSheet.columns.length} campos, excluyendo id/fechas/metadata de la plataforma).
                          </div>
                        )}

                        {!isDau && activeSheet && (
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
                            <div>
                              <label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
                                Columna Respondent ID
                              </label>
                              <p className="text-[10px] text-p-text-faint mt-0.5 mb-1">
                                Se cruza con el perfil de referencia
                              </p>
                              <select
                                className="input w-full text-sm"
                                value={columnMap.respondent_id ?? ""}
                                onChange={(e) => setColumnMap((m) => ({ ...m, respondent_id: e.target.value }))}
                              >
                                <option value="">Elegir columna...</option>
                                {activeSheet.columns.map((c) => (
                                  <option key={c} value={c}>{c}</option>
                                ))}
                              </select>
                            </div>
                            <div>
                              <label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
                                Columna de verbatim
                              </label>
                              <p className="text-[10px] text-p-text-faint mt-0.5 mb-1">
                                Texto abierto a clasificar
                              </p>
                              <select
                                className="input w-full text-sm"
                                value={columnMap.verbatim ?? ""}
                                onChange={(e) => setColumnMap((m) => ({ ...m, verbatim: e.target.value }))}
                              >
                                <option value="">Elegir columna...</option>
                                {activeSheet.columns.map((c) => (
                                  <option key={c} value={c}>{c}</option>
                                ))}
                              </select>
                            </div>
                          </div>
                        )}

                        {isAddLoadMode && (
                          <div className="flex gap-1.5 pt-1">
                            <motion.button
                              whileHover={{ scale: 1.02 }}
                              whileTap={{ scale: 0.98 }}
                              className="btn-primary text-sm py-2 flex-1 justify-center"
                              onClick={() => void handleContinueToData()}
                            >
                              Continuar <span className="opacity-60 font-normal">(Enter)</span>
                            </motion.button>
                            <motion.button
                              whileHover={{ scale: 1.02 }}
                              whileTap={{ scale: 0.98 }}
                              className="btn-ghost text-sm py-2 px-3"
                              onClick={() => {
                                setUploaded(null);
                                setColumnMap({});
                                setBatchItems([]);
                              }}
                            >
                              Cambiar archivo
                            </motion.button>
                          </div>
                        )}
                        {!isAddLoadMode && (
                          <motion.button
                            whileHover={{ scale: 1.02 }}
                            whileTap={{ scale: 0.98 }}
                            className="btn-ghost text-xs py-1.5 px-3 self-start"
                            onClick={() => {
                              setUploaded(null);
                              setColumnMap({});
                              setBatchItems([]);
                            }}
                          >
                            Cambiar archivo
                          </motion.button>
                        )}
                      </motion.div>
                    )}

                    {/* Libro de códigos — aparece debajo del archivo, en la
                        misma pantalla: no hace falta un paso aparte para
                        elegir el origen del catálogo. */}
                    {!isAddLoadMode && uploaded && project && (
                      <div className="card p-4 space-y-2.5" onKeyDown={setupPanelKeyDown}>
                        <div className="flex items-center gap-1.5 pb-1 border-b border-p-border">
                          <BookOpen className="w-3.5 h-3.5 text-p-accent shrink-0" />
                          <h2 className="text-xs font-semibold text-p-text uppercase tracking-wide">Libro de códigos</h2>
                        </div>
                        <p className="text-xs text-p-text-muted">
                          Elige Marcas, Razones o ambas, y el origen del libro solo para lo seleccionado.
                        </p>
                        <div role="radiogroup" aria-label="Alcance de la ronda" className="grid grid-cols-3 gap-1.5">
                          {SCOPE_OPTIONS.map((option) => {
                            const active = codingScope === option.value;
                            return (
                              <button
                                key={option.value}
                                type="button"
                                role="radio"
                                aria-checked={active}
                                disabled={subprojectsCreated}
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

                        {activeCodingTypes.length > 1 && (
                          <div className="flex gap-1 p-1 bg-p-bg-subtle border border-p-border rounded-lg mb-4" role="tablist">
                            {activeCodingTypes.map((codingType) => {
                              const active = (expandedCodingType || activeCodingTypes[0]) === codingType;
                              return (
                                <button
                                  key={codingType}
                                  type="button"
                                  role="tab"
                                  aria-selected={active}
                                  onClick={() => {
                                    setExpandedCodingType(codingType);
                                    playTick();
                                  }}
                                  className={[
                                    "flex-1 py-1.5 text-sm font-medium rounded-md transition-all duration-200",
                                    active
                                      ? "bg-p-surface text-p-text shadow-sm"
                                      : "text-p-text-muted hover:text-p-text hover:bg-p-surface/50",
                                  ].join(" ")}
                                >
                                  {CODING_LABELS[codingType]}
                                </button>
                              );
                            })}
                          </div>
                        )}

                        <AnimatePresence mode="wait">
                          {(() => {
                            const codingType = (expandedCodingType && activeCodingTypes.includes(expandedCodingType))
                              ? expandedCodingType
                              : activeCodingTypes[0];
                            if (!codingType) return null;

                            const selection = catalogOrigins[codingType];
                            const source = codebookSources[codingType].find(
                              (candidate) => candidate.source_subproject_id === selection.source_subproject_id
                            );
                            const originOptions = hasExistingRounds
                              ? ORIGIN_OPTIONS.filter((option) => option.value !== "scratch")
                              : ORIGIN_OPTIONS.filter((option) => option.value !== "inherited_round");

                            const catalogFile = catalogUploads[codingType];
                            const preview = catalogPreviews[codingType];
                            const confirmed = catalogConfirmed[codingType];

                            return (
                              <motion.div 
                                key={codingType}
                                initial={{ opacity: 0, y: 5 }}
                                animate={{ opacity: 1, y: 0 }}
                                exit={{ opacity: 0, y: -5 }}
                                transition={{ duration: 0.15 }}
                                role="tabpanel" 
                                className="space-y-3"
                              >
                                {activeCodingTypes.length > 1 && (
                                  <p className="text-xs font-semibold text-p-text flex items-center gap-1.5 uppercase tracking-wide">
                                    <span className="w-1.5 h-1.5 rounded-full bg-p-accent"></span>
                                    Origen para {CODING_LABELS[codingType]}
                                  </p>
                                )}
                                <div role="radiogroup" className="space-y-2">
                                  {originOptions.map((option) => {
                                    const active = selection.origin === option.value;
                                    return (
                                      <button
                                        key={option.value}
                                        type="button"
                                        role="radio"
                                        aria-checked={active}
                                        disabled={subprojectsCreated}
                                        onClick={() => {
                                          setCatalogOrigins((current) => ({
                                            ...current,
                                            [codingType]: {
                                              origin: option.value,
                                              source_subproject_id:
                                                option.value === "inherited_round" && codebookSources[codingType].length > 0
                                                  ? codebookSources[codingType][0]?.source_subproject_id ?? null
                                                  : null,
                                            },
                                          }));
                                          playTick();
                                        }}
                                        className={[
                                          "w-full flex items-start gap-2.5 text-left rounded-lg border p-3 transition-all duration-150 disabled:opacity-60 disabled:cursor-not-allowed",
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
                                </div>

                                {selection.origin === "inherited_round" && (
                                  <div className="pt-2 animate-in fade-in zoom-in-95 duration-200">
                                    <label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
                                      Libro oficial a heredar
                                    </label>
                                    {codebookSources[codingType].length === 0 ? (
                                      <p className="mt-1.5 text-xs text-p-text-muted rounded-lg bg-p-bg-subtle p-2.5">
                                        Aún no hay libros oficiales de {CODING_LABELS[codingType]} disponibles.
                                      </p>
                                    ) : (
                                      <div className="mt-1.5 flex items-center justify-between p-3 rounded-lg border border-p-border bg-p-bg-subtle">
                                        <div className="text-sm font-medium text-p-text">
                                          {codebookSources[codingType][0]?.project_name} · R{codebookSources[codingType][0]?.round_number}
                                        </div>
                                        <span className="text-[10px] uppercase font-bold text-p-accent bg-p-accent/10 px-2 py-0.5 rounded-full">
                                          Último
                                        </span>
                                      </div>
                                    )}
                                    {source && (
                                      <p className="mt-2 text-xs text-p-text-muted">
                                        Vas a heredar {source.codes} códigos, {source.aliases} alias y {source.nets} netos.
                                      </p>
                                    )}
                                  </div>
                                )}
                                
                                {selection.origin === "imported_client_catalog" && round && (
                                  <div className="pt-2 animate-in fade-in zoom-in-95 duration-200">
                                    <div className="rounded-xl border border-p-accent/20 bg-p-accent-soft/30 p-3 space-y-2.5">
                                      <div className="flex items-center justify-between gap-2">
                                        <span className="text-sm font-semibold text-p-text">
                                          Archivo de homologación
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
                                            "flex items-center justify-center gap-2 rounded-lg border border-dashed border-p-border-mid bg-p-surface",
                                            "px-3 py-4 text-sm text-p-text-muted cursor-pointer",
                                            "hover:border-p-accent/50 hover:bg-p-accent-soft hover:text-p-text",
                                            "transition-all duration-200",
                                          ].join(" ")}
                                        >
                                          <UploadCloud className="w-4 h-4 text-p-text-faint" />
                                          <span>
                                            Subir el libro de códigos{" "}
                                            <span className="text-p-text-faint">(.xlsx)</span>
                                          </span>
                                          <input
                                            type="file"
                                            accept=".xlsx,.xls"
                                            className="sr-only"
                                            onChange={(event) => {
                                              const file = event.target.files?.[0];
                                              if (file) void handleCatalogUpload(codingType, file);
                                            }}
                                          />
                                        </label>
                                      ) : (
                                        <>
                                          <div className="flex items-center justify-between gap-2">
                                            <div className="flex items-center gap-2 text-sm font-medium text-p-text min-w-0">
                                              <FileSpreadsheet className="w-4 h-4 shrink-0 text-p-accent" />
                                              <span className="truncate">{catalogFile.original_filename}</span>
                                            </div>
                                            {!confirmed && (
                                              <button
                                                type="button"
                                                onClick={() => {
                                                  setCatalogUploads(prev => ({ ...prev, [codingType]: null }));
                                                  setCatalogPreviews(prev => ({ ...prev, [codingType]: null }));
                                                  setCatalogConfirmed(prev => ({ ...prev, [codingType]: false }));
                                                }}
                                                className="text-[11px] font-medium text-p-text-muted hover:text-p-text underline shrink-0"
                                              >
                                                Cambiar
                                              </button>
                                            )}
                                          </div>
                                          <select
                                            className="input w-full text-sm bg-p-surface"
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
                                            <div className="rounded-lg bg-p-surface border border-p-border p-2.5 text-xs text-p-text-muted">
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
                                  </div>
                                )}
                              </motion.div>
                            );
                          })()}
                        </AnimatePresence>

                        {!catalogsReady && importedCatalogTypes.length > 0 && (
                          <div className="rounded-lg border border-p-warning/40 bg-p-warning/10 p-3 text-xs text-p-text-muted">
                            Confirma los libros de códigos del cliente para continuar.
                          </div>
                        )}

                        <motion.button
                          whileHover={{ scale: 1.02 }}
                          whileTap={{ scale: 0.98 }}
                          className="btn-primary text-sm py-2 w-full justify-center mt-1"
                          disabled={submitting || (!catalogsReady && importedCatalogTypes.length > 0)}
                          onClick={() => void handleContinueToData()}
                        >
                          Continuar a datos <span className="opacity-60 font-normal">(Enter)</span>
                        </motion.button>
                      </div>
                    )}
                  </div>
                )}

                {/* Paso 2: Datos — campos a codificar. */}
                {step === "data" && (
                  <div className="space-y-3">
                    <motion.button
                      onClick={() => goToStep("setup")}
                      whileHover={{ x: -2 }}
                      whileTap={{ scale: 0.98 }}
                      className="flex items-center gap-1 text-xs text-p-text-muted hover:text-p-text mb-1 transition-colors"
                    >
                      <ChevronLeft className="w-3.5 h-3.5" /> {uploaded?.original_filename ?? "Atrás"}
                    </motion.button>

                    <div className="space-y-1.5">
                      <label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
                        {isDau ? "Campos a clasificar" : "Muestra de valores"}
                      </label>
                      {activeCodingTypes.length > 0 && (
                        <RoundCodingControls
                          codingTypes={activeCodingTypes}
                          value={roundControls}
                          onChange={setRoundControls}
                          detectedMaxMentions={detectedMaxMentions}
                        />
                      )}
                      <FieldSelectionTable
                        fields={fieldPreviews}
                        value={fieldSelections}
                        onChange={setFieldSelections}
                        showCodingType={activeCodingTypes.length > 1}
                        readOnly={!isDau}
                      />
                    </div>

                    {pendingQuestions.length > 0 && (
                      <div className="space-y-3 rounded-lg border border-p-warning/40 bg-p-warning/10 p-3">
                        <div className="text-sm font-semibold text-p-text">Clasifica las variables nuevas</div>
                        <p className="text-xs text-p-text-muted">
                          Estas columnas no coinciden con ninguna variable ya clasificada del estudio. Indica si cada una es
                          {" "}{activeCodingTypes.map((t) => CODING_LABELS[t]).join(" o ")} antes de reintentar la importación.
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
                                <option value="brands">Marcas</option>
                                <option value="reasons">Razones</option>
                              </select>
                            )}
                          </div>
                        ))}
                        <button
                          type="button"
                          className="btn-primary text-sm py-2 w-full justify-center"
                          disabled={submitting}
                          onClick={() => void handleClassifyQuestions()}
                        >
                          Clasificar y continuar
                        </button>
                      </div>
                    )}

                    {pendingQuestions.length === 0 && !batchRunning && !batchDone && (
                      <div className="grid grid-cols-2 gap-3 pt-2">
                        <button
                          type="button"
                          disabled={!canImport || submitting}
                          className="btn-secondary text-sm py-2 w-full justify-center"
                          onClick={() => {
                            setShowProfileStep(false);
                            void handleContinueToReview(false);
                          }}
                        >
                          {submitting ? "Importando..." : "Continuar sin perfil"}
                        </button>
                        <button
                          type="button"
                          disabled={!canImport || submitting}
                          className="btn-primary text-sm py-2 w-full justify-center"
                          onClick={() => {
                            setShowProfileStep(true);
                            void handleContinueToReview(true);
                          }}
                        >
                          {submitting ? "Importando..." : "Continuar con perfil"}
                        </button>
                      </div>
                    )}

                    {batchItems.length > 0 && (batchRunning || batchDone) && (
                      <div className="space-y-2 pt-1">
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
                            ) : (
                              <FileSpreadsheet className="w-3.5 h-3.5 shrink-0 text-p-text-faint" />
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
                          <button
                            type="button"
                            className="btn-primary text-sm py-2 w-full justify-center mt-1"
                            onClick={() => goToStep(showProfileStep ? "profile" : "review")}
                          >
                            Continuar
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Paso 3 (opcional): Perfil de referencia — solo aparece si la
                    persona lo eligió explícitamente desde "Datos". Subirlo acá
                    ya re-dispara el cruce; "Continuar" avanza a "Revisión"
                    donde se ve el resultado (duplicados/candidatos). */}
                {step === "profile" && (
                  <div className="space-y-3">
                    <motion.button
                      onClick={() => goToStep("data")}
                      whileHover={{ x: -2 }}
                      whileTap={{ scale: 0.98 }}
                      className="flex items-center gap-1 text-xs text-p-text-muted hover:text-p-text mb-1 transition-colors"
                    >
                      <ChevronLeft className="w-3.5 h-3.5" /> Datos
                    </motion.button>

                    <div className="card p-4 space-y-2.5">
                      <div className="flex items-center gap-1.5 pb-1 border-b border-p-border">
                        <Users className="w-3.5 h-3.5 text-p-accent shrink-0" />
                        <h2 className="text-xs font-semibold text-p-text uppercase tracking-wide">
                          Perfil de referencia (opcional)
                        </h2>
                      </div>
                      {roundProfile ? (
                        <p className="text-xs text-p-text">
                          Activo: <span className="font-medium">{roundProfile.original_filename}</span>
                          {" · "}
                          {roundProfile.expected_respondents} esperados
                        </p>
                      ) : (
                        <p className="text-xs text-p-text-muted">
                          Excel pactado con el cliente (columna Respondent ID). Si lo subes, se cruza al instante contra
                          los verbatims ya importados.
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
                          onChange={async (e) => {
                            const f = e.target.files?.[0];
                            e.target.value = "";
                            if (!f) return;
                            await handleProfileUpload(f);
                          }}
                        />
                        {profileUploading
                          ? "Subiendo…"
                          : roundProfile
                            ? "Cambiar perfil"
                            : "Subir perfil .xlsx"}
                      </label>
                    </div>

                    <button
                      type="button"
                      className="btn-primary text-sm py-2 w-full justify-center"
                      onClick={() => goToStep("review")}
                    >
                      Continuar
                    </button>
                  </div>
                )}

                {/* Paso 4: Revisión — cruce de duplicados/perfil + resumen,
                    apilados verticalmente en una sola pantalla. */}
                {step === "review" && (
                  <div className="space-y-4">
                    <motion.button
                      onClick={() => goToStep(showProfileStep ? "profile" : "data")}
                      whileHover={{ x: -2 }}
                      whileTap={{ scale: 0.98 }}
                      className="flex items-center gap-1 text-xs text-p-text-muted hover:text-p-text mb-1 transition-colors"
                    >
                      <ChevronLeft className="w-3.5 h-3.5" /> {showProfileStep ? "Perfil" : "Datos"}
                    </motion.button>

                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                      <div className="card p-3 space-y-1.5 border-p-border-mid bg-p-surface shadow-sm hover:border-p-accent/30 transition-colors">
                        <div className="text-[10px] uppercase font-bold text-p-text-muted tracking-wide flex items-center gap-1.5">
                          <Check className="w-3.5 h-3.5 text-p-success" /> Importación
                        </div>
                        <div className="text-xl font-bold text-p-text leading-none">{importedCount} <span className="text-[11px] font-medium text-p-text-muted uppercase tracking-wider">Muestras</span></div>
                      </div>

                      <div className="card p-3 space-y-1.5 border-p-border-mid bg-p-surface shadow-sm hover:border-p-accent/30 transition-colors">
                        <div className="text-[10px] uppercase font-bold text-p-text-muted tracking-wide flex items-center gap-1.5">
                          <FileSpreadsheet className="w-3.5 h-3.5 text-p-accent" /> Datos de origen
                        </div>
                        <div className="text-sm font-medium text-p-text truncate" title={uploaded?.original_filename ?? "Archivo importado"}>
                          {uploaded?.original_filename ?? "Datos importados"}
                        </div>
                      </div>

                      <div className="card p-3 space-y-1.5 border-p-border-mid bg-p-surface shadow-sm hover:border-p-accent/30 transition-colors">
                        <div className="text-[10px] uppercase font-bold text-p-text-muted tracking-wide flex items-center gap-1.5">
                          <BookOpen className="w-3.5 h-3.5 text-p-accent" /> Destino
                        </div>
                        <div className="text-sm font-medium text-p-text truncate" title={project?.name}>
                          {project?.name ?? "Proyecto actual"}
                        </div>
                        <div className="text-[11px] text-p-text-muted truncate">
                          {round?.name ?? "Ronda actual"}
                        </div>
                      </div>

                      <div className="card p-3 space-y-1.5 border-p-border-mid bg-p-surface shadow-sm hover:border-p-accent/30 transition-colors">
                        <div className="text-[10px] uppercase font-bold text-p-text-muted tracking-wide flex items-center gap-1.5">
                          <Users className="w-3.5 h-3.5 text-p-accent" /> Perfil de referencia
                        </div>
                        <div className="text-sm font-medium text-p-text truncate">
                          {profileSummary?.has_profile ? "Validación activada" : "Sin validación de perfil"}
                        </div>
                      </div>
                    </div>
                    
                    <div className="rounded-xl bg-p-bg-subtle border border-p-border p-3.5 text-xs text-p-text flex items-start gap-2.5">
                      <div className="mt-0.5 relative flex items-center justify-center">
                        <span className="absolute w-2 h-2 rounded-full bg-p-success/40 animate-ping"></span>
                        <span className="relative w-2 h-2 rounded-full bg-p-success"></span>
                      </div>
                      <p className="leading-relaxed">
                        El motor de IA ya está procesando las muestras en segundo plano para los subproyectos: <span className="font-semibold text-p-text">{activeCodingTypes.map(t => CODING_LABELS[t]).join(" y ")}</span>. 
                        {(matchingProfile || profileSummary?.has_profile || profileCandidates.length > 0)
                          && " Revisa las incidencias de duplicados o candidatos a exclusión por perfil abajo antes de finalizar la configuración."}
                      </p>
                    </div>

                    {matchingProfile && (
                      <div className="card p-4 text-sm text-p-text-muted">Cruzando con el perfil…</div>
                    )}

                    {!matchingProfile && (profileSummary?.has_profile || profileCandidates.length > 0) && effectiveRoundId && importedFileId && (
                      <ProfileReviewPanel
                        roundId={effectiveRoundId}
                        fileId={importedFileId}
                        summary={profileSummary}
                        candidates={profileCandidates}
                        onCandidatesChange={setProfileCandidates}
                        showToast={showToast}
                        onAllResolved={() => {
                          playSuccess();
                          showToast("Revisión de perfil resuelta.", "success");
                        }}
                      />
                    )}

                    {!matchingProfile && duplicates.length > 0 && (
                      <section className="card p-4 space-y-3">
                        <div className="flex items-center gap-2">
                          <Users className="w-4 h-4 text-p-warning" />
                          <h2 className="text-sm font-bold uppercase tracking-wide text-p-text">
                            Posibles duplicados reales
                          </h2>
                          <span className={
                            duplicates.some((d) => d.status === "pending") ? "badge-warning" : "badge-success"
                          }>
                            {duplicates.filter((d) => d.status === "pending").length > 0
                              ? `${duplicates.filter((d) => d.status === "pending").length} pendientes`
                              : "Resueltos"}
                          </span>
                        </div>
                        <p className="text-xs text-p-text-muted">
                          El mismo ID real (persona) ya existe en otra carga de esta ronda. Decide por cada uno; el ID
                          real nunca se modifica.
                        </p>
                        <div className="space-y-2">
                          {duplicates.map((flag) => (
                            <div key={flag.flag_id} className="rounded-lg border border-p-border bg-p-bg-subtle p-3 space-y-2">
                              <div className="flex items-center justify-between gap-2 flex-wrap">
                                <div className="text-xs text-p-text">
                                  <span className="font-semibold">Serial {flag.serial ?? "—"}</span>
                                  <span className="text-p-text-muted"> · ID real </span>
                                  <code className="text-[11px]">{flag.realid ?? "—"}</code>
                                  {flag.matches.map((m, i) => (
                                    <span key={i} className="text-p-text-muted">
                                      {" "}· ya existe como Serial {m.serial ?? "—"} — Carga: {m.source_label}
                                    </span>
                                  ))}
                                </div>
                                {flag.status !== "pending" ? (
                                  <span className={flag.status === "approved_remove" ? "badge-pending" : "badge-success"}>
                                    {flag.status === "approved_keep"
                                      ? "Se mantienen ambos"
                                      : flag.status === "approved_remove"
                                        ? "Carga nueva descartada"
                                        : "Editado"}
                                  </span>
                                ) : (
                                  <div className="flex items-center gap-1.5">
                                    <button
                                      type="button"
                                      className="btn-primary text-xs py-1.5 px-2.5"
                                      disabled={resolvingFlagId === flag.flag_id}
                                      onClick={() => void handleResolve(flag, "keep")}
                                    >
                                      Mantener ambos
                                    </button>
                                    <button
                                      type="button"
                                      className="btn-ghost text-xs py-1.5 px-2.5"
                                      disabled={resolvingFlagId === flag.flag_id}
                                      onClick={() => void handleResolve(flag, "edit")}
                                    >
                                      Guardar con nota
                                    </button>
                                    <button
                                      type="button"
                                      className="btn-ghost text-xs py-1.5 px-2.5 text-p-error"
                                      disabled={resolvingFlagId === flag.flag_id}
                                      onClick={() => void handleResolve(flag, "remove")}
                                    >
                                      Quitar de esta carga
                                    </button>
                                  </div>
                                )}
                              </div>
                              {flag.status === "pending" && (
                                <input
                                  className="input w-full text-xs"
                                  placeholder="Nota opcional (se guarda con la decisión 'Guardar con nota')"
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

                    {!matchingProfile && serialCollisions.length > 0 && (
                      <section className="card p-4 space-y-3">
                        <div className="flex items-center gap-2">
                          <Info className="w-4 h-4 text-p-accent" />
                          <h2 className="text-sm font-bold uppercase tracking-wide text-p-text">
                            Seriales repetidos entre cargas
                          </h2>
                          <span className="badge-pending">Informativo</span>
                        </div>
                        <p className="text-xs text-p-text-muted">
                          El mismo Serial aparece en dos cargas con distinto ID real: son personas distintas. No requiere
                          acción — la etiqueta de carga los distingue.
                        </p>
                        <div className="space-y-1.5">
                          {serialCollisions.map((c, i) => (
                            <div key={i} className="text-xs text-p-text bg-p-bg-subtle rounded-lg p-2">
                              Serial <span className="font-semibold">{c.serial ?? "—"}</span> también existe en{" "}
                              {c.previous_source_label} (otra persona).
                            </div>
                          ))}
                        </div>
                      </section>
                    )}

                    {!matchingProfile && pendingFlags > 0 && (
                      <div className="flex items-center gap-2 text-xs text-p-text-muted">
                        <AlertCircle className="w-3.5 h-3.5 text-p-warning" />
                        Quedan {pendingFlags} pendientes de revisión — puedes continuar igual, se resuelven cuando quieras.
                      </div>
                    )}

                    {/* Resumen final — siempre visible, arriba de la barra de
                        cruce si la hubo. */}
                    <div className="card p-4 space-y-2">
                      <div className="flex items-center gap-2 text-sm font-semibold text-p-text">
                        <Check className="w-4 h-4 text-p-success" />
                        {roundName ?? "Ronda"} lista
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-xs text-p-text-muted">
                        <div>Verbatims importados: <span className="font-semibold text-p-text">{importedCount}</span></div>
                        <div>Mínimo de menciones: <span className="font-semibold text-p-text">{rThreshold}</span></div>
                        <div>% de auditoría: <span className="font-semibold text-p-text">{rAudit}</span></div>
                        <div>Tipos codificados: <span className="font-semibold text-p-text">{activeCodingTypes.map((t) => CODING_LABELS[t]).join(", ")}</span></div>
                      </div>
                      {profileSummary?.has_profile && (
                        <p className="text-xs text-p-text-muted">
                          Perfil: {profileSummary.expected} esperados · {profileSummary.arrived} llegaron · {profileSummary.extra} de más.
                        </p>
                      )}
                    </div>

                    <button
                      type="button"
                      className="btn-primary text-sm py-2 w-full justify-center"
                      onClick={goToRoundOutcome}
                    >
                      Ir al procesamiento
                    </button>
                  </div>
                )}
              </motion.div>
            </AnimatePresence>
          </div>
      </div>


    </div>
  );
}