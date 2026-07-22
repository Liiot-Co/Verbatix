import type {
  AuditApproveResult,
  AuditReadiness,
  AuditCodeReview,
  AuditItemList,
  AuditPatchResult,
  AuditPopulationCodes,
  AuditPopulationItemList,
  AuditReviewDecision,
  AuditSectionApproveResult,
  AuditReviewResult,
  AuditSessionSummary,
  BulkResolveResult,
  CatalogOriginSelection,
  CatalogPreview,
  CodebookSource,
  CodebookDraft,
  CodebookDraftApproval,
  CodebookDraftDecision,
  ColumnMap,
  FieldPreview,
  FieldSelection,
  ImportResult,
  LoadReviewState,
  LoginPayload,
  LoginResponse,
  MentionGroupDetail,
  MentionGroupStatus,
  NewCodeInput,
  PreliminarySummary,
  ProcessResult,
  ProfileCandidateFlag,
  ProfileMatchResult,
  ProjectDetail,
  ProjectListItem,
  ProyectoDetail,
  ProyectoListItem,
  ProyectoStudyItem,
  ResolutionQueue,
  ResolutionSummary,
  ResolveDecision,
  ResolveFlagResult,
  ResolveResult,
  Round,
  RoundLoad,
  RoundCode,
  RoundProfileSummary,
  RoundReport,
  RoundStatus,
  RoundSubproject,
  SheetImportSpec,
  SignupPayload,
  SignupResponse,
  UploadedFile,
  UserProfile,
  AdminUser,
  RoleCode,
  ProjectMember,
  VerbatimList,
  VerbatimSummary,
  NotificationList,
  NotificationStream,
} from "./types";
import { readAuthToken, writeAuthToken } from "@/lib/tokenStorage";
import type { PresenceStatus } from "@/lib/presence";

const BASE = "/api/v1";
const AUTH_BASE = "/api/auth";

export class ApiError extends Error {
  status: number;
  /** Machine-readable code from the backend detail (e.g. "processing_required"). */
  code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.status = status;
    if (code !== undefined) this.code = code;
  }
}

/** True for the 403 the backend raises when a round hasn't reached a resolution
 * phase yet (still importing/processing/awaiting codebook). Not a real error —
 * the UI should show a "processing" state, not blow up. */
export function isProcessingRequired(err: unknown): boolean {
  return err instanceof ApiError && err.code === "processing_required";
}

