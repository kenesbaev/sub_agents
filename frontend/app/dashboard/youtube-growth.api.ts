import type {
  AnalyzeCompetitorsRequest,
  AnalyzeChannelRequest,
  AnalyzeVideoRequest,
  CreateContentPlanRequest,
  CreateGrowthSnapshotRequest,
  YouTubeAnalysisResult,
  YouTubeCompetitorResult,
  YouTubeContentPlan,
  YouTubeGrowthApiEnvelope,
  YouTubeDelegateResponse,
  YouTubeGrowthOverview,
  YouTubeGrowthRecommendation,
  YouTubeGrowthSnapshot,
  YouTubeContentPlanItem,
  UpdateContentPlanItemRequest,
} from "./youtube-growth.types";

// Browser requests stay on the frontend origin. Next.js proxies /api server-side.
const API_URL = "";

export class YouTubeGrowthApiError extends Error {
  status: number;
  code: string;
  retryable: boolean;

  constructor(message: string, status: number, code = "request_failed", retryable = false) {
    super(message);
    this.name = "YouTubeGrowthApiError";
    this.status = status;
    this.code = code;
    this.retryable = retryable;
  }
}

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function errorDetail(payload: unknown, fallback: string) {
  const root = asObject(payload);
  const detail = root.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const nested = asObject(detail);
    if (typeof nested.message === "string") return nested.message;
  }
  if (typeof root.message === "string") return root.message;
  if (typeof root.error === "string") return root.error;
  return fallback;
}

function errorCode(payload: unknown, status: number) {
  const root = asObject(payload);
  const detail = asObject(root.detail);
  const explicit = root.code ?? root.error_code ?? detail.code ?? detail.error_code;
  if (typeof explicit === "string" && explicit) return explicit.toLowerCase();
  if (status === 401) return "not_authenticated";
  if (status === 403) return "insufficient_permissions";
  if (status === 429) return "quota_exceeded";
  if (status >= 500) return "upstream_unavailable";
  return "request_failed";
}

function errorRetryable(payload: unknown, status: number) {
  const root = asObject(payload);
  const detail = asObject(root.detail);
  if (typeof detail.retryable === "boolean") return detail.retryable;
  if (typeof root.retryable === "boolean") return root.retryable;
  return status === 408 || status === 429 || status >= 500;
}

function unwrap<T>(payload: T | YouTubeGrowthApiEnvelope<T>): T {
  if (payload && typeof payload === "object") {
    const envelope = payload as YouTubeGrowthApiEnvelope<T>;
    if (envelope.data !== undefined) return envelope.data;
    if (envelope.result !== undefined) return envelope.result;
  }
  return payload as T;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const code = errorCode(payload, response.status);
    throw new YouTubeGrowthApiError(
      errorDetail(payload, `YouTube Growth request failed (HTTP ${response.status}).`),
      response.status,
      code,
      errorRetryable(payload, response.status),
    );
  }
  return unwrap(payload as T | YouTubeGrowthApiEnvelope<T>);
}

function humanizeKey(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function readableStrings(value: unknown, prefix = ""): string[] {
  if (value === null || value === undefined || value === "") return [];
  if (typeof value === "string") return [prefix ? `${humanizeKey(prefix)}: ${value}` : value];
  if (typeof value === "number" || typeof value === "boolean") return [prefix ? `${humanizeKey(prefix)}: ${String(value)}` : String(value)];
  if (Array.isArray(value)) {
    return value.flatMap((item) => {
      if (typeof item === "string") return [item];
      if (item && typeof item === "object") {
        const object = asObject(item);
        const title = object.title ?? object.topic ?? object.name ?? object.text ?? object.question;
        const detail = object.reason ?? object.summary ?? object.description ?? object.value;
        if (typeof title === "string") return [typeof detail === "string" ? `${title} — ${detail}` : title];
      }
      return readableStrings(item, prefix);
    });
  }
  return Object.entries(asObject(value)).flatMap(([key, item]) => readableStrings(item, key));
}

function timestampLabel(value: unknown) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60);
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function normalizeSource(value: unknown, index: number) {
  if (typeof value === "string") {
    return { title: `YouTube source ${index + 1}`, url: value };
  }
  const source = asObject(value);
  return {
    title: String(source.title || source.fact || source.source_type || `YouTube source ${index + 1}`),
    url: String(source.url || ""),
    external_id: typeof source.external_id === "string" ? source.external_id : null,
    timestamp: timestampLabel(source.timestamp_seconds),
    published_at: typeof source.published_at === "string" ? source.published_at : null,
    channel_title: typeof source.channel_title === "string" ? source.channel_title : null,
    kind: typeof source.source_type === "string" ? source.source_type : null,
  };
}

