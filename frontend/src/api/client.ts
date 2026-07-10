import type { Round, UploadResult, ResolveRequest, ResolveResult, Metrics } from "./types";

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

export async function createRound(name: string): Promise<Round> {
  return request<Round>("/rounds", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
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