function getToken(): string | null {
  return readAuthToken();
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  if (options?.body instanceof FormData) {
    // Let fetch set Content-Type with boundary
  } else if (options?.headers) {
    Object.assign(headers, options.headers);
  } else {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(`${BASE}${url}`, { ...options, headers });
  if (!res.ok) {
    const text = await res.text();
    if (res.status === 401) {
      writeAuthToken(null);
      localStorage.removeItem("verbatix:user");
      window.location.href = "/login";
    }
    let message = text;
    let code: string | undefined;
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed.detail === "string") message = parsed.detail;
      else if (parsed.detail) {
        // Backend structured errors (round-sequence-and-homologation, etc.)
        // send `detail: { code, message }` — prefer the human message over
        // dumping the raw JSON object into the UI.
        message = typeof parsed.detail.message === "string"
          ? parsed.detail.message
          : JSON.stringify(parsed.detail);
        if (typeof parsed.detail.code === "string") code = parsed.detail.code;
      }
    } catch {
      // not JSON — keep raw text
    }
    throw new ApiError(res.status, message, code);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

async function authRequest<T>(url: string, options?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(`${AUTH_BASE}${url}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options?.headers as Record<string, string>),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    let message = text;
    try {
      const parsed = JSON.parse(text) as { detail?: string };
      if (parsed.detail) message = parsed.detail;
    } catch { /* keep response text */ }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const jsonHeaders = { "Content-Type": "application/json" };

/* ── Auth ── */

export async function login(payload: LoginPayload): Promise<LoginResponse> {
  return authRequest<LoginResponse>("/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function signup(payload: SignupPayload): Promise<SignupResponse> {
  return authRequest<SignupResponse>("/signup", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getMe(): Promise<UserProfile> {
  return authRequest<UserProfile>("/me", { cache: "no-store" });
}

export async function logoutSession(): Promise<void> {
  await authRequest<void>("/logout", { method: "POST" });
}

/* ── Notificaciones ── */

export async function streamNotifications(sinceSignal: number, signal?: AbortSignal): Promise<NotificationStream> {
  return request<NotificationStream>(
    `/notifications/stream?since_signal=${sinceSignal}`,
    signal ? { signal, cache: "no-store" } : { cache: "no-store" },
  );
}

export async function getNotifications(
  limit = 20,
  offset = 0,
  onlyUnread = false,
): Promise<NotificationList> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset), only_unread: String(onlyUnread) });
  return request<NotificationList>(`/notifications?${params.toString()}`);
}

export async function getUnreadCount(): Promise<{ unread_count: number; signal: number }> {
  return request<{ unread_count: number; signal: number }>("/notifications/unread-count");
}

export async function markNotificationRead(notificationId: string): Promise<{ updated: boolean }> {
  return request<{ updated: boolean }>(`/notifications/${notificationId}/read`, { method: "POST" });
}

export async function markAllNotificationsRead(): Promise<{ updated: number }> {
  return request<{ updated: number }>("/notifications/read-all", { method: "POST" });
}

export async function recoverAccount(payload: { email: string; recovery_code: string; password: string }): Promise<SignupResponse> {
  return authRequest<SignupResponse>("/recover", { method: "POST", body: JSON.stringify(payload) });
}

export async function getAdminUsers(status?: string, q?: string): Promise<AdminUser[]> {
  const params = new URLSearchParams();
  if (status) params.set("account_status", status);
  if (q) params.set("q", q);
  return request<AdminUser[]>(`/admin/users?${params}`);
}

export async function approveAndAssign(userId: string, roles: RoleCode[], studyIds: string[]): Promise<void> {
  await request(`/admin/users/${userId}/approve-and-assign`, {
    method: "POST", headers: jsonHeaders, body: JSON.stringify({ roles, study_ids: studyIds }),
  });
}

export async function setUserStatus(userId: string, accountStatus: "active" | "suspended"): Promise<void> {
  await request(`/admin/users/${userId}/status`, {
    method: "PATCH", headers: jsonHeaders, body: JSON.stringify({ account_status: accountStatus }),
  });
}

export async function setPresence(status: PresenceStatus): Promise<{ status: PresenceStatus; changed_at: string | null }> {
  return request<{ status: PresenceStatus; changed_at: string | null }>("/presence/me", {
    method: "PUT", headers: jsonHeaders, body: JSON.stringify({ status }),
  });
}

/* ── Proyectos ── */

export async function getProyectos(params?: { q?: string }): Promise<ProyectoListItem[]> {
  const qs = params && params.q ? `?q=${encodeURIComponent(params.q)}` : "";
  return request<ProyectoListItem[]>(`/proyectos${qs}`);
}

export async function getProyectoProjects(proyectoId: string): Promise<ProyectoStudyItem[]> {
  return request<ProyectoStudyItem[]>(`/proyectos/${proyectoId}/projects`);
}

export async function createProyecto(name: string): Promise<{ id: string; name: string }> {
  return request("/proyectos", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ name }),
  });
}

export async function getProyecto(proyectoId: string): Promise<ProyectoDetail> {
  return request<ProyectoDetail>(`/proyectos/${proyectoId}`);
}

/* ── Projects ── */

// Bare array, no pagination envelope — that's what the backend actually returns.
export async function getProjects(params?: { q?: string; analytic_target?: string; assigned_user_id?: string }): Promise<ProjectListItem[]> {
  const qs = params ? "?" + new URLSearchParams(Object.fromEntries(Object.entries(params).filter(([_, v]) => v))).toString() : "";
  return request<ProjectListItem[]>(`/projects${qs}`);
}

export async function createProject(
  externalCode: string,
  name: string,
  projectId?: string
): Promise<{ id: string; external_code: string; name: string; project_id: string | null; created_at: string }> {
  return request("/projects", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ external_code: externalCode, name, project_id: projectId }),
  });
}

export async function getProject(projectId: string): Promise<ProjectDetail> {
  return request<ProjectDetail>(`/projects/${projectId}`);
}

// round-sequence-and-homologation (Task 1): siguiente round_number esperado
// del proyecto — el wizard lo consume para bloquear el input.
export async function getNextRoundNumber(projectId: string): Promise<number> {
  const { next_round_number } = await request<{ next_round_number: number }>(
    `/projects/${projectId}/next-round-number`
  );
  return next_round_number;
}

export async function getProjectMembers(projectId: string): Promise<ProjectMember[]> {
  return request<ProjectMember[]>(`/projects/${projectId}/assignments`);
}

export async function assignProjectMember(projectId: string, userId: string): Promise<void> {
  await request(`/projects/${projectId}/assignments`, { method: "POST", headers: jsonHeaders, body: JSON.stringify({ user_id: userId }) });
}

export async function revokeProjectMember(projectId: string, userId: string): Promise<void> {
  await request(`/projects/${projectId}/assignments/${userId}`, { method: "DELETE" });
}

export async function deleteProject(projectId: string): Promise<void> {
  await request<void>(`/projects/${projectId}`, { method: "DELETE" });
}

export async function deleteRound(roundId: string): Promise<void> {
  await request<void>(`/rounds/${roundId}`, { method: "DELETE" });
}

export interface CreateRoundInput {
  name: string;
  round_number: number;
  min_mentions_threshold: number;
  audit_percentage: number;
}

export interface UpdateRoundInput {
  name?: string;
  min_mentions_threshold?: number;
  audit_percentage?: number;
}

export async function createRound(projectId: string, input: CreateRoundInput): Promise<Round> {
  return request<Round>(`/projects/${projectId}/rounds`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

/** Actualiza campos de la ronda in-place (sin borrar/recrear).
 *  threshold/audit solo se pueden editar antes de que haya verbatims
 *  importados — el backend devuelve 409 con code "round_has_imports" si ya hay. */
export async function updateRound(roundId: string, input: UpdateRoundInput): Promise<Round> {
  return request<Round>(`/rounds/${roundId}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export interface CreateRoundSubprojectsInput {
  /** Solo los tipos elegidos (Marcas, Razones o ambos). El origen es obligatorio por tipo. */
  catalog_origins: Partial<Record<"brands" | "reasons", CatalogOriginSelection>>;
  reuse_catalogs_from_round_id?: string | null;
}

export async function createRoundSubprojects(
  roundId: string,
  input: CreateRoundSubprojectsInput
): Promise<{ round_id: string; subprojects: RoundSubproject[] }> {
  return request(`/rounds/${roundId}/subprojects`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export async function getCodebookSources(
  projectId: string,
  codingType: "brands" | "reasons"
): Promise<CodebookSource[]> {
  return request<CodebookSource[]>(
    `/projects/${projectId}/codebook-sources?coding_type=${codingType}`
  );
}

/* ── Rondas: archivos, import, proceso (Fase 1 + Fase 2) ── */

export async function getRound(roundId: string): Promise<RoundStatus> {
  return request<RoundStatus>(`/rounds/${roundId}`);
}

/** Recupera los metadatos de un archivo ya subido sin re-subirlo.
 *  Usado al reanudar el wizard: el archivo existe en el servidor pero
 *  el cliente no tiene el objeto File en memoria. */
export async function getUploadedFile(roundId: string, fileId: string): Promise<UploadedFile> {
  return request<UploadedFile>(`/rounds/${roundId}/files/${fileId}`);
}


export async function uploadFile(roundId: string, file: File): Promise<UploadedFile> {
  const form = new FormData();
  form.append("file", file);
  return request<UploadedFile>(`/rounds/${roundId}/files`, { method: "POST", body: form });
}

export async function previewClientCatalog(
  roundId: string,
  fileId: string,
  sheet: string,
  codingType: "brands" | "reasons"
): Promise<CatalogPreview> {
  return request<CatalogPreview>(
    `/rounds/${roundId}/files/${fileId}/catalog-preview`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ sheet, coding_type: codingType }),
    }
  );
}

export async function importClientCatalog(
  roundId: string,
  fileId: string,
  sheet: string,
  codingType: "brands" | "reasons"
): Promise<CatalogPreview> {
  return request<CatalogPreview>(
    `/rounds/${roundId}/files/${fileId}/catalog-import`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ sheet, coding_type: codingType }),
    }
  );
}

