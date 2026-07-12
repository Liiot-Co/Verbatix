export type CodingType = "brands" | "reasons";
export type OriginMode = "from_scratch" | "homologated";
export type CodingStatus = "pending" | "auto_coded" | "needs_review" | "manually_coded" | "unknown";

export interface RoundProgress {
  coded: number;
  total: number;
  audit_reviewed: number;
  audit_total: number;
}

export interface RoundSummary {
  id: string;
  name: string;
  round_number: number;
  status: string;
  progress: RoundProgress;
}

export interface StudySummary {
  id: string;
  name: string;
  coding_type: CodingType;
  rounds: RoundSummary[];
}

export interface ProjectListItem {
  id: string;
  external_code: string;
  name: string;
  client_name: string | null;
  studies_count: number;
  last_study: StudySummary | null;
  updated_at: string;
}

export interface ProjectDetail {
  id: string;
  external_code: string;
  name: string;
  client_name: string | null;
  studies_count: number;
  studies: StudySummary[];
  created_at: string;
}

export interface Study {
  id: string;
  project_id: string;
  name: string;
  coding_type: CodingType;
  survey_question: string | null;
  rounds: RoundSummary[];
}

export interface Codebook {
  id: string;
  version: number;
  inherited_codes: number;
  inherited_aliases: number;
}

export interface Round {
  id: string;
  study_id: string;
  name: string;
  round_number: number;
  origin_mode: OriginMode;
  source_round_id: string | null;
  min_mentions_threshold: number;
  audit_percentage: number;
  status: string;
  codebook: Codebook;
}

export interface RoundCounters {
  verbatims_total: number;
  auto_coded: number;
  pending_review: number;
  codes_total: number;
  codes_new_this_round: number;
}

export interface RoundStatus {
  id: string;
  name: string;
  status: string;
  study_name: string;
  project_name: string;
  counters: RoundCounters;
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

export interface ImportResult {
  imported: {
    verbatims: number;
    codes: number;
    aliases: number;
    skipped_rows: number;
  };
  warnings: string[];
  round_status: string;
}

export interface VerbatimCodeRef {
  code_number: number;
  label: string;
}

export interface Verbatim {
  id: string;
  respondent_external_id: string | null;
  question_key: string | null;
  original_text: string;
  coding_status: CodingStatus;
  codes: VerbatimCodeRef[];
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
