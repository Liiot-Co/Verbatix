import type {
  AuditApproveResult,
  AuditReadiness,
  AuditCodeReview,
  AuditItemList,
  AuditPatchResult,
  AuditReviewDecision,
  AuditSectionApproveResult,
  AuditReviewResult,
  AuditSessionSummary,
  BulkResolveResult,
  ColumnMap,
  ImportResult,
  LoginPayload,
  LoginResponse,
  MentionGroupDetail,
  MentionGroupStatus,
  NewCodeInput,
  PreliminarySummary,
  ProcessResult,
  ProjectDetail,
  ProjectListItem,
  ResolutionQueue,
  ResolutionSummary,
  ResolveDecision,
  ResolveResult,
  Round,
  RoundCode,
  RoundReport,
  RoundStatus,
  SignupPayload,
  SignupResponse,
  UploadedFile,
  UserProfile,
  AdminUser,
  RoleCode,
  ProjectMember,
  VerbatimList,
  VerbatimSummary,
} from "./types";
import { readAuthToken, writeAuthToken } from "@/lib/tokenStorage";

const BASE = "/api/v1";
const AUTH_BASE = "/api/auth";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
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
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed.detail === "string") message = parsed.detail;
      else if (parsed.detail) message = JSON.stringify(parsed.detail);
    } catch {
      // not JSON — keep raw text
    }
    throw new ApiError(res.status, message);
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

export async function recoverAccount(payload: { email: string; recovery_code: string; password: string }): Promise<SignupResponse> {
  return authRequest<SignupResponse>("/recover", { method: "POST", body: JSON.stringify(payload) });
}

export async function getAdminUsers(status?: string, q?: string): Promise<AdminUser[]> {
  const params = new URLSearchParams();
  if (status) params.set("account_status", status);
  if (q) params.set("q", q);
  return request<AdminUser[]>(`/admin/users?${params}`);
}

export async function approveAndAssign(userId: string, roles: RoleCode[], projectIds: string[]): Promise<void> {
  await request(`/admin/users/${userId}/approve-and-assign`, {
    method: "POST", headers: jsonHeaders, body: JSON.stringify({ roles, project_ids: projectIds }),
  });
}

export async function setUserStatus(userId: string, accountStatus: "active" | "suspended"): Promise<void> {
  await request(`/admin/users/${userId}/status`, {
    method: "PATCH", headers: jsonHeaders, body: JSON.stringify({ account_status: accountStatus }),
  });
}

/* ── Projects ── */

// Bare array, no pagination envelope — that's what the backend actually returns.
export async function getProjects(): Promise<ProjectListItem[]> {
  return request<ProjectListItem[]>("/projects");
}

export async function createProject(
  externalCode: string,
  name: string
): Promise<{ id: string; external_code: string; name: string; created_at: string }> {
  return request("/projects", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ external_code: externalCode, name }),
  });
}

export async function getProject(projectId: string): Promise<ProjectDetail> {
  return request<ProjectDetail>(`/projects/${projectId}`);
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
}

export async function createRound(projectId: string, input: CreateRoundInput): Promise<Round> {
  return request<Round>(`/projects/${projectId}/rounds`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}


/* ── Rondas: archivos, import, proceso (Fase 1 + Fase 2) ── */

export async function getRound(roundId: string): Promise<RoundStatus> {
  return request<RoundStatus>(`/rounds/${roundId}`);
}

export async function uploadFile(roundId: string, file: File): Promise<UploadedFile> {
  const form = new FormData();
  form.append("file", file);
  return request<UploadedFile>(`/rounds/${roundId}/files`, { method: "POST", body: form });
}

export interface ImportSettings {
  codebookSheet?: string | undefined;
  codebookCodingType?: "brands" | "reasons" | undefined;
  // Capturados al soltar el archivo — solo se usan si esta importación crea un
  // subproyecto nuevo. No editables después (ver UpdateSubprojectInput).
  minMentionsThreshold?: number | undefined;
  auditPercentage?: number | undefined;
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
      min_mentions_threshold: settings.minMentionsThreshold ?? null,
      audit_percentage: settings.auditPercentage ?? null,
    }),
  });
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

export async function getPreliminary(roundId: string): Promise<PreliminarySummary> {
  return request<PreliminarySummary>(`/rounds/${roundId}/preliminary`);
}

/* ── Resolution Center (Fase 4) ── */

export async function getResolutionQueue(
  subprojectId: string,
  limit = 50,
  offset = 0,
  statuses?: MentionGroupStatus[]
): Promise<ResolutionQueue> {
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (statuses?.length) qs.set("statuses", statuses.join(","));
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

export async function downloadCodebookExport(roundId: string): Promise<void> {
  const token = getToken();
  const res = await fetch(`${BASE}/rounds/${roundId}/report/export`, {
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
