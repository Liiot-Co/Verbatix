import type {
  AuditApproveResult,
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
  Study,
  UploadedFile,
  UserProfile,
  VerbatimList,
  VerbatimSummary,
} from "./types";

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
  try {
    return localStorage.getItem("verbatix:token");
  } catch {
    return null;
  }
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
      localStorage.removeItem("verbatix:token");
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
  const res = await fetch(`${AUTH_BASE}${url}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers as Record<string, string>),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
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
  return authRequest<UserProfile>("/me", { headers: { Authorization: `Bearer ${getToken()}` } });
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

export async function deleteProject(projectId: string): Promise<void> {
  await request<void>(`/projects/${projectId}`, { method: "DELETE" });
}

export async function deleteRound(roundId: string): Promise<void> {
  await request<void>(`/rounds/${roundId}`, { method: "DELETE" });
}

export async function deleteStudy(studyId: string): Promise<void> {
  await request<void>(`/studies/${studyId}`, { method: "DELETE" });
}

/* ── Estudio (Marcas/Razones, persistente) y Ronda (ola de datos) ── */

export interface CreateStudyInput {
  name: string;
  coding_type: "brands" | "reasons";
  survey_question?: string | undefined;
}

export async function createStudy(projectId: string, input: CreateStudyInput): Promise<Study> {
  return request<Study>(`/projects/${projectId}/studies`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export interface CreateRoundInput {
  name: string;
  round_number: number;
  min_mentions_threshold: number;
  audit_percentage: number;
  origin_mode: "from_scratch" | "homologated";
  source_round_id?: string | null | undefined;
}

export async function createRound(studyId: string, input: CreateRoundInput): Promise<Round> {
  return request<Round>(`/studies/${studyId}/rounds`, {
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

export async function importFile(
  roundId: string,
  fileId: string,
  verbatimsSheet: string,
  columnMap: ColumnMap,
  codebookSheet?: string
): Promise<ImportResult> {
  return request<ImportResult>(`/rounds/${roundId}/files/${fileId}/import`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({
      verbatims_sheet: verbatimsSheet,
      codebook_sheet: codebookSheet ?? null,
      column_map: columnMap,
    }),
  });
}

export async function getVerbatims(
  roundId: string,
  limit = 100,
  offset = 0,
  status?: string
): Promise<VerbatimList> {
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (status) qs.set("status", status);
  return request<VerbatimList>(`/rounds/${roundId}/verbatims?${qs.toString()}`);
}

export async function getVerbatimsSummary(
  roundId: string,
  view: "pending" | "coded"
): Promise<VerbatimSummary> {
  return request<VerbatimSummary>(`/rounds/${roundId}/verbatims/summary?view=${view}`);
}

export async function processRound(roundId: string): Promise<ProcessResult> {
  return request<ProcessResult>(`/rounds/${roundId}/process`, { method: "POST" });
}

export async function getPreliminary(roundId: string): Promise<PreliminarySummary> {
  return request<PreliminarySummary>(`/rounds/${roundId}/preliminary`);
}

/* ── Resolution Center (Fase 4) ── */

export async function getResolutionQueue(
  roundId: string,
  limit = 50,
  offset = 0,
  statuses?: MentionGroupStatus[]
): Promise<ResolutionQueue> {
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (statuses?.length) qs.set("statuses", statuses.join(","));
  return request<ResolutionQueue>(`/rounds/${roundId}/resolution/queue?${qs.toString()}`);
}

export async function getResolutionSummary(roundId: string): Promise<ResolutionSummary> {
  return request<ResolutionSummary>(`/rounds/${roundId}/resolution/summary`);
}

export async function getRoundCodes(roundId: string, includeSystem = false): Promise<RoundCode[]> {
  const qs = new URLSearchParams({ include_system: String(includeSystem) });
  return request<RoundCode[]>(`/rounds/${roundId}/codes?${qs.toString()}`);
}

export async function createRoundCode(roundId: string, input: NewCodeInput): Promise<RoundCode> {
  return request<RoundCode>(`/rounds/${roundId}/codes`, {
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
  roundId: string,
  groupIds: string[],
  decision: ResolveDecision
): Promise<BulkResolveResult> {
  return request<BulkResolveResult>(`/rounds/${roundId}/resolution/bulk`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ group_ids: groupIds, decision }),
  });
}

/* ── Auditoría (Fase 5) ── */

// Crea o reanuda (idempotente) la sesión; con resample=true re-muestrea una
// sesión desactualizada por un reproceso del motor (crea sesión nueva).
export async function createAuditSession(
  roundId: string,
  resample = false
): Promise<AuditSessionSummary> {
  return request<AuditSessionSummary>(`/rounds/${roundId}/audit/session`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ resample }),
  });
}

export async function getAuditSession(roundId: string): Promise<AuditSessionSummary> {
  return request<AuditSessionSummary>(`/rounds/${roundId}/audit/session`);
}

export async function getAuditCodes(roundId: string): Promise<AuditCodeReview[]> {
  return request<AuditCodeReview[]>(`/rounds/${roundId}/audit/codes`);
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

export async function approveAudit(roundId: string): Promise<AuditApproveResult> {
  return request<AuditApproveResult>(`/rounds/${roundId}/audit/approve`, { method: "POST" });
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
