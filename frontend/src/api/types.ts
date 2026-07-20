export type CodingType = "brands" | "reasons";
export type OriginMode = "from_scratch" | "homologated";
export type CatalogOrigin = "scratch" | "inherited_round" | "imported_client_catalog";
export type CodingStatus = "pending" | "auto_coded" | "needs_review" | "manually_coded" | "unknown";

// REQ-07: elección de origen de catálogo por coding_type al crear una ronda.
export interface CatalogOriginSelection {
  origin: CatalogOrigin;
  source_subproject_id: string | null;
}

// GET /projects/{id}/codebook-sources — libros oficiales heredables del mismo
// tipo y cliente, para elegir como origin: "inherited_round".
export interface CodebookSource {
  source_subproject_id: string;
  round_id: string;
  codebook_id: string;
  version: number;
  project_id: string;
  project_name: string;
  round_name: string;
  round_number: number;
  codes: number;
  aliases: number;
  nets: number;
}

// POST /rounds/{id}/files/{file_id}/catalog-preview
export interface CatalogPreview {
  codes: number;
  aliases: number;
  nets: number;
  system_codes_overflow: boolean;
}

export type NotificationType = "project_assigned" | "ready_for_audit" | "audit_approved";

export interface Notification {
  id: string;
  type: NotificationType;
  title: string | null;
  body: string | null;
  related_entity_id: string | null;
  sender_id: string | null;
  sender_name: string | null;
  is_read: boolean;
  created_at: string;
  last_reminded_at: string | null;
  reminder_count: number;
}

export type NotificationPreview = Notification;

export interface NotificationStream {
  unread_count: number;
  signal: number;
  preview: NotificationPreview | null;
}

export interface NotificationList {
  items: Notification[];
  total: number;
  limit: number;
  offset: number;
}

// GET /projects/{id}: each persisted `project` is an Estudio in schema v8.
// A round contains its two coding subprojects (brands and reasons).
export interface RoundSummary {
  id: string;
  name: string;
  round_number: number;
  status: string;
  category_id?: string | null;
  subprojects: RoundSubprojectSummary[];
}

export interface RoundSubprojectSummary {
  id: string;
  coding_type: CodingType;
  verbatims_total: number;
  auto_coded: number;
}

// GET /projects returns a bare array, no pagination envelope.
export interface ProjectListItem {
  id: string;
  external_code: string;
  name: string;
  studies_count: number;
  rounds_count: number;
  created_at: string;
  assigned_users_count: number;
  assigned_users_preview: AssignedUserPreview[];
}

export interface AssignedUserPreview {
  id: string;
  name: string | null;
  email: string;
  initials: string;
  roles: RoleCode[];
}

export interface ProjectMember extends AssignedUserPreview {
  user_id: string;
  account_status: AccountStatus;
  assigned_at: string;
}

export interface ProjectDetail {
  id: string;
  external_code: string;
  name: string;
  proyecto_id: string | null;
  rounds: RoundSummary[];
  categories: { id: string; name: string }[];
  created_at: string;
}

// Una ronda es una ola de datos de un estudio: su propio Excel, verbatims,
// codebook y procesamiento — cuelga del estudio, no del proyecto.
export interface Round {
  id: string;
  project_id: string;
  name: string;
  round_number: number;
  min_mentions_threshold: number;
  audit_percentage: number;
  expected_max_mentions?: number | null;
  origin_mode: OriginMode;
  source_round_id: string | null;
  status: string;
  subprojects: RoundSubproject[];
}

export interface RoundSubproject {
  id: string;
  coding_type: CodingType;
  codebook_id: string | null;
  catalog_origin?: CatalogOrigin;
  status?: string;
  origin_mode?: OriginMode;
  source_subproject_id?: string | null;
  min_mentions_threshold?: number;
  audit_percentage?: number;
  single_code_per_response?: boolean;
  inherited_codes?: number;
  inherited_aliases?: number;
  inherited_nets?: number;
  counters?: RoundCounters;
  audit?: RoundAudit;
}

