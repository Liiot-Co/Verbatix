import type { Round, UploadResult, ResolveRequest, ResolveResult, Metrics, MarketStudy, Net, Code, SurveyItem } from "./types";

const BASE = "/api";

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, options);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function getRounds(): Promise<Round[]> {
  return request<Round[]>("/rounds");
}

export async function createRound(name: string, studyId?: number | null): Promise<Round> {
  return request<Round>("/rounds", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, study_id: studyId ?? null }),
  });
}

export async function uploadFile(
  file: File,
  answerColumn: string,
  roundId: number,
): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("answer_column", answerColumn);
  form.append("round_id", String(roundId));
  return request<UploadResult>("/upload", { method: "POST", body: form });
}

export async function resolveAnomaly(payload: ResolveRequest): Promise<ResolveResult> {
  return request<ResolveResult>("/resolve-anomaly", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function getMetrics(roundId: number): Promise<Metrics> {
  return request<Metrics>(`/metrics/${roundId}`);
}

export function exportUrl(roundId: number): string {
  return `${BASE}/export/${roundId}`;
}

// ── Studies / Netos / Codigos ────────────────────────────────────────

export async function getStudies(): Promise<MarketStudy[]> {
  return request<MarketStudy[]>("/studies");
}

export async function createStudy(name: string, client?: string): Promise<MarketStudy> {
  return request<MarketStudy>("/studies", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, client: client ?? null }),
  });
}

export async function importCodebook(studyId: number, fromStudyId: number): Promise<{ imported_nets: number; imported_codes: number }> {
  return request(`/studies/${studyId}/import-codebook`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ from_study_id: fromStudyId }),
  });
}

export async function getNets(studyId: number): Promise<Net[]> {
  return request<Net[]>(`/nets?study_id=${studyId}`);
}

export async function createNet(studyId: number, name: string): Promise<Net> {
  return request<Net>("/nets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ study_id: studyId, name }),
  });
}

export async function getCodes(studyId: number): Promise<Code[]> {
  return request<Code[]>(`/codes?study_id=${studyId}`);
}

export async function createCode(studyId: number, name: string, netId?: number | null, keywords?: string): Promise<Code> {
  return request<Code>("/codes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ study_id: studyId, name, net_id: netId ?? null, keywords: keywords ?? null }),
  });
}

export async function setResponseCodes(responseId: number, codeIds: number[]): Promise<unknown> {
  return request(`/responses/${responseId}/codes`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code_ids: codeIds }),
  });
}

// ── Historial ────────────────────────────────────────────────────────

export async function getRoundResponses(roundId: number, status?: string): Promise<SurveyItem[]> {
  const qs = status ? `?status=${status}` : "";
  return request<SurveyItem[]>(`/rounds/${roundId}/responses${qs}`);
}

export async function deleteRound(roundId: number): Promise<{ status: string }> {
  return request(`/rounds/${roundId}`, { method: "DELETE" });
}
