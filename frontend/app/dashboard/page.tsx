"use client";

import Image from "next/image";
import Link from "next/link";
import {
  Activity,
  ArrowLeft,
  Bell,
  Bot,
  BriefcaseBusiness,
  Check,
  ChevronDown,
  Clock,
  CreditCard,
  Database,
  Eye,
  LifeBuoy,
  ListTodo,
  Loader2,
  LogOut,
  Mail,
  MessageCircle,
  Moon,
  MoreVertical,
  Grid3X3,
  List,
  PanelLeftClose,
  PanelLeftOpen,
  Paperclip,
  Pencil,
  Plug,
  Plus,
  Rocket,
  Search,
  Send,
  Settings,
  Share2,
  Sun,
  Trash2,
  Video,
  X,
  User,
  UsersRound
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { type CSSProperties, FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { YouTubeGrowthPanel } from "./youtube-growth-panel";

// Browser requests stay on the frontend origin. Next.js proxies /api server-side.
const API_URL = "";

type View = "office" | "youtube-growth" | "tasks" | "activity" | "my-teams" | "shared" | "settings" | "support";
type TaskStatus = "Queued" | "Working" | "Done";
type SettingsTab = "profile" | "general" | "billing" | "notifications" | "memory" | "connected" | "writing" | "completion" | "developer";
type TeamTab = "history" | "ready" | "mine";
type TeamViewMode = "grid" | "list";
type ThemeMode = "light" | "dark" | "auto";
type ResolvedTheme = "light" | "dark";
type ConnectedAppsFilter = "all" | "connected" | "not_connected";

interface UserData {
  id: number;
  email: string;
  first_name: string | null;
  last_name: string | null;
  avatar_url: string | null;
  google_connected: boolean;
}

interface IntegrationsData {
  telegram_bot: {
    connected: boolean;
    target_chat_id: string | null;
    bot_username: string | null;
    updated_at: string | null;
  };
  instagram: {
    connected: boolean;
    ig_user_id: string | null;
    username: string | null;
    updated_at: string | null;
  };
}

interface ConnectedCapability {
  key: string;
  name: string;
  description: string;
  scope: string;
  accessLevel: string;
  granted?: boolean;
}

interface ConnectedAccount {
  id: number;
  identifier: string;
  label: string | null;
  type: string | null;
  isDefault: boolean;
  connectedAt: string | null;
  metadata?: Record<string, string | number | boolean | null>;
  grantedCapabilities?: string[];
}

interface ConnectedProvider {
  key: string;
  name: string;
  authType: string;
  status: string;
  connectionState?: "not_connected" | "connecting" | "connected" | "expired" | "reconnect_required" | "error" | "unavailable" | string;
  configured?: boolean;
  connected: boolean;
  connectedAt: string | null;
  lastError?: string | null;
  accounts: ConnectedAccount[];
  capabilities: ConnectedCapability[];
}

interface ConnectedAppsData {
  connectedCount: number;
  totalCount: number;
  providers: ConnectedProvider[];
}

interface ConnectedAppCardData {
  key: string;
  providerKey: string;
  title: string;
  description: string;
  capabilities: string[];
  requirements?: string[];
  logo: string;
  logoUrl: string;
  logoTone: string;
  connected: boolean;
  connectedAt: string | null;
  connectedLabel?: string;
  connectedValue?: string;
  connectedDetails?: Array<{ label: string; value: string }>;
  connectionState?: "not_connected" | "connecting" | "connected" | "expired" | "reconnect_required" | "error" | "unavailable" | string;
  errorMessage?: string;
  statusDetail?: string;
  connectLabel: string;
  action: "oauth" | "manual" | "secret" | "disabled";
}

interface TaskItem {
  id: number;
  title: string;
  owner: string;
  status: TaskStatus;
  persisted?: boolean;
}

interface ApiAgent {
  id: number;
  slug: string;
  name: string;
  role: string;
  avatar: string | null;
  status: string;
}

interface ApiTeamAgent {
  id: number;
  agent_id: number;
  position: number;
  role_override: string | null;
  agent: ApiAgent | null;
}

interface ApiTeam {
  id: number;
  workspace_id: number;
  slug: string;
  name: string;
  description: string | null;
  category: string | null;
  status: string;
  metadata_json: {
    source?: "ready" | "mine";
    agentsCount?: number;
    output?: string;
    tags?: string[];
    icon?: string;
    workflow?: string[];
    roster?: AgentData[];
  } | null;
  agents: ApiTeamAgent[];
}

interface ApiTask {
  id: number;
  title: string;
  description: string | null;
  status: string;
  input_json: {
    owner?: string;
  } | null;
}

interface AgentData {
  name: string;
  role: string;
  avatar?: string;
  accent: string;
}

interface WorkflowData {
  agent: string;
  text: string;
  path: string;
}

interface TeamCardData {
  id: string;
  name: string;
  category: string;
  agents: string;
  agentsCount: number;
  copy: string;
  modalCopy: string;
  output: string;
  tags: string[];
  icon: LucideIcon;
  roster: AgentData[];
  workflow: string[];
  modalWorkflow: WorkflowData[];
}

interface OfficeTeamPayload {
  id: string;
  name: string;
  agents: Array<{
    id: string;
    name: string;
    role: string;
    avatar: string;
    color: string;
  }>;
}

interface ActiveOfficeConversation {
  id: string;
  teamId: string;
  teamName: string;
  source: "ready" | "mine";
}

interface ConversationSummary extends ActiveOfficeConversation {
  lastMessage: string;
  updatedAt: string;
  unreadCount: number;
  messageCount: number;
}

interface OfficeConversationUpdate {
  id: string;
  teamId: string;
  teamName: string;
  source?: "ready" | "mine";
  lastMessage?: string;
  updatedAt?: string;
  unreadCount?: number;
  messageCount?: number;
}

const CONVERSATION_STORAGE_VERSION = 1;
const DASHBOARD_VIEW_STORAGE_KEY = "rebly-dashboard-active-view";
const DASHBOARD_TEAM_TAB_STORAGE_KEY = "rebly-dashboard-team-tab";
const DASHBOARD_OFFICE_STORAGE_KEY = "rebly-dashboard-active-office";

const dashboardViews: View[] = ["office", "youtube-growth", "tasks", "activity", "my-teams", "shared", "settings", "support"];
const teamTabs: TeamTab[] = ["history", "ready", "mine"];

function isDashboardView(value: string | null): value is View {
  return dashboardViews.includes(value as View);
}

function isTeamTab(value: string | null): value is TeamTab {
  return teamTabs.includes(value as TeamTab);
}

function conversationStorageKey(ownerId: string) {
  return `rebly-team-conversations-v${CONVERSATION_STORAGE_VERSION}:${ownerId}`;
}

function createConversationId(teamId: string) {
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${teamId}-${random}`.replace(/[^A-Za-z0-9_.-]+/g, "-");
}

function loadConversationSummaries(ownerId: string): ConversationSummary[] {
  try {
    const key = conversationStorageKey(ownerId);
    localStorage.removeItem(key);
    const raw = sessionStorage.getItem(key);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item) => item && typeof item.id === "string" && typeof item.teamId === "string")
      .map((item) => {
        const source: "ready" | "mine" = item.source === "mine" ? "mine" : "ready";
        return {
          id: String(item.id),
          teamId: String(item.teamId),
          teamName: String(item.teamName || "AI Team"),
          source,
          lastMessage: String(item.lastMessage || "New chat"),
          updatedAt: String(item.updatedAt || new Date().toISOString()),
          unreadCount: Number.isFinite(Number(item.unreadCount)) ? Number(item.unreadCount) : 0,
          messageCount: Number.isFinite(Number(item.messageCount)) ? Number(item.messageCount) : 0,
        };
      })
      .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
  } catch {
    return [];
  }
}

function saveConversationSummaries(ownerId: string, conversations: ConversationSummary[]) {
  try {
    sessionStorage.setItem(conversationStorageKey(ownerId), JSON.stringify(conversations.slice(0, 80)));
  } catch {
    // Keep the dashboard usable when browser storage is unavailable.
  }
}

function formatConversationTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (date.toDateString() === now.toDateString()) return `Today • ${time}`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return `Yesterday • ${time}`;
  return `${date.toLocaleDateString([], { month: "short", day: "numeric" })} • ${time}`;
}

const officeAgents = [
  { id: "all", name: "Team", role: "AI crew", image: "/images/agents/coordinator.png", color: "#1F2933", state: "online" },
  { id: "coordinator", name: "Atlas", role: "Coordinator", image: "/images/agents/coordinator.png", color: "#4F5BD5", state: "online" },
  { id: "mika", name: "Ava", role: "Clients", image: "/images/agents/mika.png", color: "#D04F6A", state: "online" },
  { id: "scout", name: "Scout", role: "Market", image: "/images/agents/scout.png", color: "#0097A7", state: "online" },
  { id: "dev", name: "Dex", role: "Developer", image: "/images/agents/dev.png", color: "#13A56F", state: "idle" },
  { id: "nova", name: "Echo", role: "Support", image: "/images/agents/nova.png", color: "#C98908", state: "idle" }
];

const officeRuntimeAgents = officeAgents.filter((agent) => agent.id !== "all");

const youtubeGrowthRuntimeIds: Record<string, string> = {
  Atlas: "coordinator",
  "Trend Scout": "youtube-trend-scout",
  "Competitor Analyst": "youtube-competitor-analyst",
  "Video Analyst": "youtube-video-analyst",
  "Content Strategist": "youtube-content-strategist",
  "Creative Director": "youtube-creative-director",
  "Growth Analyst": "youtube-growth-analyst",
  Publisher: "youtube-publisher",
};

function buildOfficeTeamPayload(team: TeamCardData): OfficeTeamPayload {
  const source = team.roster.length ? team.roster : [{ name: team.name, role: team.category, accent: "#4F5BD5" }];
  const socialRuntimeIds: Record<string, string> = {
    Atlas: "coordinator",
    Scout: "scout",
    Mira: "mika",
    Dex: "dev",
    Echo: "nova",
  };
  const runtimeLimit = team.id === "youtube-growth-team" ? 8 : officeRuntimeAgents.length;
  return {
    id: team.id,
    name: team.name,
    agents: source.slice(0, runtimeLimit).map((agent, index) => {
      const fallback = officeRuntimeAgents[index % officeRuntimeAgents.length] || officeRuntimeAgents[0];
      const youtubeRuntimeId = youtubeGrowthRuntimeIds[agent.name];
      return {
        id: team.id === "youtube-growth-team"
          ? youtubeRuntimeId || `youtube-agent-${index + 1}`
          : team.id === "social-posting-team"
            ? socialRuntimeIds[agent.name] || fallback.id
            : fallback.id,
        name: agent.name,
        role: agent.role || team.category,
        avatar: agent.avatar || fallback.image,
        color: agent.accent || fallback.color,
      };
    }),
  };
}

const businessAgents: AgentData[] = [
  { name: "Adam", role: "Стратег", avatar: "/images/member-man.png", accent: "#635BFF" },
  { name: "Mira", role: "Идеи и рост", avatar: "/images/member-woman.png", accent: "#16A3A3" },
  { name: "Leo", role: "Продажи", avatar: "/images/member-man.png", accent: "#2563EB" },
  { name: "Nora", role: "CRM", accent: "#8B5CF6" },
  { name: "Kai", role: "Аналитика", accent: "#0EA5E9" }
];

const fallbackAgents: AgentData[] = [
  { name: "Adam", role: "Strategist", avatar: "/images/member-man.png", accent: "#635BFF" },
  { name: "Mira", role: "Researcher", avatar: "/images/member-woman.png", accent: "#16A3A3" },
  { name: "Leo", role: "Sales", avatar: "/images/member-man.png", accent: "#2563EB" },
  { name: "Nora", role: "CRM", accent: "#8B5CF6" },
  { name: "Kai", role: "Analytics", accent: "#0EA5E9" },
  { name: "Sofia", role: "Support", avatar: "/images/member-woman.png", accent: "#EC4899" },
  { name: "Scout", role: "Signals", avatar: "/images/member-man.png", accent: "#0EA5E9" }
];

function completeTeamRoster(team: TeamCardData) {
  if (team.roster.length >= team.agentsCount) return team.roster;
  const usedNames = new Set(team.roster.map((agent) => agent.name));
  const additions = fallbackAgents.filter((agent) => !usedNames.has(agent.name)).slice(0, team.agentsCount - team.roster.length);
  return [...team.roster, ...additions];
}

const businessWorkflow = [
  "Coordinator быстро собирает контекст и фиксирует цель",
  "Adam собирает стратегию, позиционирование и план действий",
  "Mira предлагает идеи для роста, маркетинга и продукта",
  "Nora выстраивает CRM-воронку и правила follow-up",
  "Leo готовит офферы, скрипты и первые сообщения",
  "Kai смотрит метрики и собирает понятный KPI-отчёт",
  "Coordinator упаковывает всё в финальный бизнес-план"
];

const businessModalWorkflow: WorkflowData[] = [
  { agent: "Coordinator", text: "Собирает короткий бриф, уточняет клиента и задачу, чтобы команда не работала вслепую.", path: "workspace/business-ai/brief.md" },
  { agent: "Adam", text: "Формирует позиционирование, варианты стратегии и приоритеты на ближайшие шаги.", path: "workspace/business-ai/strategy.md" },
  { agent: "Mira", text: "Придумывает идеи для роста, контента, продукта и маркетинговых экспериментов.", path: "workspace/business-ai/ideas.md" },
  { agent: "Nora", text: "Собирает CRM-этапы, поля лидов, follow-up и простую автоматизацию.", path: "workspace/business-ai/crm-pipeline.md" },
  { agent: "Leo", text: "Готовит офферы, скрипты продаж, ответы на возражения и outreach-сообщения.", path: "workspace/business-ai/sales-scripts.md" },
  { agent: "Kai", text: "Проверяет KPI, конверсии и сигналы, которые стоит вынести в отчёт.", path: "workspace/business-ai/kpi-dashboard.md" },
  { agent: "Coordinator", text: "Собирает финальный отчёт: что делать дальше, кто отвечает и где результат.", path: "workspace/business-ai/final-report.md" }
];

const youtubeGrowthTeam: TeamCardData = {
  id: "youtube-growth-team",
  name: "YouTube Growth Team",
  category: "Growth",
  agents: "8 agents",
  agentsCount: 8,
  copy: "A source-backed YouTube research, content planning, creative, and channel learning team. It estimates opportunity without promising a specific number of views.",
  modalCopy: "Atlas coordinates seven internal YouTube growth roles. The team uses permitted YouTube APIs, clearly separates facts from AI interpretation, validates content plans, and asks for explicit confirmation before any publishing action.",
  output: "Video analysis + competitor synthesis + validated 7/30-day content plan + channel-specific growth recommendations",
  tags: ["YouTube", "Growth", "Research", "Content"],
  icon: Rocket,
  roster: [
    { name: "Atlas", role: "Coordinator", avatar: "/images/agents/coordinator.png", accent: "#4F5BD5" },
    { name: "Trend Scout", role: "Trends and content gaps", avatar: "/images/agents/scout.png", accent: "#0EA5E9" },
    { name: "Competitor Analyst", role: "Competitive research", avatar: "/images/member-woman.png", accent: "#14B8A6" },
    { name: "Video Analyst", role: "Metadata and transcript analysis", avatar: "/images/agents/dev.png", accent: "#2563EB" },
    { name: "Content Strategist", role: "7/30-day plans", avatar: "/images/agents/nova.png", accent: "#8B5CF6" },
    { name: "Creative Director", role: "Titles, hooks, scripts, thumbnails", avatar: "/images/member-woman.png", accent: "#EC4899" },
    { name: "Growth Analyst", role: "Channel baselines and recommendations", avatar: "/images/member-man.png", accent: "#F59E0B" },
    { name: "Publisher", role: "Approval-controlled publishing", avatar: "/images/agents/dev.png", accent: "#10B981" },
  ],
  workflow: [
    "Atlas validates the request and delegates only the required specialist roles",
    "Trend Scout and Competitor Analyst collect permitted public evidence and source URLs",
    "Video Analyst reports metadata, available captions, comments, and explicit limitations",
    "Content Strategist and Creative Director build schema-validated ideas and packaging",
    "Growth Analyst compares owned-channel results with that channel's own baseline",
    "Publisher remains a controlled capability and never publishes without explicit approval",
  ],
  modalWorkflow: [
    { agent: "Trend Scout", text: "Finds current videos, rising channels, trends, and content gaps with source URLs.", path: "youtube-growth/research" },
    { agent: "Competitor Analyst", text: "Compares relevant videos and separates observed facts from AI interpretation.", path: "youtube-growth/competitors" },
    { agent: "Video Analyst", text: "Analyzes metadata, available transcripts, comments, structure, hooks, and limitations.", path: "youtube-growth/video-analysis" },
    { agent: "Content Strategist", text: "Creates a validated 7-day or 30-day content plan for the channel context.", path: "youtube-growth/content-plan" },
    { agent: "Creative Director", text: "Creates title, hook, thumbnail, script, CTA, chapter, and Shorts variants.", path: "youtube-growth/creative" },
    { agent: "Growth Analyst", text: "Compares post-publish checkpoints with the channel's own historical baseline.", path: "youtube-growth/recommendations" },
    { agent: "Publisher", text: "Prepares a publishing preview and waits for explicit user confirmation.", path: "youtube-growth/publisher" },
    { agent: "Atlas", text: "Combines artifacts, preserves sources, and requests approval before publishing.", path: "youtube-growth/final" },
  ],
};

const socialPostingTeam: TeamCardData = {
  id: "social-posting-team",
  name: "Social Posting Team",
  category: "Social",
  agents: "5 agents",
  agentsCount: 5,
  copy: "Команда для авто-постинга: готовит идеи, captions, визуальный brief и публикует approved-посты через Connected Apps.",
  modalCopy: "Social Posting Team работает прямо в сайте. Пользователь подключает Telegram, Instagram или YouTube в Connected Apps, команда готовит пост или видео, показывает preview, а Dex отправляет approved-публикацию через backend API. Для YouTube нужен публичный HTTPS URL видео и отдельное подтверждение перед загрузкой.",
  output: "Publish-ready caption + media brief + Telegram/Instagram status + YouTube upload status",
  tags: ["Marketing", "Instagram", "Telegram", "YouTube"],
  icon: Share2,
  roster: [
    { name: "Atlas", role: "Coordinator", avatar: "/images/agents/coordinator.png", accent: "#4F5BD5" },
    { name: "Scout", role: "Research", avatar: "/images/agents/scout.png", accent: "#0EA5E9" },
    { name: "Mira", role: "Copy + creative", avatar: "/images/member-woman.png", accent: "#16A3A3" },
    { name: "Dex", role: "Publisher", avatar: "/images/agents/dev.png", accent: "#13A56F" },
    { name: "Echo", role: "Analytics", avatar: "/images/agents/nova.png", accent: "#C98908" }
  ],
  workflow: [
    "Atlas принимает задачу и выбирает платформу: Telegram, Instagram или YouTube",
    "Scout находит тему, аудиторию, угол подачи и актуальные сигналы",
    "Mira пишет caption, hook, CTA и visual brief, а для YouTube — title и description",
    "Dex проверяет Connected Apps; YouTube-видео загружает только после отдельного approval по публичному HTTPS URL",
    "Echo сохраняет статус публикации и ошибки, чтобы вернуться к ним позже"
  ],
  modalWorkflow: [
    { agent: "Atlas", text: "Собирает brief: цель поста, площадки, дедлайн, нужный формат и ограничения бренда.", path: "workspace/social/brief.md" },
    { agent: "Scout", text: "Находит темы, аудиторию, боли, тренды и лучшие углы подачи для публикации.", path: "workspace/social/research.md" },
    { agent: "Mira", text: "Пишет caption, hook, CTA, хэштеги и visual brief; для YouTube готовит title и description.", path: "workspace/social/copy.md" },
    { agent: "Dex", text: "Проверяет Telegram Bot, Instagram Graph или YouTube OAuth; YouTube-видео загружает только после approval по публичному HTTPS URL.", path: "connected-apps/publisher" },
    { agent: "Echo", text: "Записывает publish result, external id, ошибки и следующую рекомендацию.", path: "workspace/social/history.md" }
  ]
};

const readyTeams: TeamCardData[] = [
  youtubeGrowthTeam,
  socialPostingTeam,
  {
    id: "business-ai-team",
    name: "Business AI Team",
    category: "Business",
    agents: "5 agents",
    agentsCount: 5,
    copy: "Команда для стратегии, роста, CRM, продаж и аналитики, когда нужен понятный бизнес-план без лишнего шума.",
    modalCopy: "Business AI Team помогает основателям и малым командам быстро собрать стратегию, идеи роста, CRM-процессы, продажи и отчёты по метрикам.",
    output: "Стратегия + CRM-воронка + скрипты продаж + KPI-дашборд",
    tags: ["Business", "Strategy", "CRM"],
    icon: BriefcaseBusiness,
    roster: businessAgents,
    workflow: businessWorkflow,
    modalWorkflow: businessModalWorkflow
  },
  {
    id: "founders-cos",
    name: "Founder's COS",
    category: "Operations",
    agents: "1 agent",
    agentsCount: 1,
    copy: "Личный операционный помощник для фаундера: приоритеты недели, застрявшие решения и короткие апдейты для инвесторов.",
    modalCopy: "Founder's COS держит ритм основателя: собирает приоритеты, напоминает о решениях, готовит investor update и короткий недельный отчёт.",
    output: "Карточки на approve + weekly brief + inbox-log",
    tags: ["Founder", "Operations", "Digest"],
    icon: Rocket,
    roster: [{ name: "Reese", role: "Operations Manager", avatar: "/images/member-man.png", accent: "#F43F5E" }],
    workflow: [
      "Coordinator собирает короткий intake и вытаскивает важные решения",
      "Reese проверяет KPI, runway и конфликты по приоритетам",
      "Coordinator пишет недельный executive brief",
      "Coordinator готовит карточки, которые можно быстро approve"
    ],
    modalWorkflow: [
      { agent: "Coordinator", text: "Быстро собирает контекст недели: решения, дедлайны и конфликты в календаре.", path: "workspace/founder-cos/brief.md" },
      { agent: "Reese", text: "Подтягивает KPI, runway, изменения в расписании и риски по приоритетам.", path: "workspace/founder-cos/data.md" },
      { agent: "Coordinator", text: "Готовит executive brief и короткие notes по решениям.", path: "briefs/week-report.md" },
      { agent: "Coordinator", text: "Собирает approval-карточки и follow-up, готовые к отправке.", path: "briefs/inbox-log.md" }
    ]
  },
  {
    id: "marketing-team",
    name: "Marketing Team",
    category: "Growth",
    agents: "4 agents",
    agentsCount: 4,
    copy: "Маркетинг-команда для фаундера: контент-план, черновики в голосе бренда и очередь упоминаний без хаоса.",
    modalCopy: "Marketing Team превращает контекст продукта в календарь контента, идеи кампаний, готовые посты и ответы на упоминания.",
    output: "Контент-план + готовые черновики + журнал ответов",
    tags: ["Marketing", "Instagram", "Content"],
    icon: BriefcaseBusiness,
    roster: [
      { name: "Mika", role: "Контент", avatar: "/images/member-woman.png", accent: "#EC4899" },
      { name: "Marcus", role: "Копирайтинг", accent: "#F59E0B" },
      { name: "Scout", role: "Соцсети", avatar: "/images/member-man.png", accent: "#0EA5E9" },
      { name: "Hayden", role: "Комьюнити", accent: "#10B981" }
    ],
    workflow: [
      "Mika собирает контент-план на неделю",
      "Marcus пишет тексты и короткие visual briefs",
      "Scout смотрит реакции, охваты и полезные сигналы",
      "Hayden готовит ответы на упоминания и комментарии"
    ],
    modalWorkflow: [
      { agent: "Mika", text: "Собирает недельный календарь и brief для каждого поста на основе бренда.", path: "workspace/marketing/calendar.md" },
      { agent: "Marcus", text: "Пишет hooks, captions, тексты для каналов и направление для визуалов.", path: "workspace/marketing/copy.md" },
      { agent: "Scout", text: "Отмечает метрики вовлечения, удачные темы и аномалии в реакциях.", path: "workspace/marketing/signals.md" },
      { agent: "Hayden", text: "Готовит ответы на упоминания и поднимает спорные сообщения на review.", path: "workspace/marketing/replies.md" }
    ]
  },
  {
    id: "sales-team",
    name: "Sales Team",
    category: "Sales",
    agents: "4 agents",
    agentsCount: 4,
    copy: "Команда для inbound-продаж: быстро отвечает лидам, квалифицирует спрос и держит CRM в порядке.",
    modalCopy: "Sales Team помогает не терять горячих лидов: готовит первые ответы, квалифицирует запросы, собирает офферы и обновляет pipeline.",
    output: "Список квалифицированных лидов + reply drafts + CRM notes",
    tags: ["Sales", "Leads", "CRM"],
    icon: UsersRound,
    roster: [
      { name: "Leo", role: "Продажи", avatar: "/images/member-man.png", accent: "#2563EB" },
      { name: "Nora", role: "CRM", accent: "#8B5CF6" },
      { name: "Adam", role: "Офферы", avatar: "/images/member-man.png", accent: "#635BFF" }
    ],
    workflow: [
      "Leo оценивает новых лидов и сигналы покупки",
      "Nora обновляет CRM-этапы и follow-up",
      "Adam собирает оффер и аргументы для сделки"
    ],
    modalWorkflow: [
      { agent: "Leo", text: "Оценивает входящих лидов и пишет первый персональный ответ.", path: "workspace/sales/replies.md" },
      { agent: "Nora", text: "Обновляет этап сделки, follow-up дату и поля квалификации.", path: "workspace/sales/crm.md" },
      { agent: "Adam", text: "Готовит оффер, аргументы и ответы на частые возражения.", path: "workspace/sales/offers.md" }
    ]
  },
  {
    id: "support-team",
    name: "Support Team",
    category: "Support",
    agents: "5 agents",
    agentsCount: 5,
    copy: "Support-команда, которая разбирает тикеты, пишет понятные ответы и находит повторяющиеся проблемы.",
    modalCopy: "Support Team сортирует обращения, готовит человеческие ответы и превращает повторяющиеся баги в понятный issue report.",
    output: "Ответы по тикетам + issue report + список частых проблем",
    tags: ["Support", "Tickets", "QA"],
    icon: LifeBuoy,
    roster: [
      { name: "Sofia", role: "Клиенты", avatar: "/images/member-woman.png", accent: "#EC4899" },
      { name: "Kai", role: "Отчёты", accent: "#0EA5E9" },
      { name: "Mira", role: "Ответы", avatar: "/images/member-woman.png", accent: "#16A3A3" }
    ],
    workflow: [
      "Sofia сортирует обращения по срочности",
      "Mira пишет ответы из контекста продукта",
      "Kai собирает повторяющиеся проблемы в отчёт"
    ],
    modalWorkflow: [
      { agent: "Sofia", text: "Разбирает новые обращения по срочности, типу клиента и теме.", path: "workspace/support/queue.md" },
      { agent: "Mira", text: "Пишет ответы на основе сохранённого контекста и product notes.", path: "workspace/support/replies.md" },
      { agent: "Kai", text: "Собирает повторяющиеся проблемы и недельные тренды по тикетам.", path: "workspace/support/report.md" }
    ]
  }
];

const myTeams: TeamCardData[] = [
  {
    id: "my-business-ai",
    name: "Business AI",
    category: "Business",
    agents: "4 agents",
    agentsCount: 4,
    copy: "Рабочая команда для Instagram DM, Telegram follow-up, контента и ежедневных сводок.",
    modalCopy: "Business AI держит вместе ответы клиентам, follow-up, контентные задачи и ежедневный отчёт по активности.",
    output: "Ежедневная сводка + очередь approved-ответов",
    tags: ["Instagram", "Telegram", "Daily digest"],
    icon: BriefcaseBusiness,
    roster: businessAgents.slice(0, 4),
    workflow: [
      "Sofia проверяет DM-очередь и готовит ответы",
      "Leo пишет follow-up для Telegram",
      "Mira собирает ежедневную сводку"
    ],
    modalWorkflow: [
      { agent: "Sofia", text: "Проверяет DM-очередь и готовит ответы, которые можно быстро approve.", path: "workspace/business-ai/dm-queue.md" },
      { agent: "Leo", text: "Пишет Telegram follow-up с нормальным тоном и понятным next step.", path: "workspace/business-ai/telegram.md" },
      { agent: "Mira", text: "Собирает дневную сводку: что произошло, что ждёт решения и что готово.", path: "workspace/business-ai/summary.md" }
    ]
  }
];

const sharedTeams: TeamCardData[] = [
  {
    id: "launch-room",
    name: "Launch Room",
    category: "Shared",
    agents: "3 agents",
    agentsCount: 3,
    copy: "Общая launch-комната для ревью контента, задач запуска и коротких activity updates.",
    modalCopy: "Launch Room помогает держать запуск в одном месте: ревью, открытые задачи, владельцы и сводки активности.",
    output: "Launch activity report + список открытых действий",
    tags: ["Shared", "Launch", "Review"],
    icon: Share2,
    roster: businessAgents.slice(0, 3),
    workflow: [
      "Sofia проверяет launch-запросы и approvals",
      "Leo ведёт открытые action items"
    ],
    modalWorkflow: [
      { agent: "Sofia", text: "Проверяет launch-запросы и отправляет нужные approval на ревью.", path: "workspace/launch/review.md" },
      { agent: "Leo", text: "Следит за открытыми задачами, владельцами и сроками.", path: "workspace/launch/actions.md" }
    ]
  }
];

const teamIconMap: Record<string, LucideIcon> = {
  BriefcaseBusiness,
  LifeBuoy,
  Rocket,
  Share2,
  UsersRound
};

function fallbackTeamBySlug(slug: string) {
  return [...readyTeams, ...myTeams, ...sharedTeams].find((team) => team.id === slug) || null;
}

function mapApiTeamToCard(team: ApiTeam): TeamCardData {
  const fallback = fallbackTeamBySlug(team.slug);
  const metadata = team.metadata_json || {};
  const roster =
    metadata.roster?.length
      ? metadata.roster
      : team.agents
          .map((membership) => membership.agent)
          .filter((agent): agent is ApiAgent => Boolean(agent))
          .map((agent) => ({
            name: agent.name,
            role: agent.role,
            avatar: agent.avatar || undefined,
            accent: "#635BFF",
          }));
  const agentsCount = metadata.agentsCount || roster.length || fallback?.agentsCount || 0;
  return {
    id: team.slug || String(team.id),
    name: team.name || fallback?.name || "AI Team",
    category: team.category || fallback?.category || "Workspace",
    agents: `${agentsCount} ${agentsCount === 1 ? "agent" : "agents"}`,
    agentsCount,
    copy: fallback?.copy || team.description || "",
    modalCopy: fallback?.modalCopy || team.description || "",
    output: metadata.output || fallback?.output || "Workspace result",
    tags: metadata.tags?.length ? metadata.tags : fallback?.tags || [],
    icon: teamIconMap[metadata.icon || ""] || fallback?.icon || BriefcaseBusiness,
    roster: roster.length ? roster : fallback?.roster || [],
    workflow: metadata.workflow?.length ? metadata.workflow : fallback?.workflow || [],
    modalWorkflow: fallback?.modalWorkflow || [],
  };
}

const initialTasks: TaskItem[] = [
  { id: 1, title: "Review Instagram DM queue", owner: "Sofia", status: "Working" },
  { id: 2, title: "Prepare Telegram follow-up copy", owner: "Leo", status: "Queued" },
  { id: 3, title: "Create daily activity summary", owner: "Mira", status: "Done" }
];

function mapApiTaskStatus(status: string): TaskStatus {
  if (status === "completed") return "Done";
  if (status === "queued" || status === "planning" || status === "assigned") return "Queued";
  return "Working";
}

function mapTaskStatusToApi(status: TaskStatus) {
  if (status === "Done") return "completed";
  if (status === "Working") return "in_progress";
  return "queued";
}

function mapApiTaskToItem(task: ApiTask): TaskItem {
  return {
    id: task.id,
    title: task.title,
    owner: task.input_json?.owner || "Workspace",
    status: mapApiTaskStatus(task.status),
    persisted: true,
  };
}

const taskTemplates = [
  "Review Instagram DM queue",
  "Prepare Telegram follow-up copy",
  "Create daily activity summary",
  "Draft weekly content plan",
  "Check support requests",
  "Update sales lead notes"
];

const activityItems = [
  { who: "Sofia", text: "Drafted 8 customer replies", time: "09:20" },
  { who: "Leo", text: "Added competitor notes to shared context", time: "09:05" },
  { who: "Mira", text: "Moved daily summary to review", time: "08:42" },
  { who: "System", text: "Business AI office is online", time: "08:30" }
];

const agentToolRoles = [
  {
    name: "Atlas",
    role: "Coordinator",
    summary: "Routes work, checks status, approves sensitive actions, and writes Activity.",
    tools: ["assign_task", "approve_action", "write_activity_log", "schedule_task"],
    approval: "Can approve send, publish, delete, admin"
  },
  {
    name: "Scout",
    role: "Marketing / Research",
    summary: "Creates posts, captions, hashtags, image prompts, and research insights.",
    tools: ["create_post", "create_caption", "create_image_prompt", "get_social_analytics"],
    approval: "Requests approval for scheduling"
  },
  {
    name: "Ava",
    role: "Sales",
    summary: "Works with Gmail drafts, meetings, leads, CRM rows, and follow-up.",
    tools: ["create_gmail_draft", "send_gmail", "create_calendar_event", "update_google_sheet_row"],
    approval: "Needs approval for send/write"
  },
  {
    name: "Dex",
    role: "Publisher / Ops",
    summary: "Publishes approved social posts and handles operational writes.",
    tools: ["publish_social_post", "schedule_social_post", "upload_document", "edit_google_doc"],
    approval: "Needs approval for publish/write"
  },
  {
    name: "Echo",
    role: "Support",
    summary: "Handles inbox, comments, DM replies, support drafts, and knowledge lookup.",
    tools: ["read_gmail_thread", "reply_gmail", "reply_to_comment", "reply_instagram_direct"],
    approval: "Needs approval for send/reply"
  }
];

function resolveThemeMode(mode: ThemeMode): ResolvedTheme {
  const dark = mode === "dark" || (mode === "auto" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  return dark ? "dark" : "light";
}

function applyThemeMode(mode: ThemeMode): ResolvedTheme {
  const resolved = resolveThemeMode(mode);
  document.documentElement.dataset.theme = resolved;
  document.documentElement.style.colorScheme = resolved;
  localStorage.setItem("rebly-theme", mode);
  return resolved;
}

export default function DashboardPage() {
  const [user, setUser] = useState<UserData | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeView, setActiveView] = useState<View>("office");
  const [settingsTab, setSettingsTab] = useState<SettingsTab>("profile");
  const [themeMode, setThemeMode] = useState<ThemeMode>("dark");
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>("dark");
  const [teamTab, setTeamTab] = useState<TeamTab>("ready");
  const [teamViewMode, setTeamViewMode] = useState<TeamViewMode>("grid");
  const [teamSearch, setTeamSearch] = useState("");
  const [teamCategory, setTeamCategory] = useState("All");
  const [expandedTeam, setExpandedTeam] = useState("");
  const [detailTeam, setDetailTeam] = useState<TeamCardData | null>(null);
  const [openHistoryMenu, setOpenHistoryMenu] = useState("");
  const [deleteConversationTarget, setDeleteConversationTarget] = useState<ConversationSummary | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConversation, setActiveConversation] = useState<ActiveOfficeConversation | null>(null);
  const [tasks, setTasks] = useState(initialTasks);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [tasksError, setTasksError] = useState("");
  const [apiTeams, setApiTeams] = useState<TeamCardData[]>([]);
  const [teamsLoading, setTeamsLoading] = useState(false);
  const [teamsError, setTeamsError] = useState("");
  const [teamsLoaded, setTeamsLoaded] = useState(false);
  const [supportCategory, setSupportCategory] = useState("Bug");
  const [supportSubject, setSupportSubject] = useState("");
  const [supportMessage, setSupportMessage] = useState("");
  const [attachmentName, setAttachmentName] = useState("");
  const [supportStatus, setSupportStatus] = useState("");
  const [emailDigest, setEmailDigest] = useState(true);
  const [memoryEnabled, setMemoryEnabled] = useState(true);
  const [telegramBotToken, setTelegramBotToken] = useState("");
  const [telegramBotTarget, setTelegramBotTarget] = useState("");
  const [telegramBotConnected, setTelegramBotConnected] = useState(false);
  const [telegramBotStatus, setTelegramBotStatus] = useState("");
  const [instagramConnected, setInstagramConnected] = useState(false);
  const [instagramStatus, setInstagramStatus] = useState("");
  const [connectedApps, setConnectedApps] = useState<ConnectedAppsData | null>(null);
  const [connectedAppsSearch, setConnectedAppsSearch] = useState("");
  const [connectedAppsFilter, setConnectedAppsFilter] = useState<ConnectedAppsFilter>("all");
  const [configuringConnectedApp, setConfiguringConnectedApp] = useState("");
  const [manualSecretValues, setManualSecretValues] = useState<Record<string, string>>({});
  const [manualSecretStatus, setManualSecretStatus] = useState<Record<string, string>>({});
  const [oauthConnectingApps, setOauthConnectingApps] = useState<Record<string, boolean>>({});
  const [connectedAppErrors, setConnectedAppErrors] = useState<Record<string, string>>({});
  const [shopifyConnectOpen, setShopifyConnectOpen] = useState(false);
  const [shopifyShopDomain, setShopifyShopDomain] = useState("");
  const [selectedOfficeAgent, setSelectedOfficeAgent] = useState("all");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [selectedOfficeTeam, setSelectedOfficeTeam] = useState<TeamCardData | null>(null);
  const [dashboardRestored, setDashboardRestored] = useState(false);
  const officeFrameRef = useRef<HTMLIFrameElement | null>(null);

  const conversationOwnerId = user?.id ? `user-${user.id}` : "guest";

  const selectedOfficeTeamPayload = useMemo(
    () => (selectedOfficeTeam ? buildOfficeTeamPayload(selectedOfficeTeam) : null),
    [selectedOfficeTeam]
  );

  const visibleOfficeAgents = useMemo(() => {
    if (!selectedOfficeTeamPayload) return officeAgents;
    return [
      {
        id: "all",
        name: selectedOfficeTeamPayload.name,
        role: "AI team",
        image: selectedOfficeTeamPayload.agents[0]?.avatar || "/images/agents/coordinator.png",
        color: "#1F2933",
        state: "online",
      },
      ...selectedOfficeTeamPayload.agents.map((agent, index) => ({
        id: agent.id,
        name: agent.name,
        role: agent.role,
        image: agent.avatar,
        color: agent.color,
        state: index < 3 ? "online" : "idle",
      })),
    ];
  }, [selectedOfficeTeamPayload]);

  useEffect(() => {
    const storedView = localStorage.getItem(DASHBOARD_VIEW_STORAGE_KEY);
    const storedTeamTab = localStorage.getItem(DASHBOARD_TEAM_TAB_STORAGE_KEY);
    const storedOffice = localStorage.getItem(DASHBOARD_OFFICE_STORAGE_KEY);

    if (isDashboardView(storedView)) {
      setActiveView(storedView);
    }
    if (isTeamTab(storedTeamTab)) {
      setTeamTab(storedTeamTab);
    }

    if (storedOffice) {
      try {
        const parsed = JSON.parse(storedOffice) as ActiveOfficeConversation;
        if (
          parsed &&
          typeof parsed.id === "string" &&
          typeof parsed.teamId === "string" &&
          typeof parsed.teamName === "string" &&
          (parsed.source === "ready" || parsed.source === "mine")
        ) {
          const team = findTeamById(parsed.teamId);
          if (team) {
            setSelectedOfficeTeam(team);
            setActiveConversation(parsed);
            setSelectedOfficeAgent("all");
          } else {
            localStorage.removeItem(DASHBOARD_OFFICE_STORAGE_KEY);
          }
        }
      } catch {
        localStorage.removeItem(DASHBOARD_OFFICE_STORAGE_KEY);
      }
    }

    setDashboardRestored(true);
  }, []);

  useEffect(() => {
    if (!dashboardRestored) return;
    localStorage.setItem(DASHBOARD_VIEW_STORAGE_KEY, activeView);
    localStorage.setItem(DASHBOARD_TEAM_TAB_STORAGE_KEY, teamTab);
  }, [activeView, dashboardRestored, teamTab]);

  useEffect(() => {
    if (!dashboardRestored) return;
    if (selectedOfficeTeam && activeConversation) {
      localStorage.setItem(DASHBOARD_OFFICE_STORAGE_KEY, JSON.stringify(activeConversation));
      return;
    }
    localStorage.removeItem(DASHBOARD_OFFICE_STORAGE_KEY);
  }, [activeConversation, dashboardRestored, selectedOfficeTeam]);

  useEffect(() => {
    const storedTheme = localStorage.getItem("rebly-theme");
    const nextTheme: ThemeMode = storedTheme === "light" || storedTheme === "auto" ? storedTheme : "dark";
    setThemeMode(nextTheme);
    setResolvedTheme(applyThemeMode(nextTheme));

    fetch(`${API_URL}/api/auth/me`, { credentials: "include" })
      .then(async (response) => {
        if (!response.ok) {
          window.location.href = "/auth?mode=login";
          return null;
        }
        return response.json();
      })
      .then((payload) => {
        if (payload?.user) {
          setUser(payload.user);
          loadIntegrations();
          loadTeams();
          loadTasks();
        }
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (themeMode !== "auto") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setResolvedTheme(applyThemeMode("auto"));
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [themeMode]);

  useEffect(() => {
    if (loading) return;
    setConversations(loadConversationSummaries(conversationOwnerId));
  }, [conversationOwnerId, loading]);

  useEffect(() => {
    function handleOfficeMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin) return;
      const data = event.data as { type?: string; agentId?: string; conversation?: OfficeConversationUpdate };
      if (data?.type === "rebly-office-agent-selected") {
        const agentId = String(data.agentId || "");
        if (visibleOfficeAgents.some((agent) => agent.id === agentId)) {
          setSelectedOfficeAgent(agentId);
        }
        return;
      }
      if (data?.type === "rebly-office-conversation-updated" && data.conversation) {
        upsertConversationFromOffice(data.conversation);
      }
    }

    window.addEventListener("message", handleOfficeMessage);
    return () => window.removeEventListener("message", handleOfficeMessage);
  }, [activeConversation, conversationOwnerId, visibleOfficeAgents]);

  useEffect(() => {
    if (activeView !== "office") return;
    sendOfficeTeam(selectedOfficeTeamPayload, activeConversation);
    sendOfficeSelection(selectedOfficeAgent);
    sendOfficeTheme(resolvedTheme);
  }, [activeConversation, activeView, resolvedTheme, selectedOfficeAgent, selectedOfficeTeamPayload]);

  const visibleHistory = useMemo(() => {
    const query = teamSearch.trim().toLowerCase();
    if (!query) return conversations;
    return conversations.filter((conversation) =>
      `${conversation.teamName} ${conversation.lastMessage}`.toLowerCase().includes(query)
    );
  }, [conversations, teamSearch]);

  const readyTeamSource = useMemo(() => {
    if (!teamsLoaded) return readyTeams;
    const readyIds = new Set(readyTeams.map((team) => team.id));
    return apiTeams.filter((team) => readyIds.has(team.id));
  }, [apiTeams, teamsLoaded]);

  const myTeamSource = useMemo(() => {
    if (!teamsLoaded) return myTeams;
    const readyIds = new Set(readyTeams.map((team) => team.id));
    return apiTeams.filter((team) => !readyIds.has(team.id));
  }, [apiTeams, teamsLoaded]);

  const filteredTeams = useMemo(() => {
    const query = teamSearch.trim().toLowerCase();
    const source = teamTab === "mine" ? myTeamSource : readyTeamSource;
    return source.filter((team) => {
      const matchesQuery = !query || `${team.name} ${team.copy} ${team.tags.join(" ")}`.toLowerCase().includes(query);
      const matchesCategory = teamCategory === "All" || team.tags.includes(teamCategory);
      return matchesQuery && matchesCategory;
    });
  }, [myTeamSource, readyTeamSource, teamCategory, teamSearch, teamTab]);

  function updateConversations(updater: (current: ConversationSummary[]) => ConversationSummary[]) {
    setConversations((current) => {
      const next = updater(current).sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
      saveConversationSummaries(conversationOwnerId, next);
      return next;
    });
  }

  function teamSource(team: TeamCardData): "ready" | "mine" {
    return myTeamSource.some((item) => item.id === team.id) ? "mine" : "ready";
  }

  function findTeamById(teamId: string): TeamCardData | null {
    return [...readyTeamSource, ...myTeamSource, ...sharedTeams, ...readyTeams, ...myTeams].find((team) => team.id === teamId) || null;
  }

  function openConversationOffice(conversation: ActiveOfficeConversation) {
    const team = findTeamById(conversation.teamId);
    if (!team) return;
    setSelectedOfficeTeam(team);
    setActiveConversation(conversation);
    setSelectedOfficeAgent("all");
    setDetailTeam(null);
    setExpandedTeam("");
    setActiveView("office");
  }

  function openTeamOffice(team: TeamCardData) {
    const existing = conversations.find((conversation) => conversation.teamId === team.id);
    const conversation: ActiveOfficeConversation = existing
      ? {
          id: existing.id,
          teamId: existing.teamId,
          teamName: existing.teamName,
          source: existing.source,
        }
      : {
          id: createConversationId(team.id),
          teamId: team.id,
          teamName: team.name,
          source: teamSource(team),
        };
    openConversationOffice(conversation);
  }

  function upsertConversationFromOffice(update: OfficeConversationUpdate) {
    if (!update.id || !update.teamId || Number(update.messageCount || 0) <= 0) return;
    const source = update.source || activeConversation?.source || (myTeamSource.some((team) => team.id === update.teamId) ? "mine" : "ready");
    const nextConversation: ConversationSummary = {
      id: update.id,
      teamId: update.teamId,
      teamName: update.teamName || activeConversation?.teamName || findTeamById(update.teamId)?.name || "AI Team",
      source,
      lastMessage: update.lastMessage?.trim() || "New chat",
      updatedAt: update.updatedAt || new Date().toISOString(),
      unreadCount: Number.isFinite(Number(update.unreadCount)) ? Number(update.unreadCount) : 0,
      messageCount: Number.isFinite(Number(update.messageCount)) ? Number(update.messageCount) : 0,
    };
    updateConversations((current) => {
      const withoutCurrent = current.filter((conversation) => conversation.id !== nextConversation.id);
      const existing = current.find((conversation) => conversation.id === nextConversation.id);
      return [{ ...nextConversation, teamName: existing?.teamName || nextConversation.teamName }, ...withoutCurrent];
    });
  }

  function renameConversation(conversation: ConversationSummary) {
    const nextName = window.prompt("Rename history", conversation.teamName)?.trim();
    setOpenHistoryMenu("");
    if (!nextName || nextName === conversation.teamName) return;
    updateConversations((current) =>
      current.map((item) => (item.id === conversation.id ? { ...item, teamName: nextName } : item))
    );
    if (activeConversation?.id === conversation.id) {
      setActiveConversation({ ...activeConversation, teamName: nextName });
    }
  }

  function deleteConversation(conversation: ConversationSummary) {
    setOpenHistoryMenu("");
    setDeleteConversationTarget(conversation);
  }

  function confirmDeleteConversation() {
    if (!deleteConversationTarget) return;
    const conversation = deleteConversationTarget;
    updateConversations((current) => current.filter((item) => item.id !== conversation.id));
    if (activeConversation?.id === conversation.id) {
      setActiveConversation(null);
    }
    setDeleteConversationTarget(null);
  }

  async function logout() {
    await fetch(`${API_URL}/api/auth/logout`, { method: "POST", credentials: "include" });
    for (const storage of [window.sessionStorage, window.localStorage]) {
      for (let index = storage.length - 1; index >= 0; index -= 1) {
        const key = storage.key(index);
        if (key?.startsWith("rebly-office-") || key?.startsWith("rebly-team-conversations-")) {
          storage.removeItem(key);
        }
      }
    }
    window.location.href = "/";
  }

  async function loadTeams() {
    setTeamsLoading(true);
    setTeamsError("");
    try {
      const response = await fetch(`${API_URL}/api/teams`, { credentials: "include" });
      if (!response.ok) throw new Error("Unable to load teams");
      const payload = (await response.json()) as ApiTeam[];
      setApiTeams(payload.map(mapApiTeamToCard));
      setTeamsLoaded(true);
    } catch (error) {
      setTeamsError(error instanceof Error ? error.message : "Unable to load teams");
      setTeamsLoaded(false);
    } finally {
      setTeamsLoading(false);
    }
  }

  async function loadTasks() {
    setTasksLoading(true);
    setTasksError("");
    try {
      const response = await fetch(`${API_URL}/api/tasks`, { credentials: "include" });
      if (!response.ok) throw new Error("Unable to load tasks");
      const payload = (await response.json()) as ApiTask[];
      setTasks(payload.map(mapApiTaskToItem));
    } catch (error) {
      setTasksError(error instanceof Error ? error.message : "Unable to load tasks");
      setTasks(initialTasks);
    } finally {
      setTasksLoading(false);
    }
  }

  async function addTask() {
    const nextIndex = tasks.length;
    const owner = officeAgents[nextIndex % officeAgents.length].name;
    const title = taskTemplates[nextIndex % taskTemplates.length];
    try {
      const response = await fetch(`${API_URL}/api/tasks`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          status: "queued",
          priority: "normal",
          input_json: { owner },
        }),
      });
      if (!response.ok) throw new Error("Unable to create task");
      const payload = (await response.json()) as ApiTask;
      setTasks((current) => [...current, mapApiTaskToItem(payload)]);
      setTasksError("");
    } catch (error) {
      setTasksError(error instanceof Error ? error.message : "Unable to create task");
      setTasks((current) => [
        ...current,
        {
          id: Date.now(),
          title,
          owner,
          status: "Queued"
        }
      ]);
    }
  }

  async function cycleTaskStatus(id: number) {
    const target = tasks.find((task) => task.id === id);
    if (!target) return;
    const nextStatus: TaskStatus = target.status === "Queued" ? "Working" : target.status === "Working" ? "Done" : "Queued";
    if (target.persisted) {
      try {
        const response = await fetch(`${API_URL}/api/tasks/${id}`, {
          method: "PATCH",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: mapTaskStatusToApi(nextStatus) }),
        });
        if (!response.ok) throw new Error("Unable to update task");
        const payload = (await response.json()) as ApiTask;
        setTasks((current) => current.map((task) => (task.id === id ? mapApiTaskToItem(payload) : task)));
        setTasksError("");
        return;
      } catch (error) {
        setTasksError(error instanceof Error ? error.message : "Unable to update task");
      }
    }
    setTasks((current) => current.map((task) => (task.id === id ? { ...task, status: nextStatus } : task)));
  }

  function submitSupport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!supportSubject.trim() || !supportMessage.trim()) return;
    setSupportStatus("Support request queued. We will reply to your account email.");
    setSupportSubject("");
    setSupportMessage("");
    setAttachmentName("");
  }

  function openTeams(tab: TeamTab = "ready") {
    setTeamTab(tab);
    setExpandedTeam("");
    setActiveView("my-teams");
  }

  function exitOfficeTeam() {
    setSelectedOfficeTeam(null);
    setActiveConversation(null);
    setSelectedOfficeAgent("all");
    setExpandedTeam("");
    setDetailTeam(null);
    setActiveView("office");
  }

  function hireTeam(team: TeamCardData) {
    openTeamOffice(team);
  }

  function sendOfficeTeam(team: OfficeTeamPayload | null, conversation: ActiveOfficeConversation | null) {
    if (!team) return;
    officeFrameRef.current?.contentWindow?.postMessage(
      {
        type: conversation ? "rebly-office-open-conversation" : "rebly-office-set-team",
        team,
        conversation,
      },
      window.location.origin,
    );
  }

  function sendOfficeSelection(agentId: string) {
    officeFrameRef.current?.contentWindow?.postMessage(
      {
        type: "rebly-office-select-agent",
        agentId,
      },
      window.location.origin,
    );
  }

  function sendOfficeTheme(theme: ResolvedTheme) {
    officeFrameRef.current?.contentWindow?.postMessage(
      {
        type: "rebly-office-set-theme",
        theme,
      },
      window.location.origin,
    );
  }

  function selectOfficeAgent(agentId: string) {
    setActiveView("office");
    setSelectedOfficeAgent(agentId);
    sendOfficeTeam(selectedOfficeTeamPayload, activeConversation);
    sendOfficeSelection(agentId);
  }

  function changeTheme(mode: ThemeMode) {
    setThemeMode(mode);
    setResolvedTheme(applyThemeMode(mode));
  }

  async function loadIntegrations() {
    try {
      const [legacyResponse, connectedResponse] = await Promise.all([
        fetch(`${API_URL}/api/integrations`, { credentials: "include" }),
        fetch(`${API_URL}/api/connected-apps`, { credentials: "include" })
      ]);
      if (legacyResponse.ok) {
        const payload: IntegrationsData = await legacyResponse.json();
        setTelegramBotConnected(Boolean(payload.telegram_bot.connected));
        setTelegramBotTarget(payload.telegram_bot.target_chat_id || "");
        setTelegramBotStatus(
          payload.telegram_bot.connected
            ? `Connected${payload.telegram_bot.bot_username ? ` as @${payload.telegram_bot.bot_username}` : ""}`
            : ""
        );
        setInstagramConnected(Boolean(payload.instagram.connected));
        setInstagramStatus(
          payload.instagram.connected
            ? `Connected${payload.instagram.username ? ` as @${payload.instagram.username}` : ""}`
            : ""
        );
      }
      if (connectedResponse.ok) {
        const appsPayload: ConnectedAppsData = await connectedResponse.json();
        setConnectedApps(appsPayload);
      }
    } catch {
      setTelegramBotStatus("Could not load Telegram status");
      setInstagramStatus("Could not load Instagram status");
    }
  }

  async function connectTelegram(kind: "bot") {
    if (kind === "bot" && telegramBotToken.trim().length > 8 && telegramBotTarget.trim()) {
      setTelegramBotStatus("Connecting...");
      try {
        const response = await fetch(`${API_URL}/api/integrations/telegram-bot`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({
            bot_token: telegramBotToken.trim(),
            target_chat_id: telegramBotTarget.trim(),
          }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(payload.detail || "Telegram connection failed");
        }
        setTelegramBotConnected(true);
        setTelegramBotToken("");
        await loadIntegrations();
      } catch (error) {
        setTelegramBotStatus(error instanceof Error ? error.message : "Telegram connection failed");
      }
    }
  }

  async function connectOAuthProvider(providerKey: string, connectPayload?: Record<string, string>) {
    setOauthConnectingApps((current) => ({ ...current, [providerKey]: true }));
    setConnectedAppErrors((current) => {
      const next = { ...current };
      delete next[providerKey];
      return next;
    });
    try {
      const response = await fetch(`${API_URL}/api/connected-apps/${providerKey}/connect`, {
        method: "POST",
        credentials: "include",
        ...(connectPayload
          ? {
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(connectPayload),
            }
          : {}),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || typeof payload.authorizationUrl !== "string") {
        throw new Error(payload.detail || "This integration is not available yet. Please try again later.");
      }
      window.location.href = payload.authorizationUrl;
    } catch (error) {
      setOauthConnectingApps((current) => ({ ...current, [providerKey]: false }));
      setConnectedAppErrors((current) => ({
        ...current,
        [providerKey]: error instanceof Error ? error.message : "This integration is not available yet.",
      }));
    }
  }

  function setManualSecret(providerKey: string, value: string) {
    setManualSecretValues((current) => ({ ...current, [providerKey]: value }));
  }

  async function connectManualSecretProvider(providerKey: string) {
    const secret = (manualSecretValues[providerKey] || "").trim();
    if (secret.length < 6) return;
    setManualSecretStatus((current) => ({ ...current, [providerKey]: "Connecting..." }));
    try {
      const response = await fetch(`${API_URL}/api/connected-apps/${providerKey}/accounts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ secret }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail || "Connection failed");
      }
      setManualSecretValues((current) => ({ ...current, [providerKey]: "" }));
      setManualSecretStatus((current) => ({ ...current, [providerKey]: "Connected" }));
      setConfiguringConnectedApp("");
      await loadIntegrations();
    } catch (error) {
      setManualSecretStatus((current) => ({
        ...current,
        [providerKey]: error instanceof Error ? error.message : "Connection failed",
      }));
    }
  }

  async function disconnectConnectedApp(providerKey: string) {
    try {
      await fetch(`${API_URL}/api/connected-apps/${providerKey}/disconnect`, {
        method: "POST",
        credentials: "include"
      });
      setOauthConnectingApps((current) => ({ ...current, [providerKey]: false }));
      setConnectedAppErrors((current) => {
        const next = { ...current };
        delete next[providerKey];
        return next;
      });
      await loadIntegrations();
    } catch {
      // Keep the current card state; manual refresh is still available.
    }
  }

  if (loading) {
    return (
      <main className="dashboard">
        <div className="dash-main loading-state">
          <Loader2 size={24} /> Loading workspace...
        </div>
      </main>
    );
  }

  const navItems = [
    { id: "office" as View, label: "Office", icon: BriefcaseBusiness },
    { id: "youtube-growth" as View, label: "YouTube Growth", icon: Video },
    { id: "tasks" as View, label: "Tasks", icon: ListTodo },
    { id: "activity" as View, label: "Activity", icon: Activity },
    { id: "my-teams" as View, label: "Your teams", icon: UsersRound },
    { id: "shared" as View, label: "Shared with me", icon: UsersRound }
  ];

  const bottomItems = [
    { id: "settings" as View, label: "Settings", icon: Settings },
    { id: "support" as View, label: "Support", icon: LifeBuoy }
  ];

  const displayName = [user?.first_name, user?.last_name].filter(Boolean).join(" ") || user?.email || "Teamora user";
  const youtubeProvider = connectedApps?.providers.find((provider) => provider.key === "youtube");
  const youtubeAccount = youtubeProvider?.accounts?.find((account) => account.isDefault) || youtubeProvider?.accounts?.[0];
  const youtubeChannelLabel = youtubeAccount?.label || youtubeAccount?.identifier || "";
  const youtubePublishingEnabled = Boolean(
    youtubeProvider?.capabilities.some((capability) => capability.key === "youtube.upload" && capability.granted)
      || youtubeAccount?.grantedCapabilities?.includes("youtube.upload")
  );

  return (
    <main className={`dashboard ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <aside className={`sidebar ${sidebarCollapsed ? "collapsed" : ""}`} aria-label="Workspace sidebar">
        <div className="sidebar-top">
          <Link className="dash-brand" href="/" aria-label="Teamora AI home">
            <img className="dash-logo brand-logo-mark" src="/images/teamora-ai-logo-mark.svg" alt="" />
            <span>Teamora AI</span>
          </Link>
          <button
            className="sidebar-toggle"
            type="button"
            aria-label={sidebarCollapsed ? "Открыть боковую панель" : "Закрыть боковую панель"}
            aria-expanded={!sidebarCollapsed}
            data-tooltip={sidebarCollapsed ? "Открыть боковую панель" : "Закрыть боковую панель"}
            onClick={() => setSidebarCollapsed((current) => !current)}
          >
            {sidebarCollapsed ? <PanelLeftOpen size={19} /> : <PanelLeftClose size={19} />}
          </button>
        </div>

        <button className="button new-team" type="button" title="New team" onClick={() => openTeams("ready")}>
          <span>
            <Plus size={15} /> New team
          </span>
          <ChevronDown size={15} />
        </button>

        <nav className="side-nav" aria-label="Workspace">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={`side-link ${
                  (item.id === "my-teams" && activeView === "my-teams") ||
                  (activeView === item.id && item.id !== "my-teams")
                    ? "active"
                    : ""
                }`}
                key={item.id}
                type="button"
                title={item.label}
                onClick={() => {
                  if (item.id === "my-teams") {
                    openTeams("ready");
                    return;
                  }
                  setActiveView(item.id);
                }}
              >
                <Icon size={19} />
                {item.label}
              </button>
            );
          })}
        </nav>

        {activeView === "office" && selectedOfficeTeamPayload && (
          <div className="office-team-strip" aria-label="Teamora AI Office team">
            <div className="office-team-head">
              <strong>Team</strong>
              <span>{Math.max(visibleOfficeAgents.length - 1, 0)} / {Math.max(visibleOfficeAgents.length - 1, 0)}</span>
            </div>
            <div className="office-team-list">
              {visibleOfficeAgents.map((agent) => (
                <button
                  className={`office-agent-chip ${selectedOfficeAgent === agent.id ? "active" : ""}`}
                  key={agent.id}
                  type="button"
                  aria-pressed={selectedOfficeAgent === agent.id}
                  onClick={() => selectOfficeAgent(agent.id)}
                >
                  <span
                    className={`office-agent-token ${agent.id === "all" ? "initial" : ""}`}
                    style={{ "--agent-color": agent.color } as CSSProperties}
                  >
                    {agent.id === "all" ? <span aria-hidden="true">T</span> : <Image src={agent.image} width={256} height={256} alt="" />}
                  </span>
                  <span>
                    <strong>{agent.name}</strong>
                    <small>{agent.role}</small>
                  </span>
                  <i className={agent.state === "online" ? "online" : ""} aria-hidden="true" />
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="sidebar-bottom">
          {bottomItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={`side-link ${activeView === item.id ? "active" : ""}`}
                key={item.id}
                type="button"
                title={item.label}
                onClick={() => setActiveView(item.id)}
              >
                <Icon size={19} />
                {item.label}
              </button>
            );
          })}
        </div>
      </aside>

      <section className={`dash-main ${activeView === "office" ? "dash-main-office" : ""}`}>
        {activeView !== "office" && (
          <div className="dash-top-account">
            <button className="account-button top-account-button" type="button" onClick={logout}>
              <span className="brand-mark">{displayName.slice(0, 1).toUpperCase()}</span>
              <span>
                <strong>{displayName}</strong>
                <small>Owner · No plan</small>
              </span>
              <LogOut size={16} />
            </button>
          </div>
        )}

        {activeView === "office" && (
          <section className="office-view" aria-label="Teamora AI Office">
            {selectedOfficeTeamPayload ? (
              <>
                <div className="office-exit-bar">
                  <button className="button office-exit-button" type="button" onClick={exitOfficeTeam}>
                    <LogOut size={16} /> Exit team
                  </button>
                </div>
                <iframe
                  ref={officeFrameRef}
                  className="office-full-frame"
                  src="/office/index.html?embed=dashboard&theme=dark"
                  title="Business AI office"
                  onLoad={() => {
                    sendOfficeTeam(selectedOfficeTeamPayload, activeConversation);
                    sendOfficeSelection(selectedOfficeAgent);
                    sendOfficeTheme(resolvedTheme);
                  }}
                />
              </>
            ) : (
              <div className="office-empty-wrap">
                <section className="shared-panel office-empty-panel">
                  <UsersRound size={32} />
                  <strong>No team selected</strong>
                  <p>Choose a ready team to open its Office and start working with agents.</p>
                  <button className="button solid" type="button" onClick={() => openTeams("ready")}>
                    <BriefcaseBusiness size={16} /> Choose Team
                  </button>
                </section>
              </div>
            )}
          </section>
        )}

        {activeView === "youtube-growth" && (
          <section className="dashboard-view youtube-growth-view">
            <YouTubeGrowthPanel
              connected={Boolean(youtubeProvider?.connected)}
              accountId={youtubeAccount?.id}
              connectionState={youtubeProvider?.connectionState}
              channelLabel={youtubeChannelLabel}
              publishingEnabled={youtubePublishingEnabled}
              onConnect={() => void connectOAuthProvider("youtube", { youtubeAccess: "growth" })}
              onEnablePublishing={() => void connectOAuthProvider("youtube", { youtubeAccess: "publisher" })}
              onManageConnection={() => {
                setActiveView("settings");
                setSettingsTab("connected");
                setConnectedAppsSearch("YouTube");
                setConnectedAppsFilter("all");
              }}
              onOpenTeam={() => openTeamOffice(findTeamById("youtube-growth-team") || youtubeGrowthTeam)}
            />
          </section>
        )}

        {activeView === "tasks" && (
          <section className="dashboard-view">
            <div className="view-head">
              <div>
                <p className="eyebrow">Queue</p>
                <h1>Tasks</h1>
              </div>
              <button
                className="button solid"
                type="button"
                onClick={addTask}
              >
                <Plus size={16} /> Add task
              </button>
            </div>
            <div className="task-board">
              {tasksLoading ? (
                <div className="shared-panel">
                  <Loader2 size={24} />
                  <strong>Loading tasks</strong>
                  <p>Preparing your workspace queue.</p>
                </div>
              ) : tasks.length ? (
                tasks.map((task) => (
                  <article className="task-row" key={task.id}>
                    <span className={`status-badge ${task.status.toLowerCase()}`}>{task.status}</span>
                    <div>
                      <strong>{task.title}</strong>
                      <small>{task.owner}</small>
                    </div>
                    <button className="button" type="button" onClick={() => cycleTaskStatus(task.id)}>
                      <Check size={15} /> Move
                    </button>
                  </article>
                ))
              ) : (
                <div className="shared-panel">
                  <ListTodo size={24} />
                  <strong>No tasks yet</strong>
                  <p>Create a task to add it to this workspace queue.</p>
                </div>
              )}
              {tasksError && (
                <div className="shared-panel">
                  <LifeBuoy size={24} />
                  <strong>Task sync issue</strong>
                  <p>{tasksError}</p>
                </div>
              )}
            </div>
          </section>
        )}

        {activeView === "activity" && (
          <section className="dashboard-view">
            <div className="view-head">
              <div>
                <p className="eyebrow">Live log</p>
                <h1>Activity</h1>
              </div>
              <button className="button" type="button" onClick={() => setActiveView("office")}>
                <Eye size={16} /> View office
              </button>
            </div>
            <div className="activity-list">
              {activityItems.map((item) => (
                <article className="activity-card" key={`${item.who}-${item.time}`}>
                  <span>{item.time}</span>
                  <div>
                    <strong>{item.who}</strong>
                    <p>{item.text}</p>
                  </div>
                </article>
              ))}
            </div>
          </section>
        )}

        {activeView === "my-teams" && (
          <section className="dashboard-view team-marketplace teams-history-page">
            <div className="view-head teams-view-head">
              <div>
                <p className="eyebrow">Workspace</p>
                <h1>Your Teams</h1>
              </div>
            </div>

            <nav className="market-tabs teams-tabs" aria-label="Team views">
              <button className={teamTab === "history" ? "active" : ""} type="button" onClick={() => setTeamTab("history")}>
                <Clock size={16} /> History ({conversations.length})
              </button>
              <button className={teamTab === "ready" ? "active" : ""} type="button" onClick={() => setTeamTab("ready")}>
                <Rocket size={16} /> Ready Teams ({readyTeamSource.length})
              </button>
              <button className={teamTab === "mine" ? "active" : ""} type="button" onClick={() => setTeamTab("mine")}>
                <BriefcaseBusiness size={16} /> My Teams ({myTeamSource.length})
              </button>
            </nav>

            {teamTab !== "history" && (
              <div className="team-directory-toolbar">
                <label className="searchbox teams-directory-search">
                  <Search size={17} />
                  <input value={teamSearch} onChange={(event) => setTeamSearch(event.target.value)} placeholder="Search teams..." />
                </label>
                <label className="team-category">
                  <span>Category</span>
                  <select value={teamCategory} onChange={(event) => setTeamCategory(event.target.value)}>
                    <option>All</option>
                    <option>Business</option>
                    <option>Strategy</option>
                    <option>CRM</option>
                    <option>Founder</option>
                    <option>Operations</option>
                    <option>Marketing</option>
                    <option>Instagram</option>
                    <option>Telegram</option>
                    <option>YouTube</option>
                    <option>Sales</option>
                    <option>Leads</option>
                    <option>Support</option>
                    <option>Tickets</option>
                  </select>
                </label>
                <div className="teams-view-toggle" aria-label="Team view mode">
                  <button
                    className={teamViewMode === "grid" ? "active" : ""}
                    type="button"
                    aria-label="Grid view"
                    aria-pressed={teamViewMode === "grid"}
                    onClick={() => setTeamViewMode("grid")}
                  >
                    <Grid3X3 size={17} />
                  </button>
                  <button
                    className={teamViewMode === "list" ? "active" : ""}
                    type="button"
                    aria-label="List view"
                    aria-pressed={teamViewMode === "list"}
                    onClick={() => setTeamViewMode("list")}
                  >
                    <List size={17} />
                  </button>
                </div>
              </div>
            )}

            {teamTab === "history" ? (
              visibleHistory.length ? (
                <div className="history-list">
                  {visibleHistory.map((conversation) => (
                    <HistoryCard
                      conversation={conversation}
                      key={conversation.id}
                      menuOpen={openHistoryMenu === conversation.id}
                      onDelete={() => deleteConversation(conversation)}
                      onMenuToggle={() => setOpenHistoryMenu(openHistoryMenu === conversation.id ? "" : conversation.id)}
                      onOpen={() => openConversationOffice(conversation)}
                      onRename={() => renameConversation(conversation)}
                    />
                  ))}
                </div>
              ) : (
                <StartNewChatCard onOpenReadyTeams={() => setTeamTab("ready")} />
              )
            ) : (
              <div className={`market-grid ${teamViewMode === "list" ? "team-list-mode" : ""}`}>
                {teamsLoading ? (
                  <div className="shared-panel">
                    <Loader2 size={24} />
                    <strong>Loading teams</strong>
                    <p>Preparing your workspace teams.</p>
                  </div>
                ) : filteredTeams.length ? (
                  filteredTeams.map((team) => {
                    const expanded = expandedTeam === team.id;
                    return (
                      <TeamCard
                        team={team}
                        key={team.id}
                        expanded={expanded}
                        onToggle={() => setExpandedTeam(expanded ? "" : team.id)}
                        onDetails={() => setDetailTeam(team)}
                        onHire={() => openTeamOffice(team)}
                      />
                    );
                  })
                ) : (
                  <div className="shared-panel">
                    <UsersRound size={24} />
                    <strong>No teams found</strong>
                    <p>{teamsError || "This workspace does not have teams in this view yet."}</p>
                  </div>
                )}
              </div>
            )}
          </section>
        )}

        {detailTeam && <TeamDetailsModal team={detailTeam} onClose={() => setDetailTeam(null)} onHire={() => hireTeam(detailTeam)} />}

        {deleteConversationTarget && (
          <div className="delete-chat-overlay" role="presentation" onClick={() => setDeleteConversationTarget(null)}>
            <section
              className="delete-chat-modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="delete-chat-title"
              onClick={(event) => event.stopPropagation()}
            >
              <h2 id="delete-chat-title">Удалить чат?</h2>
              <p>
                Это удалит <strong>{deleteConversationTarget.teamName}</strong>.
              </p>
              <p className="delete-chat-muted">
                Посетите <span>настройки</span> для удаления всех записей в памяти, сохраненных во время этого чата.
              </p>
              <div className="delete-chat-actions">
                <button className="button cancel-delete" type="button" onClick={() => setDeleteConversationTarget(null)}>
                  Отменить
                </button>
                <button className="button confirm-delete" type="button" onClick={confirmDeleteConversation}>
                  Удалить
                </button>
              </div>
            </section>
          </div>
        )}

        {activeView === "shared" && (
          <section className="dashboard-view shared-view">
            <div className="view-head">
              <div>
                <p className="eyebrow">Collaboration</p>
                <h1>Shared with me</h1>
              </div>
            </div>
            <div className="shared-panel">
              <Share2 size={28} />
              <strong>No shared teams yet</strong>
              <p>When someone invites you to a team, it will appear here.</p>
            </div>
          </section>
        )}

        {activeView === "settings" && (
          <section className="dashboard-view settings-view">
            <div className="view-head">
              <div>
                <p className="eyebrow">Account</p>
                <h1>Settings</h1>
              </div>
            </div>
            <div className="settings-layout">
              <nav className="settings-tabs" aria-label="Settings sections">
                {[
                  { id: "profile" as SettingsTab, label: "Profile", icon: User },
                  { id: "general" as SettingsTab, label: "General", icon: Settings },
                  { id: "billing" as SettingsTab, label: "Billing", icon: CreditCard },
                  { id: "notifications" as SettingsTab, label: "Notifications", icon: Bell },
                  { id: "memory" as SettingsTab, label: "Memory", icon: Database },
                  { id: "connected" as SettingsTab, label: "Connected Apps", icon: Plug }
                ].map((tab) => {
                  const Icon = tab.icon;
                  return (
                    <button
                      className={settingsTab === tab.id ? "active" : ""}
                      key={tab.id}
                      type="button"
                      onClick={() => setSettingsTab(tab.id)}
                    >
                      <Icon size={17} />
                      {tab.label}
                    </button>
                  );
                })}
                <div className="settings-divider" />
                <button className="settings-group" type="button">
                  <Settings size={17} />
                  Advanced
                  <ChevronDown size={15} />
                </button>
                {[
                  { id: "writing" as SettingsTab, label: "Writing style", icon: MessageCircle },
                  { id: "completion" as SettingsTab, label: "Completion checks", icon: Check },
                  { id: "developer" as SettingsTab, label: "Developer access", icon: Plug }
                ].map((tab) => {
                  const Icon = tab.icon;
                  return (
                    <button
                      className={`settings-subtab ${settingsTab === tab.id ? "active" : ""}`}
                      key={tab.id}
                      type="button"
                      onClick={() => setSettingsTab(tab.id)}
                    >
                      <Icon size={16} />
                      {tab.label}
                    </button>
                  );
                })}
              </nav>
              <div className="settings-panel">
                {renderSettingsPanel({
                  tab: settingsTab,
                  displayName,
                  user,
                  emailDigest,
                  setEmailDigest,
                  memoryEnabled,
                  setMemoryEnabled,
                  themeMode,
                  changeTheme,
                  telegramBotToken,
                  setTelegramBotToken,
                  telegramBotTarget,
                  setTelegramBotTarget,
                  telegramBotConnected,
                  telegramBotStatus,
                  instagramConnected,
                  instagramStatus,
                  connectedApps,
                  connectedAppsSearch,
                  setConnectedAppsSearch,
                  connectedAppsFilter,
                  setConnectedAppsFilter,
                  configuringConnectedApp,
                  setConfiguringConnectedApp,
                  manualSecretValues,
                  manualSecretStatus,
                  oauthConnectingApps,
                  connectedAppErrors,
                  shopifyConnectOpen,
                  setShopifyConnectOpen,
                  shopifyShopDomain,
                  setShopifyShopDomain,
                  setManualSecret,
                  connectTelegram,
                  connectOAuthProvider,
                  connectManualSecretProvider,
                  disconnectConnectedApp,
                  loadIntegrations
                })}
              </div>
            </div>
          </section>
        )}

        {activeView === "support" && (
          <section className="dashboard-view support-view">
            <div className="support-top">
              <div className="support-title">
                <span className="support-icon">
                  <LifeBuoy size={24} />
                </span>
                <div>
                  <h1>Support</h1>
                  <p>Describe your issue - we read every one.</p>
                </div>
              </div>
              <button className="button" type="button" onClick={() => setActiveView("my-teams")}>
                <ArrowLeft size={15} /> Back to list
              </button>
            </div>

            <button className="support-back" type="button" onClick={() => setActiveView("office")}>
              <ArrowLeft size={15} /> Back to team setup
            </button>

            <div className="support-contact-row">
              <a className="support-contact" href="mailto:support@teamly.to">
                <Mail size={20} />
                <span>
                  <small>Email</small>
                  support@teamly.to
                </span>
              </a>
              <a className="support-contact" href="https://t.me/" target="_blank" rel="noreferrer">
                <MessageCircle size={20} />
                <span>
                  <small>Telegram group</small>
                  Join Support Group
                </span>
              </a>
            </div>

            <form className="support-form" onSubmit={submitSupport}>
              <label className="support-field">
                Category
                <select value={supportCategory} onChange={(event) => setSupportCategory(event.target.value)}>
                  <option>Bug</option>
                  <option>Billing</option>
                  <option>Account</option>
                  <option>Feature request</option>
                </select>
              </label>
              <label className="support-field">
                Subject
                <input
                  maxLength={200}
                  value={supportSubject}
                  onChange={(event) => setSupportSubject(event.target.value)}
                  placeholder="Short summary of the issue"
                />
                <small>{supportSubject.length}/200</small>
              </label>
              <label className="support-field">
                Message
                <textarea
                  maxLength={5000}
                  value={supportMessage}
                  onChange={(event) => setSupportMessage(event.target.value)}
                  placeholder="What happened? Steps to reproduce, what you expected, anything else helpful."
                />
                <small>{supportMessage.length}/5000</small>
              </label>
              <div className="support-actions">
                <label className="button attach-button">
                  <Paperclip size={16} /> Attach
                  <input
                    type="file"
                    onChange={(event) => setAttachmentName(event.target.files?.[0]?.name || "")}
                  />
                </label>
                <button className="button solid" type="submit" disabled={!supportSubject.trim() || !supportMessage.trim()}>
                  <Send size={16} /> Send
                </button>
              </div>
              {attachmentName && <p className="support-note">Attached: {attachmentName}</p>}
              {supportStatus && <p className="support-success">{supportStatus}</p>}
            </form>
          </section>
        )}
      </section>
    </main>
  );
}

function StartNewChatCard({ onOpenReadyTeams }: { onOpenReadyTeams: () => void }) {
  return (
    <button className="market-card start-chat-card" type="button" onClick={onOpenReadyTeams}>
      <span className="team-symbol">
        <Clock size={22} />
      </span>
      <div>
        <h2>Start a new chat</h2>
        <p>
          Open a team and start chatting with your AI agents.
          <br />
          Your conversations will appear here automatically.
        </p>
      </div>
    </button>
  );
}

function HistoryCard({
  conversation,
  menuOpen,
  onDelete,
  onMenuToggle,
  onOpen,
  onRename
}: {
  conversation: ConversationSummary;
  menuOpen: boolean;
  onDelete: () => void;
  onMenuToggle: () => void;
  onOpen: () => void;
  onRename: () => void;
}) {
  return (
    <article className={`history-card ${menuOpen ? "menu-open" : ""}`}>
      <button className="history-card-open" type="button" onClick={onOpen}>
        <span className="team-symbol history-symbol">
          <BriefcaseBusiness size={21} />
        </span>
        <span className="history-card-main">
          <strong>{conversation.teamName}</strong>
          <small>{conversation.lastMessage}</small>
          <em>{formatConversationTime(conversation.updatedAt)}</em>
        </span>
        {conversation.unreadCount > 0 && <span className="unread-badge">{conversation.unreadCount}</span>}
      </button>
      <button
        className="history-more"
        type="button"
        aria-expanded={menuOpen}
        aria-label={`${conversation.teamName} options`}
        onClick={onMenuToggle}
      >
        ...
      </button>
      {menuOpen && (
        <div className="history-menu" role="menu">
          <button type="button" role="menuitem" onClick={onRename}>
            <Pencil size={16} /> Rename
          </button>
          <button className="danger" type="button" role="menuitem" onClick={onDelete}>
            <Trash2 size={16} /> Delete
          </button>
        </div>
      )}
    </article>
  );
}

function TeamCard({
  team,
  expanded,
  onToggle,
  onDetails,
  onHire
}: {
  team: TeamCardData;
  expanded: boolean;
  onToggle: () => void;
  onDetails: () => void;
  onHire: () => void;
}) {
  const TeamIcon = team.icon;
  const roster = completeTeamRoster(team);

  return (
    <article
      className={`market-card premium-team-card ${expanded ? "expanded" : ""}`}
      role="button"
      tabIndex={0}
      onClick={onToggle}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onToggle();
        }
      }}
    >
      <div className="market-card-head">
        <span className="team-symbol">
          <TeamIcon size={22} />
        </span>
        <div>
          <h2>{team.name}</h2>
          <small>{team.agents}</small>
        </div>
        <button
          className="expand-team"
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onToggle();
          }}
          aria-label={expanded ? `Collapse ${team.name}` : `Expand ${team.name}`}
        >
          <ChevronDown size={18} />
        </button>
      </div>

      <div className="market-roster" aria-label={`${team.name} agents`}>
        {roster.map((agent) => (
          <AgentMiniCard agent={agent} key={agent.name} />
        ))}
      </div>

      {expanded && (
        <div className="team-expanded-content" onClick={(event) => event.stopPropagation()}>
          <p className="team-description">{team.copy}</p>
          <div className="workflow-panel">
            <h3>Как работает</h3>
            <div className="workflow-list">
              {team.workflow.map((step, index) => (
                <WorkflowStep index={index} text={step} key={step} />
              ))}
            </div>
            <div className="output-box">
              <strong>Результат</strong>
              <span>{team.output}</span>
            </div>
          </div>

          <div className="team-card-actions">
            <button className="button detail-button" type="button" onClick={onDetails}>
              <Eye size={16} /> Подробнее
            </button>
            <button
              className="button solid team-hire"
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onHire();
              }}
            >
              <Rocket size={16} /> Open Office
            </button>
          </div>
        </div>
      )}
    </article>
  );
}

function AgentMiniCard({ agent }: { agent: AgentData }) {
  return (
    <span className="agent-mini-card" style={{ borderColor: `${agent.accent}24` }}>
      {agent.avatar ? (
        <Image src={agent.avatar} width={608} height={608} alt="" />
      ) : (
        <span className="agent-initials" style={{ color: agent.accent, background: `${agent.accent}12` }}>
          {agent.name.slice(0, 1)}
        </span>
      )}
      <strong>{agent.name}</strong>
    </span>
  );
}

function WorkflowStep({ index, text }: { index: number; text: string }) {
  return (
    <div className="workflow-step">
      <span>{index + 1}</span>
      <p>{text}</p>
    </div>
  );
}

function TeamDetailsModal({ team, onClose, onHire }: { team: TeamCardData; onClose: () => void; onHire: () => void }) {
  const TeamIcon = team.icon;

  return (
    <div className="team-detail-overlay" role="dialog" aria-modal="true" aria-label={`${team.name} details`} onClick={onClose}>
      <section className="team-detail-modal" onClick={(event) => event.stopPropagation()}>
        <header className="detail-head">
          <span className="team-symbol detail-symbol">
            <TeamIcon size={28} />
          </span>
          <div>
            <h2>{team.name}</h2>
            <p>
              <span>{team.category}</span>
              <UsersRound size={14} /> {team.agents}
            </p>
          </div>
          <button className="modal-close" type="button" onClick={onClose} aria-label="Close details">
            <X size={18} />
          </button>
        </header>

        <div className="detail-modal-body">
          <p className="detail-copy">{team.modalCopy}</p>

          <div className="detail-section">
            <h3>Участники</h3>
            <div className="detail-members">
              {team.roster.map((agent) => (
                <span className="detail-member" key={agent.name} style={{ borderColor: `${agent.accent}24` }}>
                  {agent.avatar ? (
                    <Image src={agent.avatar} width={608} height={608} alt="" />
                  ) : (
                    <span className="agent-initials" style={{ color: agent.accent, background: `${agent.accent}12` }}>
                      {agent.name.slice(0, 1)}
                    </span>
                  )}
                  <strong>{agent.name}</strong>
                  <small>{agent.role}</small>
                </span>
              ))}
            </div>
          </div>

          <div className="detail-section">
            <h3>Как работает</h3>
            <div className="detail-flow">
              {team.modalWorkflow.map((step, index) => (
                <article key={`${step.agent}-${step.path}`}>
                  <span>{index + 1}</span>
                  <div>
                    <strong>{step.agent}</strong>
                    <p>{step.text}</p>
                    <small>-&gt; {step.path}</small>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </div>

        <footer className="detail-footer">
          <button className="button solid detail-hire" type="button" onClick={onHire}>
            <Rocket size={16} /> Нанять эту команду
          </button>
        </footer>
      </section>
    </div>
  );
}

function renderSettingsPanel({
  tab,
  displayName,
  user,
  emailDigest,
  setEmailDigest,
  memoryEnabled,
  setMemoryEnabled,
  themeMode,
  changeTheme,
  telegramBotToken,
  setTelegramBotToken,
  telegramBotTarget,
  setTelegramBotTarget,
  telegramBotConnected,
  telegramBotStatus,
  instagramConnected,
  instagramStatus,
  connectedApps,
  connectedAppsSearch,
  setConnectedAppsSearch,
  connectedAppsFilter,
  setConnectedAppsFilter,
  configuringConnectedApp,
  setConfiguringConnectedApp,
  manualSecretValues,
  manualSecretStatus,
  oauthConnectingApps,
  connectedAppErrors,
  shopifyConnectOpen,
  setShopifyConnectOpen,
  shopifyShopDomain,
  setShopifyShopDomain,
  setManualSecret,
  connectTelegram,
  connectOAuthProvider,
  connectManualSecretProvider,
  disconnectConnectedApp,
  loadIntegrations
}: {
  tab: SettingsTab;
  displayName: string;
  user: UserData | null;
  emailDigest: boolean;
  setEmailDigest: (value: boolean) => void;
  memoryEnabled: boolean;
  setMemoryEnabled: (value: boolean) => void;
  themeMode: ThemeMode;
  changeTheme: (mode: ThemeMode) => void;
  telegramBotToken: string;
  setTelegramBotToken: (value: string) => void;
  telegramBotTarget: string;
  setTelegramBotTarget: (value: string) => void;
  telegramBotConnected: boolean;
  telegramBotStatus: string;
  instagramConnected: boolean;
  instagramStatus: string;
  connectedApps: ConnectedAppsData | null;
  connectedAppsSearch: string;
  setConnectedAppsSearch: (value: string) => void;
  connectedAppsFilter: ConnectedAppsFilter;
  setConnectedAppsFilter: (value: ConnectedAppsFilter) => void;
  configuringConnectedApp: string;
  setConfiguringConnectedApp: (value: string) => void;
  manualSecretValues: Record<string, string>;
  manualSecretStatus: Record<string, string>;
  oauthConnectingApps: Record<string, boolean>;
  connectedAppErrors: Record<string, string>;
  shopifyConnectOpen: boolean;
  setShopifyConnectOpen: (value: boolean) => void;
  shopifyShopDomain: string;
  setShopifyShopDomain: (value: string) => void;
  setManualSecret: (providerKey: string, value: string) => void;
  connectTelegram: (kind: "bot") => void;
  connectOAuthProvider: (providerKey: string, connectPayload?: Record<string, string>) => void | Promise<void>;
  connectManualSecretProvider: (providerKey: string) => void | Promise<void>;
  disconnectConnectedApp: (providerKey: string) => void | Promise<void>;
  loadIntegrations: () => void | Promise<void>;
}) {
  if (tab === "profile") {
    return (
      <div className="settings-page">
        <div className="settings-page-head">
          <h1>Profile</h1>
          <p>Account details and business context</p>
        </div>
        <section className="settings-hero-card">
          <span className="settings-avatar">{displayName.slice(0, 1).toUpperCase()}</span>
          <div>
            <h2>{displayName}</h2>
            <p>Owner · Team Lead</p>
            <span className="active-badge">Active</span>
          </div>
        </section>
        <section className="settings-block about-block">
          <div className="settings-block-head">
            <Image src="/images/member-man.png" width={608} height={608} alt="" />
            <div>
              <h2>About you</h2>
              <p>Help your agents understand your business</p>
            </div>
            <button className="button" type="button">
              <Paperclip size={15} /> Edit
            </button>
          </div>
          {["Your role", "What does your company do?", "Website", "Goals & challenges"].map((label) => (
            <div className="settings-line" key={label}>
              <span>{label}</span>
              <strong>-</strong>
            </div>
          ))}
        </section>
        <section className="settings-block">
          <h2>Account details</h2>
          <div className="settings-line">
            <span>Email</span>
            <strong>{user?.email || "-"}</strong>
          </div>
          <div className="settings-line">
            <span>Plan</span>
            <strong>No plan</strong>
          </div>
          <div className="settings-line">
            <span>Teams</span>
            <strong>0 / 0</strong>
          </div>
          <div className="settings-line">
            <span>Role</span>
            <strong>Owner</strong>
          </div>
        </section>
      </div>
    );
  }

  if (tab === "general") {
    return (
      <div className="settings-page">
        <div className="settings-page-head">
          <h1>General</h1>
          <p>Team name, appearance, and follow-up behavior</p>
        </div>
        <section className="settings-block">
          <h2>Identity</h2>
          <p>Choose how this team appears in your workspace.</p>
          <label className="settings-field">
            Team name
            <input defaultValue="My Team" />
          </label>
        </section>
        <section className="settings-block">
          <h2>Team status</h2>
          <span className="warning-badge">Not connected</span>
        </section>
        <section className="settings-block appearance-block">
          <h2>Appearance</h2>
          <div className="theme-segment">
            <button className={themeMode === "light" ? "active" : ""} type="button" onClick={() => changeTheme("light")}>
              <Sun size={15} /> Light
            </button>
            <button className={themeMode === "dark" ? "active" : ""} type="button" onClick={() => changeTheme("dark")}>
              <Moon size={15} /> Dark
            </button>
            <button className={themeMode === "auto" ? "active" : ""} type="button" onClick={() => changeTheme("auto")}>
              <Clock size={15} /> Auto
            </button>
          </div>
          <div className="theme-caption">
            <strong>Theme</strong>
            <span>Currently {themeMode} mode</span>
          </div>
        </section>
        <section className="settings-block">
          <h2>Agent follow-up</h2>
          <label className="settings-field small-field">
            Check for new work
            <select defaultValue="30 min">
              <option>15 min</option>
              <option>30 min</option>
              <option>1 hour</option>
            </select>
          </label>
          <label className="toggle-row plain-toggle">
            <span>
              <strong>Work without prompting</strong>
              <small>Agents wait for your next message</small>
            </span>
            <input type="checkbox" />
          </label>
        </section>
      </div>
    );
  }

  if (tab === "billing") {
    return (
      <div className="settings-page">
        <div className="settings-page-head">
          <h1>Billing</h1>
          <p>Plan and payment details</p>
        </div>
        <section className="settings-block">
          <h2>Current plan</h2>
          <div className="settings-line">
            <span>Plan</span>
            <strong>No plan</strong>
          </div>
          <div className="settings-line">
            <span>Credits</span>
            <strong>$0</strong>
          </div>
          <button className="button solid" type="button">
            Manage billing
          </button>
        </section>
      </div>
    );
  }

  if (tab === "notifications") {
    return (
      <div className="settings-page">
        <div className="settings-page-head">
          <h1>Notifications</h1>
          <p>Email updates for team activity</p>
        </div>
        <section className="settings-block notification-block">
          <div>
            <h2>My team updates</h2>
            <p>Request and readiness emails for custom teams</p>
          </div>
          <label className="switch">
            <input type="checkbox" checked={emailDigest} onChange={(event) => setEmailDigest(event.target.checked)} />
            <span />
          </label>
          <strong>{emailDigest ? "Enabled" : "Disabled"}</strong>
        </section>
      </div>
    );
  }

  if (tab === "memory") {
    return (
      <div className="settings-page">
        <div className="settings-page-head">
          <h1>Memory</h1>
          <p>Reusable business context for agents</p>
        </div>
        <section className="settings-block notification-block">
          <div>
            <h2>Workspace memory</h2>
            <p>Keep useful context for future Business AI work</p>
          </div>
          <label className="switch">
            <input type="checkbox" checked={memoryEnabled} onChange={(event) => setMemoryEnabled(event.target.checked)} />
            <span />
          </label>
          <strong>{memoryEnabled ? "Enabled" : "Disabled"}</strong>
        </section>
      </div>
    );
  }

  if (tab === "connected") {
    const providerCards: ConnectedProvider[] =
      connectedApps?.providers ?? [
        { key: "google", name: "Google", authType: "oauth2", status: user?.google_connected ? "Connected" : "Not Connected", connected: Boolean(user?.google_connected), connectedAt: null, accounts: [], capabilities: [] },
        { key: "telegram", name: "Telegram", authType: "bot_token", status: telegramBotConnected ? "Connected" : "Not Connected", connected: telegramBotConnected, connectedAt: null, accounts: [], capabilities: [] },
        { key: "instagram", name: "Instagram", authType: "meta_oauth2", status: instagramConnected ? "Connected" : "Not Connected", connected: instagramConnected, connectedAt: null, accounts: [], capabilities: [] },
        { key: "facebook", name: "Facebook", authType: "meta_oauth2", status: "Not Connected", connected: false, connectedAt: null, accounts: [], capabilities: [] },
        { key: "linkedin", name: "LinkedIn", authType: "oauth2", status: "Not Connected", connected: false, connectedAt: null, accounts: [], capabilities: [] },
        { key: "youtube", name: "YouTube", authType: "oauth2", status: "Not Connected", connected: false, connectedAt: null, accounts: [], capabilities: [] },
        { key: "shopify", name: "Shopify", authType: "oauth2", status: "Not Connected", connected: false, connectedAt: null, accounts: [], capabilities: [] }
      ];
    const providersByKey = new Map(providerCards.map((provider) => [provider.key, provider]));
    const appCards = buildConnectedAppCards(providersByKey, {
      google: Boolean(user?.google_connected || providersByKey.get("google")?.connected),
      telegram: Boolean(telegramBotConnected || providersByKey.get("telegram")?.connected),
      instagram: Boolean(instagramConnected || providersByKey.get("instagram")?.connected),
      userEmail: user?.email || "",
      telegramTarget: telegramBotTarget,
      telegramStatus: telegramBotStatus,
      instagramStatus,
      connecting: oauthConnectingApps,
      errors: connectedAppErrors
    });
    const connectedCount = appCards.filter((card) => card.connected).length;
    const filteredCards = appCards.filter((card) => {
      const matchesSearch = `${card.title} ${card.description} ${card.capabilities.join(" ")} ${(card.requirements || []).join(" ")}`
        .toLowerCase()
        .includes(connectedAppsSearch.trim().toLowerCase());
      const matchesFilter =
        connectedAppsFilter === "all" ||
        (connectedAppsFilter === "connected" && card.connected) ||
        (connectedAppsFilter === "not_connected" && !card.connected);
      return matchesSearch && matchesFilter;
    });
    const secretModalCard = appCards.find((card) => card.providerKey === configuringConnectedApp && card.action === "secret") || null;
    const shopifyModalCard = appCards.find((card) => card.providerKey === "shopify") || null;
    const openShopifyConnect = () => {
      setShopifyShopDomain(defaultShopifyDomain(providersByKey.get("shopify")));
      setShopifyConnectOpen(true);
    };
    const closeShopifyConnect = () => {
      setShopifyConnectOpen(false);
      setShopifyShopDomain("");
    };
    return (
      <div className="settings-page connected-apps-page">
        <div className="connected-apps-head">
          <div>
            <h1>Connected Apps</h1>
            <p>Connect your favorite apps and unlock powerful automation with your AI agents.</p>
          </div>
          <div className="connected-head-actions">
            <section className="connected-summary-card">
              <span className="connected-summary-icon">
                <Plug size={18} />
              </span>
              <div>
                <strong>{connectedCount} of {appCards.length} connected</strong>
                <p>Workspace integrations</p>
              </div>
            </section>
            <button className="connected-refresh-button" type="button" onClick={loadIntegrations}>
              <Clock size={15} /> Refresh
            </button>
          </div>
        </div>
        <div className="connected-toolbar">
          <label className="connected-search">
            <Search size={16} />
            <input
              type="search"
              name="rebly-connected-apps-search"
              value={connectedAppsSearch}
              onChange={(event) => setConnectedAppsSearch(event.target.value)}
              placeholder="Search apps..."
              autoComplete="off"
              autoCorrect="off"
              spellCheck={false}
            />
          </label>
          <div className="connected-filter" role="tablist" aria-label="Connected apps filter">
            {[
              ["all", "All"],
              ["connected", "Connected"],
              ["not_connected", "Not connected"]
            ].map(([value, label]) => (
              <button
                className={connectedAppsFilter === value ? "active" : ""}
                key={value}
                type="button"
                onClick={() => setConnectedAppsFilter(value as ConnectedAppsFilter)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="connected-view-toggle" aria-label="Connected apps view">
            <button className="active" type="button" aria-pressed="true" title="Grid view">
              <Grid3X3 size={15} />
            </button>
            <button type="button" aria-pressed="false" title="List view">
              <List size={16} />
            </button>
          </div>
        </div>
        <div className="connected-app-list">
          {filteredCards.map((card) => {
            const isTelegram = card.providerKey === "telegram";
            const isManual = card.action === "manual";
            const isSecret = card.action === "secret";
            const isShopify = card.providerKey === "shopify";
            const isConfiguring = configuringConnectedApp === card.providerKey;
            return (
              <ConnectionCard
                key={card.key}
                card={card}
                token={isTelegram ? telegramBotToken : undefined}
                setToken={isTelegram ? setTelegramBotToken : undefined}
                target={isTelegram ? telegramBotTarget : undefined}
                setTarget={isTelegram ? setTelegramBotTarget : undefined}
                tokenLabel="Bot Token"
                tokenPlaceholder="Bot Token"
                targetPlaceholder="Channel / Group Username or ID"
                configuring={isManual && isConfiguring}
                onConnect={() => {
                  if (card.action === "disabled") return;
                  setConnectedAppsSearch("");
                  setConnectedAppsFilter("all");
                  if ((isManual || isSecret) && !isConfiguring) {
                    setConfiguringConnectedApp(card.providerKey);
                    return;
                  }
                  if (isTelegram) connectTelegram("bot");
                  else if (isShopify) openShopifyConnect();
                  else connectOAuthProvider(card.providerKey);
                }}
                onReconnect={() => {
                  setConnectedAppsSearch("");
                  setConnectedAppsFilter("all");
                  if (isManual || isSecret) {
                    setConfiguringConnectedApp(card.providerKey);
                    return;
                  }
                  if (isShopify) openShopifyConnect();
                  else connectOAuthProvider(card.providerKey);
                }}
                onDisconnect={() => {
                  setConfiguringConnectedApp("");
                  disconnectConnectedApp(card.providerKey);
                }}
                onCancelConfigure={() => setConfiguringConnectedApp("")}
              />
            );
          })}
        </div>
        <section className="connected-security">
          <span className="connected-security-icon">
            <Check size={17} />
          </span>
          <div>
            <strong>Your data is safe and secure</strong>
            <p>OAuth tokens are encrypted on the backend. The frontend never receives access tokens.</p>
          </div>
          <button className="connected-security-link" type="button">
            Learn more
          </button>
        </section>
        {secretModalCard && (
          <ApiKeyConnectModal
            card={secretModalCard}
            secret={manualSecretValues[secretModalCard.providerKey] || ""}
            statusText={manualSecretStatus[secretModalCard.providerKey]}
            onChange={(value) => setManualSecret(secretModalCard.providerKey, value)}
            onConnect={() => connectManualSecretProvider(secretModalCard.providerKey)}
            onClose={() => setConfiguringConnectedApp("")}
          />
        )}
        {shopifyConnectOpen && shopifyModalCard && (
          <ShopifyConnectModal
            card={shopifyModalCard}
            shopDomain={shopifyShopDomain}
            statusText={connectedAppErrors.shopify}
            isConnecting={Boolean(oauthConnectingApps.shopify)}
            onChange={setShopifyShopDomain}
            onConnect={(shopDomain) => connectOAuthProvider("shopify", { shopDomain })}
            onClose={closeShopifyConnect}
          />
        )}
      </div>
    );
  }

  if (tab === "writing") {
    return (
      <div className="settings-page">
        <div className="settings-page-head">
          <h1>Writing style</h1>
          <p>Choose how agents format replies by default</p>
        </div>
        <section className="settings-block">
          <h2>Writing style</h2>
          <p>Choose how agents format replies by default, without changing the team setup.</p>
        </section>
        <div className="writing-grid">
          {[
            ["Default", "Use the team's normal instructions."],
            ["Terse", "Short answers without preamble."],
            ["Verbose", "Explain reasoning and tradeoffs clearly."],
            ["Formal", "Use a formal register."],
            ["Custom", "Use your own markdown instructions."]
          ].map(([name, copy], index) => (
            <button className={`writing-card ${index === 0 ? "active" : ""}`} type="button" key={name}>
              <h2>{name} {index === 0 && <Check size={16} />}</h2>
              <p>{copy}</p>
            </button>
          ))}
        </div>
        <button className="button solid save-writing" type="button">
          Save
        </button>
      </div>
    );
  }

  return (
    <div className="settings-page">
      <div className="settings-page-head">
        <h1>{tab === "completion" ? "Completion checks" : "Developer access"}</h1>
        <p>{tab === "completion" ? "Review rules before work is marked done" : "API keys and technical controls"}</p>
      </div>
      <section className="settings-block">
        <h2>{tab === "completion" ? "Checks" : "Access"}</h2>
        <p>{tab === "completion" ? "Require agents to confirm output quality before closing work." : "Developer controls will appear here when enabled."}</p>
      </section>
    </div>
  );
}

function formatConnectedDate(value: string | null) {
  if (!value) return "Not connected";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function firstConnectedAccount(providers: Map<string, ConnectedProvider>, key: string) {
  return providers.get(key)?.accounts?.[0] || null;
}

function metadataValue(account: ConnectedAccount | null, key: string) {
  const value = account?.metadata?.[key];
  return value === null || value === undefined ? "" : String(value);
}

function accountValue(account: ConnectedAccount | null, fallback = "") {
  return account?.label || fallback || account?.identifier || "";
}

function normalizeShopifyDomain(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\//, "")
    .replace(/\/.*$/, "")
    .replace(/\.+$/, "");
}

function isShopifyDomain(value: string) {
  return /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.myshopify\.com$/i.test(normalizeShopifyDomain(value));
}

function defaultShopifyDomain(provider: ConnectedProvider | undefined) {
  const account = provider?.accounts.find((candidate) => candidate.isDefault);
  if (!account) return "";
  const candidates = [
    metadataValue(account, "shopDomain"),
    metadataValue(account, "shop_domain"),
    account.identifier,
    account.label || "",
  ];
  return candidates.map(normalizeShopifyDomain).find(isShopifyDomain) || "";
}

function asHandle(value: string) {
  const clean = value.trim();
  if (!clean) return "";
  return clean.startsWith("@") ? clean : `@${clean}`;
}

function telegramBotFromStatus(statusText: string) {
  const match = statusText.match(/@[\w_]+/);
  return match?.[0] || "";
}

function buildConnectedAppCards(
  providers: Map<string, ConnectedProvider>,
  overrides: {
    google: boolean;
    telegram: boolean;
    instagram: boolean;
    userEmail: string;
    telegramTarget: string;
    telegramStatus: string;
    instagramStatus: string;
    connecting: Record<string, boolean>;
    errors: Record<string, string>;
  }
): ConnectedAppCardData[] {
  const providerConnected = (key: string) => {
    if (key === "google") return overrides.google;
    if (key === "telegram") return overrides.telegram;
    if (key === "instagram") return overrides.instagram;
    return Boolean(providers.get(key)?.connected);
  };
  const connectedAt = (key: string) => providers.get(key)?.connectedAt || null;
  const connectionState = (key: string) => {
    if (overrides.connecting[key]) return "connecting";
    if (overrides.errors[key]) return "error";
    return providers.get(key)?.connectionState || (providerConnected(key) ? "connected" : "not_connected");
  };
  const connectionError = (key: string) => overrides.errors[key] || providers.get(key)?.lastError || undefined;
  const googleAccount = firstConnectedAccount(providers, "google");
  const telegramAccount = firstConnectedAccount(providers, "telegram");
  const instagramAccount = firstConnectedAccount(providers, "instagram");
  const facebookAccount = firstConnectedAccount(providers, "facebook");
  const linkedinAccount = firstConnectedAccount(providers, "linkedin");
  const youtubeAccount = firstConnectedAccount(providers, "youtube");
  const telegramBot = asHandle(metadataValue(telegramAccount, "botUsername") || telegramBotFromStatus(overrides.telegramStatus));
  const telegramTarget = accountValue(telegramAccount, overrides.telegramTarget);
  const instagramUsername = asHandle(metadataValue(instagramAccount, "username") || accountValue(instagramAccount));
  const instagramBusiness = metadataValue(instagramAccount, "businessAccount") || metadataValue(instagramAccount, "pageName");
  const facebookPage = metadataValue(facebookAccount, "pageName") || accountValue(facebookAccount);
  const linkedinCompany = metadataValue(linkedinAccount, "company");
  const youtubeChannel = accountValue(youtubeAccount);
  const catalogCards: ConnectedAppCardData[] = [
    {
      key: "google",
      providerKey: "google",
      title: "Google Workspace",
      description: "Connect Google Workspace so agents can work with email, calendar, files, docs, and spreadsheets.",
      capabilities: ["Gmail", "Drive", "Docs", "Sheets", "Calendar", "Gmail Send", "CRM"],
      logo: "G",
      logoUrl: "https://cdn.simpleicons.org/google",
      logoTone: "google",
      connected: providerConnected("google"),
      connectedAt: connectedAt("google"),
      connectedLabel: "Connected as",
      connectedValue: accountValue(googleAccount, overrides.userEmail),
      connectLabel: "Connect with Google",
      action: "oauth"
    },
    {
      key: "telegram",
      providerKey: "telegram",
      title: "Telegram Bot",
      description: "Connect a Telegram bot to publish approved messages to your channel or group.",
      capabilities: ["Messages", "Photos", "Videos", "Schedule", "Groups"],
      logo: "T",
      logoUrl: "https://cdn.simpleicons.org/telegram",
      logoTone: "telegram",
      connected: providerConnected("telegram"),
      connectedAt: connectedAt("telegram"),
      connectedLabel: "Connected as",
      connectedValue: telegramBot,
      connectedDetails: telegramTarget ? [{ label: "Publishing to", value: telegramTarget }] : [],
      statusDetail: overrides.telegramStatus,
      connectLabel: "Verify & Connect",
      action: "manual"
    },
    {
      key: "instagram",
      providerKey: "instagram",
      title: "Instagram",
      description: "Connect Instagram so agents can prepare posts, comments, stories, reels, and campaign follow-up.",
      capabilities: ["Images", "Reels", "Stories", "Carousels", "Comments", "Insights"],
      logo: "I",
      logoUrl: "https://cdn.simpleicons.org/instagram",
      logoTone: "instagram",
      connected: providerConnected("instagram"),
      connectedAt: connectedAt("instagram"),
      connectedLabel: "Connected as",
      connectedValue: instagramUsername || accountValue(instagramAccount),
      connectedDetails: instagramBusiness ? [{ label: "Business Account", value: instagramBusiness }] : [],
      statusDetail: overrides.instagramStatus,
      connectLabel: "Connect with Meta",
      action: "oauth"
    },
    {
      key: "facebook",
      providerKey: "facebook",
      title: "Facebook Page",
      description: "Connect a Facebook Page for publishing, comments, videos, and Messenger workflows.",
      capabilities: ["Posts", "Photos", "Videos", "Comments"],
      logo: "f",
      logoUrl: "https://cdn.simpleicons.org/facebook",
      logoTone: "facebook",
      connected: providerConnected("facebook"),
      connectedAt: connectedAt("facebook"),
      connectedLabel: "Facebook Page",
      connectedValue: facebookPage,
      connectLabel: "Connect with Meta",
      action: "oauth"
    },
    {
      key: "linkedin",
      providerKey: "linkedin",
      title: "LinkedIn",
      description: "Connect LinkedIn to publish company or member updates and review performance signals.",
      capabilities: ["Posts", "Images", "Analytics", "Company"],
      logo: "in",
      logoUrl: "https://cdn.jsdelivr.net/npm/simple-icons@v13/icons/linkedin.svg",
      logoTone: "linkedin",
      connected: providerConnected("linkedin"),
      connectedAt: connectedAt("linkedin"),
      connectedLabel: "Connected as",
      connectedValue: accountValue(linkedinAccount),
      connectedDetails: linkedinCompany ? [{ label: "Company", value: linkedinCompany }] : [],
      connectLabel: "Connect with LinkedIn",
      action: "oauth"
    },
    {
      key: "youtube",
      providerKey: "youtube",
      title: "YouTube",
      description: "Connect a YouTube channel for source-backed research and owned-channel analytics. Publishing is an explicit permission upgrade.",
      capabilities: ["Research", "Channel analytics", "Approved upload"],
      logo: "YT",
      logoUrl: "https://cdn.simpleicons.org/youtube",
      logoTone: "youtube",
      connected: providerConnected("youtube"),
      connectedAt: connectedAt("youtube"),
      connectedLabel: "Connected channel",
      connectedValue: youtubeChannel,
      connectLabel: "Connect with Google",
      action: "oauth"
    },
    {
      key: "shopify",
      providerKey: "shopify",
      title: "Shopify",
      description: "Connect Shopify to sync products, orders, customers, inventory, and storefront workflows.",
      capabilities: ["Products", "Orders", "Customers", "Inventory", "Discounts", "Analytics"],
      logo: "S",
      logoUrl: "https://cdn.simpleicons.org/shopify",
      logoTone: "shopify",
      connected: providerConnected("shopify"),
      connectedAt: connectedAt("shopify"),
      connectedLabel: "Store",
      connectedValue: accountValue(firstConnectedAccount(providers, "shopify")),
      connectLabel: "Connect",
      action: "oauth"
    },
  ];
  const extraCatalogCards: ConnectedAppCardData[] = [
    {
      key: "tiktok",
      providerKey: "tiktok",
      title: "TikTok",
      description: "Connect TikTok to plan short-form video publishing, comments, trends, and campaign analytics.",
      capabilities: ["Videos", "Comments", "Trends", "Analytics", "Scheduling"],
      logo: "T",
      logoUrl: "https://cdn.simpleicons.org/tiktok",
      logoTone: "tiktok",
      connected: providerConnected("tiktok"),
      connectedAt: connectedAt("tiktok"),
      connectedLabel: "Account",
      connectedValue: accountValue(firstConnectedAccount(providers, "tiktok")),
      connectLabel: "Connect",
      action: "oauth"
    },
    {
      key: "x",
      providerKey: "x",
      title: "X",
      description: "Connect X to draft posts, monitor replies, track mentions, and coordinate brand activity.",
      capabilities: ["Posts", "Replies", "Mentions", "Analytics"],
      logo: "X",
      logoUrl: "https://cdn.simpleicons.org/x",
      logoTone: "x",
      connected: providerConnected("x"),
      connectedAt: connectedAt("x"),
      connectedLabel: "Account",
      connectedValue: accountValue(firstConnectedAccount(providers, "x")),
      connectLabel: "Connect",
      action: "oauth"
    },
    {
      key: "discord",
      providerKey: "discord",
      title: "Discord",
      description: "Connect a Discord account to identify the user and view servers they can access. Channel posting needs a separate bot or webhook installation.",
      capabilities: ["Profile", "Email", "Servers"],
      logo: "D",
      logoUrl: "https://cdn.simpleicons.org/discord",
      logoTone: "discord",
      connected: providerConnected("discord"),
      connectedAt: connectedAt("discord"),
      connectedLabel: "Account",
      connectedValue: accountValue(firstConnectedAccount(providers, "discord")),
      connectLabel: "Connect",
      action: "oauth"
    },
    {
      key: "slack",
      providerKey: "slack",
      title: "Slack",
      description: "Connect Slack to route internal updates, approvals, alerts, and agent handoffs.",
      capabilities: ["Channels", "Alerts", "Approvals", "Threads"],
      logo: "S",
      logoUrl: "https://cdn.simpleicons.org/slack",
      logoTone: "slack",
      connected: providerConnected("slack"),
      connectedAt: connectedAt("slack"),
      connectedLabel: "Workspace",
      connectedValue: accountValue(firstConnectedAccount(providers, "slack")),
      connectLabel: "Connect",
      action: "oauth"
    },
    {
      key: "notion",
      providerKey: "notion",
      title: "Notion",
      description: "Connect Notion to sync docs, tasks, CRM databases, briefs, and team knowledge.",
      capabilities: ["Docs", "Databases", "Tasks", "Knowledge"],
      logo: "N",
      logoUrl: "https://cdn.simpleicons.org/notion",
      logoTone: "notion",
      connected: providerConnected("notion"),
      connectedAt: connectedAt("notion"),
      connectedLabel: "Workspace",
      connectedValue: accountValue(firstConnectedAccount(providers, "notion")),
      connectLabel: "Connect",
      action: "oauth"
    },
    {
      key: "github",
      providerKey: "github",
      title: "GitHub",
      description: "Connect GitHub to inspect repos, issues, pull requests, releases, and engineering activity.",
      capabilities: ["Repos", "Issues", "Pull Requests", "Releases"],
      logo: "GH",
      logoUrl: "https://cdn.simpleicons.org/github",
      logoTone: "github",
      connected: providerConnected("github"),
      connectedAt: connectedAt("github"),
      connectedLabel: "Organization",
      connectedValue: accountValue(firstConnectedAccount(providers, "github")),
      connectLabel: "Connect",
      action: "oauth"
    },
    {
      key: "dropbox",
      providerKey: "dropbox",
      title: "Dropbox",
      description: "Connect Dropbox to search files, organize folders, share assets, and build knowledge bases.",
      capabilities: ["Files", "Folders", "Sharing", "Search"],
      logo: "D",
      logoUrl: "https://cdn.simpleicons.org/dropbox",
      logoTone: "dropbox",
      connected: providerConnected("dropbox"),
      connectedAt: connectedAt("dropbox"),
      connectedLabel: "Account",
      connectedValue: accountValue(firstConnectedAccount(providers, "dropbox")),
      connectLabel: "Connect",
      action: "oauth"
    },
    {
      key: "onedrive",
      providerKey: "onedrive",
      title: "OneDrive",
      description: "Connect OneDrive to sync Microsoft files, folders, documents, and team resources.",
      capabilities: ["Files", "Folders", "Docs", "Sharing"],
      logo: "OD",
      logoUrl: "https://cdn.simpleicons.org/microsoftonedrive",
      logoTone: "onedrive",
      connected: providerConnected("onedrive"),
      connectedAt: connectedAt("onedrive"),
      connectedLabel: "Account",
      connectedValue: accountValue(firstConnectedAccount(providers, "onedrive")),
      connectLabel: "Connect",
      action: "oauth"
    },
    {
      key: "stripe",
      providerKey: "stripe",
      title: "Stripe",
      description: "Connect Stripe to review payments, subscriptions, customers, invoices, and revenue signals.",
      capabilities: ["Payments", "Customers", "Invoices", "Revenue"],
      logo: "S",
      logoUrl: "https://cdn.simpleicons.org/stripe",
      logoTone: "stripe",
      connected: providerConnected("stripe"),
      connectedAt: connectedAt("stripe"),
      connectedLabel: "Account",
      connectedValue: accountValue(firstConnectedAccount(providers, "stripe")),
      connectLabel: "Connect",
      action: "oauth"
    },
    {
      key: "openai",
      providerKey: "openai",
      title: "OpenAI",
      description: "Connect OpenAI to manage AI workflows, prompts, automation outputs, and model-powered tools.",
      capabilities: ["Models", "Prompts", "Tools", "Automation"],
      logo: "AI",
      logoUrl: "https://cdn.simpleicons.org/openai",
      logoTone: "openai",
      connected: providerConnected("openai"),
      connectedAt: connectedAt("openai"),
      connectedLabel: "Workspace",
      connectedValue: accountValue(firstConnectedAccount(providers, "openai")),
      connectLabel: "Add API Key",
      action: "secret"
    },
    {
      key: "claude",
      providerKey: "claude",
      title: "Claude",
      description: "Connect Claude to coordinate AI writing, research, reasoning, and team assistant workflows.",
      capabilities: ["Models", "Writing", "Research", "Reasoning"],
      logo: "C",
      logoUrl: "https://cdn.simpleicons.org/claude",
      logoTone: "claude",
      connected: providerConnected("claude"),
      connectedAt: connectedAt("claude"),
      connectedLabel: "Workspace",
      connectedValue: accountValue(firstConnectedAccount(providers, "claude")),
      connectLabel: "Add API Key",
      action: "secret"
    },
    {
      key: "zapier",
      providerKey: "zapier",
      title: "Zapier",
      description: "Connect Zapier to trigger cross-app automations, webhooks, tasks, and operational workflows.",
      capabilities: ["Zaps", "Webhooks", "Tasks", "Automation"],
      logo: "Z",
      logoUrl: "https://cdn.simpleicons.org/zapier",
      logoTone: "zapier",
      connected: providerConnected("zapier"),
      connectedAt: connectedAt("zapier"),
      connectedLabel: "Workspace",
      connectedValue: accountValue(firstConnectedAccount(providers, "zapier")),
      connectLabel: "Add Webhook",
      action: "secret"
    },
  ];
  return [...catalogCards, ...extraCatalogCards].map((card) => ({
    ...card,
    connectionState: connectionState(card.providerKey),
    errorMessage: connectionError(card.providerKey),
  }));
}

function ApiKeyConnectModal({
  card,
  secret,
  statusText,
  onChange,
  onConnect,
  onClose,
}: {
  card: ConnectedAppCardData;
  secret: string;
  statusText?: string;
  onChange: (value: string) => void;
  onConnect: () => void | Promise<void>;
  onClose: () => void;
}) {
  const fieldLabel = card.providerKey === "zapier" ? "Webhook URL" : "API Key";
  const placeholder = card.providerKey === "zapier" ? "https://hooks.zapier.com/..." : "Paste API key";
  return (
    <div className="api-key-overlay" role="dialog" aria-modal="true" aria-label={`${card.title} connection`} onClick={onClose}>
      <section className="api-key-modal" onClick={(event) => event.stopPropagation()}>
        <button className="modal-close" type="button" onClick={onClose} aria-label="Close">
          <X size={18} />
        </button>
        <div className="api-key-modal-head">
          <span className={`app-logo app-logo-${card.logoTone}`}>
            <img
              src={card.logoUrl}
              alt=""
              onError={(event) => {
                event.currentTarget.style.display = "none";
                const fallback = event.currentTarget.nextElementSibling as HTMLElement | null;
                if (fallback) fallback.style.display = "inline";
              }}
            />
            <span>{card.logo}</span>
          </span>
          <div>
            <h2>{card.title}</h2>
            <span>{fieldLabel}</span>
          </div>
        </div>
        <label className="api-key-field">
          <span>{fieldLabel}</span>
          <input
            type="password"
            value={secret}
            onChange={(event) => onChange(event.target.value)}
            placeholder={placeholder}
            autoComplete="new-password"
            autoCorrect="off"
            spellCheck={false}
          />
        </label>
        {statusText && <small className="api-key-status">{statusText}</small>}
        <div className="api-key-actions">
          <button className="button" type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="button solid" type="button" onClick={onConnect} disabled={secret.trim().length < 6}>
            Connect
          </button>
        </div>
      </section>
    </div>
  );
}

function ShopifyConnectModal({
  card,
  shopDomain,
  statusText,
  isConnecting,
  onChange,
  onConnect,
  onClose,
}: {
  card: ConnectedAppCardData;
  shopDomain: string;
  statusText?: string;
  isConnecting: boolean;
  onChange: (value: string) => void;
  onConnect: (shopDomain: string) => void | Promise<void>;
  onClose: () => void;
}) {
  const normalizedDomain = normalizeShopifyDomain(shopDomain);
  const validDomain = isShopifyDomain(normalizedDomain);
  const validationMessage = shopDomain.trim() && !validDomain ? "Enter a valid .myshopify.com store domain." : statusText;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!validDomain || isConnecting) return;
    void onConnect(normalizedDomain);
  }

  return (
    <div className="api-key-overlay" role="dialog" aria-modal="true" aria-label="Connect Shopify" onClick={onClose}>
      <section className="api-key-modal" onClick={(event) => event.stopPropagation()}>
        <button className="modal-close" type="button" onClick={onClose} aria-label="Close">
          <X size={18} />
        </button>
        <div className="api-key-modal-head">
          <span className={`app-logo app-logo-${card.logoTone}`}>
            <img
              src={card.logoUrl}
              alt=""
              onError={(event) => {
                event.currentTarget.style.display = "none";
              }}
            />
            <span>{card.logo}</span>
          </span>
          <div>
            <h2>Connect Shopify</h2>
            <span>Enter the store domain before continuing to Shopify.</span>
          </div>
        </div>
        <form onSubmit={submit}>
          <label className="api-key-field">
            <span>Store domain</span>
            <input
              type="text"
              name="rebly-shopify-store-domain"
              value={shopDomain}
              onChange={(event) => onChange(event.target.value)}
              placeholder="your-store.myshopify.com"
              autoComplete="url"
              autoCorrect="off"
              autoCapitalize="none"
              inputMode="url"
              spellCheck={false}
              autoFocus
              aria-invalid={Boolean(shopDomain.trim() && !validDomain)}
              aria-describedby="shopify-domain-help"
            />
          </label>
          <small id="shopify-domain-help" className={validationMessage ? "api-key-status" : "shopify-domain-help"}>
            {validationMessage || "Use the .myshopify.com domain shown in your Shopify admin."}
          </small>
          <div className="api-key-actions">
            <button className="button" type="button" onClick={onClose}>
              Cancel
            </button>
            <button className="button solid" type="submit" disabled={!validDomain || isConnecting}>
              {isConnecting ? "Connecting..." : "Continue to Shopify"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

function ConnectionCard({
  card,
  token,
  setToken,
  target,
  setTarget,
  tokenLabel,
  tokenPlaceholder,
  targetPlaceholder,
  statusText,
  configuring,
  onConnect,
  onReconnect,
  onDisconnect,
  onCancelConfigure
}: {
  card: ConnectedAppCardData;
  token?: string;
  setToken?: (value: string) => void;
  target?: string;
  setTarget?: (value: string) => void;
  tokenLabel?: string;
  tokenPlaceholder?: string;
  targetPlaceholder?: string;
  statusText?: string;
  configuring?: boolean;
  onConnect?: () => void;
  onReconnect?: () => void;
  onDisconnect?: () => void;
  onCancelConfigure?: () => void;
}) {
  const isTokenCard = Boolean(setToken && onConnect);
  const canSubmitToken = !isTokenCard || Boolean(token && token.trim().length >= (setTarget ? 9 : 6) && (!setTarget || target));
  const normalizedState = card.connectionState || (card.connected ? "connected" : "not_connected");
  const statusLabel =
    normalizedState === "connecting"
      ? "Connecting"
      : normalizedState === "connected"
        ? "Connected"
        : normalizedState === "expired"
          ? "Expired"
          : normalizedState === "reconnect_required"
            ? "Reconnect Required"
            : normalizedState === "error"
              ? "Error"
              : normalizedState === "unavailable"
                ? "Unavailable"
                : "Not connected";
  const statusTone =
    normalizedState === "connected"
      ? "connected"
      : normalizedState === "connecting"
        ? "connecting"
        : normalizedState === "expired" || normalizedState === "reconnect_required" || normalizedState === "unavailable"
          ? "warning"
          : normalizedState === "error"
            ? "error"
            : "";
  const isConnecting = normalizedState === "connecting";
  const isUnavailable = normalizedState === "unavailable";
  const needsReconnect = normalizedState === "expired" || normalizedState === "reconnect_required" || normalizedState === "error";
  const primaryConnectLabel = isUnavailable
    ? "Unavailable"
    : isConnecting
      ? "Connecting..."
      : needsReconnect && card.action === "oauth" ? "Reconnect" : card.connectLabel;
  const shouldShowAccount = Boolean(card.connectedValue && (card.connected || needsReconnect));
  const visibleCapabilities = card.capabilities.slice(0, 4);
  const extraCapabilities = Math.max(card.capabilities.length - visibleCapabilities.length, 0);
  return (
    <article className="connected-card">
      <button className="connected-card-menu" type="button" aria-label={`${card.title} menu`}>
        <MoreVertical size={17} />
      </button>
      <div className="connected-card-top">
        <span className={`app-logo app-logo-${card.logoTone}`}>
          <img
            src={card.logoUrl}
            alt=""
            onError={(event) => {
              event.currentTarget.style.display = "none";
              const fallback = event.currentTarget.nextElementSibling as HTMLElement | null;
              if (fallback) fallback.style.display = "inline";
            }}
          />
          <span>{card.logo}</span>
        </span>
        <div className="connected-card-title">
          <h2>{card.title}</h2>
          <span className={`connected-status-pill ${statusTone}`}>
            {statusLabel}
          </span>
        </div>
      </div>
      <div className="connected-card-main">
        <p>{card.description}</p>
        {card.requirements && card.requirements.length > 0 && !card.connected && (
          <div className="requirement-list" aria-label={`${card.title} requirements`}>
            <strong>Requirements</strong>
            <div>
              {card.requirements.map((requirement) => (
                <span key={requirement}>{requirement}</span>
              ))}
            </div>
          </div>
        )}
        <div className="capability-list">
          {visibleCapabilities.map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
          {extraCapabilities > 0 && <span>+{extraCapabilities}</span>}
        </div>
        {card.errorMessage && !configuring && <small className="connected-card-error">{card.errorMessage}</small>}
        {configuring && isTokenCard && (
          <div className="connection-fields">
            <label>
              <span>{tokenLabel || "Token"}</span>
              <input
                type="password"
                name={`rebly-${card.providerKey}-token`}
                value={token}
                onChange={(event) => setToken?.(event.target.value)}
                placeholder={tokenPlaceholder || "Bot Token"}
                autoComplete="new-password"
                autoCorrect="off"
                spellCheck={false}
              />
            </label>
            {setTarget && (
              <label>
                <span>Channel / Group Username or ID</span>
                <input
                  type="text"
                  name={`rebly-${card.providerKey}-target`}
                  value={target}
                  onChange={(event) => setTarget(event.target.value)}
                  placeholder={targetPlaceholder || "@channel or chat id"}
                  disabled={false}
                  autoComplete="off"
                  autoCorrect="off"
                  spellCheck={false}
                />
              </label>
            )}
            {(statusText || card.statusDetail) && <small>{statusText || card.statusDetail}</small>}
          </div>
        )}
      </div>
      {shouldShowAccount && (
        <div className="connected-account-cell">
          <div className="connected-account" data-initial={(card.connectedValue || card.title).slice(0, 1).toUpperCase()}>
            <strong>{card.connectedLabel}</strong>
            <span>{card.connectedValue}</span>
            {card.connectedAt && <small>{formatConnectedDate(card.connectedAt)}</small>}
            {card.connectedDetails?.map((detail) => (
              <div className="connected-account-detail" key={`${detail.label}-${detail.value}`}>
                <strong>{detail.label}</strong>
                <span>{detail.value}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="connected-actions">
        {configuring && isTokenCard ? (
          <>
            <button
              className="button solid connect-button"
              type="button"
              onClick={onConnect}
              disabled={!canSubmitToken || isConnecting}
            >
              {card.connectLabel}
            </button>
            <button className="button connect-button" type="button" onClick={onCancelConfigure}>
              Cancel
            </button>
          </>
        ) : card.connected ? (
          <>
            <button className="button connect-button" type="button" onClick={onReconnect}>
              {card.action === "oauth" ? "Reconnect" : "Manage"}
            </button>
            <button className="button danger-button connect-button" type="button" onClick={onDisconnect}>
              Disconnect
            </button>
          </>
        ) : (
            <button
            className="button solid connect-button"
            type="button"
            onClick={onConnect}
            aria-disabled={card.action === "disabled"}
            disabled={isConnecting || isUnavailable}
          >
            {primaryConnectLabel}
          </button>
        )}
      </div>
    </article>
  );
}