export interface ImportSettings {
  codebookSheet?: string | undefined;
  codebookCodingType?: "brands" | "reasons" | undefined;
  // Hojas adicionales del mismo Excel (Marcas y Razones en hojas separadas en
  // vez de columnas dentro de la misma hoja) — se suman a verbatimsSheet en un
  // único import atómico (un snapshot, una pasada de duplicados).
  extraSheets?: SheetImportSpec[] | undefined;
  // REQ-03: etiqueta de la carga, confirmada/editada por el analista antes de importar.
  sourceLabel?: string | undefined;
  // Capturados al soltar el archivo — solo se usan si esta importación crea un
  // subproyecto nuevo. No editables después (ver UpdateSubprojectInput).
  minMentionsThreshold?: number | undefined;
  auditPercentage?: number | undefined;
  // Wizard de selección de campos: None conserva el comportamiento actual
  // (todos los campos incluidos, sin pre-clasificar).
  fieldSelections?: FieldSelection[] | undefined;
  // REQ-08: una vez por Marcas / Razones.
  singleCodeByType?: Partial<Record<"brands" | "reasons", boolean>> | undefined;
  // REQ-04: máximo de la ronda + decisión si hay overflow.
  expectedMaxMentions?: number | null | undefined;
  mentionsDecision?: "process_all" | "limit_to_expected" | null | undefined;
  // REQ-05: diferir el motor hasta cruce/resolución de perfil.
  deferProcessing?: boolean | undefined;
}

