"use client";

import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Clock3,
  ExternalLink,
  FileText,
  Lightbulb,
  Link2,
  Loader2,
  Pencil,
  RefreshCw,
  Save,
  Search,
  Send,
  ShieldAlert,
  Sparkles,
  TrendingUp,
  Video,
  X,
} from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";

import { YouTubeGrowthApiError, youtubeGrowthApi } from "./youtube-growth.api";
import type {
  YouTubeAnalysisResult,
  YouTubeCompetitorResult,
  YouTubeContentGoal,
  YouTubeContentPlan,
  YouTubeContentPlanItem,
  YouTubeGrowthOverview,
  YouTubeGrowthCheckpoint,
  YouTubeGrowthRecommendation,
  YouTubeGrowthSnapshot,
  YouTubeGrowthTab,
  YouTubeGrowthUiStatus,
  YouTubeMetric,
  YouTubeOpportunityComponent,
  YouTubeSource,
  UpdateContentPlanItemRequest,
} from "./youtube-growth.types";
import styles from "./youtube-growth.module.css";

const SCORE_DISCLAIMER = "This score estimates content potential and does not guarantee a specific number of views.";

const tabs: Array<{ id: YouTubeGrowthTab; label: string; icon: typeof Video }> = [
  { id: "overview", label: "Overview", icon: BarChart3 },
  { id: "analyze", label: "Analyze video", icon: Video },
  { id: "competitors", label: "Competitors", icon: Search },
  { id: "content-plan", label: "Content plan", icon: FileText },
  { id: "recommendations", label: "Growth recommendations", icon: TrendingUp },
];

interface YouTubeGrowthPanelProps {
  connected: boolean;
  accountId?: number;
  connectionState?: string;
  channelLabel?: string;
  publishingEnabled: boolean;
  onConnect: () => void;
  onEnablePublishing: () => void;
  onManageConnection: () => void;
  onOpenTeam: (artifactId?: string | number) => void;
}

interface FeedbackState {
  status: YouTubeGrowthUiStatus;
  message: string;
  retry?: (() => void) | null;
}

const idleFeedback: FeedbackState = { status: "idle", message: "", retry: null };

function statusFromError(error: unknown): FeedbackState {
  if (error instanceof DOMException && error.name === "AbortError") return idleFeedback;
  if (error instanceof YouTubeGrowthApiError) {
    const code = error.code.toLowerCase();
    if (code.includes("scope") || code.includes("permission")) {
      return { status: "insufficient_permissions", message: error.message };
    }
    if (code.includes("quota") || error.status === 429) {
      return { status: "quota_exceeded", message: error.message };
    }
    if (code.includes("not_connected") || code.includes("connection_required")) {
      return { status: "not_connected", message: error.message };
    }
    return { status: error.retryable ? "retry" : "partial", message: error.message };
  }
  return {
    status: "retry",
    message: error instanceof Error ? error.message : "The YouTube Growth service did not respond.",
  };
}

function statusFromLimitations(items?: string[]): FeedbackState {
  const limitations = arrayOfStrings(items);
  if (!limitations.length) return { status: "success", message: "" };
  const combined = limitations.join(" ").toLowerCase();
  if (combined.includes("caption") || combined.includes("transcript")) {
    return { status: "captions_unavailable", message: limitations[0] };
  }
  if (combined.includes("comment") && (combined.includes("disabled") || combined.includes("unavailable"))) {
    return { status: "comments_disabled", message: limitations[0] };
  }
  if (combined.includes("analytics") || combined.includes("metric") || combined.includes("scope")) {
    return { status: "analytics_unavailable", message: limitations[0] };
  }
  return { status: "partial", message: limitations[0] };
}

function completedFeedback(items: string[] | undefined, message: string): FeedbackState {
  const feedback = statusFromLimitations(items);
  return feedback.status === "success" ? { status: "success", message } : feedback;
}

function safeDate(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}

function normalizedUrl(value?: string | null) {
  if (!value) return "";
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : "";
  } catch {
    return "";
  }
}

