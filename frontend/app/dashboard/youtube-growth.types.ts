export type YouTubeGrowthTab = "overview" | "analyze" | "competitors" | "content-plan" | "recommendations";

export type YouTubeGrowthUiStatus =
  | "idle"
  | "loading"
  | "empty"
  | "not_connected"
  | "insufficient_permissions"
  | "quota_exceeded"
  | "captions_unavailable"
  | "comments_disabled"
  | "analytics_unavailable"
  | "partial"
  | "retry"
  | "success";

export type YouTubeConfidence = "low" | "medium" | "high";
export type YouTubeContentFormat = "long_video" | "short" | "live";
export type YouTubeContentGoal = "awareness" | "engagement" | "leads" | "sales";
export type YouTubeGrowthCheckpoint = "1h" | "6h" | "24h" | "72h" | "7d";

export interface YouTubeSource {
  title: string;
  url: string;
  external_id?: string | null;
  timestamp?: string | null;
  published_at?: string | null;
  channel_title?: string | null;
  kind?: string | null;
}

export interface YouTubeMetric {
  key?: string;
  label: string;
  value: string | number | null;
  comparison?: string | null;
  available?: boolean;
}

export interface YouTubeOpportunityComponent {
  key: "topic_demand" | "competition_gap" | "hook_strength" | "packaging" | "channel_fit" | "timing" | string;
  label: string;
  score: number;
  weight: number;
  explanation: string;
}

export interface YouTubeAnalysisResult {
  id: string | number;
  kind?: "video" | "channel" | "competitors";
  status?: string;
  title?: string;
  subject_url?: string;
  summary: string;
  facts?: string[];
  insights?: string[];
  limitations?: string[];
  metrics?: YouTubeMetric[];
  sources: YouTubeSource[];
  opportunity_score?: number | null;
  score_components?: YouTubeOpportunityComponent[];
  created_at?: string;
  partial?: boolean;
}

export interface YouTubeCompetitorResult {
  id: string | number;
  kind?: "competitors";
  status?: string;
  query?: string;
  summary: string;
  breakout_videos?: Array<{
    title: string;
    url: string;
    channel_title?: string;
    reason?: string;
    views_to_subscribers_ratio?: number | null;
  }>;
  patterns?: string[];
  content_gaps?: string[];
  facts?: string[];
  interpretations?: string[];
  limitations?: string[];
  sources: YouTubeSource[];
  created_at?: string;
  partial?: boolean;
}

export interface YouTubeContentPlanItem {
  record_id?: number;
  plan_id?: number;
  position?: number;
  approved?: boolean;
  updated_at?: string;
  publish_date: string;
  content_pillar: string;
  target_audience: string;
  topic: string;
  why_now: string;
  format: YouTubeContentFormat;
  goal: YouTubeContentGoal;
  estimated_duration: string;
  titles: string[];
  hooks: string[];
  thumbnail_briefs: string[];
  script_outline: string[];
  cta: string;
  description_draft: string;
  chapters: Array<string | { title?: string; timestamp?: string }>;
  shorts_ideas: string[];
  sources: YouTubeSource[];
  primary_kpi: string;
  opportunity_score: number;
  confidence: YouTubeConfidence;
  score_explanation: string;
  score_components?: YouTubeOpportunityComponent[];
  facts_to_verify?: string[];
}

export interface YouTubeContentPlan {
  id: string | number;
  status?: string;
  days: 7 | 30;
  niche?: string;
  language?: string;
  region?: string;
  items: YouTubeContentPlanItem[];
  limitations?: string[];
  sources?: YouTubeSource[];
  created_at?: string;
  disclaimer?: string;
}

export interface YouTubeGrowthRecommendation {
  id?: string;
  title: string;
  recommendation: string;
  reason?: string;
  period?: "1h" | "6h" | "24h" | "72h" | "7d" | string;
  confidence?: YouTubeConfidence;
  video_url?: string;
  sources?: YouTubeSource[];
}

export interface YouTubeGrowthSnapshot {
  id: string | number;
  video_id: string;
  checkpoint: YouTubeGrowthCheckpoint;
  status: "queued" | "running" | "completed" | "partial" | "failed";
  metrics: YouTubeMetric[];
  baseline: YouTubeMetric[];
  recommendations: YouTubeGrowthRecommendation[];
  limitations: string[];
  sources: YouTubeSource[];
  scheduled_for?: string | null;
  observed_at?: string | null;
  created_at?: string;
}

export interface YouTubeGrowthOverview {
  accounts?: Array<{
    id: number;
    channel_id: string;
    label?: string | null;
    connected: boolean;
    can_read: boolean;
    can_analyze_private_metrics: boolean;
    can_upload: boolean;
    url?: string;
  }>;
  channel?: {
    account_id?: number;
    id?: string;
    title?: string;
    url?: string;
    thumbnail_url?: string;
  } | null;
  metrics?: YouTubeMetric[];
  recent_analyses?: YouTubeAnalysisResult[];
  recent_plans?: YouTubeContentPlan[];
  recommendations?: YouTubeGrowthRecommendation[];
  limitations?: string[];
  analytics_available?: boolean;
  created_at?: string;
}

export interface YouTubeDelegateResponse {
  coordinator_task_id: number;
  child_tasks: Array<{ id: number; role: string; status: string }>;
  artifact_ids: number[];
  status: "queued";
  message: string;
}

export interface YouTubeGrowthApiEnvelope<T> {
  data?: T;
  result?: T;
  status?: string;
  warnings?: string[];
  limitations?: string[];
  partial?: boolean;
}

export interface AnalyzeVideoRequest {
  account_id?: number;
  url: string;
  language: string;
  region: string;
  include_comments: boolean;
  include_captions?: boolean;
  idempotency_key?: string;
}

export interface AnalyzeChannelRequest {
  account_id?: number;
  url: string;
  language: string;
  region: string;
  max_videos: number;
  idempotency_key?: string;
}

export interface AnalyzeCompetitorsRequest {
  query: string;
  language: string;
  region: string;
  limit: number;
  idempotency_key?: string;
}

export interface CreateContentPlanRequest {
  analysis_ids: number[];
  days: 7 | 30;
  niche: string;
  language: string;
  region: string;
  goal: YouTubeContentGoal;
  publishing_frequency: string;
  content_pillars: string[];
  target_audience?: string;
  idempotency_key?: string;
}

export interface CreateGrowthSnapshotRequest {
  account_id: number;
  video_id: string;
  checkpoint: YouTubeGrowthCheckpoint;
  baseline_video_count?: number;
  idempotency_key?: string;
}

export type UpdateContentPlanItemRequest = Partial<Pick<
  YouTubeContentPlanItem,
  | "publish_date"
  | "content_pillar"
  | "target_audience"
  | "topic"
  | "why_now"
  | "format"
  | "goal"
  | "estimated_duration"
  | "titles"
  | "hooks"
  | "thumbnail_briefs"
  | "script_outline"
  | "cta"
  | "description_draft"
  | "chapters"
  | "shorts_ideas"
  | "facts_to_verify"
  | "primary_kpi"
  | "confidence"
  | "approved"
>> & { sources?: string[] };
