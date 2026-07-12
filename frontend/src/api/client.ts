import type {
  ColumnMap,
  ImportResult,
  Paginated,
  ProjectDetail,
  ProjectListItem,
  Round,
  RoundStatus,
  Study,
  UploadedFile,
  Verbatim,
} from "./types";

const BASE = "/api/v1";

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, options);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

const jsonHeaders = { "Content-Type": "application/json" };

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

export async function getProject(projectId: string): Promise<ProjectDetail> {
  return request<ProjectDetail>(`/projects/${projectId}`);
}

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
  origin_mode: "from_scratch" | "homologated";
  source_round_id?: string | null | undefined;
  min_mentions_threshold: number;
  audit_percentage: number;
}

export async function createRound(studyId: string, input: CreateRoundInput): Promise<Round> {
  return request<Round>(`/studies/${studyId}/rounds`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

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
