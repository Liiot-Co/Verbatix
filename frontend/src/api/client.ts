import type {
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
  SignupPayload,
  SignupResponse,
  Studio,
  StudioCode,
  StudioStatus,
  UploadedFile,
  UserProfile,
  VerbatimList,
} from "./types";

const BASE = "/api/v1";
const AUTH_BASE = "/api/auth";

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
    throw new Error(`API ${res.status}: ${text}`);
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

export async function deleteStudio(studioId: string): Promise<void> {
  await request<void>(`/studios/${studioId}`, { method: "DELETE" });
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

export interface CreateStudioInput {
  name: string;
  coding_type: "brands" | "reasons";
  survey_question?: string | undefined;
  origin_mode: "from_scratch" | "homologated";
  source_studio_id?: string | null | undefined;
  min_mentions_threshold: number;
  audit_percentage: number;
}

export async function createStudio(roundId: string, input: CreateStudioInput): Promise<Studio> {
  return request<Studio>(`/rounds/${roundId}/studios`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

/* ── Studios: files, import, process (Fase 1 + Fase 2) ── */

export async function getStudio(studioId: string): Promise<StudioStatus> {
  return request<StudioStatus>(`/studios/${studioId}`);
}

export async function uploadFile(studioId: string, file: File): Promise<UploadedFile> {
  const form = new FormData();
  form.append("file", file);
  return request<UploadedFile>(`/studios/${studioId}/files`, { method: "POST", body: form });
}

export async function importFile(
  studioId: string,
  fileId: string,
  verbatimsSheet: string,
  columnMap: ColumnMap,
  codebookSheet?: string
): Promise<ImportResult> {
  return request<ImportResult>(`/studios/${studioId}/files/${fileId}/import`, {
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
  studioId: string,
  limit = 100,
  offset = 0,
  status?: string
): Promise<VerbatimList> {
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (status) qs.set("status", status);
  return request<VerbatimList>(`/studios/${studioId}/verbatims?${qs.toString()}`);
}

export async function processStudio(studioId: string): Promise<ProcessResult> {
  return request<ProcessResult>(`/studios/${studioId}/process`, { method: "POST" });
}

export async function getPreliminary(studioId: string): Promise<PreliminarySummary> {
  return request<PreliminarySummary>(`/studios/${studioId}/preliminary`);
}

/* ── Resolution Center (Fase 4) ── */

export async function getResolutionQueue(
  studioId: string,
  limit = 50,
  offset = 0,
  statuses?: MentionGroupStatus[]
): Promise<ResolutionQueue> {
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (statuses?.length) qs.set("statuses", statuses.join(","));
  return request<ResolutionQueue>(`/studios/${studioId}/resolution/queue?${qs.toString()}`);
}

export async function getResolutionSummary(studioId: string): Promise<ResolutionSummary> {
  return request<ResolutionSummary>(`/studios/${studioId}/resolution/summary`);
}

export async function getStudioCodes(studioId: string, includeSystem = false): Promise<StudioCode[]> {
  const qs = new URLSearchParams({ include_system: String(includeSystem) });
  return request<StudioCode[]>(`/studios/${studioId}/codes?${qs.toString()}`);
}

export async function createStudioCode(studioId: string, input: NewCodeInput): Promise<StudioCode> {
  return request<StudioCode>(`/studios/${studioId}/codes`, {
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

export async function bulkResolve(
  studioId: string,
  groupIds: string[],
  decision: ResolveDecision
): Promise<BulkResolveResult> {
  return request<BulkResolveResult>(`/studios/${studioId}/resolution/bulk`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ group_ids: groupIds, decision }),
  });
}