// GET /rounds/{id} — la ronda completa + contadores en vivo y contexto de navegación.
export interface RoundCounters {
  verbatims_total: number;
  mention_groups: number;
  codes_total: number;
  aliases_total: number;
}

export interface RoundNavContext {
  study_name: string;
  category_name: string | null;
  project_id: string;
  project_name: string;
  project_external_code: string | null;
}

// Bloque `audit` de GET /rounds/{id}: el estado que leen los badges y el
// dashboard. 'not_started' = ronda "sin auditar".
export interface RoundAudit {
  status: "not_started" | "in_progress" | "approved";
  reviewed_items: number;
  total_items: number;
  target_met: boolean;
}

export interface RoundStatus extends Round, RoundNavContext {
  counters: RoundCounters;
  audit: RoundAudit;
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
  file_type: string;
  // REQ-03: etiqueta sugerida de la carga (filename limpio) y aviso si el
  // mismo archivo (checksum) ya se subió en esta ronda — nunca se duplica en silencio.
  suggested_source_label: string;
  duplicate_of: {
    file_id: string;
    original_filename: string;
    source_label: string | null;
    status: string;
  } | null;
}

// Metadata por campo/columna para el wizard de selección de campos
// (preview-fields): sugerencia solo para .dau (guess_coding_type), nunca
// para Excel.
export interface FieldPreview {
  field: string;
  suggested_coding_type: CodingType | null;
  /** REQ-08: sugerencia de interruptor (false = multi / 1:N). null = sin señal. */
  suggested_single_code_per_response?: boolean | null;
  /** REQ-04: máximo de menciones detectadas por encuestado en el archivo. */
  detected_max_mentions?: number;
  reason: string | null;
  sample_values: string[];
}

export interface FieldSelection {
  field: string;
  included: boolean;
  coding_type: CodingType | null;
}

export interface ColumnMap {
  respondent_id?: string;
  question_key?: string;
  verbatim: string;
  input_code?: string;
}

// POST /rounds/{id}/process — queued as a background task; poll round status.
export interface ProcessResult {
  status: "queued";
  round_id: string;
}

export interface CodebookDraftGroup {
  id: string;
  text: string | null;
  normalized_text: string;
  frequency: number;
}

export interface CodebookDraftCode {
  id: string;
  code_number: number;
  label: string;
  net_name: string | null;
  definition: string | null;
  inclusion_criteria: string[];
  exclusion_criteria: string[];
  examples: string[];
  approval_status: "pending" | "approved" | "revoked";
  is_system: boolean;
  mentions: number;
  mention_groups: number;
  groups: CodebookDraftGroup[];
}

export interface CodebookDraft {
  id: string;
  subproject_id: string;
  round_id: string;
  coding_type: CodingType;
  origin: string;
  status: string;
  version: number;
  codes: CodebookDraftCode[];
}

export interface CodebookDraftDecision {
  code_id: string;
  decision: "approve" | "reject";
  label: string;
  net_name: string | null;
  definition: string | null;
  inclusion_criteria: string[];
  exclusion_criteria: string[];
  examples: string[];
}

export interface CodebookDraftApproval {
  codebook_id: string;
  round_id: string;
  status: "approved";
  approved_codes: number;
  rejected_codes: number;
  ready_to_process: boolean;
}

// REQ-03: un posible duplicado real (mismo realid en otra carga de la ronda),
// insertado y pendiente de decisión humana.
export interface DuplicateFlag {
  flag_id: string;
  status: "pending" | "approved_keep" | "approved_remove" | "edited" | "resolved";
  serial: string | null;
  realid: string | null;
  matches: { serial: string | null; source_label: string }[];
}

// Aviso informativo (no bloqueante): mismo Serial en dos cargas, personas distintas.
export interface SerialCollision {
  serial: string | null;
  new_realid: string | null;
  previous_realid: string | null;
  previous_source_label: string;
}

export interface LoadReviewState {
  duplicates: DuplicateFlag[];
  serial_collisions: SerialCollision[];
  pending_flags: number;
  requires_review: boolean;
}