function youtubeVideoId(value?: string | null) {
  const candidate = String(value || "").trim();
  if (/^[A-Za-z0-9_-]{3,64}$/.test(candidate)) return candidate;
  try {
    const parsed = new URL(candidate);
    const hostname = parsed.hostname.toLowerCase().replace(/^www\./, "");
    let id = "";
    if (hostname === "youtu.be") id = parsed.pathname.split("/").filter(Boolean)[0] || "";
    if (hostname === "youtube.com" || hostname.endsWith(".youtube.com")) {
      id = parsed.searchParams.get("v") || parsed.pathname.match(/^\/(?:shorts|embed|live)\/([^/?#]+)/)?.[1] || "";
    }
    return /^[A-Za-z0-9_-]{3,64}$/.test(id) ? id : "";
  } catch {
    return "";
  }
}

function arrayOfStrings(value?: string[]) {
  return Array.isArray(value) ? value.filter((item) => typeof item === "string" && item.trim()) : [];
}

function freshIdempotencyKey(scope: string) {
  const suffix = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `yt-growth-${scope}-${suffix}`.slice(0, 120);
}

function sourceKey(source: YouTubeSource, index: number) {
  return `${source.url}-${source.timestamp || ""}-${index}`;
}

function Sources({ sources }: { sources?: YouTubeSource[] }) {
  const safeSources = (sources || []).filter((source) => normalizedUrl(source.url));
  if (!safeSources.length) return null;
  return (
    <section className={styles.sources} aria-label="Sources">
      <div className={styles.sectionTitle}>
        <Link2 size={15} />
        <strong>Sources</strong>
      </div>
      <div className={styles.sourceList}>
        {safeSources.map((source, index) => (
          <a href={normalizedUrl(source.url)} target="_blank" rel="noreferrer noopener" key={sourceKey(source, index)}>
            <span>
              <strong>{source.title || source.channel_title || "YouTube source"}</strong>
              <small>
                {[source.channel_title, source.timestamp, safeDate(source.published_at)].filter(Boolean).join(" · ") || "Open source"}
              </small>
            </span>
            <ExternalLink size={14} />
          </a>
        ))}
      </div>
    </section>
  );
}

function Metrics({ metrics }: { metrics?: YouTubeMetric[] }) {
  const available = (metrics || []).filter((metric) => metric.available !== false && metric.value !== null && metric.value !== undefined);
  if (!available.length) return null;
  return (
    <div className={styles.metricsGrid}>
      {available.map((metric, index) => (
        <article key={`${metric.key || metric.label}-${index}`}>
          <small>{metric.label}</small>
          <strong>{String(metric.value)}</strong>
          {metric.comparison ? <span>{metric.comparison}</span> : null}
        </article>
      ))}
    </div>
  );
}

function Limitations({ items }: { items?: string[] }) {
  const limitations = arrayOfStrings(items);
  if (!limitations.length) return null;
  return (
    <div className={styles.limitations}>
      <AlertTriangle size={16} />
      <div>
        <strong>Analysis limitations</strong>
        <ul>
          {limitations.map((item) => <li key={item}>{item}</li>)}
        </ul>
      </div>
    </div>
  );
}

function OpportunityScore({ score, components }: { score?: number | null; components?: YouTubeOpportunityComponent[] }) {
  if (score === null || score === undefined) return null;
  const normalized = Math.max(0, Math.min(100, Number(score) || 0));
  return (
    <section className={styles.scoreCard}>
      <div className={styles.scoreHead}>
        <div>
          <span>Growth Opportunity Score</span>
          <strong>{Math.round(normalized)}<small>/100</small></strong>
        </div>
        <div className={styles.scoreRing} style={{ "--score": `${normalized * 3.6}deg` } as React.CSSProperties} aria-hidden="true" />
      </div>
      {components?.length ? (
        <div className={styles.scoreComponents}>
          {components.map((component, index) => (
            <div key={`${component.key}-${index}`}>
              <span>
                <strong>{component.label}</strong>
                <small>{Math.round(component.weight * (component.weight <= 1 ? 100 : 1))}% weight</small>
              </span>
              <span>{Math.round(component.score)}/100</span>
              <p>{component.explanation}</p>
            </div>
          ))}
        </div>
      ) : null}
      <p className={styles.disclaimer}>{SCORE_DISCLAIMER}</p>
    </section>
  );
}

function Feedback({ feedback }: { feedback: FeedbackState }) {
  if (feedback.status === "idle") return null;
  if (feedback.status === "success") {
    return (
      <div className={`${styles.feedback} ${styles.feedback_success}`} role="status" aria-live="polite">
        <CheckCircle2 size={19} />
        <div>
          <strong>Completed</strong>
          <span>{feedback.message || "The request completed successfully."}</span>
        </div>
      </div>
    );
  }
  if (feedback.status === "loading") {
    return (
      <div className={`${styles.feedback} ${styles.loadingFeedback}`} role="status">
        <Loader2 className={styles.spin} size={18} />
        <div>
          <strong>Teamora agents are working</strong>
          <span>{feedback.message || "Collecting permitted YouTube data and validating the result..."}</span>
          <i><span /></i>
        </div>
      </div>
    );
  }
  const copy: Record<string, { title: string; icon: typeof AlertTriangle }> = {
    empty: { title: "Nothing here yet", icon: Lightbulb },
    not_connected: { title: "YouTube is not connected", icon: Video },
    insufficient_permissions: { title: "Additional YouTube permission is required", icon: ShieldAlert },
    quota_exceeded: { title: "YouTube API quota is temporarily unavailable", icon: Clock3 },
    captions_unavailable: { title: "Captions are unavailable", icon: AlertTriangle },
    comments_disabled: { title: "Comments are disabled", icon: AlertTriangle },
    analytics_unavailable: { title: "Channel analytics are unavailable", icon: BarChart3 },
    partial: { title: "Partial analysis", icon: AlertTriangle },
    retry: { title: "Request could not be completed", icon: RefreshCw },
  };
  const item = copy[feedback.status] || copy.retry;
  const Icon = item.icon;
  return (
    <div className={`${styles.feedback} ${styles[`feedback_${feedback.status}`] || ""}`} role="status">
      <Icon size={19} />
      <div>
        <strong>{item.title}</strong>
        <span>{feedback.message}</span>
      </div>
      {feedback.retry ? (
        <button type="button" onClick={feedback.retry}>
          <RefreshCw size={14} /> Retry
        </button>
      ) : null}
    </div>
  );
}

function EmptyState({ title, copy, action }: { title: string; copy: string; action?: ReactNode }) {
  return (
    <div className={styles.emptyState}>
      <span><Sparkles size={22} /></span>
      <strong>{title}</strong>
      <p>{copy}</p>
      {action}
    </div>
  );
}

function OverviewTab({ overview, onAnalyze }: { overview: YouTubeGrowthOverview | null; onAnalyze: () => void }) {
  if (!overview) {
    return <EmptyState title="Start with a real YouTube signal" copy="Analyze a video or competitor set. Teamora will keep sources and limitations attached to every conclusion." action={<button className={styles.primaryButton} type="button" onClick={onAnalyze}>Analyze a video</button>} />;
  }
  const recentAnalyses = overview.recent_analyses || [];
  const recentPlans = overview.recent_plans || [];
  return (
    <div className={styles.resultStack}>
      {overview.channel ? (
        <section className={styles.channelCard}>
          {overview.channel.thumbnail_url ? <img src={overview.channel.thumbnail_url} alt="" /> : <span><Video size={24} /></span>}
          <div>
            <small>Connected channel</small>
            <strong>{overview.channel.title || "YouTube channel"}</strong>
            {overview.channel.url ? <a href={normalizedUrl(overview.channel.url)} target="_blank" rel="noreferrer noopener">Open channel <ExternalLink size={13} /></a> : null}
          </div>
          {overview.created_at ? <time>{safeDate(overview.created_at)}</time> : null}
        </section>
      ) : null}
      <Metrics metrics={overview.metrics} />
      <div className={styles.overviewColumns}>
        <section className={styles.dataCard}>
          <div className={styles.sectionTitle}><Video size={15} /><strong>Recent analyses</strong></div>
          {recentAnalyses.length ? recentAnalyses.slice(0, 4).map((analysis) => (
            <article className={styles.compactResult} key={analysis.id}>
              <strong>{analysis.title || "YouTube analysis"}</strong>
              <p>{analysis.summary}</p>
              <small>{safeDate(analysis.created_at)}</small>
            </article>
          )) : <p className={styles.mutedCopy}>No saved analyses yet.</p>}
        </section>
        <section className={styles.dataCard}>
          <div className={styles.sectionTitle}><FileText size={15} /><strong>Content plans</strong></div>
          {recentPlans.length ? recentPlans.slice(0, 4).map((plan) => (
            <article className={styles.compactResult} key={plan.id}>
              <strong>{plan.days}-day content plan</strong>
              <p>{plan.items.length} validated ideas{plan.niche ? ` for ${plan.niche}` : ""}</p>
              <small>{safeDate(plan.created_at)}</small>
            </article>
          )) : <p className={styles.mutedCopy}>No saved plans yet.</p>}
        </section>
      </div>
      <Limitations items={overview.limitations} />
    </div>
  );
}

function AnalysisResult({ result }: { result: YouTubeAnalysisResult }) {
  return (
    <div className={styles.resultStack}>
      <section className={styles.resultHero}>
        <span><CheckCircle2 size={20} /></span>
        <div>
          <small>Validated analysis {result.created_at ? `· ${safeDate(result.created_at)}` : ""}</small>
          <h2>{result.title || "Video analysis"}</h2>
          <p>{result.summary}</p>
        </div>
      </section>
      <Metrics metrics={result.metrics} />
      <OpportunityScore score={result.opportunity_score} components={result.score_components} />
      <InsightColumns facts={result.facts} insights={result.insights} />
      <Limitations items={result.limitations} />
      <Sources sources={result.sources} />
    </div>
  );
}

function InsightColumns({ facts, insights }: { facts?: string[]; insights?: string[] }) {
  const factItems = arrayOfStrings(facts);
  const insightItems = arrayOfStrings(insights);
  if (!factItems.length && !insightItems.length) return null;
  return (
    <div className={styles.overviewColumns}>
      {factItems.length ? <BulletCard title="Observed facts" items={factItems} icon={<CheckCircle2 size={15} />} /> : null}
      {insightItems.length ? <BulletCard title="AI interpretation" items={insightItems} icon={<Sparkles size={15} />} /> : null}
    </div>
  );
}

function BulletCard({ title, items, icon }: { title: string; items: string[]; icon: ReactNode }) {
  return (
    <section className={styles.dataCard}>
      <div className={styles.sectionTitle}>{icon}<strong>{title}</strong></div>
      <ul className={styles.bulletList}>{items.map((item) => <li key={item}>{item}</li>)}</ul>
    </section>
  );
}

function CompetitorResult({ result }: { result: YouTubeCompetitorResult }) {
  return (
    <div className={styles.resultStack}>
      <section className={styles.resultHero}>
        <span><TrendingUp size={20} /></span>
        <div>
          <small>Competitor synthesis {result.created_at ? `· ${safeDate(result.created_at)}` : ""}</small>
          <h2>{result.query || "Competitive landscape"}</h2>
          <p>{result.summary}</p>
        </div>
      </section>
      {result.breakout_videos?.length ? (
        <section className={styles.dataCard}>
          <div className={styles.sectionTitle}><TrendingUp size={15} /><strong>Breakout videos</strong></div>
          <div className={styles.breakoutList}>
            {result.breakout_videos.map((video, index) => (
              <a key={`${video.url}-${index}`} href={normalizedUrl(video.url)} target="_blank" rel="noreferrer noopener">
                <span><strong>{video.title}</strong><small>{[video.channel_title, video.reason].filter(Boolean).join(" · ")}</small></span>
                <ExternalLink size={14} />
              </a>
            ))}
          </div>
        </section>
      ) : null}
      <div className={styles.overviewColumns}>
        {arrayOfStrings(result.patterns).length ? <BulletCard title="Repeated patterns" items={arrayOfStrings(result.patterns)} icon={<Search size={15} />} /> : null}
        {arrayOfStrings(result.content_gaps).length ? <BulletCard title="Content gaps" items={arrayOfStrings(result.content_gaps)} icon={<Lightbulb size={15} />} /> : null}
      </div>
      <InsightColumns facts={result.facts} insights={result.interpretations} />
      <Limitations items={result.limitations} />
      <Sources sources={result.sources} />
    </div>
  );
}

function editableItem(item: YouTubeContentPlanItem): YouTubeContentPlanItem {
  return {
    ...item,
    titles: [...item.titles],
    hooks: [...item.hooks],
    thumbnail_briefs: [...item.thumbnail_briefs],
    script_outline: [...item.script_outline],
    chapters: [...item.chapters],
    shorts_ideas: [...item.shorts_ideas],
    facts_to_verify: [...(item.facts_to_verify || [])],
    sources: [...item.sources],
  };
}

function inputLines(value: string) {
  return value.split("\n").map((line) => line.trim()).filter(Boolean);
}

function chapterLines(items: YouTubeContentPlanItem["chapters"]) {
  return items.map((item) => typeof item === "string" ? item : [item.timestamp, item.title].filter(Boolean).join(" "));
}

function planItemUpdate(item: YouTubeContentPlanItem): UpdateContentPlanItemRequest {
  return {
    publish_date: item.publish_date,
    content_pillar: item.content_pillar,
    target_audience: item.target_audience,
    topic: item.topic,
    why_now: item.why_now,
    format: item.format,
    goal: item.goal,
    estimated_duration: item.estimated_duration,
    titles: item.titles,
    hooks: item.hooks,
    thumbnail_briefs: item.thumbnail_briefs,
    script_outline: item.script_outline,
    cta: item.cta,
    description_draft: item.description_draft,
    chapters: chapterLines(item.chapters),
    shorts_ideas: item.shorts_ideas,
    facts_to_verify: item.facts_to_verify,
    primary_kpi: item.primary_kpi,
    confidence: item.confidence,
  };
}

interface PlanItemProps {
  item: YouTubeContentPlanItem;
  index: number;
  onUpdate: (itemId: number, update: UpdateContentPlanItemRequest) => Promise<YouTubeContentPlanItem>;
}

function PlanItem({ item, index, onUpdate }: PlanItemProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(() => editableItem(item));
  const [saving, setSaving] = useState(false);
  const [itemMessage, setItemMessage] = useState("");

  useEffect(() => {
    if (!editing) setDraft(editableItem(item));
  }, [editing, item]);

  async function saveChanges() {
    if (!item.record_id) return;
    setSaving(true);
    setItemMessage("");
    try {
      await onUpdate(item.record_id, planItemUpdate(draft));
      setEditing(false);
      setItemMessage("Changes saved and schema-validated.");
    } catch (error) {
      setItemMessage(error instanceof Error ? error.message : "The idea could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  async function toggleApproval() {
    if (!item.record_id) return;
    setSaving(true);
    setItemMessage("");
    try {
      await onUpdate(item.record_id, { approved: !item.approved });
      setItemMessage(item.approved ? "Idea approval removed." : "Idea approved for Teamora delegation. This does not publish it.");
    } catch (error) {
      setItemMessage(error instanceof Error ? error.message : "The approval could not be updated.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <details className={styles.planItem} open={index === 0}>
      <summary>
        <time>{safeDate(item.publish_date) || item.publish_date}</time>
        <span>
          <strong>{item.topic}</strong>
          <small>{item.content_pillar} · {item.format.replace("_", " ")} · {item.goal}{item.approved ? " · approved" : ""}</small>
        </span>
        <b>{Math.round(item.opportunity_score)}/100</b>
      </summary>
      <div className={styles.planBody}>
        <div className={styles.planActions}>
          <span className={item.approved ? styles.approvedBadge : styles.draftBadge}>
            {item.approved ? <CheckCircle2 size={13} /> : <Clock3 size={13} />}
            {item.approved ? "Approved idea" : "Draft idea"}
          </span>
          {item.record_id ? (
            <div>
              <button className={styles.secondaryButton} type="button" disabled={saving} onClick={() => { setDraft(editableItem(item)); setEditing((value) => !value); setItemMessage(""); }}>
                {editing ? <X size={14} /> : <Pencil size={14} />} {editing ? "Cancel" : "Edit"}
              </button>
              <button className={item.approved ? styles.secondaryButton : styles.primaryButton} type="button" disabled={saving || editing} onClick={() => void toggleApproval()}>
                <CheckCircle2 size={14} /> {item.approved ? "Remove approval" : "Approve idea"}
              </button>
            </div>
          ) : null}
        </div>
        {editing ? (
          <div className={styles.planEditor}>
            <div className={styles.inlineFields}>
              <label>Publish date<input type="date" value={draft.publish_date.slice(0, 10)} onChange={(event) => setDraft({ ...draft, publish_date: event.target.value })} /></label>
              <label>Content pillar<input value={draft.content_pillar} onChange={(event) => setDraft({ ...draft, content_pillar: event.target.value })} /></label>
            </div>
            <label>Topic<input value={draft.topic} onChange={(event) => setDraft({ ...draft, topic: event.target.value })} /></label>
            <label>Target audience<textarea value={draft.target_audience} onChange={(event) => setDraft({ ...draft, target_audience: event.target.value })} /></label>
            <label>Why now<textarea value={draft.why_now} onChange={(event) => setDraft({ ...draft, why_now: event.target.value })} /></label>
            <div className={styles.inlineFields}>
              <label>Format<select value={draft.format} onChange={(event) => setDraft({ ...draft, format: event.target.value as YouTubeContentPlanItem["format"] })}><option value="long_video">Long video</option><option value="short">Short</option><option value="live">Live</option></select></label>
              <label>Goal<select value={draft.goal} onChange={(event) => setDraft({ ...draft, goal: event.target.value as YouTubeContentGoal })}><option value="awareness">Awareness</option><option value="engagement">Engagement</option><option value="leads">Leads</option><option value="sales">Sales</option></select></label>
            </div>
            <div className={styles.inlineFields}>
              <label>Estimated duration<input value={draft.estimated_duration} onChange={(event) => setDraft({ ...draft, estimated_duration: event.target.value })} /></label>
              <label>Primary KPI<input value={draft.primary_kpi} onChange={(event) => setDraft({ ...draft, primary_kpi: event.target.value })} /></label>
            </div>
            <label>Title variants, one per line<textarea value={draft.titles.join("\n")} onChange={(event) => setDraft({ ...draft, titles: inputLines(event.target.value) })} /></label>
            <label>Opening hooks, one per line<textarea value={draft.hooks.join("\n")} onChange={(event) => setDraft({ ...draft, hooks: inputLines(event.target.value) })} /></label>
            <label>Thumbnail briefs, one per line<textarea value={draft.thumbnail_briefs.join("\n")} onChange={(event) => setDraft({ ...draft, thumbnail_briefs: inputLines(event.target.value) })} /></label>
            <label>Script outline, one section per line<textarea value={draft.script_outline.join("\n")} onChange={(event) => setDraft({ ...draft, script_outline: inputLines(event.target.value) })} /></label>
            <label>CTA<textarea value={draft.cta} onChange={(event) => setDraft({ ...draft, cta: event.target.value })} /></label>
            <label>Description draft<textarea value={draft.description_draft} onChange={(event) => setDraft({ ...draft, description_draft: event.target.value })} /></label>
            <label>Chapters, one per line<textarea value={chapterLines(draft.chapters).join("\n")} onChange={(event) => setDraft({ ...draft, chapters: inputLines(event.target.value) })} /></label>
            <label>Shorts ideas, one per line<textarea value={draft.shorts_ideas.join("\n")} onChange={(event) => setDraft({ ...draft, shorts_ideas: inputLines(event.target.value) })} /></label>
            <label>Facts to verify, one per line<textarea value={(draft.facts_to_verify || []).join("\n")} onChange={(event) => setDraft({ ...draft, facts_to_verify: inputLines(event.target.value) })} /></label>
            <div className={styles.editorFooter}>
              <span>The backend re-validates every edit. Score values cannot be edited directly.</span>
              <button className={styles.primaryButton} type="button" disabled={saving} onClick={() => void saveChanges()}><Save size={14} /> Save changes</button>
            </div>
          </div>
        ) : (
          <>
            <p>{item.why_now}</p>
            <div className={styles.planGrid}>
              <BulletCard title="Title variants" items={arrayOfStrings(item.titles)} icon={<FileText size={15} />} />
              <BulletCard title="Opening hooks" items={arrayOfStrings(item.hooks)} icon={<Sparkles size={15} />} />
              <BulletCard title="Thumbnail briefs" items={arrayOfStrings(item.thumbnail_briefs)} icon={<Lightbulb size={15} />} />
              <BulletCard title="Script outline" items={arrayOfStrings(item.script_outline)} icon={<FileText size={15} />} />
            </div>
            <div className={styles.planMeta}>
              <span><small>Audience</small><strong>{item.target_audience}</strong></span>
              <span><small>Duration</small><strong>{item.estimated_duration}</strong></span>
              <span><small>Primary KPI</small><strong>{item.primary_kpi}</strong></span>
              <span><small>Confidence</small><strong>{item.confidence}</strong></span>
            </div>
            <section className={styles.copyBlock}><strong>CTA</strong><p>{item.cta}</p></section>
            <section className={styles.copyBlock}><strong>Description draft</strong><p>{item.description_draft}</p></section>
            <div className={styles.planGrid}>
              {chapterLines(item.chapters).length ? <BulletCard title="Chapters" items={chapterLines(item.chapters)} icon={<Clock3 size={15} />} /> : null}
              {arrayOfStrings(item.shorts_ideas).length ? <BulletCard title="Shorts ideas" items={arrayOfStrings(item.shorts_ideas)} icon={<Video size={15} />} /> : null}
            </div>
            <OpportunityScore score={item.opportunity_score} components={item.score_components} />
            {item.score_explanation ? <p className={styles.scoreExplanation}>{item.score_explanation}</p> : null}
            {arrayOfStrings(item.facts_to_verify).length ? <BulletCard title="Facts to verify" items={arrayOfStrings(item.facts_to_verify)} icon={<ShieldAlert size={15} />} /> : null}
            <Sources sources={item.sources} />
          </>
        )}
        {itemMessage ? <p className={styles.itemMessage} role="status" aria-live="polite">{itemMessage}</p> : null}
      </div>
    </details>
  );
}

function PlanResult({ plan, onSendToTeam, onUpdateItem }: { plan: YouTubeContentPlan; onSendToTeam: (id: string | number) => void; onUpdateItem: PlanItemProps["onUpdate"] }) {
  const approvedCount = plan.items.filter((item) => item.approved).length;
  return (
    <div className={styles.resultStack}>
      <section className={styles.resultHero}>
        <span><FileText size={20} /></span>
        <div>
          <small>Schema-validated plan {plan.created_at ? `· ${safeDate(plan.created_at)}` : ""}</small>
          <h2>{plan.days}-day content plan</h2>
          <p>{plan.items.length} ideas based on available channel, trend, and competitor evidence.</p>
        </div>
        <button className={styles.primaryButton} type="button" disabled={!approvedCount} onClick={() => onSendToTeam(plan.id)}><Send size={15} /> Send approved ideas to team</button>
      </section>
      <p className={styles.approvalSummary}>{approvedCount} of {plan.items.length} ideas approved. Approval delegates an idea to Teamora; it never publishes to YouTube.</p>
      <p className={styles.disclaimer}>{SCORE_DISCLAIMER}</p>
      <div className={styles.planList}>{plan.items.map((item, index) => <PlanItem item={item} index={index} onUpdate={onUpdateItem} key={item.record_id || `${item.publish_date}-${item.topic}-${index}`} />)}</div>
      <Limitations items={plan.limitations} />
      <Sources sources={plan.sources} />
    </div>
  );
}

function Recommendations({ items }: { items: YouTubeGrowthRecommendation[] }) {
  if (!items.length) return <EmptyState title="No recommendations yet" copy="Recommendations appear after Teamora has real results to compare with this channel's own baseline." />;
  return (
    <div className={styles.recommendationList}>
      {items.map((item, index) => (
        <article key={item.id || `${item.title}-${index}`}>
          <span><TrendingUp size={18} /></span>
          <div>
            <small>{item.period ? `Checkpoint ${item.period}` : "Growth recommendation"}{item.confidence ? ` · ${item.confidence} confidence` : ""}</small>
            <h2>{item.title}</h2>
            <p>{item.recommendation}</p>
            {item.reason ? <em>{item.reason}</em> : null}
            <Sources sources={item.sources} />
          </div>
        </article>
      ))}
    </div>
  );
}

function SnapshotResult({ snapshot }: { snapshot: YouTubeGrowthSnapshot }) {
  return (
    <section className={styles.snapshotCard} aria-live="polite">
      <div className={styles.sectionTitle}>
        {snapshot.status === "completed" ? <CheckCircle2 size={16} /> : <Clock3 size={16} />}
        <strong>{snapshot.checkpoint} checkpoint · {snapshot.status}</strong>
      </div>
      <p>
        Video {snapshot.video_id}
        {snapshot.observed_at ? ` · observed ${safeDate(snapshot.observed_at)}` : snapshot.scheduled_for ? ` · scheduled ${safeDate(snapshot.scheduled_for)}` : ""}
      </p>
      <Metrics metrics={snapshot.metrics} />
      {snapshot.baseline.length ? (
        <details>
          <summary>Channel baseline used for comparison</summary>
          <Metrics metrics={snapshot.baseline} />
        </details>
      ) : null}
      <Limitations items={snapshot.limitations} />
      <Sources sources={snapshot.sources} />
    </section>
  );
}

export function YouTubeGrowthPanel({ connected, accountId, connectionState, channelLabel, publishingEnabled, onConnect, onEnablePublishing, onManageConnection, onOpenTeam }: YouTubeGrowthPanelProps) {
  const [activeTab, setActiveTab] = useState<YouTubeGrowthTab>("overview");
  const [feedback, setFeedback] = useState<FeedbackState>(idleFeedback);
  const [overview, setOverview] = useState<YouTubeGrowthOverview | null>(null);
  const [analysis, setAnalysis] = useState<YouTubeAnalysisResult | null>(null);
  const [channelAnalysis, setChannelAnalysis] = useState<YouTubeAnalysisResult | null>(null);
  const [competitors, setCompetitors] = useState<YouTubeCompetitorResult | null>(null);
  const [plan, setPlan] = useState<YouTubeContentPlan | null>(null);
  const [recommendations, setRecommendations] = useState<YouTubeGrowthRecommendation[]>([]);
  const [snapshot, setSnapshot] = useState<YouTubeGrowthSnapshot | null>(null);
  const [analysisMode, setAnalysisMode] = useState<"video" | "channel">("video");
  const [videoUrl, setVideoUrl] = useState("");
  const [channelUrl, setChannelUrl] = useState("");
  const [channelVideoLimit, setChannelVideoLimit] = useState(25);
  const [snapshotVideo, setSnapshotVideo] = useState("");
  const [snapshotCheckpoint, setSnapshotCheckpoint] = useState<YouTubeGrowthCheckpoint>("24h");
  const [competitorQuery, setCompetitorQuery] = useState("");
  const [competitorLimit, setCompetitorLimit] = useState(20);
  const [niche, setNiche] = useState("");
  const [targetAudience, setTargetAudience] = useState("");
  const [language, setLanguage] = useState("en");
  const [region, setRegion] = useState("US");
  const [goal, setGoal] = useState<YouTubeContentGoal>("awareness");
  const [planDays, setPlanDays] = useState<7 | 30>(7);
  const [publishingFrequency, setPublishingFrequency] = useState("3 per week");
  const [pillars, setPillars] = useState("");
  const [selectedAnalysisIds, setSelectedAnalysisIds] = useState<number[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<number | undefined>(accountId);
  const idempotencyKeys = useRef<Record<string, { fingerprint: string; key: string }>>({});

  const connectionNeedsAttention = ["expired", "reconnect_required", "error"].includes(String(connectionState || ""));
  const isBusy = feedback.status === "loading";
  const analysisOptions = useMemo(() => {
    const candidates = [...(overview?.recent_analyses || []), analysis, channelAnalysis, competitors];
    const seen = new Set<number>();
    return candidates.flatMap((item) => {
      if (!item || !["completed", "partial"].includes(String(item.status || ""))) return [];
      const id = Number(item.id);
      if (!Number.isInteger(id) || id <= 0 || seen.has(id)) return [];
      seen.add(id);
      const title = "title" in item && typeof item.title === "string" ? item.title : "";
      const query = "query" in item && typeof item.query === "string" ? item.query : "";
      return [{ id, label: title || query || item.summary || `Analysis ${id}`, kind: item.kind || ("query" in item ? "competitors" : "video") }];
    }).slice(0, 20);
  }, [analysis, channelAnalysis, competitors, overview?.recent_analyses]);
  const sourceAnalysisIds = useMemo(() => selectedAnalysisIds.filter((id) => analysisOptions.some((item) => item.id === id)), [analysisOptions, selectedAnalysisIds]);
  const accounts = overview?.accounts || [];
  const resolvedAccountId = selectedAccountId || accountId || accounts[0]?.id || overview?.channel?.account_id;
  const selectedAccount = accounts.find((item) => item.id === resolvedAccountId);
  const displayOverview = overview && selectedAccount ? {
    ...overview,
    channel: {
      account_id: selectedAccount.id,
      id: selectedAccount.channel_id,
      title: selectedAccount.label || selectedAccount.channel_id || "Connected YouTube channel",
      url: selectedAccount.url,
    },
  } : overview;

  function operationKey(scope: string, payload: unknown) {
    const fingerprint = JSON.stringify(payload);
    const existing = idempotencyKeys.current[scope];
    if (existing?.fingerprint === fingerprint) return existing.key;
    const key = freshIdempotencyKey(scope);
    idempotencyKeys.current[scope] = { fingerprint, key };
    return key;
  }

  function completeOperation(scope: string) {
    delete idempotencyKeys.current[scope];
  }

  function selectAnalysis(id: number, checked: boolean) {
    setSelectedAnalysisIds((current) => checked
      ? Array.from(new Set([...current, id])).slice(0, 20)
      : current.filter((candidate) => candidate !== id));
  }

  async function loadOverview(signal?: AbortSignal) {
    if (!connected) return;
    setFeedback({ status: "loading", message: "Loading channel baseline and recent Teamora artifacts..." });
    try {
      const result = await youtubeGrowthApi.getOverview(signal);
      setOverview(result);
      setSelectedAccountId((current) => {
        const available = result.accounts || [];
        if (current && available.some((item) => item.id === current)) return current;
        if (accountId && available.some((item) => item.id === accountId)) return accountId;
        return available[0]?.id || accountId;
      });
      setFeedback(completedFeedback(result.limitations, "Channel context and saved YouTube artifacts loaded."));
    } catch (error) {
      const next = statusFromError(error);
      if (next.status !== "idle") setFeedback({ ...next, retry: () => void loadOverview() });
    }
  }

  useEffect(() => {
    if (!connected) {
      setFeedback({ status: "not_connected", message: "Connect your YouTube channel through Teamora Connected Apps to use channel analytics and saved plans." });
      return;
    }
    const controller = new AbortController();
    void loadOverview(controller.signal);
    return () => controller.abort();
    // The connection identity is the only trigger; tab changes must not refetch the overview.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, channelLabel]);

  useEffect(() => {
    if (accountId) setSelectedAccountId(accountId);
  }, [accountId]);

  const connectionCopy = useMemo(() => {
    if (connectionNeedsAttention) return "Reconnect YouTube to restore the required permissions.";
    if (connected) return channelLabel || "YouTube connected";
    return "Connect YouTube to begin";
  }, [channelLabel, connected, connectionNeedsAttention]);

  async function submitVideo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const url = normalizedUrl(videoUrl);
    if (!url) {
      setFeedback({ status: "retry", message: "Enter a valid public YouTube video URL." });
      return;
    }
    setFeedback({ status: "loading", message: "Reading permitted metadata, captions, comments, and source links..." });
    try {
      const request = { account_id: resolvedAccountId, url, language, region, include_comments: true, include_captions: true };
      const result = await youtubeGrowthApi.analyzeVideo({ ...request, idempotency_key: operationKey("video-analysis", request) });
      setAnalysis(result);
      const resultId = Number(result.id);
      if (Number.isInteger(resultId) && resultId > 0) selectAnalysis(resultId, true);
      completeOperation("video-analysis");
      setFeedback(completedFeedback(result.limitations, "Video analysis completed and saved with its sources."));
    } catch (error) {
      const next = statusFromError(error);
      setFeedback({ ...next, retry: () => void submitVideo(new Event("submit") as unknown as FormEvent<HTMLFormElement>) });
    }
  }

  async function submitChannel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const url = normalizedUrl(channelUrl);
    if (!url) {
      setFeedback({ status: "retry", message: "Enter a valid public YouTube channel URL." });
      return;
    }
    setFeedback({ status: "loading", message: `Analyzing up to ${channelVideoLimit} permitted videos from this channel...` });
    try {
      const request = { account_id: resolvedAccountId, url, language, region, max_videos: channelVideoLimit };
      const result = await youtubeGrowthApi.analyzeChannel({ ...request, idempotency_key: operationKey("channel-analysis", request) });
      setChannelAnalysis(result);
      const resultId = Number(result.id);
      if (Number.isInteger(resultId) && resultId > 0) selectAnalysis(resultId, true);
      completeOperation("channel-analysis");
      setFeedback(completedFeedback(result.limitations, "Channel analysis completed and saved with its sources."));
    } catch (error) {
      const next = statusFromError(error);
      setFeedback({ ...next, retry: () => void submitChannel(new Event("submit") as unknown as FormEvent<HTMLFormElement>) });
    }
  }

  async function submitCompetitors(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!competitorQuery.trim()) {
      setFeedback({ status: "retry", message: "Enter a topic, niche, channel URL, or competitor name." });
      return;
    }
    setFeedback({ status: "loading", message: "Comparing permitted public videos and separating facts from AI interpretation..." });
    try {
      const request = { query: competitorQuery.trim(), language, region, limit: competitorLimit };
      const result = await youtubeGrowthApi.analyzeCompetitors({ ...request, idempotency_key: operationKey("competitor-analysis", request) });
      setCompetitors(result);
      const resultId = Number(result.id);
      if (Number.isInteger(resultId) && resultId > 0) selectAnalysis(resultId, true);
      completeOperation("competitor-analysis");
      setFeedback(completedFeedback(result.limitations, `Competitor analysis completed across up to ${competitorLimit} videos.`));
    } catch (error) {
      const next = statusFromError(error);
      setFeedback({ ...next, retry: () => void submitCompetitors(new Event("submit") as unknown as FormEvent<HTMLFormElement>) });
    }
  }

  async function submitPlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!niche.trim()) {
      setFeedback({ status: "retry", message: "Enter the channel niche before creating a content plan." });
      return;
    }
    if (!sourceAnalysisIds.length) {
      setFeedback({ status: "empty", message: "Complete a video, channel, or competitor analysis first so the content plan remains source-backed." });
      return;
    }
    setFeedback({ status: "loading", message: `Creating and validating a ${planDays}-day content plan...` });
    try {
      const request = {
        analysis_ids: sourceAnalysisIds,
        days: planDays,
        niche: niche.trim(),
        language,
        region,
        goal,
        publishing_frequency: publishingFrequency,
        target_audience: targetAudience.trim() || undefined,
        content_pillars: pillars.split(",").map((item) => item.trim()).filter(Boolean).length
          ? pillars.split(",").map((item) => item.trim()).filter(Boolean)
          : [niche.trim()],
      };
      const result = await youtubeGrowthApi.createContentPlan({ ...request, idempotency_key: operationKey("content-plan", request) });
      setPlan(result);
      completeOperation("content-plan");
      setFeedback(completedFeedback(result.limitations, `${planDays}-day plan created and schema-validated.`));
    } catch (error) {
      const next = statusFromError(error);
      setFeedback({ ...next, retry: () => void submitPlan(new Event("submit") as unknown as FormEvent<HTMLFormElement>) });
    }
  }

  async function loadRecommendations() {
    setFeedback({ status: "loading", message: "Comparing published results with this channel's own baseline..." });
    try {
      const videoId = youtubeVideoId(snapshotVideo);
      const result = await youtubeGrowthApi.getGrowthState(videoId || undefined);
      setRecommendations(result.recommendations);
      if (result.snapshots.length) {
        setSnapshot(result.snapshots.find((item) => item.checkpoint === snapshotCheckpoint) || result.snapshots[0]);
      }
      setFeedback({ status: "success", message: result.snapshots.length ? "Performance checkpoint refreshed from saved YouTube Analytics results." : "Growth recommendations refreshed." });
    } catch (error) {
      const next = statusFromError(error);
      setFeedback({ ...next, retry: () => void loadRecommendations() });
    }
  }

  async function submitSnapshot(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const videoId = youtubeVideoId(snapshotVideo);
    if (!videoId) {
      setFeedback({ status: "retry", message: "Enter a valid owned YouTube video URL or video ID." });
      return;
    }
    if (!resolvedAccountId) {
      setFeedback({ status: "insufficient_permissions", message: "Reconnect YouTube so Teamora can identify the channel account for private analytics." });
      return;
    }
    setFeedback({ status: "loading", message: `Creating the ${snapshotCheckpoint} performance checkpoint and comparing it with this channel's own baseline...` });
    try {
      const request = {
        account_id: resolvedAccountId,
        video_id: videoId,
        checkpoint: snapshotCheckpoint,
        baseline_video_count: 20,
      };
      const result = await youtubeGrowthApi.createGrowthSnapshot({ ...request, idempotency_key: operationKey("growth-snapshot", request) });
      setSnapshot(result);
      const growthState = await youtubeGrowthApi.getGrowthState(videoId);
      setRecommendations(growthState.recommendations);
      setSnapshot(growthState.snapshots.find((item) => item.checkpoint === snapshotCheckpoint) || result);
      completeOperation("growth-snapshot");
      if (result.status === "queued") {
        setFeedback({
          status: "partial",
          message: result.scheduled_for
            ? `The checkpoint is queued until ${safeDate(result.scheduled_for)}; no result was invented before metrics are available.`
            : "The checkpoint is queued until YouTube Analytics data becomes available.",
        });
      } else if (result.status === "failed") {
        setFeedback({ status: "retry", message: result.limitations[0] || "The growth checkpoint failed and can be retried.", retry: () => void submitSnapshot(new Event("submit") as unknown as FormEvent<HTMLFormElement>) });
      } else {
        setFeedback(completedFeedback(result.limitations, `${snapshotCheckpoint} checkpoint completed and compared with this channel's baseline.`));
      }
    } catch (error) {
      const next = statusFromError(error);
      setFeedback({ ...next, retry: () => void submitSnapshot(new Event("submit") as unknown as FormEvent<HTMLFormElement>) });
    }
  }

  async function sendPlanToTeam(artifactId: string | number) {
    setFeedback({ status: "loading", message: "Coordinator is creating delegated work for the YouTube Growth team..." });
    try {
      const request = { artifactId: Number(artifactId), approvedItemIds: plan?.items.filter((item) => item.approved).map((item) => item.record_id) || [] };
      const result = await youtubeGrowthApi.delegateContentPlan(artifactId, operationKey("delegate-plan", request));
      completeOperation("delegate-plan");
      setFeedback({ status: "success", message: result.message || "The plan was queued for the Teamora team." });
      onOpenTeam(artifactId);
    } catch (error) {
      const next = statusFromError(error);
      setFeedback({ ...next, retry: () => void sendPlanToTeam(artifactId) });
    }
  }

  async function updatePlanItem(itemId: number, update: UpdateContentPlanItemRequest) {
    if (!plan) throw new Error("The content plan is no longer available.");
    const updated = await youtubeGrowthApi.updateContentPlanItem(plan.id, itemId, update);
    setPlan((current) => current ? {
      ...current,
      items: current.items.map((item) => item.record_id === itemId ? updated : item),
    } : current);
    setOverview((current) => current ? {
      ...current,
      recent_plans: current.recent_plans?.map((candidate) => candidate.id === plan.id ? {
        ...candidate,
        items: candidate.items.map((item) => item.record_id === itemId ? updated : item),
      } : candidate),
    } : current);
    return updated;
  }

  function selectTab(tab: YouTubeGrowthTab) {
    setActiveTab(tab);
    if (!isBusy) setFeedback(idleFeedback);
    if (tab === "recommendations" && !snapshotVideo && youtubeVideoId(videoUrl)) setSnapshotVideo(videoUrl);
    if (tab === "recommendations" && connected && !recommendations.length) void loadRecommendations();
  }

  return (
    <section className={styles.panel} aria-label="YouTube Growth Agent" aria-busy={isBusy}>
      <header className={styles.header}>
        <div className={styles.heading}>
          <span className={styles.youtubeMark}><Video size={23} /></span>
          <div>
            <p>Teamora specialist</p>
            <h1>YouTube Growth Agent</h1>
            <span>Research, plan, analyze, and improve with real sources.</span>
          </div>
        </div>
        <div className={styles.headerActions}>
          {accounts.length > 1 ? (
            <label className={styles.channelPicker}>
              <span>Channel</span>
              <select value={resolvedAccountId || ""} onChange={(event) => setSelectedAccountId(Number(event.target.value) || undefined)} disabled={isBusy}>
                {accounts.map((account) => <option value={account.id} key={account.id}>{account.label || account.channel_id}</option>)}
              </select>
            </label>
          ) : null}
          {connected && !connectionNeedsAttention && !publishingEnabled ? (
            <button className={styles.publisherButton} type="button" onClick={onEnablePublishing}>
              <Send size={14} /> Enable approved publishing
            </button>
          ) : null}
          <button className={`${styles.connectionButton} ${connected && !connectionNeedsAttention ? styles.connected : ""}`} type="button" onClick={connected && !connectionNeedsAttention ? onManageConnection : onConnect}>
            {connected && !connectionNeedsAttention ? <CheckCircle2 size={15} /> : <Video size={15} />}
            <span>{connectionCopy}</span>
          </button>
        </div>
      </header>

      <nav className={styles.tabs} aria-label="YouTube Growth sections">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <button className={activeTab === tab.id ? styles.active : ""} type="button" key={tab.id} onClick={() => selectTab(tab.id)} aria-pressed={activeTab === tab.id}>
              <Icon size={16} /> {tab.label}
            </button>
          );
        })}
      </nav>

      <div className={styles.content}>
        {!connected ? (
          <div className={styles.connectionEmpty}>
            <span><Video size={30} /></span>
            <h2>Connect YouTube to activate the Growth Agent</h2>
            <p>Teamora uses the existing Connected Apps OAuth flow. Access tokens remain on the backend and publishing always requires your confirmation.</p>
            <div><button className={styles.primaryButton} type="button" onClick={onConnect}>Connect YouTube</button><button className={styles.secondaryButton} type="button" onClick={onManageConnection}>Open Connected Apps</button></div>
          </div>
        ) : (
          <>
            <Feedback feedback={feedback} />
            {activeTab === "overview" ? <OverviewTab overview={displayOverview} onAnalyze={() => selectTab("analyze")} /> : null}

            {activeTab === "analyze" ? (
              <div className={styles.workspaceGrid}>
                <form className={styles.controlCard} onSubmit={analysisMode === "video" ? submitVideo : submitChannel}>
                  <div className={styles.sectionTitle}><Video size={16} /><strong>{analysisMode === "video" ? "Analyze a video" : "Analyze a channel"}</strong></div>
                  <p>{analysisMode === "video" ? "Metadata, available captions, statistics, comments, sources, and limitations. Teamora does not claim to inspect frames unless you upload an owned file." : "Review permitted channel metadata and up to 50 recent videos through the official YouTube API, with source links and honest limitations."}</p>
                  <label>Analysis target<select value={analysisMode} onChange={(event) => setAnalysisMode(event.target.value === "channel" ? "channel" : "video")}><option value="video">Single video</option><option value="channel">YouTube channel</option></select></label>
                  {analysisMode === "video" ? (
                    <label>Video URL<input type="url" value={videoUrl} onChange={(event) => setVideoUrl(event.target.value)} placeholder="https://www.youtube.com/watch?v=..." required /></label>
                  ) : (
                    <>
                      <label>Channel URL<input type="url" value={channelUrl} onChange={(event) => setChannelUrl(event.target.value)} placeholder="https://www.youtube.com/@channel" required /></label>
                      <label>Videos to compare<select value={channelVideoLimit} onChange={(event) => setChannelVideoLimit(Math.max(1, Math.min(50, Number(event.target.value) || 25)))}><option value={10}>10 videos</option><option value={25}>25 videos</option><option value={50}>50 videos</option></select></label>
                    </>
                  )}
                  <div className={styles.inlineFields}>
                    <label>Language<input value={language} onChange={(event) => setLanguage(event.target.value)} maxLength={12} /></label>
                    <label>Region<input value={region} onChange={(event) => setRegion(event.target.value.toUpperCase())} maxLength={2} /></label>
                  </div>
                  <button className={styles.primaryButton} type="submit" disabled={isBusy}><Search size={15} /> Analyze {analysisMode}</button>
                </form>
                <div className={styles.results}>
                  {analysisMode === "video"
                    ? analysis ? <AnalysisResult result={analysis} /> : !isBusy ? <EmptyState title="No video analyzed yet" copy="Paste a YouTube URL to start a source-backed analysis." /> : null
                    : channelAnalysis ? <AnalysisResult result={channelAnalysis} /> : !isBusy ? <EmptyState title="No channel analyzed yet" copy="Paste a YouTube channel URL to compare its permitted public video signals." /> : null}
                </div>
              </div>
            ) : null}

            {activeTab === "competitors" ? (
              <div className={styles.workspaceGrid}>
                <form className={styles.controlCard} onSubmit={submitCompetitors}>
                  <div className={styles.sectionTitle}><TrendingUp size={16} /><strong>Competitor research</strong></div>
                  <p>Compare 10–50 relevant public videos and identify breakout patterns, recurring hooks, and content gaps.</p>
                  <label>Topic or competitor<input value={competitorQuery} onChange={(event) => setCompetitorQuery(event.target.value)} placeholder="AI automation for small business" required /></label>
                  <label>Videos to compare<select value={competitorLimit} onChange={(event) => setCompetitorLimit(Math.max(10, Math.min(50, Number(event.target.value) || 20)))}><option value={10}>10 videos</option><option value={20}>20 videos</option><option value={30}>30 videos</option><option value={50}>50 videos</option></select></label>
                  <div className={styles.inlineFields}>
                    <label>Language<input value={language} onChange={(event) => setLanguage(event.target.value)} maxLength={12} /></label>
                    <label>Region<input value={region} onChange={(event) => setRegion(event.target.value.toUpperCase())} maxLength={2} /></label>
                  </div>
                  <button className={styles.primaryButton} type="submit" disabled={isBusy}><Search size={15} /> Research competitors</button>
                </form>
                <div className={styles.results}>{competitors ? <CompetitorResult result={competitors} /> : !isBusy ? <EmptyState title="No competitor set yet" copy="Enter a topic or competitor to find evidence-backed patterns and gaps." /> : null}</div>
              </div>
            ) : null}

            {activeTab === "content-plan" ? (
              <div className={styles.workspaceGrid}>
                <form className={styles.controlCard} onSubmit={submitPlan}>
                  <div className={styles.sectionTitle}><FileText size={16} /><strong>Create content plan</strong></div>
                  <p>Generate validated ideas using your niche, audience context, available channel history, trends, and competitors.</p>
                  <label>Niche<input value={niche} onChange={(event) => setNiche(event.target.value)} placeholder="B2B AI automation" required /></label>
                  <label>Target audience<textarea value={targetAudience} onChange={(event) => setTargetAudience(event.target.value)} placeholder="Operations leaders at growing service businesses" /></label>
                  <label>Content pillars<input value={pillars} onChange={(event) => setPillars(event.target.value)} placeholder="Tutorials, case studies, founder stories" /></label>
                  <div className={styles.inlineFields}>
                    <label>Plan length<select value={planDays} onChange={(event) => setPlanDays(Number(event.target.value) === 30 ? 30 : 7)}><option value={7}>7 days</option><option value={30}>30 days</option></select></label>
                    <label>Publishing frequency<select value={publishingFrequency} onChange={(event) => setPublishingFrequency(event.target.value)}><option value="daily">Daily</option><option value="5 per week">5 per week</option><option value="3 per week">3 per week</option><option value="2 per week">2 per week</option><option value="weekly">Weekly</option></select></label>
                  </div>
                  <div className={styles.inlineFields}>
                    <label>Goal<select value={goal} onChange={(event) => setGoal(event.target.value as YouTubeContentGoal)}><option value="awareness">Awareness</option><option value="engagement">Engagement</option><option value="leads">Leads</option><option value="sales">Sales</option></select></label>
                    <label>Language<input value={language} onChange={(event) => setLanguage(event.target.value)} maxLength={12} /></label>
                  </div>
                  <label>Region<input value={region} onChange={(event) => setRegion(event.target.value.toUpperCase())} maxLength={2} /></label>
                  <fieldset className={styles.analysisSelector}>
                    <legend>Source analyses</legend>
                    {analysisOptions.length ? analysisOptions.map((item) => (
                      <label key={item.id}>
                        <input type="checkbox" checked={sourceAnalysisIds.includes(item.id)} onChange={(event) => selectAnalysis(item.id, event.target.checked)} />
                        <span><strong>{item.label}</strong><small>{item.kind} artifact #{item.id}</small></span>
                      </label>
                    )) : <p>Complete an analysis first. New results are selected automatically and can be changed here.</p>}
                  </fieldset>
                  <button className={styles.primaryButton} type="submit" disabled={isBusy}><Sparkles size={15} /> Create plan</button>
                  <p className={styles.sourceContext}>{sourceAnalysisIds.length ? `Uses ${sourceAnalysisIds.length} explicitly selected analysis artifact${sourceAnalysisIds.length === 1 ? "" : "s"}.` : "Select at least one completed analysis so every plan remains source-backed."}</p>
                  <p className={styles.formDisclaimer}>{SCORE_DISCLAIMER}</p>
                </form>
                <div className={styles.results}>{plan ? <PlanResult plan={plan} onSendToTeam={(artifactId) => void sendPlanToTeam(artifactId)} onUpdateItem={updatePlanItem} /> : !isBusy ? <EmptyState title="No content plan yet" copy="Choose 7 or 30 days, then let Teamora create a schema-validated plan." /> : null}</div>
              </div>
            ) : null}

            {activeTab === "recommendations" ? (
              <div className={styles.workspaceGrid}>
                <form className={styles.controlCard} onSubmit={submitSnapshot}>
                  <div className={styles.sectionTitle}><TrendingUp size={16} /><strong>Create performance checkpoint</strong></div>
                  <p>Only videos owned by the connected channel can use private analytics. Teamora compares each checkpoint with that channel&apos;s own comparable-video baseline.</p>
                  <label>Owned video URL or ID<input value={snapshotVideo} onChange={(event) => setSnapshotVideo(event.target.value)} placeholder="https://www.youtube.com/watch?v=..." required /></label>
                  <label>Checkpoint<select value={snapshotCheckpoint} onChange={(event) => setSnapshotCheckpoint(event.target.value as YouTubeGrowthCheckpoint)}><option value="1h">1 hour</option><option value="6h">6 hours</option><option value="24h">24 hours</option><option value="72h">72 hours</option><option value="7d">7 days</option></select></label>
                  <button className={styles.primaryButton} type="submit" disabled={isBusy}><BarChart3 size={15} /> Create checkpoint</button>
                  <p className={styles.sourceContext}>YouTube Analytics may expose only daily aggregates; unavailable early metrics remain explicitly unavailable.</p>
                </form>
                <div className={styles.results}>
                  <div className={styles.resultStack}>
                    <section className={styles.recommendationIntro}>
                      <div><p>Channel-specific baselines</p><h2>Growth recommendations</h2><span>Checks compare results after 1h, 6h, 24h, 72h, and 7d. Missing metrics are shown as unavailable, never invented.</span></div>
                      <button className={styles.secondaryButton} type="button" onClick={() => void loadRecommendations()} disabled={isBusy}><RefreshCw size={14} /> Refresh</button>
                    </section>
                    {snapshot ? <SnapshotResult snapshot={snapshot} /> : null}
                    <Recommendations items={recommendations} />
                  </div>
                </div>
              </div>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}