function normalizeSources(value: unknown) {
  return (Array.isArray(value) ? value : []).map(normalizeSource).filter((source) => source.url);
}

function normalizeMetrics(value: unknown) {
  if (Array.isArray(value)) return value;
  return Object.entries(asObject(value)).map(([key, raw]) => {
    const object = asObject(raw);
    const metricValue = Object.keys(object).length ? (object.value ?? object.current ?? object.total ?? raw) : raw;
    const displayValue = metricValue && typeof metricValue === "object" ? JSON.stringify(metricValue) : metricValue as string | number | null;
    return {
      key,
      label: humanizeKey(key),
      value: displayValue,
      comparison: typeof object.comparison === "string" ? object.comparison : null,
      available: object.available !== false,
    };
  });
}

const scoreMetadata: Record<string, { label: string; weight: number }> = {
  topic_demand: { label: "Topic demand", weight: 0.25 },
  competition_gap: { label: "Competition gap", weight: 0.2 },
  hook_strength: { label: "Hook strength", weight: 0.2 },
  title_thumbnail_packaging: { label: "Title and thumbnail packaging", weight: 0.15 },
  channel_fit: { label: "Channel fit", weight: 0.1 },
  timing_relevance: { label: "Timing and relevance", weight: 0.1 },
};

function normalizeScore(value: unknown) {
  const breakdown = asObject(value);
  const components = asObject(breakdown.components);
  return {
    score: typeof breakdown.total_score === "number" ? breakdown.total_score : null,
    explanation: typeof breakdown.explanation === "string" ? breakdown.explanation : "",
    components: Object.entries(components).map(([key, raw]) => {
      const component = asObject(raw);
      const metadata = scoreMetadata[key] || { label: humanizeKey(key), weight: 0 };
      return {
        key,
        label: metadata.label,
        score: Number(component.score || 0),
        weight: metadata.weight,
        explanation: String(component.explanation || "No explanation was returned."),
      };
    }),
  };
}

function normalizeAnalysis(payload: unknown): YouTubeAnalysisResult {
  const raw = asObject(payload);
  const score = normalizeScore(raw.score_components);
  return {
    id: typeof raw.id === "number" || typeof raw.id === "string" ? raw.id : "analysis",
    kind: raw.kind === "video" || raw.kind === "channel" || raw.kind === "competitors" ? raw.kind : undefined,
    status: typeof raw.status === "string" ? raw.status : undefined,
    title: typeof raw.title === "string" ? raw.title : undefined,
    subject_url: typeof raw.subject_url === "string" ? raw.subject_url : undefined,
    summary: String(raw.summary || "The analysis completed without a written summary."),
    facts: readableStrings(raw.facts),
    insights: readableStrings(raw.insights),
    limitations: readableStrings(raw.limitations),
    metrics: normalizeMetrics(raw.metrics),
    sources: normalizeSources(raw.sources),
    partial: Boolean(raw.partial),
    opportunity_score: typeof raw.opportunity_score === "number" ? raw.opportunity_score : score.score,
    score_components: score.components,
    created_at: typeof raw.created_at === "string" ? raw.created_at : undefined,
  };
}

function candidateObjects(value: unknown, keys: string[]) {
  const object = asObject(value);
  for (const key of keys) {
    if (Array.isArray(object[key])) return object[key] as unknown[];
  }
  return [];
}

