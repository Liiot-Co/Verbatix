import type {
  ColumnMap,
  ImportResult,
  LoginPayload,
  LoginResponse,
  Paginated,
  ProjectDetail,
  ProjectListItem,
  Round,
  RoundStatus,
  SignupPayload,
  SignupResponse,
  Studio,
  UploadedFile,
  UserProfile,
  Verbatim,
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

export async function getProjects(): Promise<Paginated<ProjectListItem>> {
  return request<Paginated<ProjectListItem>>("/projects");
}

export async function createProject(
  externalCode: string,
  name: string,
  clientName?: string
): Promise<{ id: string; external_code: string; name: string; client_name: string | null; created_at: string }> {
  return request("/projects", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ external_code: externalCode, name, client_name: clientName ?? null }),
  });
}

// TODO: backend has no GET /projects/{id} route yet — this 404s until one exists.
export async function getProject(projectId: string): Promise<ProjectDetail> {
  return request<ProjectDetail>(`/projects/${projectId}`);
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

// TODO: none of GET/POST /rounds/{id}/... below exist on the backend yet —
// file upload/import lands on a studio in the schema, not a round. Wiring
// these is the pipeline work called out separately, not a routing fix.

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
  page = 1,
  pageSize = 50,
  status?: string
): Promise<Paginated<Verbatim>> {
  const qs = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (status) qs.set("status", status);
  return request<Paginated<Verbatim>>(`/rounds/${roundId}/verbatims?${qs.toString()}`);
}
