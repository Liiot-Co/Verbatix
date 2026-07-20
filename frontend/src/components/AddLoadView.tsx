import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useDropzone } from "react-dropzone";
import { motion } from "framer-motion";
import {
  AlertCircle,
  AlertTriangle,
  Check,
  FileSpreadsheet,
  Info,
  Loader2,
  UploadCloud,
  Users,
} from "lucide-react";
import {
  classifyQuestion,
  getRound,
  getRoundProfile,
  importFile,
  previewFields,
  resolveImportFlag,
  uploadFile,
  uploadRoundProfile,
} from "@/api/client";
import type {
  CodingType,
  ColumnMap,
  DetectedSheet,
  DuplicateFlag,
  FieldPreview,
  FieldSelection,
  ProfileCandidateFlag,
  ProfileReviewSummary,
  RoundProfileSummary,
  RoundStatus,
  SerialCollision,
  UploadedFile,
} from "@/api/types";
import { useVerbatixStore } from "@/store/useVerbatixStore";
import { playSuccess, playTick } from "@/lib/sound";
import Breadcrumb from "./Breadcrumb";
import FieldSelectionTable, { initialFieldSelections } from "./FieldSelectionTable";
import ProfileReviewPanel from "./ProfileReviewPanel";
import RoundCodingControls, {
  detectedMaxFromFields,
  hasPendingRoundMentionDecision,
  type RoundCodingControlsValue,
} from "./RoundCodingControls";
import { guessExcelColumnMap } from "@/lib/excelColumns";

type Step = "upload" | "confirm" | "review";

/**
 * REQ-03 — "Agregar nueva carga": sube un archivo adicional a una ronda
 * EXISTENTE (no crea rondas nuevas, a diferencia del wizard). Tras importar,
 * muestra las 3 secciones de revisión: duplicados reales por realid
 * (decisión humana: mantener/editar/quitar), avisos de Serial repetido
 * (informativos) y variables sin calzar (se clasifican Marcas/Razones).
 * El motor arranca solo cuando la cola de duplicados queda resuelta.
 */