function normalizeCompetitors(payload: unknown): YouTubeCompetitorResult {
  const raw = asObject(payload);
  const facts = asObject(raw.facts);
  const insights = asObject(raw.insights);
  const sources = normalizeSources(raw.sources);
  const breakoutIds = new Set(
    (Array.isArray(insights.breakout_video_ids) ? insights.breakout_video_ids : [])
      .map((value) => String(value || ""))
      .filter(Boolean),
  );
  const explicitBreakouts = [
    ...candidateObjects(facts, ["breakout_videos", "top_videos"]),
    ...candidateObjects(insights, ["breakout_videos"]),
  ];
  const sampledBreakouts = candidateObjects(facts, ["videos"]).filter((item) => {
    const video = asObject(item);
    return breakoutIds.has(String(video.video_id || video.id || ""));
  });
  const candidates = explicitBreakouts.length ? explicitBreakouts : sampledBreakouts;
  const breakout = candidates.map((item) => {
    const video = asObject(item);
    const videoId = String(video.video_id || video.id || "");
    const source = sources.find((item) => item.external_id === videoId);
    return {
      title: String(video.title || video.name || "YouTube video"),
      url: String(video.url || video.video_url || source?.url || (videoId ? `https://www.youtube.com/watch?v=${videoId}` : "")),
      channel_title: typeof video.channel_title === "string" ? video.channel_title : undefined,
      reason: typeof video.reason === "string" ? video.reason : undefined,
      views_to_subscribers_ratio: typeof video.views_to_subscribers_ratio === "number" ? video.views_to_subscribers_ratio : null,
    };
  }).filter((item) => item.url);
  const repeatedTopics = (Array.isArray(insights.repeated_topics) ? insights.repeated_topics : []).map((value) => {
    const signal = asObject(value);
    const term = String(signal.term || "Topic");
    const count = Number(signal.video_count || 0);
    return count > 0 ? `${term}: repeated in ${count} sampled videos` : term;
  });
  const titleFormats = (Array.isArray(insights.title_format_signals) ? insights.title_format_signals : []).map((value) => {
    const signal = asObject(value);
    return `${humanizeKey(String(signal.pattern || "title format"))}: ${Number(signal.video_count || 0)} sampled videos`;
  });
  const ctaSignals = (Array.isArray(insights.description_cta_signals) ? insights.description_cta_signals : []).map((value) => {
    const signal = asObject(value);
    return `${humanizeKey(String(signal.signal || "CTA"))}: ${Number(signal.video_count || 0)} descriptions`;
  });
  const contentGaps = (Array.isArray(insights.content_gaps) ? insights.content_gaps : []).map((value) => {
    const gap = asObject(value);
    const term = String(gap.term || "Content gap hypothesis");
    const interpretation = typeof gap.interpretation === "string" ? gap.interpretation : "";
    return interpretation ? `${term} — ${interpretation}` : term;
  });
  return {
    id: typeof raw.id === "number" || typeof raw.id === "string" ? raw.id : "competitors",
    kind: "competitors",
    status: typeof raw.status === "string" ? raw.status : undefined,
    query: typeof facts.query === "string" ? facts.query : typeof raw.query === "string" ? raw.query : undefined,
    summary: String(raw.summary || "Competitor analysis completed."),
    breakout_videos: breakout,
    patterns: [...repeatedTopics, ...titleFormats, ...ctaSignals],
    content_gaps: contentGaps.length ? contentGaps : readableStrings(insights.gaps),
    facts: readableStrings(raw.facts),
    interpretations: readableStrings(raw.insights),
    limitations: readableStrings(raw.limitations),
    sources,
    partial: Boolean(raw.partial),
    created_at: typeof raw.created_at === "string" ? raw.created_at : undefined,
  };
}

function normalizePlanItem(value: unknown, scoreValue: unknown, recordValue?: unknown): YouTubeContentPlanItem {
  const item = asObject(value);
  const record = asObject(recordValue);
  const score = normalizeScore(scoreValue);
  return {
    record_id: typeof record.id === "number" ? record.id : undefined,
    plan_id: typeof record.plan_id === "number" ? record.plan_id : undefined,
    position: typeof record.position === "number" ? record.position : undefined,
    approved: record.approved === true,
    updated_at: typeof record.updated_at === "string" ? record.updated_at : undefined,
    publish_date: String(item.publish_date || ""),
    content_pillar: String(item.content_pillar || ""),
    target_audience: String(item.target_audience || ""),
    topic: String(item.topic || "Untitled idea"),
    why_now: String(item.why_now || ""),
    format: item.format === "short" || item.format === "live" ? item.format : "long_video",
    goal: item.goal === "engagement" || item.goal === "leads" || item.goal === "sales" ? item.goal : "awareness",
    estimated_duration: String(item.estimated_duration || ""),
    titles: readableStrings(item.titles),
    hooks: readableStrings(item.hooks),
    thumbnail_briefs: readableStrings(item.thumbnail_briefs),
    script_outline: readableStrings(item.script_outline),
    cta: String(item.cta || ""),
    description_draft: String(item.description_draft || ""),
    chapters: readableStrings(item.chapters),
    shorts_ideas: readableStrings(item.shorts_ideas),
    sources: normalizeSources(item.sources),
    primary_kpi: String(item.primary_kpi || ""),
    opportunity_score: Number(item.opportunity_score ?? score.score ?? 0),
    confidence: item.confidence === "low" || item.confidence === "high" ? item.confidence : "medium",
    score_explanation: String(item.score_explanation || score.explanation || ""),
    score_components: score.components,
    facts_to_verify: readableStrings(item.facts_to_verify),
  };
}

