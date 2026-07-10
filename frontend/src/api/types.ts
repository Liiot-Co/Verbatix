export type ItemStatus = "auto_approved" | "requires_human" | "generic" | "rejected" | "manual_resolved";

export interface Round {
  id: number;
  name: string;
  created_at: string;
  total?: number;
  auto_approved?: number;
  requires_human?: number;
}

export interface SurveyItem {
  id: number;
  original_text: string;
  extracted_term: string | null;
  suggested_brand: string | null;
  official_brand_id: number | null;
  confidence: number;
  status: ItemStatus;
}

export interface UploadResult {
  round_id: number;
  total: number;
  auto_approved: number;
  requires_human: number;
  generic: number;
  items: SurveyItem[];
}

export interface ResolveRequest {
  response_id: number;
  resolved_brand: string;
}

export interface ResolveResult {
  resolved: SurveyItem;
  cascade_resolved: SurveyItem[];
}

export interface BrandCount {
  brand: string;
  count: number;
}

export interface Metrics {
  total: number;
  auto_approved: number;
  requires_human: number;
  generic: number;
  manual_resolved: number;
  top_brands: BrandCount[];
}