export async function previewFields(
  roundId: string,
  fileId: string,
  sheet?: string
): Promise<{ fields: FieldPreview[] }> {
  return request<{ fields: FieldPreview[] }>(
    `/rounds/${roundId}/files/${fileId}/preview-fields`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ sheet: sheet ?? null }),
    }
  );
}

export async function importFile(
  roundId: string,
  fileId: string,
  verbatimsSheet: string,
  columnMap: ColumnMap,
  settings: ImportSettings = {}
): Promise<ImportResult> {
  return request<ImportResult>(`/rounds/${roundId}/files/${fileId}/import`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({
      verbatims_sheet: verbatimsSheet,
      codebook_sheet: settings.codebookSheet ?? null,
      codebook_coding_type: settings.codebookSheet ? settings.codebookCodingType : null,
      column_map: columnMap,
      extra_sheets: settings.extraSheets ?? null,
      source_label: settings.sourceLabel ?? null,
      min_mentions_threshold: settings.minMentionsThreshold ?? null,
      audit_percentage: settings.auditPercentage ?? null,
      field_selections: settings.fieldSelections ?? null,
      single_code_by_type: settings.singleCodeByType ?? null,
      expected_max_mentions: settings.expectedMaxMentions ?? null,
      mentions_decision: settings.mentionsDecision ?? null,
      defer_processing: settings.deferProcessing ?? false,
    }),
  });
}

export async function getRoundLoads(roundId: string): Promise<RoundLoad[]> {
  return request<RoundLoad[]>(`/rounds/${roundId}/loads`);
}

export async function getLoadReview(roundId: string, fileId: string): Promise<LoadReviewState> {
  return request<LoadReviewState>(`/rounds/${roundId}/files/${fileId}/review`);
}

/** Task 3/4: cruce explícito de duplicados + perfil por Respondent ID sobre
 * una carga ya importada — se dispara desde el wizard después de que el
 * analista confirma los campos seleccionados (ya no corre dentro de import). */
export async function matchProfile(
  roundId: string,
  fileId: string
): Promise<ProfileMatchResult> {
  return request<ProfileMatchResult>(
    `/rounds/${roundId}/files/${fileId}/profile-match`,
    { method: "POST", headers: jsonHeaders }
  );
}

export async function resolveImportFlag(
  flagId: string,
  action: "keep" | "remove" | "edit",
  note?: string
): Promise<ResolveFlagResult> {
  return request<ResolveFlagResult>(`/import-review/${flagId}/resolve`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ action, note: note ?? null }),
  });
}

export async function resolveProfileFlagsBulk(
  flagIds: string[],
  action: "keep" | "remove"
): Promise<{
  resolved: number;
  status: ProfileCandidateFlag["status"];
  flag_ids: string[];
  pending_flags: number;
  already_resolved?: boolean;
  processing: { status: "queued" | "blocked_on_review" };
}> {
  return request(`/import-review/bulk-resolve`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ flag_ids: flagIds, action }),
  });
}

/** Una sola petición: mantener/excluir todos los pendientes de perfil de la carga. */
export async function resolveAllProfileForFile(
  roundId: string,
  fileId: string,
  action: "keep" | "remove"
): Promise<{
  resolved: number;
  status: ProfileCandidateFlag["status"];
  flag_ids: string[];
  pending_flags: number;
  already_resolved?: boolean;
  processing: { status: "queued" | "blocked_on_review" };
}> {
  return request(`/rounds/${roundId}/files/${fileId}/profile-review/resolve-all`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ action }),
  });
}

/* ── REQ-05: perfil de referencia ── */