export interface ImportResult {
  imported: {
    verbatims: number;
    codes: number;
    aliases: number;
    skipped_rows: number;
  };
  // Queued as a background task right after import — the LLM pass can take
  // minutes, so the response doesn't wait for it. Poll GET /rounds/{id} for
  // status: 'processing' (still working) -> 'preliminary_ready' (done).
  pending_questions: string[];
  processing: { status: "queued" | "blocked_on_classification" | "blocked_on_review" };
  warnings: string[];
  // REQ-03: presente cuando la ronda ya tenía otra carga validada.
  is_additional_load: boolean;
  review: { duplicates: DuplicateFlag[]; serial_collisions: SerialCollision[]; pending_flags: number };
  round_status: string;
}

// GET /rounds/{id}/loads — las cargas de verbatims de la ronda (REQ-03).
export interface RoundLoad {
  file_id: string;
  source_label: string;
  original_filename: string;
  file_type: string;
  status: string;
  respondents_count: number;
  verbatims_count: number;
  pending_flags: number;
  created_at: string | null;
}

export interface ResolveFlagResult {
  flag_id: string;
  status: DuplicateFlag["status"];
  already_resolved: boolean;
  removed_verbatims?: number;
  pending_flags: number;
  processing: { status: "queued" | "blocked_on_review" };
}

// GET /rounds/{id}/preliminary
export interface PreliminarySummary {
  summary: {
    auto_coded: number;
    pending_review: number;
    suggested: number;
    abstained: number;
    engine_errors: number;
    anomalies: number;
    resolved: number;
  };
}

// GET /rounds/{id}/verbatims — manual code assignment/edit is still Fase 3;
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
  // REQ-03: carga de origen; null = "Carga original / sin registrar".
  source_label: string | null;
  codes: VerbatimCode[];
}

export interface VerbatimList {
  total: number;
  items: Verbatim[];
}

// GET /rounds/{id}/verbatims/summary?view=pending|coded — one row per
// mention/código, never per verbatim. `code_number`/`label` are null for a
// pending row with no engine suggestion yet.
export interface VerbatimSummaryRow {
  code_id: string | null;
  code_number: number | null;
  label: string | null;
  content: string | null;
  frequency: number;
  percentage: number;
}

export interface VerbatimSummary {
  items: VerbatimSummaryRow[];
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
  name?: string;
}

export interface SignupResponse {
  access_token: string;
  token_type: string;
  recovery_code: string;
  user: { id: string; email: string };
}

export type RoleCode = "admin" | "codificador" | "supervisor";
export type AccountStatus = "pending" | "active" | "suspended";
export type Capability =
  | "users.manage" | "assignments.manage" | "projects.manage" | "rounds.manage"
  | "resolution.view" | "resolution.edit" | "audit.view" | "audit.edit"
  | "audit.approve" | "reports.view" | "reports.export";

export interface UserProfile {
  id: string;
  email: string;
  name: string | null;
  roles: RoleCode[];
  capabilities: Capability[];
  account_status: AccountStatus;
  presence_status: PresenceStatus;
  presence_changed_at: string | null;
  assignments_count: number;
  created_at: string;
}

export interface AdminUser extends UserProfile {
  assignments_count: number;
  project_ids: string[];
}

/* ── Resolution Center (Fase 4) ── */

export type MentionGroupStatus =
  | "auto_coded" | "below_threshold" | "anomaly" | "pending_review" | "resolved"
  | "suggested" | "garbage" | "engine_error" | "abstained" | "conflict";

export interface RoundCode {
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
  round_id: string;
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
  codes_assigned: RoundCode[];
  verbatims_updated: number;
  new_code: { id: string; code_number: number; label: string; is_new: boolean } | null;
  auto_resolved_groups: { id: string; normalized_text: string }[];
  similar_suggestions: {
    id: string;
    normalized_text: string;
    status: string;
    score: number;
  }[];
}

export interface BulkResolveResult {
  resolved: ResolveResult[];
  failed: { group_id: string; error: string }[];
}

/* ── Auditoría (Fase 5) ── */