function normalizePlanItemRecord(payload: unknown): YouTubeContentPlanItem {
  const record = asObject(payload);
  return normalizePlanItem(record.item, record.score_breakdown, record);
}

function normalizePlan(payload: unknown): YouTubeContentPlan {
  const raw = asObject(payload);
  const breakdowns = Array.isArray(raw.score_breakdowns) ? raw.score_breakdowns : [];
  const rawItems = Array.isArray(raw.items) ? raw.items : [];
  const itemRecords = Array.isArray(raw.item_records) ? raw.item_records : [];
  return {
    id: typeof raw.id === "number" || typeof raw.id === "string" ? raw.id : "plan",
    status: typeof raw.status === "string" ? raw.status : undefined,
    days: Number(raw.days) === 30 ? 30 : 7,
    items: itemRecords.length
      ? itemRecords.map(normalizePlanItemRecord)
      : rawItems.map((value, index) => normalizePlanItem(value, breakdowns[index])),
    limitations: readableStrings(raw.limitations),
    created_at: typeof raw.created_at === "string" ? raw.created_at : undefined,
    disclaimer: typeof raw.disclaimer === "string" ? raw.disclaimer : undefined,
  };
}

function normalizeOverview(payload: unknown): YouTubeGrowthOverview {
  const raw = asObject(payload);
  const accounts = Array.isArray(raw.accounts) ? raw.accounts.map(asObject) : [];
  const account = accounts[0];
  return {
    accounts: accounts.flatMap((item) => {
      if (typeof item.id !== "number") return [];
      const channelId = String(item.channel_id || "");
      return [{
        id: item.id,
        channel_id: channelId,
        label: typeof item.label === "string" ? item.label : null,
        connected: item.connected === true,
        can_read: item.can_read === true,
        can_analyze_private_metrics: item.can_analyze_private_metrics === true,
        can_upload: item.can_upload === true,
        url: channelId ? `https://www.youtube.com/channel/${channelId}` : undefined,
      }];
    }),
    channel: account ? {
      account_id: typeof account.id === "number" ? account.id : undefined,
      id: String(account.channel_id || account.id || ""),
      title: String(account.label || account.channel_id || "Connected YouTube channel"),
      url: account.channel_id ? `https://www.youtube.com/channel/${String(account.channel_id)}` : undefined,
    } : null,
    recent_analyses: (Array.isArray(raw.recent_analyses) ? raw.recent_analyses : []).map(normalizeAnalysis),
    recent_plans: (Array.isArray(raw.recent_plans) ? raw.recent_plans : []).map(normalizePlan),
    limitations: readableStrings(raw.missing_permissions),
    analytics_available: accounts.some((item) => item.can_analyze_private_metrics === true),
  };
}

function normalizeSnapshot(payload: unknown): YouTubeGrowthSnapshot {
  const raw = asObject(payload);
  const checkpoint = ["1h", "6h", "24h", "72h", "7d"].includes(String(raw.checkpoint))
    ? String(raw.checkpoint) as YouTubeGrowthSnapshot["checkpoint"]
    : "24h";
  const status = ["queued", "running", "completed", "partial", "failed"].includes(String(raw.status))
    ? String(raw.status) as YouTubeGrowthSnapshot["status"]
    : "partial";
  return {
    id: typeof raw.id === "number" || typeof raw.id === "string" ? raw.id : "snapshot",
    video_id: String(raw.video_id || ""),
    checkpoint,
    status,
    metrics: normalizeMetrics(raw.metrics),
    baseline: normalizeMetrics(raw.baseline),
    recommendations: normalizeRecommendations([raw]),
    limitations: readableStrings(raw.limitations),
    sources: normalizeSources(raw.sources),
    scheduled_for: typeof raw.scheduled_for === "string" ? raw.scheduled_for : null,
    observed_at: typeof raw.observed_at === "string" ? raw.observed_at : null,
    created_at: typeof raw.created_at === "string" ? raw.created_at : undefined,
  };
}