export async function uploadRoundProfile(
  roundId: string,
  file: File,
  opts?: { sheet?: string; codingType?: "brands" | "reasons" | null }
): Promise<{
  profile_file_id: string;
  original_filename: string;
  total_rows: number;
  expected_respondents: number;
  coding_type: "brands" | "reasons" | null;
  sheet: string;
}> {
  const form = new FormData();
  form.append("file", file);
  const params = new URLSearchParams();
  if (opts?.sheet) params.set("sheet", opts.sheet);
  if (opts?.codingType) params.set("coding_type", opts.codingType);
  const qs = params.toString() ? `?${params.toString()}` : "";
  return request(`/rounds/${roundId}/profile${qs}`, { method: "POST", body: form });
}

export async function getRoundProfile(
  roundId: string
): Promise<RoundProfileSummary | null> {
  return request(`/rounds/${roundId}/profile`);
}

export async function classifyQuestion(
  projectId: string,
  input: { question_key: string; coding_type: "brands" | "reasons" }
): Promise<{ id: string; question_key: string; coding_type: "brands" | "reasons" }> {
  return request(`/projects/${projectId}/questions/classify`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export async function getVerbatims(
  subprojectId: string,
  limit = 100,
  offset = 0,
  status?: string
): Promise<VerbatimList> {
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (status) qs.set("status", status);
  return request<VerbatimList>(`/subprojects/${subprojectId}/verbatims?${qs.toString()}`);
}

export async function getVerbatimsSummary(
  subprojectId: string,
  view: "pending" | "coded"
): Promise<VerbatimSummary> {
  return request<VerbatimSummary>(`/subprojects/${subprojectId}/verbatims/summary?view=${view}`);
}

export async function processRound(roundId: string): Promise<ProcessResult> {
  return request<ProcessResult>(`/rounds/${roundId}/process`, { method: "POST" });
}

export async function getCodebookDraft(subprojectId: string): Promise<CodebookDraft> {
  return request<CodebookDraft>(`/subprojects/${subprojectId}/codebook-draft`);
}

export async function approveCodebookDraft(
  subprojectId: string,
  codes: CodebookDraftDecision[],
): Promise<CodebookDraftApproval> {
  return request<CodebookDraftApproval>(`/subprojects/${subprojectId}/codebook-draft/approve`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ codes }),
  });
}

export async function getPreliminary(roundId: string): Promise<PreliminarySummary> {
  return request<PreliminarySummary>(`/rounds/${roundId}/preliminary`);
}

/* ── Resolution Center (Fase 4) ── */

export async function getResolutionQueue(
  subprojectId: string,
  limit = 50,
  offset = 0,
  statuses?: MentionGroupStatus[],
  q?: string
): Promise<ResolutionQueue> {
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (statuses?.length) qs.set("statuses", statuses.join(","));
  if (q) qs.set("q", q);
  return request<ResolutionQueue>(`/subprojects/${subprojectId}/resolution/queue?${qs.toString()}`);
}

export async function getResolutionSummary(subprojectId: string): Promise<ResolutionSummary> {
  return request<ResolutionSummary>(`/subprojects/${subprojectId}/resolution/summary`);
}

export async function getRoundCodes(subprojectId: string, includeSystem = false): Promise<RoundCode[]> {
  const qs = new URLSearchParams({ include_system: String(includeSystem) });
  return request<RoundCode[]>(`/subprojects/${subprojectId}/codes?${qs.toString()}`);
}

export async function createRoundCode(subprojectId: string, input: NewCodeInput): Promise<RoundCode> {
  return request<RoundCode>(`/subprojects/${subprojectId}/codes`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export async function getMentionGroup(groupId: string): Promise<MentionGroupDetail> {
  return request<MentionGroupDetail>(`/mention-groups/${groupId}`);
}

export async function resolveMentionGroup(groupId: string, decision: ResolveDecision): Promise<ResolveResult> {
  return request<ResolveResult>(`/mention-groups/${groupId}/resolve`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(decision),
  });
}

export async function unresolveMentionGroup(groupId: string): Promise<{ group_id: string; status: string }> {
  return request<{ group_id: string; status: string }>(`/mention-groups/${groupId}/unresolve`, {
    method: "POST",
    headers: jsonHeaders,
  });
}

export async function bulkResolve(
  subprojectId: string,
  groupIds: string[],
  decision: ResolveDecision
): Promise<BulkResolveResult> {
  return request<BulkResolveResult>(`/subprojects/${subprojectId}/resolution/bulk`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ group_ids: groupIds, decision }),
  });
}