export default function AddLoadView() {
  const { roundId } = useParams<{ roundId: string }>();
  const navigate = useNavigate();
  const showToast = useVerbatixStore((s) => s.showToast);

  const [round, setRound] = useState<RoundStatus | null>(null);
  const [step, setStep] = useState<Step>("upload");
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
  const [submitting, setSubmitting] = useState(false);

  const [pendingQuestions, setPendingQuestions] = useState<string[]>([]);
  const [questionTypes, setQuestionTypes] = useState<Record<string, CodingType>>({});

  const [duplicates, setDuplicates] = useState<DuplicateFlag[]>([]);
  const [profileCandidates, setProfileCandidates] = useState<ProfileCandidateFlag[]>([]);
  const [profileSummary, setProfileSummary] = useState<ProfileReviewSummary | null>(null);
  const [roundProfile, setRoundProfile] = useState<RoundProfileSummary | null>(null);
  const [profileUploading, setProfileUploading] = useState(false);
  const [serialCollisions, setSerialCollisions] = useState<SerialCollision[]>([]);
  const [importedCount, setImportedCount] = useState(0);
  const [editNotes, setEditNotes] = useState<Record<string, string>>({});
  const [resolvingFlagId, setResolvingFlagId] = useState<string | null>(null);

  useEffect(() => {
    if (!roundId) return;
    getRound(roundId)
      .then(setRound)
      .catch(() => showToast("No se pudo cargar la ronda.", "error"));
    getRoundProfile(roundId)
      .then(setRoundProfile)
      .catch(() => setRoundProfile(null));
  }, [roundId, showToast]);

  const onDrop = useCallback(
    async (accepted: File[]) => {
      const [file] = accepted;
      if (!file || !roundId) return;
      try {
        const result = await uploadFile(roundId, file);
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
        setStep("confirm");
        playTick();
      } catch {
        showToast("No se pudo subir el archivo.", "error");
      }
    },
    [roundId, showToast]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    multiple: false,
    accept: {
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/vnd.ms-excel": [".xls"],
      "application/octet-stream": [".dau"],
    },
  });

  const activeSheet: DetectedSheet | undefined = uploaded?.detected_sheets.find(
    (s) => s.name === verbatimsSheet
  );
  const isDau = uploaded?.file_type === "dau";
  const activeCodingTypesKey = (round?.subprojects ?? [])
    .map((s) => s.coding_type)
    .slice()
    .sort()
    .join(",");
  const activeCodingTypes = useMemo(
    () => (activeCodingTypesKey ? (activeCodingTypesKey.split(",") as CodingType[]) : []),
    [activeCodingTypesKey],
  );
  const detectedMaxMentions = detectedMaxFromFields(fieldPreviews);
  const canImport = !!(
    uploaded
    && verbatimsSheet
    && (isDau || (Boolean(columnMap.verbatim) && Boolean(columnMap.respondent_id)))
    && (!hasPendingRoundMentionDecision(roundControls, detectedMaxMentions, activeCodingTypes))
  );
  const showCodingType = (round?.subprojects.length ?? 0) > 1;

  // Selección de campos: solo al cambiar archivo/hoja — no al tocar el interruptor.
  useEffect(() => {
    if (!roundId || !uploaded || !round) {
      setFieldPreviews([]);
      setFieldSelections([]);
      return;
    }
    if (!isDau && !verbatimsSheet) return;
    const fileId = uploaded.file_id;
    const expectedFromRound = round.expected_max_mentions ?? null;
    const types = (round.subprojects ?? []).map((s) => s.coding_type as CodingType);
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
  }, [roundId, uploaded?.file_id, verbatimsSheet, isDau, round?.id]); // round por id a propósito

  const pendingFlags = useMemo(
    () =>
      duplicates.filter((d) => d.status === "pending").length
      + profileCandidates.filter((c) => c.status === "pending").length,
    [duplicates, profileCandidates]
  );

  const handleProfileUpload = useCallback(async (file: File) => {
    if (!roundId) return;
    setProfileUploading(true);
    try {
      const result = await uploadRoundProfile(roundId, file);
      setRoundProfile({
        profile_file_id: result.profile_file_id,
        original_filename: result.original_filename,
        total_rows: result.total_rows,
        expected_respondents: result.expected_respondents,
        created_at: null,
      });
      showToast(
        `Perfil cargado: ${result.expected_respondents} Respondent ID esperados`,
        "success"
      );
      playTick();
    } catch (err) {
      const message = err instanceof Error ? err.message : "No se pudo leer el perfil.";
      showToast(message, "error");
    } finally {
      setProfileUploading(false);
    }
  }, [roundId, showToast]);

  const handleImport = useCallback(async () => {
    if (!roundId || !uploaded || !canImport) return;
    setSubmitting(true);
    try {
      const result = await importFile(
        roundId,
        uploaded.file_id,
        verbatimsSheet,
        columnMap as ColumnMap,
        {
          sourceLabel: sourceLabel.trim() || undefined,
          // Solo .dau: ver nota en CreationWizard sobre por qué Excel no envía
          // field_selections (su question_key viene de la columna "Question ID",
          // no del nombre de columna).
          ...(isDau ? { fieldSelections } : {}),
          singleCodeByType: Object.fromEntries(
            activeCodingTypes.map((ct) => [ct, roundControls.singleCodeByType[ct] ?? false])
          ),
          expectedMaxMentions: roundControls.expectedMaxMentions,
          mentionsDecision: roundControls.mentionsDecision,
        }
      );
      if (result.pending_questions.length > 0) {
        setPendingQuestions(result.pending_questions);
        setQuestionTypes(
          Object.fromEntries(result.pending_questions.map((q) => [q, "brands" as CodingType]))
        );
        showToast("Clasifica las variables nuevas antes de continuar.", "info");
        return;
      }
      setImportedCount(result.imported.verbatims);
      setDuplicates(result.review.duplicates);
      setProfileCandidates(result.review.profile_candidates ?? []);
      setProfileSummary(result.review.profile ?? null);
      setSerialCollisions(result.review.serial_collisions);
      playSuccess();
      if (result.review.pending_flags === 0) {
        showToast(
          `Importados ${result.imported.verbatims} verbatims · codificando en el motor...`,
          "success"
        );
        navigate(`/rounds/${roundId}/preliminary`);
        return;
      }
      setStep("review");
      showToast(
        `Importados ${result.imported.verbatims} verbatims · ${result.review.pending_flags} pendientes de revisión.`,
        "info"
      );
    } catch {
      showToast("No se pudo importar el archivo.", "error");
    } finally {
      setSubmitting(false);
    }
  }, [roundId, uploaded, canImport, verbatimsSheet, columnMap, sourceLabel, isDau, fieldSelections, roundControls, activeCodingTypes, navigate, showToast]);

  const handleClassifyQuestions = useCallback(async () => {
    if (!round?.project_id || pendingQuestions.length === 0) return;
    setSubmitting(true);
    try {
      await Promise.all(
        pendingQuestions.map((questionKey) =>
          classifyQuestion(round.project_id!, {
            question_key: questionKey,
            coding_type: questionTypes[questionKey] ?? "brands",
          })
        )
      );
      setPendingQuestions([]);
      setSubmitting(false);
      await handleImport();
    } catch {
      showToast("No se pudieron clasificar las variables nuevas.", "error");
      setSubmitting(false);
    }
  }, [round, pendingQuestions, questionTypes, handleImport, showToast]);

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
        if (result.pending_flags === 0) {
          playSuccess();
          showToast("Revisión resuelta · codificando en el motor...", "success");
          navigate(`/rounds/${roundId}/preliminary`);
        }
      } catch {
        showToast("No se pudo resolver la decisión.", "error");
      } finally {
        setResolvingFlagId(null);
      }
    },
    [resolvingFlagId, editNotes, navigate, roundId, showToast]
  );

  const studyName = round?.project_name ?? "Estudio";

  return (
    <div className="max-w-3xl mx-auto py-4 space-y-6">
      <Breadcrumb
        items={[
          { label: "Proyectos", to: "/" },
          ...(round ? [{ label: studyName, to: `/projects/${round.project_id}` }] : []),
          { label: round?.name ?? "Ronda", to: `/rounds/${roundId}` },
          { label: "Nueva carga" },
        ]}
      />

      <div className="space-y-1">
        <h1 className="font-heading text-2xl font-semibold text-p-text tracking-tight">
          Agregar nueva carga
        </h1>
        <p className="text-sm text-p-text-muted">
          Los datos nuevos se suman a <span className="font-semibold text-p-text">{round?.name ?? "la ronda"}</span> sin
          tocar lo ya codificado. El Serial y el ID real del encuestado nunca se modifican.
        </p>
      </div>

      {step === "upload" && (
        <div
          {...getRootProps()}
          className={["dropzone", isDragActive ? "dropzone-active" : "hover:border-p-accent/40"].join(" ")}
        >
          <input {...getInputProps()} />
          <motion.div
            initial={{ opacity: 0, scale: 0.98 }}
            animate={isDragActive ? { opacity: 1, scale: 1.05 } : { opacity: 1, scale: 1 }}
            className="dropzone-icon"
          >
            <UploadCloud />
          </motion.div>
          <span className="text-sm font-medium text-p-text">
            Arrastra el archivo de la nueva carga, o haz clic para elegirlo
          </span>
          <span className="text-xs text-p-text-faint">.xlsx, .xls o .dau</span>
        </div>
      )}

      {step === "confirm" && uploaded && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="card p-4 space-y-3"
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
                . Si continúas, todos sus encuestados aparecerán como posibles duplicados para revisión.
              </span>
            </div>
          )}

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
              Distingue esta carga de las anteriores cuando un Serial se repite (ej. "Serial 1 — Carga: Parte 1").
            </p>
          </div>

          <div className="rounded-lg border border-p-border bg-p-bg-subtle p-3 space-y-2">
            <label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
              Perfil de referencia (opcional)
            </label>
            <p className="text-[11px] text-p-text-faint">
              Excel pactado con el cliente (`Respondent ID`). Si no se carga, la importación sigue igual que hoy.
            </p>
            {roundProfile ? (
              <p className="text-xs text-p-text">
                Activo: <span className="font-medium">{roundProfile.original_filename}</span>
                {" · "}
                {roundProfile.expected_respondents} Respondent ID esperados
              </p>
            ) : (
              <p className="text-xs text-p-text-muted">Sin perfil cargado.</p>
            )}
            <label className="btn-secondary text-xs py-1.5 px-2.5 inline-flex items-center gap-1.5 cursor-pointer">
              <input
                type="file"
                accept=".xlsx,.xls"
                className="sr-only"
                disabled={profileUploading}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void handleProfileUpload(f);
                  e.target.value = "";
                }}
              />
              {profileUploading ? "Subiendo…" : "Subir perfil .xlsx"}
            </label>
          </div>

          <div>
            <label className="text-xs font-semibold text-p-text-muted uppercase tracking-wide">
              Hoja de verbatims
            </label>
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
                <option key={s.name} value={s.name}>
                  {s.name} ({s.rows} filas)
                </option>
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
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
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
                    <option key={c} value={c}>
                      {c}
                    </option>
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
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}

          {fieldPreviews.length > 0 && (
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
                showCodingType={showCodingType}
                readOnly={!isDau}
              />
            </div>
          )}

          {pendingQuestions.length > 0 && (
            <div className="space-y-3 rounded-lg border border-p-warning/40 bg-p-warning/10 p-3">
              <div className="text-sm font-semibold text-p-text">Variables sin calzar con las cargas anteriores</div>
              <p className="text-xs text-p-text-muted">
                Estas columnas no coinciden con ninguna variable ya clasificada del estudio. Indica si cada una es
                Marcas o Razones para continuar.
              </p>
              {pendingQuestions.map((questionKey) => (
                <div key={questionKey} className="grid grid-cols-[1fr_150px] gap-2 items-center">
                  <code className="truncate text-xs text-p-text">{questionKey}</code>
                  <select
                    className="input text-sm"
                    value={questionTypes[questionKey] ?? "brands"}
                    onChange={(event) =>
                      setQuestionTypes((current) => ({
                        ...current,
                        [questionKey]: event.target.value as CodingType,
                      }))
                    }
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

          {pendingQuestions.length === 0 && (
            <div className="flex gap-1.5 pt-1">
              <button
                type="button"
                disabled={!canImport || submitting}
                className="btn-primary text-sm py-2 flex-1 justify-center"
                onClick={handleImport}
              >
                {submitting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" /> Importando...
                  </>
                ) : (
                  "Importar carga"
                )}
              </button>
              <button
                type="button"
                className="btn-ghost text-sm py-2 px-3"
                onClick={() => {
                  setUploaded(null);
                  setColumnMap({});
                  setStep("upload");
                }}
              >
                Cambiar archivo
              </button>
            </div>
          )}
        </motion.div>
      )}

      {step === "review" && (
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
          <div className="card p-4 space-y-1">
            <div className="flex items-center gap-2 text-sm font-semibold text-p-text">
              <Check className="w-4 h-4 text-p-success" />
              {importedCount} verbatims importados como{" "}
              <span className="text-p-accent">{sourceLabel || uploaded?.original_filename}</span>
            </div>
            <p className="text-xs text-p-text-muted">
              El motor arrancará automáticamente cuando resuelvas los pendientes de revisión
              (duplicados y/o candidatos a exclusión por perfil). Nada se borra sin tu aprobación.
            </p>
          </div>

          <ProfileReviewPanel
            roundId={roundId!}
            fileId={uploaded!.file_id}
            summary={profileSummary}
            candidates={profileCandidates}
            onCandidatesChange={setProfileCandidates}
            showToast={showToast}
            onAllResolved={() => {
              playSuccess();
              showToast("Revisión resuelta · codificando en el motor...", "success");
              navigate(`/rounds/${roundId}/preliminary`);
            }}
          />

          {/* Sección 1: duplicados reales (mismo realid) — decisión humana */}
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
              El mismo ID real (persona) ya existe en otra carga de esta ronda. Decide por cada uno; el ID real
              nunca se modifica.
            </p>
            {duplicates.length === 0 ? (
              <p className="text-sm text-p-text-faint py-2">Sin duplicados detectados.</p>
            ) : (
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
            )}
          </section>

          {/* Sección 2: Serial repetido entre cargas — informativo, no bloquea */}
          <section className="card p-4 space-y-3">
            <div className="flex items-center gap-2">
              <Info className="w-4 h-4 text-p-accent" />
              <h2 className="text-sm font-bold uppercase tracking-wide text-p-text">
                Seriales repetidos entre cargas
              </h2>
              <span className="badge-pending">Informativo</span>
            </div>
            <p className="text-xs text-p-text-muted">
              El mismo Serial aparece en dos cargas con distinto ID real: son personas distintas (cada plataforma
              numera desde 1). No requiere acción — la etiqueta de carga los distingue.
            </p>
            {serialCollisions.length === 0 ? (
              <p className="text-sm text-p-text-faint py-2">Sin seriales repetidos.</p>
            ) : (
              <div className="space-y-1.5">
                {serialCollisions.map((c, i) => (
                  <div key={i} className="text-xs text-p-text bg-p-bg-subtle rounded-lg p-2">
                    Serial <span className="font-semibold">{c.serial ?? "—"}</span> también existe en{" "}
                    {c.previous_source_label} (otra persona).
                  </div>
                ))}
              </div>
            )}
          </section>

          {pendingFlags > 0 && (
            <div className="flex items-center gap-2 text-xs text-p-text-muted">
              <AlertCircle className="w-3.5 h-3.5 text-p-warning" />
              El procesamiento está en pausa hasta resolver los {pendingFlags} pendientes de revisión.
            </div>
          )}
        </motion.div>
      )}
    </div>
  );
}