export type AuditItemStatus = "pending" | "correct" | "reassigned";
export type AuditSessionStatus = "pending" | "in_progress" | "approved";
export type AuditCodeReviewStatus = "pending" | "approved" | "with_corrections";

export interface AuditReadiness {
  ready: boolean;
  pending: number;
  round_status: string | null;
  subprojects: Array<{
    id: string;
    coding_type: CodingType;
    total: number;
    pending: number;
    auto_coded: number;
    resolved: number;
    progress_pct: number;
    ready: boolean;
  }>;
}

// GET/POST /rounds/{id}/audit/session — resumen de la última sesión.
export interface AuditSessionSummary {
  id: string;
  round_id: string;
  processing_run_id: string | null;
  target_percentage: number;
  total_items: number;
  reviewed_items: number;
  target_met: boolean;
  status: AuditSessionStatus;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string | null;
  progress_pct: number;
  items_pending: number;
  items_correct: number;
  items_reassigned: number;
  // Hubo un run del motor posterior al muestreo: la sesión quedó desactualizada
  // y la UI ofrece re-muestrear (POST session con resample: true).
  is_stale: boolean;
}

// GET /rounds/{id}/audit/codes — la capa de agrupación por código de la muestra.
export interface AuditCodeReview {
  id: string;
  code: { id: string; code_number: number; label: string; net: string | null };
  items_count: number;
  reviewed_count: number;
  corrections_count: number;
  status: AuditCodeReviewStatus;
}

export interface AuditItemCode {
  code_id: string;
  code_number: number;
  label: string;
  source: VerbatimCode["source"];
}

// GET /audit-code-reviews/{id}/items — un verbatim muestreado dentro de un código.
export interface AuditItem {
  id: string;
  verbatim_id: string;
  original_text: string;
  normalized_text: string | null;
  coding_status: CodingStatus;
  codes_snapshot: AuditItemCode[];
  current_codes: AuditItemCode[];
  status: AuditItemStatus;
  comment: string | null;
  comments: AuditComment[];
  reviewed_at: string | null;
}

export interface AuditComment {
  id: string;
  author_id: string | null;
  author_name: string | null;
  author_email: string | null;
  roles: RoleCode[];
  content: string;
  created_at: string;
  updated_at: string;
}

export interface AuditItemList {
  total: number;
  items: AuditItem[];
}

// Solo correcciones por item — lo "correcto" se da al aprobar la SECCIÓN
// (approveAuditSection), no marcando verbatim por verbatim.
export interface AuditReviewDecision {
  action: "reassign" | "remove";
  code_ids?: string[];
  new_code?: NewCodeInput | null;
  comment?: string | null;
  expected_status?: AuditItemStatus | null;
}

export interface AuditReviewResult {
  item_id: string;
  status: AuditItemStatus;
  already_reviewed: boolean;
  new_code: { id: string; code_number: number; label: string; is_new: boolean } | null;
  summary: AuditSessionSummary;
}

export interface AuditPatchResult {
  item_id: string;
  status: AuditItemStatus;
  comment: string | null;
}

// POST /audit-code-reviews/{id}/approve — cierra una sección: los items sin
// corregir quedan 'correct' y el code review pasa a approved/with_corrections.
export interface AuditSectionApproveResult {
  review_id: string;
  status: AuditCodeReviewStatus;
  items_marked: number;
  already_approved: boolean;
  summary: AuditSessionSummary;
}

export type AuditApproveResult = AuditSessionSummary & { already_approved: boolean };

/* ── Reporte final (Fase 5) ── */

export interface ReportCodeStat {
  id: string;
  code_number: number;
  label: string;
  net: string | null;
  frequency: number;
  pct: number;
  samples: string[];
}

// GET /rounds/{id}/report
export interface RoundReport {
  verbatims_total: number;
  auto_coded: number;
  auto_coded_pct: number;
  manually_coded: number;
  manually_coded_pct: number;
  processed_at: string | null;
  codes: ReportCodeStat[];
}
import type { PresenceStatus } from "@/lib/presence";
