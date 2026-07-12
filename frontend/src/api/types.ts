export type CodingType = "brands" | "reasons";
export type OriginMode = "from_scratch" | "homologated";
export type CodingStatus = "pending" | "auto_coded" | "needs_review" | "manually_coded" | "unknown";

// Matches GET /projects/{id}/rounds[].studios[] — a lightweight progress
// summary, not the full Studio (that's a separate GET /studios/{id} call).
export interface StudioSummary {
  id: string;
  name: string;
  coding_type: CodingType;
  status: string;
  verbatims_total: number;
  auto_coded: number;
}

export interface RoundSummary {
  id: string;
  name: string;
  round_number: number;
  status: string;
  studios: StudioSummary[];
}

// GET /projects returns a bare array, no pagination envelope.
export interface ProjectListItem {
  id: string;
  external_code: string;
  name: string;
  rounds_count: number;
  created_at: string;
}

export interface ProjectDetail {
  id: string;
  external_code: string;
  name: string;
  rounds: RoundSummary[];
  created_at: string;
}

export interface Codebook {
  id: string;
  inherited_codes: number;
  inherited_aliases: number;
}

// Rounds belong directly to a project. Each round can hold multiple studios
// (typically one "brands" + one "reasons"), created separately below.
export interface Round {
  id: string;
  project_id: string;
  name: string;
  round_number: number;
  status: string;
}

// A studio is one coding stream (brands or reasons) within a round — it owns
// the codebook, imported files, and verbatims for that stream.
export interface Studio {
  id: string;
  round_id: string;
  name: string;
  coding_type: CodingType;
  survey_question: string | null;
  origin_mode: OriginMode;
  source_studio_id: string | null;
  min_mentions_threshold: number;
  audit_percentage: number;
  status: string;
  codebook: Codebook;
}

// GET /studios/{id} — the full studio row plus live counters.
export interface StudioCounters {
  verbatims_total: number;
  mention_groups: number;
  codes_total: number;
  aliases_total: number;
}

export interface StudioStatus extends Studio {
  counters: StudioCounters;
}

export interface DetectedSheet {
  name: string;
  rows: number;
  guessed_as: "verbatims" | "codebook" | "unknown";
  columns: string[];
}

export interface UploadedFile {
  file_id: string;
  original_filename: string;
  total_rows: number;
  detected_sheets: DetectedSheet[];
  status: string;
}

export interface ColumnMap {
  respondent_id?: string;
  question_key?: string;
  verbatim: string;
  input_code?: string;
}

// POST /studios/{id}/process
export interface ProcessResult {
  run_id: string;
  groups_classified: number;
  anomalies: number;
  total: number;
}

export interface ImportResult {
  imported: {
    verbatims: number;
    codes: number;
    aliases: number;
    skipped_rows: number;
  };
  // Queued as a background task right after import — the LLM pass can take
  // minutes, so the response doesn't wait for it. Poll GET /studios/{id} for
  // status: 'files_uploaded' (still processing) -> 'preliminary_ready' (done).
  processing: { status: "queued" };
  warnings: string[];
  studio_status: string;
}

// GET /studios/{id}/preliminary
export interface PreliminarySummary {
  summary: {
    auto_coded: number;
    pending_review: number;
    anomalies: number;
    resolved: number;
  };
}

// GET /studios/{id}/verbatims — manual code assignment/edit is still Fase 3;
// codes[] is read-only transparency into what the engine assigned and why.
export interface VerbatimCode {
  code_number: number;
  label: string;
  net: string | null;
  source: "engine_exact" | "engine_fuzzy" | "homologation" | "analyst_manual" | "audit_correction";
  confidence_score: number | null;
  matched_alias: string | null;
}

export interface Verbatim {
  id: string;
  respondent_external_id: string | null;
  question_key: string | null;
  original_text: string;
  normalized_text: string | null;
  coding_status: CodingStatus;
  mention_group_id: string | null;
  codes: VerbatimCode[];
}

export interface VerbatimList {
  total: number;
  items: Verbatim[];
}

export interface Paginated<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

export interface ApiErrorBody {
  error: { code: string; message: string; details: Record<string, unknown> };
}

/* ── Auth ── */

export interface LoginPayload {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token?: string;
  token_type: string;
  expires_in?: number;
  user: { id: string; email: string };
}

export interface SignupPayload {
  email: string;
  password: string;
}

export interface SignupResponse {
  id?: string;
  email?: string;
  access_token?: string;
  token_type?: string;
}

export interface UserProfile {
  id: string;
  email: string;
  name: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
}

/* ── Resolution Center (Fase 4) ── */

export type MentionGroupStatus = "auto_coded" | "below_threshold" | "anomaly" | "pending_review" | "resolved";

export interface StudioCode {
  id: string;
  code_number: number;
  label: string;
  net: string | null;
  is_system: boolean;
}

export interface CodeSuggestion {
  id: string;
  code_number: number;
  label: string;
}

export interface ResolutionQueueItem {
  id: string;
  normalized_text: string;
  sample_text: string | null;
  frequency_count: number;
  status: MentionGroupStatus;
  suggested_code: CodeSuggestion | null;
}

export interface ResolutionQueue {
  total: number;
  items: ResolutionQueueItem[];
}

export interface ResolutionSummary {
  pending: number;
  auto_coded: number;
  resolved: number;
  progress_pct: number;
  can_close: boolean;
}

export interface MentionGroupDetail {
  id: string;
  studio_id: string;
  normalized_text: string;
  sample_text: string | null;
  frequency_count: number;
  status: MentionGroupStatus;
  verbatims_count: number;
  samples: string[];
  suggested_code: CodeSuggestion | null;
}

export interface NewCodeInput {
  label: string;
  net_id?: string | null;
}

export interface ResolveDecision {
  action: "approve" | "discard";
  code_ids: string[];
  new_code?: NewCodeInput | null;
  add_alias?: boolean;
  expected_status?: MentionGroupStatus | null;
}

export interface ResolveResult {
  group_id: string;
  status: "resolved";
  already_resolved: boolean;
  codes_assigned: StudioCode[];
  verbatims_updated: number;
  new_code: { id: string; code_number: number; label: string; is_new: boolean } | null;
}

export interface BulkResolveResult {
  resolved: ResolveResult[];
  failed: { group_id: string; error: string }[];
}