function normalizeRecommendations(payload: unknown): YouTubeGrowthRecommendation[] {
  const rows = Array.isArray(payload) ? payload : Array.isArray(asObject(payload).items) ? asObject(payload).items as unknown[] : [];
  return rows.flatMap((row, rowIndex) => {
    if (typeof row === "string") return [{ title: "Growth recommendation", recommendation: row }];
    const snapshot = asObject(row);
    const recommendations = Array.isArray(snapshot.recommendations) ? snapshot.recommendations : [snapshot];
    return recommendations.flatMap((item, itemIndex) => {
      if (typeof item === "string") {
        return [{
          id: `${String(snapshot.id || rowIndex)}-${itemIndex}`,
          title: `Recommendation after ${String(snapshot.checkpoint || "latest check")}`,
          recommendation: item,
          period: typeof snapshot.checkpoint === "string" ? snapshot.checkpoint : undefined,
          reason: readableStrings(snapshot.limitations).join(" ") || undefined,
        }];
      }
      const recommendation = asObject(item);
      if (!recommendation.recommendation && !recommendation.title) return [];
      return [{
        id: String(recommendation.id || `${rowIndex}-${itemIndex}`),
        title: String(recommendation.title || "Growth recommendation"),
        recommendation: String(recommendation.recommendation || recommendation.text || ""),
        reason: typeof recommendation.reason === "string" ? recommendation.reason : undefined,
        period: typeof recommendation.period === "string" ? recommendation.period : typeof snapshot.checkpoint === "string" ? snapshot.checkpoint : undefined,
        confidence: recommendation.confidence === "low" || recommendation.confidence === "high" ? recommendation.confidence : undefined,
        video_url: typeof recommendation.video_url === "string" ? recommendation.video_url : undefined,
        sources: normalizeSources(recommendation.sources),
      }];
    });
  });
}

export const youtubeGrowthApi = {
  getOverview(signal?: AbortSignal) {
    return request<unknown>("/api/youtube-growth/overview", { signal }).then(normalizeOverview);
  },

  analyzeVideo(input: AnalyzeVideoRequest, signal?: AbortSignal) {
    return request<unknown>("/api/youtube-growth/analyze/video", {
      method: "POST",
      body: JSON.stringify(input),
      signal,
    }).then(normalizeAnalysis);
  },

  analyzeChannel(input: AnalyzeChannelRequest, signal?: AbortSignal) {
    return request<unknown>("/api/youtube-growth/analyze/channel", {
      method: "POST",
      body: JSON.stringify(input),
      signal,
    }).then(normalizeAnalysis);
  },

  analyzeCompetitors(input: AnalyzeCompetitorsRequest, signal?: AbortSignal) {
    return request<unknown>("/api/youtube-growth/analyze/competitors", {
      method: "POST",
      body: JSON.stringify(input),
      signal,
    }).then(normalizeCompetitors);
  },

  createContentPlan(input: CreateContentPlanRequest, signal?: AbortSignal) {
    return request<unknown>("/api/youtube-growth/content-plans", {
      method: "POST",
      body: JSON.stringify(input),
      signal,
    }).then(normalizePlan);
  },

  updateContentPlanItem(planId: string | number, itemId: number, input: UpdateContentPlanItemRequest, signal?: AbortSignal) {
    return request<unknown>(`/api/youtube-growth/content-plans/${Number(planId)}/items/${itemId}`, {
      method: "PATCH",
      body: JSON.stringify(input),
      signal,
    }).then(normalizePlanItemRecord);
  },

  createGrowthSnapshot(input: CreateGrowthSnapshotRequest, signal?: AbortSignal) {
    return request<unknown>("/api/youtube-growth/growth-snapshots", {
      method: "POST",
      body: JSON.stringify(input),
      signal,
    }).then(normalizeSnapshot);
  },

  getRecommendations(signal?: AbortSignal) {
    return request<unknown>("/api/youtube-growth/recommendations", { signal }).then(normalizeRecommendations);
  },

  getGrowthState(videoId?: string, signal?: AbortSignal) {
    const query = videoId ? `?video_id=${encodeURIComponent(videoId)}` : "";
    return request<unknown>(`/api/youtube-growth/recommendations${query}`, { signal }).then((payload) => {
      const rows = Array.isArray(payload) ? payload : [];
      return {
        snapshots: rows.map(normalizeSnapshot),
        recommendations: normalizeRecommendations(rows),
      };
    });
  },

  delegateContentPlan(artifactId: string | number, idempotencyKey?: string, signal?: AbortSignal) {
    return request<YouTubeDelegateResponse>("/api/youtube-growth/delegate", {
      method: "POST",
      body: JSON.stringify({
        action: "create_content_plan",
        input: { source: "youtube_growth_dashboard" },
        artifact_ids: [Number(artifactId)],
        ...(idempotencyKey ? { idempotency_key: idempotencyKey } : {}),
      }),
      signal,
    });
  },
};