/* ── Auditoría (Fase 5) ── */

export async function getAuditReadiness(roundId: string): Promise<AuditReadiness> {
  return request<AuditReadiness>(`/rounds/${roundId}/audit/readiness`);
}

// Crea o reanuda (idempotente) la sesión; con resample=true re-muestrea una
// sesión desactualizada por un reproceso del motor (crea sesión nueva).
export async function createAuditSession(
  subprojectId: string,
  resample = false
): Promise<AuditSessionSummary> {
  return request<AuditSessionSummary>(`/subprojects/${subprojectId}/audit/session`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ resample }),
  });
}

export async function getAuditSession(subprojectId: string): Promise<AuditSessionSummary> {
  return request<AuditSessionSummary>(`/subprojects/${subprojectId}/audit/session`);
}

export async function getAuditCodes(subprojectId: string): Promise<AuditCodeReview[]> {
  return request<AuditCodeReview[]>(`/subprojects/${subprojectId}/audit/codes`);
}

export async function getAuditPopulationCodes(
  subprojectId: string
): Promise<AuditPopulationCodes> {
  return request<AuditPopulationCodes>(`/subprojects/${subprojectId}/audit/population/codes`);
}

export async function getAuditPopulationItems(
  subprojectId: string,
  codeId: string,
  limit = 100,
  offset = 0
): Promise<AuditPopulationItemList> {
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return request<AuditPopulationItemList>(
    `/subprojects/${subprojectId}/audit/population/codes/${codeId}/items?${qs.toString()}`
  );
}

export async function getAuditItems(
  reviewId: string,
  limit = 100,
  offset = 0
): Promise<AuditItemList> {
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return request<AuditItemList>(`/audit-code-reviews/${reviewId}/items?${qs.toString()}`);
}

export async function reviewAuditItem(
  itemId: string,
  decision: AuditReviewDecision
): Promise<AuditReviewResult> {
  return request<AuditReviewResult>(`/audit-items/${itemId}/review`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(decision),
  });
}

export async function patchAuditItem(
  itemId: string,
  input: { comment?: string | null }
): Promise<AuditPatchResult> {
  return request<AuditPatchResult>(`/audit-items/${itemId}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export async function editAuditComment(commentId: string, content: string): Promise<void> {
  await request(`/audit-comments/${commentId}`, { method: "PATCH", headers: jsonHeaders, body: JSON.stringify({ content }) });
}

export async function deleteAuditComment(commentId: string): Promise<void> {
  await request(`/audit-comments/${commentId}`, { method: "DELETE" });
}

// Aprueba una sección (un código de la muestra): da por correctos los items
// que el analista no corrigió.
export async function approveAuditSection(reviewId: string): Promise<AuditSectionApproveResult> {
  return request<AuditSectionApproveResult>(`/audit-code-reviews/${reviewId}/approve`, {
    method: "POST",
  });
}

export async function deleteAuditItem(itemId: string): Promise<AuditReviewResult> {
  return request<AuditReviewResult>(`/audit-items/${itemId}`, { method: "DELETE" });
}

export async function approveAudit(subprojectId: string): Promise<AuditApproveResult> {
  return request<AuditApproveResult>(`/subprojects/${subprojectId}/audit/approve`, { method: "POST" });
}

/* ── Reporte final (Fase 5) ── */

export async function getRoundReport(roundId: string): Promise<RoundReport> {
  return request<RoundReport>(`/rounds/${roundId}/report`);
}

export async function downloadCodebookExport(roundId: string, formats: string[]): Promise<void> {
  const token = getToken();
  const query = formats.length ? `?formats=${formats.join(",")}` : "";
  const res = await fetch(`${BASE}/rounds/${roundId}/report/export${query}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    if (res.status === 401) {
      localStorage.removeItem("verbatix:token");
      localStorage.removeItem("verbatix:user");
      window.location.href = "/login";
    }
    const text = await res.text();
    throw new ApiError(res.status, text);
  }
  const buffer = await res.arrayBuffer();
  const contentType = res.headers.get("Content-Type") ?? "application/zip";
  const blob = new Blob([buffer], { type: contentType });
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = disposition.match(/filename="?([^";\n]+)"?/);
  const filename = match?.[1] ?? "LC_export.zip";
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  setTimeout(() => URL.revokeObjectURL(url), 200);
}
