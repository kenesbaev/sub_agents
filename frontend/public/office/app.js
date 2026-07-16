import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const officeParams = new URLSearchParams(window.location.search);
const isDashboardEmbed = officeParams.get("embed") === "dashboard";
document.body.classList.toggle("embedded-dashboard", isDashboardEmbed);

function configuredAuthApi() {
  const configured = officeParams.get("apiUrl");
  if (configured) {
    try {
      const url = new URL(configured, window.location.origin);
      if (url.protocol === "https:" || (url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname))) {
        return url.origin;
      }
    } catch {
      // Fall back to the existing local development endpoint below.
    }
  }
  return window.location.hostname === "localhost" ? "http://localhost:8000" : "http://127.0.0.1:8000";
}

const workspace = document.querySelector(".workspace");
const canvas = document.querySelector("#officeCanvas");
const bubbleLayer = document.querySelector("#bubbleLayer");
const rosterList = document.querySelector("#rosterList");
const activityFeed = document.querySelector("#activityFeed");
const activeCount = document.querySelector("#activeCount");
const focusName = document.querySelector("#focusName");
const queueCount = document.querySelector("#queueCount");
const clock = document.querySelector("#clock");
const teamStatus = document.querySelector("#teamStatus");
const officeTitle = document.querySelector("#officeTitle");
const viewBtn = document.querySelector("#viewBtn");
const chatTab = document.querySelector("#chatTab");
const activityTab = document.querySelector("#activityTab");
const chatView = document.querySelector("#chatView");
const activityView = document.querySelector("#activityView");
const chatTarget = document.querySelector("#chatTarget");
const chatMessages = document.querySelector("#chatMessages");
const chatComposer = document.querySelector("#chatComposer");
const chatInput = document.querySelector("#chatInput");
const chatSend = document.querySelector("#chatSend");
const chatStop = document.querySelector("#chatStop");
const chatFileInput = document.querySelector("#chatFileInput");
const chatAttachmentPreview = document.querySelector("#chatAttachmentPreview");
const chatResizeHandle = document.querySelector("#chatResizeHandle");

const AGENT_CHAT_API_PATH = "/api/agents/chat";
const AGENT_CHAT_TIMEOUT_MS = 240000;
const AGENT_CHAT_API_CANDIDATES = buildAgentChatApiCandidates();
const AUTH_API = configuredAuthApi();
const GOOGLE_ACTION_LABELS = {
  search_gmail: "Search Gmail",
  create_gmail_draft: "Create Gmail draft",
  send_gmail: "Send Gmail message",
  list_calendar_events: "View calendar events",
  create_calendar_event: "Create calendar event",
  read_google_sheet: "Read Google Sheet",
  append_google_sheet_row: "Append Google Sheets row",
};
const GOOGLE_WRITE_ACTION_TOOLS = new Set([
  "create_gmail_draft",
  "send_gmail",
  "create_calendar_event",
  "append_google_sheet_row",
]);
const CHAT_STORAGE_VERSION = 2;
const CHAT_WIDTH_STORAGE_KEY = "rebly-office-chat-width";
const CHAT_WIDTH_MIN = 280;
const CHAT_WIDTH_MAX = 520;
const MAIN_WIDTH_MIN = 520;

let officeConversationId = "default";
let officeConversationTeamId = "default-team";
let officeConversationTeamName = "Teamora AI Office";
let officeConversationSource = "ready";
let accountKey = getGuestAccountKey();
let chatSessionId = getOrCreateChatSessionId(accountKey);
let storageReady = false;
let selectedChatImages = [];
let activeChatRun = null;

function buildAgentChatApiCandidates() {
  const protocol = window.location.protocol || "http:";
  const host = window.location.hostname || "127.0.0.1";
  const preferred = `${protocol}//${host}:4173${AGENT_CHAT_API_PATH}`;
  const loopback = host === "127.0.0.1" ? "localhost" : "127.0.0.1";
  const fallback = `${protocol}//${loopback}:4173${AGENT_CHAT_API_PATH}`;
  return [...new Set([preferred, fallback])];
}

const tasks = [
  "Route request",
  "Check context",
  "Prepare report",
  "Review answer",
  "Draft reply",
];

const teamProfile = {
  id: "all",
  name: "Team",
  role: "AI crew",
  color: "#1f2933",
  state: "focused",
  bubble: "Ready",
  active: true,
};

const DEFAULT_ROOMS = {
  open: {
    name: "Open Space",
    center: new THREE.Vector3(0, 0, -2.45),
    size: { x: 13.8, z: 5.95 },
    bounds: { minX: -6.75, maxX: 6.75, minZ: -5.35, maxZ: 0.25 },
  },
  kitchen: {
    name: "Kitchen",
    center: new THREE.Vector3(-3.55, 0, 3.05),
    size: { x: 6.8, z: 5.05 },
    bounds: { minX: -6.75, maxX: -0.35, minZ: 0.65, maxZ: 5.35 },
  },
  relax: {
    name: "Relax Room",
    center: new THREE.Vector3(3.55, 0, 3.05),
    size: { x: 6.8, z: 5.05 },
    bounds: { minX: 0.35, maxX: 6.75, minZ: 0.65, maxZ: 5.35 },
  },
};

const DEFAULT_WORK_STATIONS = [
  {
    point: new THREE.Vector3(-5.05, 0, -2.15),
    desk: new THREE.Vector3(-4.65, 0, -2.85),
    rotation: -0.08,
    color: "#d04f6a",
    activity: "Campaign desk",
  },
  {
    point: new THREE.Vector3(-2.25, 0, -3.45),
    desk: new THREE.Vector3(-1.9, 0, -4.05),
    rotation: 0.03,
    color: "#0097a7",
    activity: "Research pod",
  },
  {
    point: new THREE.Vector3(0.05, 0, -1.35),
    desk: new THREE.Vector3(0.45, 0, -1.95),
    rotation: -0.04,
    color: "#4f5bd5",
    activity: "Command desk",
  },
  {
    point: new THREE.Vector3(2.65, 0, -3.25),
    desk: new THREE.Vector3(3.05, 0, -3.85),
    rotation: 0.05,
    color: "#13a56f",
    activity: "Build desk",
  },
  {
    point: new THREE.Vector3(4.75, 0, -1.35),
    desk: new THREE.Vector3(5.1, 0, -1.95),
    rotation: -0.06,
    color: "#c98908",
    activity: "Support desk",
  },
];

const DEFAULT_ROOM_GATEWAYS = {
  open: new THREE.Vector3(0, 0, 0.15),
  kitchen: new THREE.Vector3(-2.7, 0, 0.95),
  relax: new THREE.Vector3(2.7, 0, 0.95),
};

const DEFAULT_IDLE_DESTINATIONS = [
  {
    id: "kitchen-coffee",
    room: "kitchen",
    kind: "coffee",
    point: new THREE.Vector3(-5.55, 0, 2.0),
    face: new THREE.Vector3(-5.9, 0, 1.3),
    bubbles: ["Coffee?", "Taking coffee"],
  },
  {
    id: "kitchen-table",
    room: "kitchen",
    kind: "talk",
    point: new THREE.Vector3(-3.65, 0, 4.15),
    face: new THREE.Vector3(-2.85, 0, 4.15),
    bubbles: ["Quick sync", "Menu break"],
  },
  {
    id: "kitchen-snack",
    room: "kitchen",
    kind: "coffee",
    point: new THREE.Vector3(-1.75, 0, 2.75),
    face: new THREE.Vector3(-2.35, 0, 2.95),
    bubbles: ["Snack ready", "Recharge"],
  },
  {
    id: "relax-sofa",
    room: "relax",
    kind: "rest",
    point: new THREE.Vector3(2.35, 0, 3.1),
    face: new THREE.Vector3(5.85, 0, 2.65),
    bubbles: ["Reset", "Thinking"],
  },
  {
    id: "relax-tv",
    room: "relax",
    kind: "screen",
    point: new THREE.Vector3(4.75, 0, 3.9),
    face: new THREE.Vector3(6.55, 0, 2.4),
    bubbles: ["Watching metrics", "Reviewing"],
  },
  {
    id: "relax-books",
    room: "relax",
    kind: "read",
    point: new THREE.Vector3(5.9, 0, 4.55),
    face: new THREE.Vector3(6.4, 0, 4.35),
    bubbles: ["Reading notes", "Learning"],
  },
  {
    id: "open-whiteboard",
    room: "open",
    kind: "talk",
    point: new THREE.Vector3(1.45, 0, -4.65),
    face: new THREE.Vector3(2.4, 0, -5.2),
    bubbles: ["Plan next", "Board check"],
  },
  {
    id: "open-plants",
    room: "open",
    kind: "talk",
    point: new THREE.Vector3(-0.65, 0, -0.25),
    face: new THREE.Vector3(0.55, 0, -0.35),
    bubbles: ["Team sync", "Discussing"],
  },
  {
    id: "open-window",
    room: "open",
    kind: "focused",
    point: new THREE.Vector3(-5.95, 0, -4.65),
    face: new THREE.Vector3(-6.65, 0, -4.4),
    bubbles: ["Market notes", "Thinking"],
  },
];

const DEFAULT_AGENTS = [
  {
    id: "coordinator",
    name: "Atlas",
    role: "Coordinator",
    kind: "robot",
    color: "#4f5bd5",
    avatar: "/images/agents/coordinator.png",
    slot: 2,
    state: "focused",
    bubble: "Ready",
    active: true,
  },
  {
    id: "mika",
    name: "Ava",
    role: "Clients",
    kind: "human",
    color: "#d04f6a",
    avatar: "/images/agents/mika.png",
    slot: 0,
    state: "idle",
    bubble: "Ready",
    active: true,
  },
  {
    id: "scout",
    name: "Scout",
    role: "Market",
    kind: "human",
    color: "#0097a7",
    avatar: "/images/agents/scout.png",
    slot: 1,
    state: "idle",
    bubble: "Ready",
    active: true,
  },
  {
    id: "dev",
    name: "Dex",
    role: "Developer",
    kind: "human",
    color: "#13a56f",
    avatar: "/images/agents/dev.png",
    slot: 3,
    state: "idle",
    bubble: "Ready",
    active: true,
  },
  {
    id: "nova",
    name: "Echo",
    role: "Support",
    kind: "human",
    color: "#c98908",
    avatar: "/images/agents/nova.png",
    slot: 4,
    state: "idle",
    bubble: "Ready",
    active: true,
  },
];

let rooms = DEFAULT_ROOMS;
let workStations = DEFAULT_WORK_STATIONS;
let slots = workStations.map((station) => station.point.clone());
let roomGateways = DEFAULT_ROOM_GATEWAYS;
let idleDestinations = DEFAULT_IDLE_DESTINATIONS;

const TEAM_HOUSE_TEAM_IDS = new Set(["sales-team", "marketing-team"]);
const TEAM_HOUSE_SIZE = Object.freeze({
  width: 32,
  depth: 23,
  minX: -16,
  maxX: 16,
  minZ: -11.5,
  maxZ: 11.5,
  minY: -0.4,
  maxY: 4.15,
});

const TEAM_HOUSE_TEAM_SEAT_SLOTS = {
  "sales-team": [0, 1, 2, 3, 8],
  "marketing-team": [4, 5, 6, 7, 12],
};

const TEAM_HOUSE_ROOMS = {
  open: {
    name: "Central Open Workspace",
    center: new THREE.Vector3(-0.7, 0, -0.8),
    size: { x: 13.8, z: 9.1 },
    bounds: { minX: -7.6, maxX: 6.2, minZ: -5.35, maxZ: 3.75 },
  },
  reception: {
    name: "Reception",
    center: new THREE.Vector3(-12.0, 0, 6.7),
    size: { x: 7.7, z: 8.3 },
    bounds: { minX: -15.85, maxX: -8.15, minZ: 2.65, maxZ: 10.95 },
  },
  sales: {
    name: "Sales and CRM",
    center: new THREE.Vector3(-12.0, 0, -4.15),
    size: { x: 7.7, z: 13.5 },
    bounds: { minX: -15.85, maxX: -8.15, minZ: -10.95, maxZ: 2.55 },
  },
  coordinator: {
    name: "Coordinator Room",
    center: new THREE.Vector3(-4.45, 0, -8.35),
    size: { x: 6.3, z: 5.15 },
    bounds: { minX: -7.6, maxX: -1.3, minZ: -10.95, maxZ: -5.8 },
  },
  research: {
    name: "Research and Analytics",
    center: new THREE.Vector3(2.55, 0, -8.35),
    size: { x: 6.9, z: 5.15 },
    bounds: { minX: -0.9, maxX: 6.0, minZ: -10.95, maxZ: -5.8 },
  },
  automation: {
    name: "Automation and Integrations",
    center: new THREE.Vector3(11.1, 0, -8.35),
    size: { x: 9.5, z: 5.15 },
    bounds: { minX: 6.35, maxX: 15.85, minZ: -10.95, maxZ: -5.8 },
  },
  marketing: {
    name: "Marketing and Content Studio",
    center: new THREE.Vector3(11.1, 0, -1.75),
    size: { x: 9.5, z: 7.3 },
    bounds: { minX: 6.35, maxX: 15.85, minZ: -5.4, maxZ: 1.9 },
  },
  support: {
    name: "Customer Support",
    center: new THREE.Vector3(11.1, 0, 4.0),
    size: { x: 9.5, z: 3.5 },
    bounds: { minX: 6.35, maxX: 15.85, minZ: 2.25, maxZ: 5.75 },
  },
  meeting: {
    name: "Meeting Room",
    center: new THREE.Vector3(-4.45, 0, 7.55),
    size: { x: 6.3, z: 6.8 },
    bounds: { minX: -7.6, maxX: -1.3, minZ: 4.15, maxZ: 10.95 },
  },
  cafe: {
    name: "AI Cafe",
    center: new THREE.Vector3(1.72, 0, 7.55),
    size: { x: 5.25, z: 6.8 },
    bounds: { minX: -0.9, maxX: 4.35, minZ: 4.15, maxZ: 10.95 },
  },
  lounge: {
    name: "Lounge",
    center: new THREE.Vector3(7.4, 0, 8.55),
    size: { x: 5.2, z: 4.8 },
    bounds: { minX: 4.8, maxX: 10.0, minZ: 6.15, maxZ: 10.95 },
  },
  recreation: {
    name: "Recreation Corner",
    center: new THREE.Vector3(13.05, 0, 8.55),
    size: { x: 5.6, z: 4.8 },
    bounds: { minX: 10.25, maxX: 15.85, minZ: 6.15, maxZ: 10.95 },
  },
};

const TEAM_HOUSE_WORK_STATIONS = [
  { point: new THREE.Vector3(-13.5, 0, -5.1), desk: new THREE.Vector3(-13.35, 0, -5.85), rotation: 0, color: "#4f78e8", activity: "Client pipeline", room: "sales" },
  { point: new THREE.Vector3(-10.25, 0, -5.1), desk: new THREE.Vector3(-10.1, 0, -5.85), rotation: 0, color: "#2563eb", activity: "Deal review", room: "sales" },
  { point: new THREE.Vector3(-13.5, 0, -1.25), desk: new THREE.Vector3(-13.35, 0, -2.0), rotation: 0, color: "#60a5fa", activity: "CRM update", room: "sales" },
  { point: new THREE.Vector3(-10.25, 0, -1.25), desk: new THREE.Vector3(-10.1, 0, -2.0), rotation: 0, color: "#1d4ed8", activity: "Follow up", room: "sales" },
  { point: new THREE.Vector3(8.35, 0, -3.65), desk: new THREE.Vector3(8.5, 0, -4.4), rotation: 0, color: "#8b5cf6", activity: "Campaign studio", room: "marketing" },
  { point: new THREE.Vector3(11.5, 0, -3.65), desk: new THREE.Vector3(11.65, 0, -4.4), rotation: 0, color: "#a855f7", activity: "Content calendar", room: "marketing" },
  { point: new THREE.Vector3(8.35, 0, -0.4), desk: new THREE.Vector3(8.5, 0, -1.15), rotation: 0, color: "#7c3aed", activity: "Creative review", room: "marketing" },
  { point: new THREE.Vector3(11.5, 0, -0.4), desk: new THREE.Vector3(11.65, 0, -1.15), rotation: 0, color: "#c084fc", activity: "Performance report", room: "marketing" },
  { point: new THREE.Vector3(-5.45, 0, -2.45), desk: new THREE.Vector3(-5.3, 0, -3.2), rotation: 0, color: "#4f5bd5", activity: "Open workspace", room: "open" },
  { point: new THREE.Vector3(-2.55, 0, -2.45), desk: new THREE.Vector3(-2.4, 0, -3.2), rotation: 0, color: "#0ea5e9", activity: "Open workspace", room: "open" },
  { point: new THREE.Vector3(-5.45, 0, 1.2), desk: new THREE.Vector3(-5.3, 0, 0.45), rotation: 0, color: "#2563eb", activity: "Open workspace", room: "open" },
  { point: new THREE.Vector3(-2.55, 0, 1.2), desk: new THREE.Vector3(-2.4, 0, 0.45), rotation: 0, color: "#14b8a6", activity: "Open workspace", room: "open" },
  { point: new THREE.Vector3(0.8, 0, -2.45), desk: new THREE.Vector3(0.95, 0, -3.2), rotation: 0, color: "#8b5cf6", activity: "Open workspace", room: "open" },
  { point: new THREE.Vector3(3.7, 0, -2.45), desk: new THREE.Vector3(3.85, 0, -3.2), rotation: 0, color: "#06b6d4", activity: "Open workspace", room: "open" },
  { point: new THREE.Vector3(0.8, 0, 1.2), desk: new THREE.Vector3(0.95, 0, 0.45), rotation: 0, color: "#6366f1", activity: "Open workspace", room: "open" },
  { point: new THREE.Vector3(3.7, 0, 1.2), desk: new THREE.Vector3(3.85, 0, 0.45), rotation: 0, color: "#2dd4bf", activity: "Open workspace", room: "open" },
  { point: new THREE.Vector3(-5.55, 0, -8.1), desk: new THREE.Vector3(-5.4, 0, -8.85), rotation: 0, color: "#6d5ce7", activity: "Team coordination", room: "coordinator" },
  { point: new THREE.Vector3(0.55, 0, -8.1), desk: new THREE.Vector3(0.7, 0, -8.85), rotation: 0, color: "#0ea5e9", activity: "Research analysis", room: "research" },
  { point: new THREE.Vector3(3.5, 0, -8.1), desk: new THREE.Vector3(3.65, 0, -8.85), rotation: 0, color: "#38bdf8", activity: "Insight report", room: "research" },
  { point: new THREE.Vector3(12.2, 0, -8.1), desk: new THREE.Vector3(12.35, 0, -8.85), rotation: 0, color: "#1e3a8a", activity: "Integration monitor", room: "automation" },
  { point: new THREE.Vector3(8.6, 0, 3.55), desk: new THREE.Vector3(8.75, 0, 2.8), rotation: 0, color: "#10b981", activity: "Customer queue", room: "support" },
  { point: new THREE.Vector3(11.85, 0, 3.55), desk: new THREE.Vector3(12.0, 0, 2.8), rotation: 0, color: "#22c55e", activity: "Support reply", room: "support" },
];

const TEAM_HOUSE_ROOM_GATEWAYS = {
  open: new THREE.Vector3(-0.6, 0, 0.15),
  reception: new THREE.Vector3(-7.85, 0, 4.85),
  sales: new THREE.Vector3(-7.85, 0, -1.05),
  coordinator: new THREE.Vector3(-4.45, 0, -5.55),
  research: new THREE.Vector3(2.55, 0, -5.55),
  automation: new THREE.Vector3(6.15, 0, -5.55),
  marketing: new THREE.Vector3(6.15, 0, -1.65),
  support: new THREE.Vector3(6.15, 0, 3.85),
  meeting: new THREE.Vector3(-4.45, 0, 3.95),
  cafe: new THREE.Vector3(1.7, 0, 3.95),
  lounge: new THREE.Vector3(5.2, 0, 5.95),
  recreation: new THREE.Vector3(10.05, 0, 5.95),
};

const TEAM_HOUSE_IDLE_DESTINATIONS = [
  { id: "sales-crm-wall", room: "sales", kind: "screen", point: new THREE.Vector3(-14.25, 0, -8.2), face: new THREE.Vector3(-14.25, 0, -10.8), bubbles: ["Reviewing pipeline", "Checking leads"], teams: ["sales-team"] },
  { id: "sales-huddle", room: "sales", kind: "talk", point: new THREE.Vector3(-11.7, 0, 1.15), face: new THREE.Vector3(-13.0, 0, 1.15), bubbles: ["Sales huddle", "Closing plan"], teams: ["sales-team"] },
  { id: "sales-window", room: "sales", kind: "focused", point: new THREE.Vector3(-9.0, 0, -8.15), face: new THREE.Vector3(-8.25, 0, -8.15), bubbles: ["Forecasting", "Planning next"], teams: ["sales-team"] },
  { id: "marketing-screen", room: "marketing", kind: "screen", point: new THREE.Vector3(14.15, 0, -3.8), face: new THREE.Vector3(14.15, 0, -5.1), bubbles: ["Watching metrics", "Campaign check"], teams: ["marketing-team"] },
  { id: "marketing-studio", room: "marketing", kind: "talk", point: new THREE.Vector3(12.0, 0, 1.1), face: new THREE.Vector3(10.55, 0, 1.1), bubbles: ["Creative sync", "Reviewing content"], teams: ["marketing-team"] },
  { id: "marketing-board", room: "marketing", kind: "focused", point: new THREE.Vector3(7.2, 0, -0.15), face: new THREE.Vector3(6.45, 0, -0.15), bubbles: ["Researching", "Building a brief"], teams: ["marketing-team"] },
  { id: "central-team-pulse", room: "open", kind: "screen", point: new THREE.Vector3(-0.45, 0, -4.25), face: new THREE.Vector3(-0.45, 0, -5.05), bubbles: ["Reviewing team pulse", "Checking priorities"], teams: ["sales-team", "marketing-team"] },
  { id: "central-whiteboard", room: "open", kind: "talk", point: new THREE.Vector3(4.85, 0, 1.45), face: new THREE.Vector3(5.7, 0, 1.45), bubbles: ["Planning together", "Board check"], teams: ["sales-team", "marketing-team"] },
  { id: "coordinator-table", room: "coordinator", kind: "talk", point: new THREE.Vector3(-3.55, 0, -8.1), face: new THREE.Vector3(-4.45, 0, -8.1), bubbles: ["Quick sync", "Team alignment"], teams: ["sales-team", "marketing-team"] },
  { id: "research-wall", room: "research", kind: "screen", point: new THREE.Vector3(4.75, 0, -7.1), face: new THREE.Vector3(5.65, 0, -7.1), bubbles: ["Reading signals", "Exploring insights"], teams: ["sales-team", "marketing-team"] },
  { id: "support-queue", room: "support", kind: "focused", point: new THREE.Vector3(14.1, 0, 4.0), face: new THREE.Vector3(14.1, 0, 2.45), bubbles: ["Checking support", "Resolving queue"], teams: ["sales-team", "marketing-team"] },
  { id: "automation-rack", room: "automation", kind: "screen", point: new THREE.Vector3(14.3, 0, -8.0), face: new THREE.Vector3(14.3, 0, -10.5), bubbles: ["Monitoring automations", "Checking integrations"], teams: ["sales-team", "marketing-team"] },
  { id: "team-house-meeting", room: "meeting", kind: "talk", point: new THREE.Vector3(-3.65, 0, 7.35), face: new THREE.Vector3(-4.45, 0, 7.35), bubbles: ["Meeting room", "Sharing an update"], teams: ["sales-team", "marketing-team"] },
  { id: "team-house-cafe", room: "cafe", kind: "coffee", point: new THREE.Vector3(0.15, 0, 7.4), face: new THREE.Vector3(-0.65, 0, 7.4), bubbles: ["Coffee break", "Recharging"], teams: ["sales-team", "marketing-team"] },
  { id: "team-house-lounge", room: "lounge", kind: "rest", point: new THREE.Vector3(6.5, 0, 8.55), face: new THREE.Vector3(8.25, 0, 8.55), bubbles: ["Thinking", "Taking a reset"], teams: ["sales-team", "marketing-team"] },
  { id: "team-house-recreation", room: "recreation", kind: "talk", point: new THREE.Vector3(12.45, 0, 8.55), face: new THREE.Vector3(13.35, 0, 8.55), bubbles: ["Quick game", "Taking a break"], teams: ["sales-team", "marketing-team"] },
  { id: "team-house-reception", room: "reception", kind: "talk", point: new THREE.Vector3(-13.0, 0, 7.25), face: new THREE.Vector3(-12.0, 0, 7.25), bubbles: ["Welcoming a task", "Checking in"], teams: ["sales-team", "marketing-team"] },
];

let activeOfficeLayout = "classic";
let activeOfficeTeamId = "default-team";

let agents = DEFAULT_AGENTS.map(cloneAgent);

const legacyAuthorToAgentId = {
  Coordinator: "coordinator",
  Atlas: "coordinator",
  Mika: "mika",
  Ava: "mika",
  Scout: "scout",
  Dev: "dev",
  Dex: "dev",
  Nova: "nova",
  Echo: "nova",
};

function cloneAgent(agent) {
  return { ...agent };
}

function normalizeTeamAgent(rawAgent, index) {
  const base = DEFAULT_AGENTS[index % DEFAULT_AGENTS.length];
  const requestedId = String(rawAgent?.id || "").trim();
  const allowedId = DEFAULT_AGENTS.some((agent) => agent.id === requestedId) ? requestedId : base.id;
  const runtimeBase = DEFAULT_AGENTS.find((agent) => agent.id === allowedId) || base;
  const name = String(rawAgent?.name || base.name || `Agent ${index + 1}`).trim();
  const role = String(rawAgent?.role || base.role || "AI agent").trim();
  return {
    id: allowedId,
    name,
    role,
    kind: runtimeBase.kind || "human",
    color: String(rawAgent?.color || rawAgent?.accent || runtimeBase.color || "#4f5bd5"),
    avatar: String(rawAgent?.avatar || runtimeBase.avatar || "/images/agents/coordinator.png"),
    slot: index % slots.length,
    state: index === 0 ? "focused" : "idle",
    bubble: index === 0 ? "Team ready" : "Ready",
    active: true,
  };
}

function normalizeTeamPayload(data) {
  const team = data && typeof data === "object" ? data : {};
  const sourceAgents = Array.isArray(team.agents) ? team.agents : [];
  const nextAgents = sourceAgents
    .slice(0, Math.min(DEFAULT_AGENTS.length, slots.length))
    .map(normalizeTeamAgent)
    .filter((agent) => agent.name);
  if (!nextAgents.length) return null;
  return {
    id: String(team.id || "custom-team"),
    name: String(team.name || "Team"),
    agents: nextAgents,
  };
}

let selectedChatId = "all";
let chatBusy = false;
let chatThreads = createEmptyChatThreads();

const agentStyles = [
  {
    skin: "#aab3c7",
    hair: "#626b83",
    pants: "#5a6278",
    shoes: "#34394b",
    face: "#111827",
    mouth: "#ef3f5a",
  },
  {
    skin: "#f0b889",
    hair: "#f2a15f",
    pants: "#d58352",
    shoes: "#8d6047",
    face: "#1d2433",
    mouth: "#9a4338",
  },
  {
    skin: "#a06f50",
    hair: "#202737",
    pants: "#4669c9",
    shoes: "#915c35",
    face: "#111827",
    mouth: "#6b2f31",
  },
  {
    skin: "#d59668",
    hair: "#232737",
    pants: "#16a085",
    shoes: "#6f4d35",
    face: "#172033",
    mouth: "#7f3a35",
  },
  {
    skin: "#62b37f",
    hair: "#2e3349",
    pants: "#42c6a3",
    shoes: "#7d4d2d",
    face: "#151b2b",
    mouth: "#185f49",
  },
];

let selectedIndex = 0;
let queued = 3;
const bubbles = new Map();
const bubblePresentation = new Map();
const MAX_FULL_AGENT_CARDS = 3;
const BUBBLE_EDGE_PADDING = 10;
let hoveredAgentIndex = -1;
let cameraTransition = null;

const scene = new THREE.Scene();
scene.background = new THREE.Color("#f4f6f8");

const camera = new THREE.OrthographicCamera(-7, 7, 4.6, -4.6, 0.1, 100);
camera.position.set(9.8, 8.1, 10.8);
camera.lookAt(0, 0.7, 0.2);

let renderer = null;
let controls = null;
try {
  renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: false,
    powerPreference: "high-performance",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  controls = new OrbitControls(camera, canvas);
  controls.target.set(0, 0.7, 0.2);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.enablePan = true;
  controls.screenSpacePanning = true;
  controls.minZoom = 0.5;
  controls.maxZoom = 2.05;
  controls.minPolarAngle = Math.PI * 0.18;
  controls.maxPolarAngle = Math.PI * 0.5;
  controls.addEventListener("start", () => {
    cameraTransition = null;
  });
  controls.update();
} catch (error) {
  canvas.dataset.webgl = "unavailable";
  canvas.hidden = true;
  console.warn("3D workspace disabled because WebGL is unavailable.", error);
}

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();

const ambient = new THREE.HemisphereLight("#ffffff", "#9ca3af", 2.8);
scene.add(ambient);

const sun = new THREE.DirectionalLight("#ffffff", 3.2);
sun.position.set(5, 8, 4);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
sun.shadow.camera.near = 1;
sun.shadow.camera.far = 28;
sun.shadow.camera.left = -10;
sun.shadow.camera.right = 10;
sun.shadow.camera.top = 10;
sun.shadow.camera.bottom = -10;
scene.add(sun);

const root = new THREE.Group();
scene.add(root);

const clickTargets = [];
const gltfLoader = new GLTFLoader();
const gltfCache = new Map();
const loadedAssetNames = new Set();
let teamWorkActive = false;
let teamWorkTimer = null;
let roamingTimer = null;

function createCanvasTexture(
  base = "#edf1f5",
  line = "#d7dee9",
  accents = [
    { color: "rgba(79, 91, 213, 0.08)", x: 0, y: 192, w: 512, h: 64 },
    { color: "rgba(0, 151, 167, 0.08)", x: 192, y: 0, w: 64, h: 512 },
  ],
  repeat = { x: 2.2, y: 1.4 },
) {
  const textureCanvas = document.createElement("canvas");
  textureCanvas.width = 512;
  textureCanvas.height = 512;
  const ctx = textureCanvas.getContext("2d");
  ctx.fillStyle = base;
  ctx.fillRect(0, 0, 512, 512);
  ctx.strokeStyle = line;
  ctx.lineWidth = 2;
  for (let i = 0; i <= 512; i += 64) {
    ctx.beginPath();
    ctx.moveTo(i, 0);
    ctx.lineTo(i, 512);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0, i);
    ctx.lineTo(512, i);
    ctx.stroke();
  }
  accents.forEach((accent) => {
    ctx.fillStyle = accent.color;
    ctx.fillRect(accent.x, accent.y, accent.w, accent.h);
  });

  const texture = new THREE.CanvasTexture(textureCanvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(repeat.x, repeat.y);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function createWoodTexture(base = "#d9b27e", line = "#b98756") {
  const textureCanvas = document.createElement("canvas");
  textureCanvas.width = 512;
  textureCanvas.height = 512;
  const ctx = textureCanvas.getContext("2d");
  ctx.fillStyle = base;
  ctx.fillRect(0, 0, 512, 512);
  ctx.strokeStyle = line;
  ctx.lineWidth = 3;
  for (let y = 0; y < 512; y += 58) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(512, y + 18 * Math.sin(y * 0.03));
    ctx.stroke();
  }
  ctx.strokeStyle = "rgba(255,255,255,0.22)";
  ctx.lineWidth = 1;
  for (let x = 36; x < 512; x += 82) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x - 16, 512);
    ctx.stroke();
  }

  const texture = new THREE.CanvasTexture(textureCanvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(1.8, 1.45);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function addOffice() {
  const foundation = new THREE.Mesh(
    new THREE.BoxGeometry(14.8, 0.34, 11.35),
    new THREE.MeshStandardMaterial({
      color: "#dbeafe",
      roughness: 0.68,
    }),
  );
  foundation.position.y = -0.32;
  foundation.receiveShadow = true;
  root.add(foundation);

  addRoomFloor(rooms.open, createCanvasTexture("#eef3f8", "#d8e2ee", [], { x: 2.7, y: 1.15 }));
  addRoomFloor(rooms.kitchen, createWoodTexture("#efd3a7", "#c99a64"));
  addRoomFloor(rooms.relax, createWoodTexture("#e1c09a", "#b98761"));

  addRoomShell();
  addOpenSpaceRoom();
  addKitchenRoom();
  addRelaxRoom();
  addRoomLights();
}

function shouldUseTeamHouse(teamId) {
  return TEAM_HOUSE_TEAM_IDS.has(String(teamId || "").trim().toLowerCase());
}

function assignOfficeSeats(teamId) {
  const teamSeats = TEAM_HOUSE_TEAM_SEAT_SLOTS[String(teamId || "").trim().toLowerCase()];
  agents.forEach((agent, index) => {
    const nextSlot = teamSeats?.[index] ?? index;
    agent.slot = ((nextSlot % slots.length) + slots.length) % slots.length;
  });
}

function setOfficeLayout(teamId) {
  const nextTeamId = String(teamId || "default-team").trim().toLowerCase();
  const nextLayout = shouldUseTeamHouse(nextTeamId) ? "team-house" : "classic";
  const needsRebuild = activeOfficeLayout !== nextLayout || root.children.length === 0;

  activeOfficeTeamId = nextTeamId;
  activeOfficeLayout = nextLayout;
  rooms = nextLayout === "team-house" ? TEAM_HOUSE_ROOMS : DEFAULT_ROOMS;
  workStations = nextLayout === "team-house" ? TEAM_HOUSE_WORK_STATIONS : DEFAULT_WORK_STATIONS;
  slots = workStations.map((station) => station.point.clone());
  roomGateways = nextLayout === "team-house" ? TEAM_HOUSE_ROOM_GATEWAYS : DEFAULT_ROOM_GATEWAYS;
  idleDestinations =
    nextLayout === "team-house" ? TEAM_HOUSE_IDLE_DESTINATIONS : DEFAULT_IDLE_DESTINATIONS;

  if (renderer && needsRebuild) {
    root.clear();
    if (nextLayout === "team-house") {
      addTeamHouse();
    } else {
      addOffice();
    }

    const shadowExtent = nextLayout === "team-house" ? 19 : 10;
    sun.shadow.camera.left = -shadowExtent;
    sun.shadow.camera.right = shadowExtent;
    sun.shadow.camera.top = shadowExtent;
    sun.shadow.camera.bottom = -shadowExtent;
    sun.shadow.camera.updateProjectionMatrix();
  }

  if (controls) resetView();
  if (window.agentOfficeDebug) {
    Object.assign(window.agentOfficeDebug, {
      activeOfficeLayout,
      activeOfficeTeamId,
      rooms,
      workStations,
      idleDestinations,
    });
  }
}

function addTeamHouse() {
  const { width, depth } = TEAM_HOUSE_SIZE;
  const foundation = new THREE.Mesh(
    new THREE.BoxGeometry(width + 0.6, 0.42, depth + 0.6),
    new THREE.MeshStandardMaterial({ color: "#d6e5ff", roughness: 0.72 }),
  );
  foundation.position.set(0, -0.32, 0);
  foundation.receiveShadow = true;
  root.add(foundation);

  addTeamHouseZoneFloor(0, 0, width - 0.2, depth - 0.2, "#f4d9ae", "#d7af78", "rgba(255,255,255,0.18)");
  addTeamHouseZoneFloor(-12, -4.15, 7.65, 13.45, "#e9f2ff", "#c9dcff", "rgba(37,99,235,0.08)");
  addTeamHouseZoneFloor(-12, 6.8, 7.65, 8.05, "#f6f8ff", "#d8e2fb", "rgba(79,91,213,0.07)");
  addTeamHouseZoneFloor(-4.45, -8.35, 6.2, 5.0, "#ede8ff", "#d8cdfa", "rgba(109,92,231,0.12)");
  addTeamHouseZoneFloor(2.55, -8.35, 6.8, 5.0, "#e2f7ff", "#bce8fb", "rgba(14,165,233,0.1)");
  addTeamHouseZoneFloor(11.1, -8.35, 9.4, 5.0, "#dae7f7", "#b7c8e2", "rgba(30,58,138,0.13)");
  addTeamHouseZoneFloor(-0.7, -0.8, 13.65, 8.95, "#f6e1be", "#dfbd8a", "rgba(99,102,241,0.05)");
  addTeamHouseZoneFloor(11.1, -1.75, 9.4, 7.15, "#f4ecff", "#ddcdfa", "rgba(139,92,246,0.1)");
  addTeamHouseZoneFloor(11.1, 4.0, 9.4, 3.35, "#e6f8ef", "#c0ead3", "rgba(16,185,129,0.1)");
  addTeamHouseZoneFloor(-4.45, 7.55, 6.2, 6.65, "#eff3ff", "#d5def4", "rgba(79,91,213,0.07)");
  addTeamHouseZoneFloor(1.72, 7.55, 5.1, 6.65, "#fff0d8", "#f1c88e", "rgba(245,158,11,0.11)");
  addTeamHouseZoneFloor(7.4, 8.55, 5.05, 4.65, "#e7f6f1", "#c5e7dd", "rgba(16,185,129,0.08)");
  addTeamHouseZoneFloor(13.05, 8.55, 5.45, 4.65, "#e6efff", "#cbd9f2", "rgba(59,130,246,0.08)");

  const wallColor = "#e5edff";
  const wallTrim = "#c8d8f4";
  addBox(root, width + 0.6, 2.9, 0.3, wallColor, new THREE.Vector3(0, 1.15, -11.65), {
    roughness: 0.82,
  });
  addBox(root, 0.3, 2.9, depth + 0.6, wallColor, new THREE.Vector3(-16.3, 1.15, 0), {
    roughness: 0.82,
  });
  addBox(root, width + 0.6, 0.36, 0.22, wallTrim, new THREE.Vector3(0, 0.08, 11.5), {
    roughness: 0.65,
  });
  addBox(root, 0.22, 0.36, depth + 0.6, wallTrim, new THREE.Vector3(16.2, 0.08, 0), {
    roughness: 0.65,
  });

  addTeamHouseLowDivider(-7.92, -6.95, 7.1, Math.PI / 2, "#cbdcff");
  addTeamHouseLowDivider(-7.92, 8.05, 4.95, Math.PI / 2, "#d4def4");
  addTeamHouseLowDivider(6.18, -8.35, 5.0, Math.PI / 2, "#c1d2ee");
  addTeamHouseLowDivider(6.18, 4.0, 3.35, Math.PI / 2, "#b9ead2");
  addTeamHouseLowDivider(10.1, 6.0, 5.65, Math.PI / 2, "#c6d8ef");
  addTeamHouseLowDivider(-1.1, 4.0, 5.1, Math.PI / 2, "#d5def4");
  addTeamHouseLowDivider(4.55, 7.55, 6.65, Math.PI / 2, "#f4d4a0");
  addTeamHouseGlassDivider(6.18, -1.7, 5.05, Math.PI / 2, 1.34);
  addTeamHouseGlassDivider(-1.1, -8.35, 5.0, Math.PI / 2, 1.3);
  addTeamHouseGlassDivider(6.18, 8.55, 4.55, Math.PI / 2, 1.3);

  addTeamHouseRug(-4.45, -8.35, 5.2, 3.45, "#d9d0ff");
  addTeamHouseRug(-4.45, 7.55, 4.8, 4.2, "#dce7ff");
  addTeamHouseRug(1.72, 7.55, 3.95, 4.2, "#ffe0aa");
  addTeamHouseRug(7.4, 8.55, 3.8, 3.05, "#d7f0e6");
  addTeamHouseRug(13.05, 8.55, 4.25, 3.2, "#dbeafe");
  addTeamHouseWalkway(-0.78, -0.75, 1.45, 8.6);

  TEAM_HOUSE_WORK_STATIONS.forEach((station, index) => {
    addTeamHouseDesk(station, index);
    addPad(station.point, station.color);
  });

  addTeamHouseSign("SALES and CRM", "pipeline / clients / close", "#2563eb", 3.7, 0.62, -12.0, 2.25, -11.46);
  addTeamHouseSign("COORDINATOR", "alignment / decisions", "#6d5ce7", 3.0, 0.58, -4.45, 2.25, -11.46);
  addTeamHouseSign("RESEARCH", "signals / insights", "#0ea5e9", 3.05, 0.58, 2.55, 2.25, -11.46);
  addTeamHouseSign("AUTOMATION", "integrations / runs", "#1e3a8a", 3.55, 0.62, 11.1, 2.25, -11.46);
  addTeamHouseScreen("CRM PULSE", "LEADS  24   WIN RATE  68%", "#2563eb", -12.0, 1.25, -11.42, 3.7, 1.08);
  addTeamHouseScreen("TEAM PULSE", "FOCUS  92%   TASKS  08", "#6d5ce7", -4.45, 1.25, -11.42, 3.0, 1.08);
  addTeamHouseScreen("RESEARCH LAB", "SIGNALS  07   INSIGHTS  16", "#0ea5e9", 2.55, 1.25, -11.42, 3.05, 1.08);
  addTeamHouseScreen("AUTOMATION OPS", "RUNS  14   HEALTH  99%", "#1e3a8a", 11.1, 1.25, -11.42, 3.55, 1.08);

  addTeamHouseSign("MARKETING STUDIO", "content / campaigns / reach", "#8b5cf6", 3.85, 0.58, 11.1, 2.05, 1.98);
  addTeamHouseScreen("CAMPAIGN LAB", "REACH  +38%   CONTENT  12", "#8b5cf6", 11.1, 1.1, 1.94, 3.85, 0.98);
  addTeamHouseSign("CUSTOMER SUPPORT", "queue / care / resolve", "#10b981", 3.8, 0.55, 11.1, 1.82, 5.86);
  addTeamHouseScreen("SUPPORT QUEUE", "OPEN  03   SLA  98%", "#10b981", 11.1, 1.02, 5.82, 3.35, 0.88);

  addTeamHouseCentralWorkspace();
  addTeamHouseSalesZone(-12.0, -4.15);
  addTeamHouseMeetingTable(-4.45, -8.35);
  addTeamHouseResearchPod(2.55, -8.35);
  addTeamHouseAutomationLab(11.1, -8.35);
  addTeamHouseMarketingStudio(11.1, -1.75);
  addTeamHouseSupportZone(11.1, 4.0);
  addTeamHouseReception(-12.0, 6.8);
  addTeamHouseMeetingRoom(-4.45, 7.55);
  addTeamHouseCafe(1.72, 7.55);
  addTeamHouseLounge(7.4, 8.55);
  addTeamHouseRecreationCorner(13.05, 8.55);

  [
    [-15.1, -10.2, 0.7],
    [-8.75, -10.2, 0.65],
    [-0.2, -10.2, 0.7],
    [7.05, -10.2, 0.65],
    [15.05, -10.2, 0.7],
    [-15.1, 10.2, 0.72],
    [-8.6, 10.2, 0.65],
    [4.9, 10.2, 0.62],
    [15.05, 10.2, 0.72],
  ].forEach(([x, z, scale]) => addFloorPlant(x, z, scale));

  [
    [-12.0, -7.25, "#dbeafe"],
    [-4.45, -7.25, "#ede9fe"],
    [2.55, -7.25, "#dff6ff"],
    [11.1, -7.25, "#d8e7ff"],
    [-4.45, -0.3, "#fff7e6"],
    [2.4, -0.3, "#e8edff"],
    [11.1, -1.35, "#f4e8ff"],
    [-12.0, 7.3, "#edf2ff"],
    [1.72, 7.35, "#fff0d3"],
    [11.1, 4.0, "#e4f8ee"],
  ].forEach(([x, z, color]) => addTeamHousePendant(x, z, color));
}

function addTeamHouseGlassDivider(x, z, length, rotation = 0, height = 1.58) {
  const divider = new THREE.Group();
  divider.position.set(x, 0, z);
  divider.rotation.y = rotation;
  root.add(divider);

  const glass = new THREE.Mesh(
    new THREE.BoxGeometry(length, height, 0.05),
    new THREE.MeshStandardMaterial({
      color: "#d9efff",
      transparent: true,
      opacity: 0.38,
      roughness: 0.15,
      metalness: 0.04,
    }),
  );
  glass.position.y = height / 2 + 0.06;
  glass.castShadow = true;
  divider.add(glass);
  addBox(divider, length + 0.08, 0.1, 0.1, "#c7d7ef", new THREE.Vector3(0, 0.12, 0));
  addBox(divider, length + 0.08, 0.08, 0.1, "#c7d7ef", new THREE.Vector3(0, height + 0.08, 0));
  for (let offset = -length / 2 + 0.65; offset < length / 2; offset += 1.35) {
    addBox(divider, 0.06, height + 0.08, 0.08, "#c7d7ef", new THREE.Vector3(offset, height / 2 + 0.08, 0));
  }
}

function addTeamHouseRug(x, z, width, depth, color) {
  const rug = new THREE.Mesh(
    new THREE.BoxGeometry(width, 0.055, depth),
    new THREE.MeshStandardMaterial({ color, roughness: 0.9 }),
  );
  rug.position.set(x, 0.035, z);
  rug.receiveShadow = true;
  root.add(rug);
}

function addTeamHouseZoneFloor(x, z, width, depth, base, line, accent) {
  const texture = createCanvasTexture(
    base,
    line,
    [
      { color: accent, x: 0, y: 64, w: 512, h: 72 },
      { color: accent, x: 260, y: 256, w: 96, h: 256 },
    ],
    { x: Math.max(1.2, width / 5.5), y: Math.max(1.1, depth / 5.5) },
  );
  const floor = new THREE.Mesh(
    new THREE.BoxGeometry(width, 0.09, depth),
    new THREE.MeshStandardMaterial({ map: texture, roughness: 0.86, metalness: 0.01 }),
  );
  floor.position.set(x, -0.005, z);
  floor.receiveShadow = true;
  root.add(floor);
  return floor;
}

function addTeamHouseWalkway(x, z, width, depth) {
  addBox(root, width, 0.065, depth, "#f8fafc", new THREE.Vector3(x, 0.04, z), { roughness: 0.92 });
  addBox(root, 0.08, 0.074, depth, "#cbd5e1", new THREE.Vector3(x - width / 2, 0.075, z), { roughness: 0.58 });
  addBox(root, 0.08, 0.074, depth, "#cbd5e1", new THREE.Vector3(x + width / 2, 0.075, z), { roughness: 0.58 });
}

function addTeamHouseLowDivider(x, z, length, rotation = 0, accent = "#cbd5e1") {
  const divider = new THREE.Group();
  divider.position.set(x, 0, z);
  divider.rotation.y = rotation;
  root.add(divider);
  addBox(divider, length, 0.46, 0.42, "#eff5ff", new THREE.Vector3(0, 0.24, 0), { roughness: 0.78 });
  addBox(divider, length + 0.08, 0.08, 0.5, accent, new THREE.Vector3(0, 0.52, 0), { roughness: 0.62 });
  for (let offset = -length / 2 + 0.48; offset < length / 2 - 0.2; offset += 0.78) {
    const leaf = new THREE.Mesh(
      new THREE.ConeGeometry(0.08, 0.34, 7),
      new THREE.MeshStandardMaterial({ color: offset % 1.56 > 0.7 ? "#16a34a" : "#65a30d", roughness: 0.72 }),
    );
    leaf.position.set(offset, 0.74, (offset % 1.56 > 0.7 ? 0.1 : -0.1));
    leaf.rotation.z = offset % 1.56 > 0.7 ? 0.35 : -0.35;
    leaf.castShadow = true;
    divider.add(leaf);
  }
}

function addTeamHouseCentralWorkspace() {
  addTeamHouseSign("CENTRAL WORKSPACE", "build / collaborate / ship", "#4f5bd5", 3.85, 0.56, -0.6, 1.92, -5.22);
  addTeamHouseScreen("TEAM STATUS", "FOCUS  92%   TASKS  08   READY  05", "#4f5bd5", -0.6, 1.0, -5.18, 4.15, 1.02);
  addTeamHouseWhiteboard("SPRINT BOARD", ["PLAN", "CREATE", "REVIEW", "SHIP"], "#0ea5e9", 5.82, 1.45, 1.55, 1.7, 1.05);
  addTeamHousePlanterDivider(-0.75, -2.8, 2.7, "#c7d2fe");
  addTeamHousePlanterDivider(-0.75, 1.0, 2.7, "#c7d2fe");
  addTeamHousePlanterDivider(-6.9, -0.7, 2.5, "#dbeafe", Math.PI / 2);
  addShelf(-7.0, -4.3, 0.72, Math.PI / 2);
  addShelf(5.5, -4.3, 0.68, -Math.PI / 2);
  addFloorPlant(-6.75, 2.75, 0.56);
  addFloorPlant(5.4, 2.75, 0.56);
}

function addTeamHouseSalesZone(x, z) {
  addTeamHouseScreen("CRM DASHBOARD", "LEADS / DEALS / FORECAST", "#2563eb", x, 1.35, -10.98, 3.55, 1.0);
  addTeamHouseWhiteboard("SALES PLAY", ["QUALIFY", "DEMO", "CLOSE"], "#2563eb", -8.42, 1.35, -2.75, 1.42, 0.98);
  const huddle = new THREE.Mesh(
    new THREE.CylinderGeometry(1.12, 1.12, 0.13, 28),
    new THREE.MeshStandardMaterial({ color: "#f8fbff", roughness: 0.5 }),
  );
  huddle.position.set(-12.0, 0.72, 1.08);
  huddle.castShadow = true;
  root.add(huddle);
  addBox(root, 0.24, 0.72, 0.24, "#64748b", new THREE.Vector3(-12.0, 0.35, 1.08), { roughness: 0.5 });
  [-1.35, 1.35].forEach((offset, index) => {
    const chair = new THREE.Group();
    chair.position.set(-12.0 + offset, 0, 1.08);
    chair.rotation.y = index ? -Math.PI / 2 : Math.PI / 2;
    root.add(chair);
    addOfficeChair(chair, 0, 0, index);
  });
  addShelf(-15.1, -1.0, 0.7, Math.PI / 2);
  addFloorPlant(-15.0, 1.8, 0.58);
}

function addTeamHousePlanterDivider(x, z, width, accent, rotation = 0) {
  const group = new THREE.Group();
  group.position.set(x, 0, z);
  group.rotation.y = rotation;
  root.add(group);
  addBox(group, width, 0.44, 0.42, "#e5e7eb", new THREE.Vector3(0, 0.23, 0), { roughness: 0.78 });
  addBox(group, width + 0.04, 0.06, 0.46, accent, new THREE.Vector3(0, 0.48, 0), { roughness: 0.65 });
  for (let offset = -width / 2 + 0.25; offset < width / 2; offset += 0.45) {
    const leaf = new THREE.Mesh(
      new THREE.ConeGeometry(0.095, 0.45, 7),
      new THREE.MeshStandardMaterial({ color: offset % 0.9 > 0.42 ? "#22c55e" : "#15803d", roughness: 0.7 }),
    );
    leaf.position.set(offset, 0.77, 0);
    leaf.rotation.z = offset % 0.9 > 0.42 ? 0.28 : -0.28;
    leaf.castShadow = true;
    group.add(leaf);
  }
}

function createTeamHouseWhiteboardTexture(title, lines, accent) {
  const textureCanvas = document.createElement("canvas");
  textureCanvas.width = 760;
  textureCanvas.height = 420;
  const ctx = textureCanvas.getContext("2d");
  ctx.fillStyle = "#fbfdff";
  ctx.fillRect(0, 0, 760, 420);
  ctx.strokeStyle = "#cbd5e1";
  ctx.lineWidth = 10;
  ctx.strokeRect(18, 18, 724, 384);
  ctx.fillStyle = "#0f172a";
  ctx.font = "800 48px ui-sans-serif, system-ui";
  ctx.fillText(title, 48, 86);
  lines.forEach((line, index) => {
    ctx.fillStyle = index % 2 ? "#475569" : accent;
    ctx.fillRect(54, 124 + index * 64, 22, 22);
    ctx.fillStyle = "#334155";
    ctx.font = "700 31px ui-sans-serif, system-ui";
    ctx.fillText(line, 98, 145 + index * 64);
  });
  ctx.strokeStyle = accent;
  ctx.lineWidth = 7;
  ctx.beginPath();
  ctx.moveTo(478, 316);
  ctx.lineTo(548, 246);
  ctx.lineTo(628, 278);
  ctx.lineTo(696, 190);
  ctx.stroke();
  const texture = new THREE.CanvasTexture(textureCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function addTeamHouseWhiteboard(title, lines, accent, x, y, z, width, height) {
  addBox(root, width + 0.13, height + 0.13, 0.06, "#cbd5e1", new THREE.Vector3(x, y, z - 0.04), { roughness: 0.6 });
  const board = new THREE.Mesh(
    new THREE.PlaneGeometry(width, height),
    new THREE.MeshBasicMaterial({ map: createTeamHouseWhiteboardTexture(title, lines, accent) }),
  );
  board.position.set(x, y, z);
  root.add(board);
}

function addTeamHouseDesk(station, index) {
  const group = new THREE.Group();
  group.position.copy(station.desk);
  group.rotation.y = station.rotation || 0;
  root.add(group);

  addBox(group, 1.72, 0.18, 0.92, "#997652", new THREE.Vector3(0, 0.56, 0), { roughness: 0.67 });
  addBox(group, 1.84, 0.075, 1.02, "#6e5745", new THREE.Vector3(0, 0.71, 0), { roughness: 0.6 });
  [-0.69, 0.69].forEach((legX) => {
    [-0.35, 0.35].forEach((legZ) => {
      addBox(group, 0.09, 0.56, 0.09, "#293546", new THREE.Vector3(legX, 0.28, legZ), {
        roughness: 0.55,
      });
    });
  });
  addMonitor(group, -0.2, -0.2, station.color);
  addBox(group, 0.55, 0.035, 0.2, "#1f2937", new THREE.Vector3(0.3, 0.76, 0.24), { roughness: 0.42 });
  addBox(group, 0.2, 0.04, 0.18, "#fbfdff", new THREE.Vector3(-0.57, 0.76, 0.21), { roughness: 0.78 });
  addOfficeChair(group, -0.14, 0.77, index);
  addDeskLamp(group, 0.68, -0.25, station.color);
}

function addTeamHouseSign(title, subtitle, accent, width, height, x, y, z) {
  addBox(root, width + 0.18, height + 0.14, 0.06, "#edf4ff", new THREE.Vector3(x, y, z - 0.035), {
    roughness: 0.65,
  });
  const sign = new THREE.Mesh(
    new THREE.PlaneGeometry(width, height),
    new THREE.MeshBasicMaterial({ map: createSignTexture(title, subtitle, accent), transparent: true }),
  );
  sign.position.set(x, y, z);
  root.add(sign);
}

function createTeamHouseScreenTexture(title, detail, accent) {
  const textureCanvas = document.createElement("canvas");
  textureCanvas.width = 960;
  textureCanvas.height = 360;
  const ctx = textureCanvas.getContext("2d");
  ctx.fillStyle = "#101827";
  ctx.fillRect(0, 0, 960, 360);
  ctx.fillStyle = accent;
  ctx.fillRect(0, 0, 960, 10);
  ctx.fillStyle = "#eaf3ff";
  ctx.font = "800 54px ui-monospace, SFMono-Regular, Menlo, monospace";
  ctx.fillText(title, 44, 90);
  ctx.fillStyle = "#9edfff";
  ctx.font = "700 27px ui-sans-serif, system-ui";
  ctx.fillText(detail, 46, 145);
  ctx.strokeStyle = accent;
  ctx.lineWidth = 8;
  ctx.beginPath();
  ctx.moveTo(48, 294);
  ctx.lineTo(205, 242);
  ctx.lineTo(345, 270);
  ctx.lineTo(505, 185);
  ctx.lineTo(664, 220);
  ctx.lineTo(886, 112);
  ctx.stroke();
  for (let index = 0; index < 5; index += 1) {
    ctx.fillStyle = index % 2 ? "#67e8f9" : accent;
    ctx.fillRect(48 + index * 164, 184, 92, 18 + index * 15);
  }
  const texture = new THREE.CanvasTexture(textureCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function addTeamHouseScreen(title, detail, accent, x, y, z, width, height) {
  addBox(root, width + 0.14, height + 0.14, 0.07, "#1e293b", new THREE.Vector3(x, y, z - 0.04), {
    roughness: 0.45,
    emissive: accent,
    emissiveIntensity: 0.12,
  });
  const screen = new THREE.Mesh(
    new THREE.PlaneGeometry(width, height),
    new THREE.MeshBasicMaterial({ map: createTeamHouseScreenTexture(title, detail, accent) }),
  );
  screen.position.set(x, y, z);
  root.add(screen);
}

function addTeamHouseMeetingTable(x, z) {
  const tableTop = new THREE.Mesh(
    new THREE.CylinderGeometry(1.55, 1.55, 0.14, 42),
    new THREE.MeshStandardMaterial({ color: "#fbfdff", roughness: 0.48 }),
  );
  tableTop.position.set(x, 0.8, z);
  tableTop.castShadow = true;
  tableTop.receiveShadow = true;
  root.add(tableTop);
  addBox(root, 0.36, 0.78, 0.36, "#64748b", new THREE.Vector3(x, 0.38, z), { roughness: 0.5 });
  for (let index = 0; index < 5; index += 1) {
    const angle = (index / 5) * Math.PI * 2 + 0.3;
    const chair = new THREE.Group();
    chair.position.set(x + Math.cos(angle) * 2.05, 0, z + Math.sin(angle) * 2.05);
    chair.rotation.y = -angle;
    root.add(chair);
    addOfficeChair(chair, 0, 0, index);
  }
  addBox(root, 0.38, 0.08, 0.3, "#6d5ce7", new THREE.Vector3(x, 0.92, z - 0.18), {
    emissive: "#6d5ce7",
    emissiveIntensity: 0.22,
  });
}

function addTeamHouseResearchPod(x, z) {
  addTeamHouseScreen("SIGNAL MAP", "TRENDS  07   INSIGHTS  16", "#0ea5e9", x, 1.22, -5.73, 3.25, 0.96);
  addTeamHouseWhiteboard("INSIGHT LOOP", ["COLLECT", "COMPARE", "DECIDE"], "#0ea5e9", 5.65, 1.35, -7.5, 1.18, 0.92);
  addBox(root, 0.9, 0.72, 0.74, "#8da4bd", new THREE.Vector3(x - 2.2, 0.36, z + 0.85), { roughness: 0.58 });
  addBox(root, 1.02, 0.08, 0.86, "#f8fafc", new THREE.Vector3(x - 2.2, 0.76, z + 0.85), { roughness: 0.45 });
  addMonitor(root, x - 2.3, z + 0.65, "#0ea5e9");
  addFloorPlant(x + 2.85, z + 1.3, 0.58);
  addShelf(-0.25, -9.7, 0.58, 0);
}

function addTeamHouseAutomationLab(x, z) {
  addTeamHouseScreen("FLOW CONTROL", "WEBHOOKS  11   SYNC  99%", "#1e3a8a", x, 1.2, -5.73, 3.7, 0.96);
  addTeamHouseWhiteboard("AUTOMATE", ["TRIGGER", "ROUTE", "VERIFY"], "#1e3a8a", 7.0, 1.35, -8.0, 1.18, 0.92);
  [-2.9, -2.1, -1.3, 2.1, 2.9].forEach((offset, index) => {
    addTeamHouseServerRack(x + offset, z + (index % 2 ? 0.6 : -0.5), index % 2 ? "#2563eb" : "#1e3a8a");
  });
  addBox(root, 2.2, 0.18, 0.9, "#0f172a", new THREE.Vector3(x - 0.7, 0.62, z + 1.05), {
    roughness: 0.48,
    emissive: "#10234f",
    emissiveIntensity: 0.18,
  });
  addMonitor(root, x - 1.1, z + 0.83, "#2563eb");
  addMonitor(root, x - 0.2, z + 0.83, "#38bdf8");
}

function addTeamHouseSalesHuddle(x, z) {
  const table = new THREE.Mesh(
    new THREE.CylinderGeometry(0.9, 0.9, 0.13, 32),
    new THREE.MeshStandardMaterial({ color: "#f8fafc", roughness: 0.5 }),
  );
  table.position.set(x, 0.72, z);
  table.castShadow = true;
  root.add(table);
  addBox(root, 0.26, 0.7, 0.26, "#64748b", new THREE.Vector3(x, 0.35, z), { roughness: 0.48 });
  [-1.15, 1.15].forEach((offset, index) => {
    const chair = new THREE.Group();
    chair.position.set(x + offset, 0, z);
    chair.rotation.y = index ? -Math.PI / 2 : Math.PI / 2;
    root.add(chair);
    addOfficeChair(chair, 0, 0, index);
  });
  addTeamHouseScreen("SALES BOARD", "PIPELINE / DEALS / FORECAST", "#4f78e8", x, 1.3, 5.18, 3.0, 1.0);
}

function addTeamHouseMarketingStudio(x, z) {
  addTeamHouseWhiteboard("CONTENT BOARD", ["IDEATE", "CREATE", "MEASURE"], "#8b5cf6", 7.05, 1.34, -2.2, 1.2, 0.9);
  addBox(root, 1.45, 0.72, 0.78, "#8da4bd", new THREE.Vector3(x + 1.7, 0.36, z + 1.0), { roughness: 0.58 });
  addBox(root, 1.55, 0.08, 0.88, "#f8fafc", new THREE.Vector3(x + 1.7, 0.76, z + 1.0), { roughness: 0.45 });
  addMonitor(root, x + 1.58, z + 0.82, "#8b5cf6");
  const tripod = new THREE.Group();
  tripod.position.set(x + 3.1, 0, z + 1.05);
  root.add(tripod);
  addBox(tripod, 0.09, 1.1, 0.09, "#334155", new THREE.Vector3(0, 0.55, 0));
  [-0.42, 0, 0.42].forEach((offset) => {
    const leg = addBox(tripod, 0.055, 0.7, 0.055, "#334155", new THREE.Vector3(0, 0.32, 0));
    leg.rotation.z = offset;
  });
  addBox(tripod, 0.42, 0.25, 0.28, "#1e293b", new THREE.Vector3(0, 1.12, 0), { roughness: 0.4 });
  addBox(tripod, 0.18, 0.12, 0.04, "#67e8f9", new THREE.Vector3(0, 1.12, -0.16), {
    emissive: "#0ea5e9",
    emissiveIntensity: 0.35,
  });
  addShelf(15.0, -0.8, 0.66, Math.PI / 2);
  addFloorPlant(14.95, 1.1, 0.58);
}

function addTeamHouseSupportZone(x, z) {
  addTeamHouseWhiteboard("CARE LOOP", ["LISTEN", "SOLVE", "FOLLOW UP"], "#10b981", 7.05, 1.33, 4.1, 1.2, 0.9);
  addBox(root, 1.5, 1.35, 0.5, "#dcefe5", new THREE.Vector3(x + 3.25, 0.68, z + 0.8), { roughness: 0.72 });
  for (let row = 0; row < 3; row += 1) {
    addBox(root, 1.2, 0.1, 0.04, "#8dd3b2", new THREE.Vector3(x + 3.25, 0.35 + row * 0.35, z + 0.53), {
      emissive: "#10b981",
      emissiveIntensity: 0.15,
    });
  }
  addTeamHouseWaterCooler(x - 3.15, z + 0.75);
  addFloorPlant(x + 3.8, z - 0.85, 0.58);
}

function addTeamHouseReception(x, z) {
  addTeamHouseSign("TEAMORA AI", "reception / command center", "#4f5bd5", 3.2, 0.55, x, 1.88, 3.1);
  addBox(root, 4.2, 0.82, 1.0, "#eaf1ff", new THREE.Vector3(x, 0.41, z), { roughness: 0.58 });
  addBox(root, 4.4, 0.1, 1.13, "#fbfdff", new THREE.Vector3(x, 0.86, z), { roughness: 0.42 });
  addBox(root, 1.45, 0.34, 0.08, "#4f5bd5", new THREE.Vector3(x, 1.16, z - 0.53), {
    emissive: "#4f5bd5",
    emissiveIntensity: 0.24,
  });
  addBox(root, 0.58, 0.52, 0.18, "#1e293b", new THREE.Vector3(x - 1.35, 1.2, z), { roughness: 0.42 });
  addBox(root, 0.42, 0.18, 0.08, "#67e8f9", new THREE.Vector3(x - 1.35, 1.25, z - 0.14), {
    emissive: "#0ea5e9",
    emissiveIntensity: 0.36,
  });
  addSofa(x - 1.25, z + 2.25, 0);
  addCoffeeTable(x + 0.65, z + 2.05);
  addFloorPlant(x - 2.55, z - 0.55, 0.62);
  addFloorPlant(x + 2.4, z + 2.2, 0.52);
}

function addTeamHouseCafe(x, z) {
  addTeamHouseSign("AI CAFE", "coffee / quick sync", "#f59e0b", 2.75, 0.5, x, 1.55, 4.12);
  addBox(root, 3.45, 0.76, 0.86, "#a6794d", new THREE.Vector3(x, 0.38, z - 0.85), { roughness: 0.66 });
  addBox(root, 3.58, 0.09, 0.98, "#fbfdff", new THREE.Vector3(x, 0.8, z - 0.85), { roughness: 0.45 });
  addBox(root, 0.46, 0.46, 0.32, "#1f2937", new THREE.Vector3(x - 1.05, 1.05, z - 0.85), { roughness: 0.4 });
  addBox(root, 0.24, 0.22, 0.34, "#334155", new THREE.Vector3(x - 1.05, 1.37, z - 0.85), { roughness: 0.4 });
  [-0.78, 0.78].forEach((offset, index) => {
    const stool = new THREE.Group();
    stool.position.set(x + offset, 0, z - 2.05);
    root.add(stool);
    addBox(stool, 0.44, 0.11, 0.44, index ? "#f59e0b" : "#fb923c", new THREE.Vector3(0, 0.58, 0), { roughness: 0.52 });
    addBox(stool, 0.08, 0.58, 0.08, "#475569", new THREE.Vector3(0, 0.29, 0), { roughness: 0.5 });
  });
  addTeamHouseWaterCooler(x + 2.1, z + 1.5);
  addShelf(-0.35, 9.9, 0.58, 0);
  addFloorPlant(x - 2.0, z + 1.85, 0.52);
}

function addTeamHouseLounge(x, z) {
  addTeamHouseSign("LOUNGE", "reset / think / share", "#10b981", 2.55, 0.48, x, 1.48, 6.12);
  addBox(root, 2.8, 0.42, 0.9, "#64748b", new THREE.Vector3(x - 0.9, 0.32, z + 0.1), { roughness: 0.7 });
  addBox(root, 2.8, 0.55, 0.2, "#64748b", new THREE.Vector3(x - 0.9, 0.76, z + 0.47), { roughness: 0.7 });
  addBox(root, 1.0, 0.42, 0.9, "#8b5cf6", new THREE.Vector3(x + 1.45, 0.32, z - 0.45), { roughness: 0.7 });
  addBox(root, 0.96, 0.1, 0.74, "#f8fafc", new THREE.Vector3(x + 0.15, 0.48, z - 0.08), { roughness: 0.48 });
  addBox(root, 0.14, 0.42, 0.14, "#475569", new THREE.Vector3(x + 0.15, 0.21, z - 0.08), { roughness: 0.5 });
  addFloorLamp(x + 2.1, z + 1.35);
  addFloorPlant(x - 2.0, z + 1.55, 0.5);
}

function addTeamHouseMeetingRoom(x, z) {
  addTeamHouseSign("MEETING ROOM", "align / decide / move", "#4f5bd5", 3.0, 0.52, x, 1.52, 4.12);
  const table = new THREE.Mesh(
    new THREE.BoxGeometry(3.2, 0.13, 1.32),
    new THREE.MeshStandardMaterial({ color: "#fbfdff", roughness: 0.48 }),
  );
  table.position.set(x, 0.78, z);
  table.castShadow = true;
  table.receiveShadow = true;
  root.add(table);
  [-1.22, 1.22].forEach((offset, index) => {
    [-0.95, 0.95].forEach((side, sideIndex) => {
      const chair = new THREE.Group();
      chair.position.set(x + offset, 0, z + side);
      chair.rotation.y = sideIndex ? Math.PI : 0;
      root.add(chair);
      addOfficeChair(chair, 0, 0, index + sideIndex);
    });
  });
  addBox(root, 0.34, 0.68, 0.34, "#64748b", new THREE.Vector3(x, 0.36, z), { roughness: 0.5 });
  addTeamHouseWhiteboard("MEETING NOTES", ["GOAL", "OWNER", "NEXT"], "#4f5bd5", -1.38, 1.35, 6.25, 1.15, 0.9);
  addFloorPlant(x + 2.25, z + 1.85, 0.54);
}

function addTeamHouseRecreationCorner(x, z) {
  addTeamHouseSign("RECREATION", "recharge / rally / return", "#0ea5e9", 2.95, 0.48, x, 1.48, 6.12);
  addBox(root, 3.45, 0.78, 1.6, "#0f766e", new THREE.Vector3(x, 0.92, z), { roughness: 0.48 });
  addBox(root, 3.56, 0.08, 1.7, "#10b981", new THREE.Vector3(x, 1.35, z), { roughness: 0.42 });
  addBox(root, 0.07, 0.62, 1.76, "#f8fafc", new THREE.Vector3(x, 1.7, z), { roughness: 0.48 });
  [-1.35, 1.35].forEach((offset) => {
    [-0.57, 0.57].forEach((side) => {
      addBox(root, 0.11, 0.82, 0.11, "#334155", new THREE.Vector3(x + offset, 0.42, z + side), { roughness: 0.52 });
    });
  });
  const ball = new THREE.Mesh(
    new THREE.SphereGeometry(0.1, 12, 12),
    new THREE.MeshStandardMaterial({ color: "#f8fafc", roughness: 0.42 }),
  );
  ball.position.set(x + 0.38, 1.55, z - 0.26);
  ball.castShadow = true;
  root.add(ball);
  addBox(root, 0.5, 0.08, 0.32, "#f59e0b", new THREE.Vector3(x - 2.1, 0.22, z - 1.1), { roughness: 0.48 });
  addFloorPlant(x + 2.15, z + 1.45, 0.5);
}

function addTeamHouseWaterCooler(x, z) {
  addBox(root, 0.34, 0.86, 0.34, "#dbeafe", new THREE.Vector3(x, 0.43, z), { roughness: 0.44 });
  const bottle = new THREE.Mesh(
    new THREE.CylinderGeometry(0.18, 0.16, 0.45, 16),
    new THREE.MeshStandardMaterial({ color: "#b9e6ff", transparent: true, opacity: 0.72, roughness: 0.18 }),
  );
  bottle.position.set(x, 1.1, z);
  bottle.castShadow = true;
  root.add(bottle);
  addBox(root, 0.09, 0.08, 0.05, "#0ea5e9", new THREE.Vector3(x - 0.08, 0.62, z - 0.19), { emissive: "#0ea5e9", emissiveIntensity: 0.22 });
  addBox(root, 0.09, 0.08, 0.05, "#ef4444", new THREE.Vector3(x + 0.08, 0.62, z - 0.19), { emissive: "#ef4444", emissiveIntensity: 0.18 });
}

function addTeamHouseServerRack(x, z, accent) {
  addBox(root, 0.56, 1.5, 0.58, "#1e293b", new THREE.Vector3(x, 0.75, z), { roughness: 0.45 });
  for (let index = 0; index < 5; index += 1) {
    addBox(root, 0.38, 0.08, 0.04, accent, new THREE.Vector3(x, 0.28 + index * 0.23, z - 0.31), {
      emissive: accent,
      emissiveIntensity: 0.38,
    });
  }
}

function addTeamHousePendant(x, z, color) {
  const light = new THREE.Mesh(
    new THREE.CylinderGeometry(0.24, 0.28, 0.16, 20),
    new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.25, roughness: 0.38 }),
  );
  light.position.set(x, 2.55, z);
  light.castShadow = true;
  root.add(light);
  addBox(root, 0.035, 0.85, 0.035, "#cbd5e1", new THREE.Vector3(x, 2.95, z), { roughness: 0.42 });
}

function addRoomFloor(room, texture) {
  const floor = new THREE.Mesh(
    new THREE.BoxGeometry(room.size.x, 0.2, room.size.z),
    new THREE.MeshStandardMaterial({
      map: texture,
      roughness: 0.78,
      metalness: 0.03,
    }),
  );
  floor.position.set(room.center.x, -0.08, room.center.z);
  floor.receiveShadow = true;
  root.add(floor);
  return floor;
}

function addRoomShell() {
  const wallMat = new THREE.MeshStandardMaterial({
    color: "#d7e1ee",
    roughness: 0.82,
  });
  const innerWallMat = new THREE.MeshStandardMaterial({
    color: "#eef3f8",
    roughness: 0.78,
  });
  const trimMat = new THREE.MeshStandardMaterial({
    color: "#cbd7e6",
    roughness: 0.62,
  });
  const glassMat = new THREE.MeshStandardMaterial({
    color: "#d7ecff",
    transparent: true,
    opacity: 0.46,
    roughness: 0.2,
  });

  addWallBlock(14.8, 2.55, 0.3, new THREE.Vector3(0, 1.05, -5.62), wallMat);
  addWallBlock(0.3, 2.55, 11.35, new THREE.Vector3(-7.38, 1.05, 0), wallMat);
  addWallBlock(0.22, 0.58, 11.35, new THREE.Vector3(7.36, 0.16, 0), trimMat);
  addWallBlock(14.8, 0.34, 0.22, new THREE.Vector3(0, 0.03, 5.58), trimMat);
  addWallBlock(0.22, 0.34, 11.35, new THREE.Vector3(7.36, 0.03, 0), trimMat);

  addWallBlock(5.35, 1.45, 0.2, new THREE.Vector3(-4.6, 0.62, 0.4), innerWallMat);
  addWallBlock(5.35, 1.45, 0.2, new THREE.Vector3(4.6, 0.62, 0.4), innerWallMat);
  addWallBlock(0.2, 1.45, 3.35, new THREE.Vector3(0, 0.62, 2.65), innerWallMat);

  addWallBlock(1.5, 0.16, 0.12, new THREE.Vector3(-2.05, 1.45, 0.35), trimMat);
  addWallBlock(1.5, 0.16, 0.12, new THREE.Vector3(2.05, 1.45, 0.35), trimMat);
  addWallBlock(0.12, 0.16, 1.2, new THREE.Vector3(0, 1.45, 0.85), trimMat);

  for (let i = 0; i < 5; i += 1) {
    const panel = new THREE.Mesh(new THREE.BoxGeometry(1.35, 0.78, 0.08), glassMat);
    panel.position.set(-5.4 + i * 2.45, 1.62, -5.78);
    root.add(panel);
  }

  addSignPlane("OPEN SPACE", "work / collaborate / ship", "#4f5bd5", 3.25, 0.78, -4.8, 1.86, -5.8);
  addSignPlane("KITCHEN", "coffee / snacks", "#f59e0b", 2.4, 0.62, -4.9, 1.5, 0.28);
  addSignPlane("RELAX ROOM", "rest / recharge", "#10b981", 2.55, 0.62, 4.9, 1.5, 0.28);
}

function addOpenSpaceRoom() {
  workStations.forEach((station, index) => {
    addDesk(station.desk.x, station.desk.z, index, station.rotation, station.color);
    addPad(station.point, agents[index]?.color || station.color);
  });

  addWhiteboard(2.75, -5.43, 3.7, 1.15, "TASKS", ["PLAN", "BUILD", "TEST", "DEPLOY"]);
  addWallScreen(-4.7, -5.44, 3.2, 1.0);
  addPlantDivider(-0.85, -0.55, 2.0);
  addPlantDivider(1.15, -0.55, 2.0);
  addShelf(6.1, -4.35, 0.75, Math.PI * 0.5);
  addFloorPlant(5.75, -0.45, 0.75);
  addFloorPlant(-6.05, -0.55, 0.65);
}

function addKitchenRoom() {
  addKitchenCounter(-6.15, 1.6, 0);
  addKitchenCounter(-5.05, 1.6, 1);
  addKitchenCounter(-3.95, 1.6, 2);
  addFridge(-6.15, 3.45);
  addCoffeeMachine(-5.02, 1.2);
  addSink(-4.05, 1.16);
  addDiningSet(-3.55, 4.2);
  addWaterCooler(-1.0, 1.35);
  addShelf(-6.85, 4.65, 0.62, Math.PI * 0.5);

  addFoodModel("cup-coffee", new THREE.Vector3(-5.0, 0.82, 1.05), 0.18, 0.2);
  addFoodModel("mug", new THREE.Vector3(-3.45, 0.74, 4.2), 0.18, -0.4);
  addFoodModel("plate", new THREE.Vector3(-3.2, 0.75, 4.05), 0.2, 0);
  addFoodModel("apple", new THREE.Vector3(-3.75, 0.82, 4.2), 0.16, 0.4);
  addFoodModel("banana", new THREE.Vector3(-3.95, 0.82, 4.0), 0.16, 1.1);
  addFoodModel("donut", new THREE.Vector3(-2.95, 0.82, 4.34), 0.15, 0.2);
}

function addRelaxRoom() {
  addRug(3.65, 3.55, 3.4, 2.45, "#c7d2fe", 0.15);
  addSofa(2.2, 3.2, 0.0);
  addLoungeChair(4.35, 4.35, -0.6);
  addCoffeeTable(3.45, 3.65);
  addTvStand(6.12, 2.55);
  addShelf(6.25, 4.6, 0.72, Math.PI * 0.5);
  addFloorLamp(1.05, 4.75);
  addFloorPlant(1.25, 2.0, 0.62);
  addBeanBag(4.95, 2.0);
  addFoodModel("cup", new THREE.Vector3(3.25, 0.62, 3.56), 0.16, 0);
  addFoodModel("bowl", new THREE.Vector3(3.6, 0.63, 3.72), 0.16, 0.3);
}

function addRoomLights() {
  addPendant(-4.0, 2.75, -2.25, "#fff5d6");
  addPendant(2.5, 2.75, -2.25, "#fff5d6");
  addPendant(-3.5, 2.55, 3.35, "#fff0c7");
  addPendant(3.9, 2.55, 3.45, "#f1f5ff");
}

function addWallBlock(width, height, depth, position, mat) {
  const wall = new THREE.Mesh(new THREE.BoxGeometry(width, height, depth), mat);
  wall.position.copy(position);
  wall.castShadow = true;
  wall.receiveShadow = true;
  root.add(wall);
  return wall;
}

function createSignTexture(title, subtitle, accent = "#4f5bd5") {
  const textureCanvas = document.createElement("canvas");
  textureCanvas.width = 768;
  textureCanvas.height = 256;
  const ctx = textureCanvas.getContext("2d");
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, 768, 256);
  ctx.fillStyle = accent;
  ctx.fillRect(0, 0, 18, 256);
  ctx.fillStyle = "#111827";
  ctx.font = "800 58px ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI'";
  ctx.fillText(title, 54, 105);
  ctx.fillStyle = "#64748b";
  ctx.font = "600 30px ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI'";
  ctx.fillText(subtitle, 56, 162);
  ctx.fillStyle = "rgba(79, 91, 213, 0.08)";
  ctx.fillRect(54, 190, 560, 18);
  const texture = new THREE.CanvasTexture(textureCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function addSignPlane(title, subtitle, accent, width, height, x, y, z) {
  const sign = new THREE.Mesh(
    new THREE.PlaneGeometry(width, height),
    new THREE.MeshBasicMaterial({
      map: createSignTexture(title, subtitle, accent),
      transparent: true,
    }),
  );
  sign.position.set(x, y, z);
  root.add(sign);
  return sign;
}

function addWhiteboard(x, z, width, height, title, lines) {
  const textureCanvas = document.createElement("canvas");
  textureCanvas.width = 768;
  textureCanvas.height = 384;
  const ctx = textureCanvas.getContext("2d");
  ctx.fillStyle = "#f8fafc";
  ctx.fillRect(0, 0, 768, 384);
  ctx.strokeStyle = "#334155";
  ctx.lineWidth = 12;
  ctx.strokeRect(18, 18, 732, 348);
  ctx.fillStyle = "#111827";
  ctx.font = "800 52px ui-sans-serif, system-ui";
  ctx.fillText(title, 58, 82);
  ctx.font = "600 34px ui-sans-serif, system-ui";
  lines.forEach((line, index) => {
    ctx.fillText(`• ${line}`, 62, 145 + index * 48);
  });
  ctx.strokeStyle = "#64748b";
  ctx.lineWidth = 4;
  ctx.beginPath();
  ctx.moveTo(430, 120);
  ctx.lineTo(620, 285);
  ctx.stroke();
  for (let i = 0; i < 5; i += 1) {
    ctx.fillStyle = i % 2 ? "#fbbf24" : "#f87171";
    ctx.fillRect(585 + (i % 2) * 58, 125 + i * 36, 34, 34);
  }
  const texture = new THREE.CanvasTexture(textureCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;

  const board = new THREE.Mesh(
    new THREE.PlaneGeometry(width, height),
    new THREE.MeshBasicMaterial({ map: texture }),
  );
  board.position.set(x, 1.62, z);
  root.add(board);
  return board;
}

function addWallScreen(x, z, width, height) {
  const textureCanvas = document.createElement("canvas");
  textureCanvas.width = 768;
  textureCanvas.height = 256;
  const ctx = textureCanvas.getContext("2d");
  ctx.fillStyle = "#111827";
  ctx.fillRect(0, 0, 768, 256);
  ctx.fillStyle = "#38bdf8";
  ctx.shadowColor = "#38bdf8";
  ctx.shadowBlur = 18;
  ctx.font = "800 58px ui-monospace, SFMono-Regular, Menlo, monospace";
  ctx.fillText("AI AGENTS", 54, 110);
  ctx.shadowBlur = 0;
  ctx.fillStyle = "#dbeafe";
  ctx.font = "600 28px ui-sans-serif, system-ui";
  ctx.fillText("WORK. COLLABORATE. EVOLVE.", 58, 165);
  const texture = new THREE.CanvasTexture(textureCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;

  const screen = new THREE.Mesh(
    new THREE.PlaneGeometry(width, height),
    new THREE.MeshBasicMaterial({ map: texture }),
  );
  screen.position.set(x, 1.72, z);
  root.add(screen);
  return screen;
}

function addDesk(x, z, index, rotation = 0, accent = "#4f5bd5") {
  const group = new THREE.Group();
  group.position.set(x, 0, z);
  group.rotation.y = rotation;
  root.add(group);

  addBox(group, 1.58, 0.18, 0.86, "#9b7a58", new THREE.Vector3(0, 0.56, 0), {
    roughness: 0.68,
  });
  addBox(group, 1.7, 0.07, 0.94, "#6f5845", new THREE.Vector3(0, 0.71, 0), {
    roughness: 0.62,
  });
  [-0.64, 0.64].forEach((legX) => {
    [-0.32, 0.32].forEach((legZ) => {
      addBox(group, 0.08, 0.56, 0.08, "#2f3a4a", new THREE.Vector3(legX, 0.28, legZ), {
        roughness: 0.55,
      });
    });
  });

  addMonitor(group, -0.18, -0.18, accent);
  addBox(group, 0.52, 0.035, 0.18, "#1f2937", new THREE.Vector3(0.26, 0.75, 0.22), {
    roughness: 0.45,
  });
  addBox(group, 0.22, 0.025, 0.18, "#334155", new THREE.Vector3(-0.52, 0.75, 0.22), {
    roughness: 0.45,
  });
  addOfficeChair(group, -0.15, 0.72, index);
  addDeskLamp(group, 0.64, -0.22, accent);
  if (index % 2 === 0) {
    addFoodModel("cup-coffee", new THREE.Vector3(x + 0.42, 0.83, z + 0.1), 0.13, 0.4);
  }
  return group;
}

function addMonitor(parent, x, z, accent) {
  addBox(parent, 0.08, 0.22, 0.08, "#1f2937", new THREE.Vector3(x, 0.88, z + 0.04), {
    roughness: 0.5,
  });
  addBox(parent, 0.56, 0.05, 0.24, "#111827", new THREE.Vector3(x, 0.76, z + 0.08), {
    roughness: 0.5,
  });
  addBox(parent, 0.7, 0.5, 0.08, "#1e293b", new THREE.Vector3(x, 1.08, z), {
    roughness: 0.4,
  });
  addBox(parent, 0.56, 0.36, 0.024, accent, new THREE.Vector3(x, 1.08, z - 0.045), {
    roughness: 0.35,
    emissive: accent,
    emissiveIntensity: 0.32,
  });
}

function addOfficeChair(parent, x, z, index) {
  const color = index % 2 ? "#334155" : "#475569";
  addBox(parent, 0.48, 0.16, 0.46, color, new THREE.Vector3(x, 0.35, z), { roughness: 0.65 });
  addBox(parent, 0.48, 0.58, 0.14, color, new THREE.Vector3(x, 0.72, z + 0.2), {
    roughness: 0.65,
  });
  addBox(parent, 0.1, 0.33, 0.1, "#1f2937", new THREE.Vector3(x, 0.17, z), {
    roughness: 0.5,
  });
}

function addDeskLamp(parent, x, z, accent) {
  addBox(parent, 0.08, 0.34, 0.08, "#475569", new THREE.Vector3(x, 0.94, z), {
    roughness: 0.45,
  });
  const shade = new THREE.Mesh(
    new THREE.ConeGeometry(0.18, 0.18, 18),
    new THREE.MeshStandardMaterial({
      color: "#f8fafc",
      emissive: accent,
      emissiveIntensity: 0.18,
      roughness: 0.5,
    }),
  );
  shade.position.set(x, 1.18, z);
  shade.rotation.x = Math.PI;
  shade.castShadow = true;
  parent.add(shade);
}

function addPad(slot, color) {
  const pad = new THREE.Mesh(
    new THREE.CircleGeometry(0.58, 36),
    new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.13,
      depthWrite: false,
    }),
  );
  pad.rotation.x = -Math.PI / 2;
  pad.position.set(slot.x, 0.025, slot.z);
  root.add(pad);
}

function addPlantDivider(x, z, width) {
  addBox(root, width, 0.5, 0.42, "#d6d3d1", new THREE.Vector3(x, 0.26, z), {
    roughness: 0.78,
  });
  for (let i = 0; i < 5; i += 1) {
    const leaf = new THREE.Mesh(
      new THREE.ConeGeometry(0.12, 0.65, 8),
      new THREE.MeshStandardMaterial({ color: i % 2 ? "#15803d" : "#22c55e", roughness: 0.7 }),
    );
    leaf.position.set(x - width * 0.38 + i * (width / 4.5), 0.8, z);
    leaf.rotation.x = 0.25 + i * 0.08;
    leaf.rotation.z = i % 2 ? 0.35 : -0.35;
    leaf.castShadow = true;
    root.add(leaf);
  }
}

function addFloorPlant(x, z, scale = 0.7) {
  const pot = new THREE.Mesh(
    new THREE.CylinderGeometry(0.26 * scale, 0.34 * scale, 0.42 * scale, 16),
    new THREE.MeshStandardMaterial({ color: "#8b5e3c", roughness: 0.78 }),
  );
  pot.position.set(x, 0.22 * scale, z);
  pot.castShadow = true;
  pot.receiveShadow = true;
  root.add(pot);
  for (let i = 0; i < 7; i += 1) {
    const leaf = new THREE.Mesh(
      new THREE.ConeGeometry(0.09 * scale, 0.75 * scale, 8),
      new THREE.MeshStandardMaterial({ color: i % 2 ? "#16a34a" : "#65a30d", roughness: 0.72 }),
    );
    leaf.position.set(x, 0.72 * scale, z);
    leaf.rotation.z = (i / 7) * Math.PI * 2;
    leaf.rotation.x = 0.35;
    leaf.castShadow = true;
    root.add(leaf);
  }
}

function addShelf(x, z, scale = 0.72, rotation = 0) {
  const group = new THREE.Group();
  group.position.set(x, 0, z);
  group.rotation.y = rotation;
  group.scale.setScalar(scale);
  root.add(group);
  addBox(group, 0.9, 1.65, 0.28, "#5b4636", new THREE.Vector3(0, 0.82, 0), { roughness: 0.68 });
  addBox(group, 0.8, 1.46, 0.24, "#f8fafc", new THREE.Vector3(0, 0.86, -0.02), {
    roughness: 0.8,
  });
  for (let i = 0; i < 4; i += 1) {
    addBox(group, 0.82, 0.055, 0.3, "#6f5845", new THREE.Vector3(0, 0.32 + i * 0.38, 0), {
      roughness: 0.65,
    });
  }
  for (let i = 0; i < 9; i += 1) {
    addBox(
      group,
      0.07,
      0.27 + (i % 3) * 0.04,
      0.18,
      ["#4f5bd5", "#ef4444", "#10b981", "#f59e0b"][i % 4],
      new THREE.Vector3(-0.32 + i * 0.08, 0.44 + (i % 3) * 0.38, -0.16),
      { roughness: 0.7 },
    );
  }
}

function addKitchenCounter(x, z, index) {
  addBox(root, 1.0, 0.74, 0.68, "#d6a86e", new THREE.Vector3(x, 0.37, z), { roughness: 0.7 });
  addBox(root, 1.04, 0.08, 0.72, "#f8fafc", new THREE.Vector3(x, 0.78, z), { roughness: 0.45 });
  addBox(root, 0.08, 0.55, 0.03, "#b77943", new THREE.Vector3(x - 0.24, 0.38, z - 0.35), {
    roughness: 0.7,
  });
  addBox(root, 0.08, 0.55, 0.03, "#b77943", new THREE.Vector3(x + 0.24, 0.38, z - 0.35), {
    roughness: 0.7,
  });
  if (index === 2) {
    addBox(root, 0.4, 0.06, 0.34, "#94a3b8", new THREE.Vector3(x, 0.84, z), {
      roughness: 0.35,
      metalness: 0.2,
    });
  }
}

function addFridge(x, z) {
  addBox(root, 0.74, 1.55, 0.64, "#e2e8f0", new THREE.Vector3(x, 0.78, z), {
    roughness: 0.45,
    metalness: 0.08,
  });
  addBox(root, 0.03, 1.18, 0.04, "#64748b", new THREE.Vector3(x - 0.33, 0.78, z - 0.34), {
    roughness: 0.45,
  });
  addBox(root, 0.64, 0.035, 0.04, "#cbd5e1", new THREE.Vector3(x, 1.12, z - 0.35), {
    roughness: 0.45,
  });
}

function addCoffeeMachine(x, z) {
  addBox(root, 0.42, 0.36, 0.28, "#1f2937", new THREE.Vector3(x, 0.98, z), {
    roughness: 0.35,
  });
  addBox(root, 0.24, 0.12, 0.04, "#38bdf8", new THREE.Vector3(x, 1.05, z - 0.16), {
    emissive: "#0ea5e9",
    emissiveIntensity: 0.35,
    roughness: 0.35,
  });
}

function addSink(x, z) {
  const bowl = new THREE.Mesh(
    new THREE.CylinderGeometry(0.23, 0.2, 0.08, 24),
    new THREE.MeshStandardMaterial({ color: "#cbd5e1", roughness: 0.35, metalness: 0.25 }),
  );
  bowl.position.set(x, 0.88, z);
  bowl.castShadow = true;
  root.add(bowl);
  addBox(root, 0.07, 0.28, 0.06, "#64748b", new THREE.Vector3(x + 0.24, 1.02, z), {
    roughness: 0.35,
    metalness: 0.2,
  });
}

function addDiningSet(x, z) {
  addBox(root, 1.75, 0.12, 1.05, "#f2d4a3", new THREE.Vector3(x, 0.62, z), { roughness: 0.7 });
  [-0.62, 0.62].forEach((legX) => {
    [-0.35, 0.35].forEach((legZ) => {
      addBox(root, 0.08, 0.58, 0.08, "#ad7f51", new THREE.Vector3(x + legX, 0.31, z + legZ), {
        roughness: 0.68,
      });
    });
  });
  [
    [x - 1.0, z, Math.PI * 0.5],
    [x + 1.0, z, -Math.PI * 0.5],
    [x, z - 0.72, 0],
    [x, z + 0.72, Math.PI],
  ].forEach(([cx, cz, rotation], index) => {
    const group = new THREE.Group();
    group.position.set(cx, 0, cz);
    group.rotation.y = rotation;
    root.add(group);
    addBox(group, 0.42, 0.12, 0.42, "#e2e8f0", new THREE.Vector3(0, 0.34, 0), {
      roughness: 0.72,
    });
    addBox(group, 0.42, 0.48, 0.1, index % 2 ? "#d1d5db" : "#f8fafc", new THREE.Vector3(0, 0.66, 0.2), {
      roughness: 0.72,
    });
  });
}

function addWaterCooler(x, z) {
  addBox(root, 0.34, 0.72, 0.34, "#e2e8f0", new THREE.Vector3(x, 0.36, z), { roughness: 0.58 });
  const bottle = new THREE.Mesh(
    new THREE.CylinderGeometry(0.18, 0.18, 0.52, 18),
    new THREE.MeshStandardMaterial({
      color: "#bae6fd",
      transparent: true,
      opacity: 0.72,
      roughness: 0.2,
    }),
  );
  bottle.position.set(x, 0.98, z);
  bottle.castShadow = true;
  root.add(bottle);
}

function addRug(x, z, width, depth, color, opacity = 0.2) {
  const rug = new THREE.Mesh(
    new THREE.BoxGeometry(width, 0.035, depth),
    new THREE.MeshStandardMaterial({
      color,
      transparent: true,
      opacity,
      roughness: 0.9,
    }),
  );
  rug.position.set(x, 0.035, z);
  rug.receiveShadow = true;
  root.add(rug);
}

function addSofa(x, z, rotation) {
  const group = new THREE.Group();
  group.position.set(x, 0, z);
  group.rotation.y = rotation;
  root.add(group);
  addBox(group, 1.7, 0.42, 0.62, "#94a3b8", new THREE.Vector3(0, 0.35, 0), { roughness: 0.78 });
  addBox(group, 1.72, 0.76, 0.22, "#64748b", new THREE.Vector3(0, 0.68, 0.3), { roughness: 0.78 });
  addBox(group, 0.24, 0.48, 0.68, "#64748b", new THREE.Vector3(-0.96, 0.44, 0), { roughness: 0.78 });
  addBox(group, 0.24, 0.48, 0.68, "#64748b", new THREE.Vector3(0.96, 0.44, 0), { roughness: 0.78 });
  addBox(group, 0.38, 0.18, 0.14, "#facc15", new THREE.Vector3(-0.32, 0.72, -0.18), {
    roughness: 0.78,
  });
  addBox(group, 0.38, 0.18, 0.14, "#38bdf8", new THREE.Vector3(0.28, 0.72, -0.18), {
    roughness: 0.78,
  });
}

function addLoungeChair(x, z, rotation) {
  const group = new THREE.Group();
  group.position.set(x, 0, z);
  group.rotation.y = rotation;
  root.add(group);
  addBox(group, 0.64, 0.32, 0.72, "#a78bfa", new THREE.Vector3(0, 0.32, 0), { roughness: 0.78 });
  addBox(group, 0.66, 0.68, 0.18, "#7c3aed", new THREE.Vector3(0, 0.68, 0.28), { roughness: 0.78 });
}

function addCoffeeTable(x, z) {
  addBox(root, 1.2, 0.12, 0.64, "#7c5f46", new THREE.Vector3(x, 0.46, z), { roughness: 0.68 });
  addBox(root, 1.28, 0.04, 0.72, "#e2e8f0", new THREE.Vector3(x, 0.55, z), {
    roughness: 0.25,
    metalness: 0.08,
  });
  [-0.48, 0.48].forEach((legX) => {
    [-0.22, 0.22].forEach((legZ) => {
      addBox(root, 0.07, 0.42, 0.07, "#4b5563", new THREE.Vector3(x + legX, 0.24, z + legZ), {
        roughness: 0.55,
      });
    });
  });
}

function addTvStand(x, z) {
  addBox(root, 1.6, 0.34, 0.46, "#6f5845", new THREE.Vector3(x, 0.24, z), { roughness: 0.68 });
  const tv = new THREE.Mesh(
    new THREE.BoxGeometry(1.48, 0.84, 0.08),
    new THREE.MeshStandardMaterial({
      color: "#111827",
      roughness: 0.35,
      emissive: "#12213d",
      emissiveIntensity: 0.45,
    }),
  );
  tv.position.set(x, 0.92, z - 0.24);
  tv.castShadow = true;
  root.add(tv);
  addBox(root, 1.18, 0.56, 0.025, "#4f5bd5", new THREE.Vector3(x, 0.92, z - 0.29), {
    emissive: "#4f5bd5",
    emissiveIntensity: 0.28,
    roughness: 0.35,
  });
}

function addFloorLamp(x, z) {
  addBox(root, 0.08, 1.15, 0.08, "#475569", new THREE.Vector3(x, 0.62, z), {
    roughness: 0.45,
  });
  const shade = new THREE.Mesh(
    new THREE.ConeGeometry(0.32, 0.38, 24),
    new THREE.MeshStandardMaterial({
      color: "#fef3c7",
      emissive: "#fde68a",
      emissiveIntensity: 0.42,
      roughness: 0.55,
    }),
  );
  shade.position.set(x, 1.35, z);
  shade.rotation.x = Math.PI;
  shade.castShadow = true;
  root.add(shade);
}

function addBeanBag(x, z) {
  const bean = new THREE.Mesh(
    new THREE.SphereGeometry(0.48, 24, 14),
    new THREE.MeshStandardMaterial({ color: "#f97316", roughness: 0.9 }),
  );
  bean.position.set(x, 0.36, z);
  bean.scale.set(1.18, 0.58, 0.95);
  bean.castShadow = true;
  bean.receiveShadow = true;
  root.add(bean);
}

function addPendant(x, y, z, color) {
  addBox(root, 0.035, 0.52, 0.035, "#94a3b8", new THREE.Vector3(x, y + 0.25, z), {
    roughness: 0.45,
  });
  const lamp = new THREE.Mesh(
    new THREE.CylinderGeometry(0.24, 0.3, 0.22, 24),
    new THREE.MeshStandardMaterial({
      color,
      emissive: color,
      emissiveIntensity: 0.45,
      roughness: 0.55,
    }),
  );
  lamp.position.set(x, y, z);
  lamp.castShadow = true;
  root.add(lamp);
}

function addFoodModel(name, position, scale = 0.16, rotation = 0) {
  const holder = new THREE.Group();
  holder.position.copy(position);
  holder.rotation.y = rotation;
  holder.scale.setScalar(scale);
  root.add(holder);

  const path = `/office/assets/kenney-food/${name}.glb`;
  const addScene = (asset) => {
    const model = asset.clone(true);
    model.traverse((child) => {
      if (!child.isMesh) return;
      child.castShadow = true;
      child.receiveShadow = true;
    });
    holder.add(model);
    loadedAssetNames.add(name);
  };

  if (gltfCache.has(path)) {
    addScene(gltfCache.get(path));
    return holder;
  }

  gltfLoader.load(
    path,
    (gltf) => {
      gltfCache.set(path, gltf.scene);
      addScene(gltf.scene);
    },
    undefined,
    () => {
      addBox(root, 0.16, 0.1, 0.16, "#f59e0b", position.clone(), { roughness: 0.7 });
    },
  );
  return holder;
}

function material(color, options = {}) {
  return new THREE.MeshStandardMaterial({
    color,
    roughness: options.roughness ?? 0.72,
    metalness: options.metalness ?? 0.02,
    emissive: options.emissive || "#000000",
    emissiveIntensity: options.emissiveIntensity ?? 0,
  });
}

function lerpAngle(from, to, amount) {
  const fullTurn = Math.PI * 2;
  const delta = ((((to - from) % fullTurn) + Math.PI * 3) % fullTurn) - Math.PI;
  return from + delta * amount;
}

function addBox(parent, width, height, depth, color, position, options) {
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(width, height, depth),
    material(color, options),
  );
  mesh.position.set(position.x, position.y, position.z);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}

function addPivotedLimb(parent, pivotPosition, size, color, options) {
  const pivot = new THREE.Group();
  pivot.position.set(pivotPosition.x, pivotPosition.y, pivotPosition.z);
  parent.add(pivot);

  const mesh = addBox(
    pivot,
    size.x,
    size.y,
    size.z,
    color,
    new THREE.Vector3(0, -size.y / 2, 0),
    options,
  );
  return { pivot, mesh };
}

function createAgentRig(agent, index) {
  const style = agentStyles[index % agentStyles.length];
  const isRobot = agent.kind === "robot";
  const rigRoot = new THREE.Group();
  rigRoot.name = `${agent.name}Rig`;
  rigRoot.scale.setScalar(isRobot ? 1.02 : 0.98);

  const torso = new THREE.Group();
  torso.position.y = 0.94;
  rigRoot.add(torso);

  const bodyColor = isRobot ? "#737b91" : agent.color;
  const body = addBox(torso, 0.64, 0.76, 0.4, bodyColor, new THREE.Vector3(0, 0, 0), {
    roughness: isRobot ? 0.45 : 0.68,
    metalness: isRobot ? 0.28 : 0.02,
  });

  if (isRobot) {
    addBox(torso, 0.7, 0.1, 0.43, "#ef3f5a", new THREE.Vector3(0, 0.25, 0.03), {
      emissive: "#4d0d16",
      emissiveIntensity: 0.25,
    });
    addBox(torso, 0.52, 0.08, 0.44, "#ef3f5a", new THREE.Vector3(0, -0.08, 0.04), {
      emissive: "#4d0d16",
      emissiveIntensity: 0.2,
    });
  } else {
    addBox(torso, 0.42, 0.12, 0.42, "#ffffff", new THREE.Vector3(0, 0.28, 0.015), {
      roughness: 0.82,
    });
  }

  const head = new THREE.Group();
  head.position.y = 1.5;
  rigRoot.add(head);

  const headColor = isRobot ? "#aeb7c6" : style.skin;
  addBox(head, 0.56, 0.52, 0.5, headColor, new THREE.Vector3(0, 0, 0), {
    roughness: isRobot ? 0.5 : 0.75,
    metalness: isRobot ? 0.18 : 0.02,
  });

  if (isRobot) {
    addBox(head, 0.38, 0.08, 0.53, "#ef3f5a", new THREE.Vector3(0, 0.28, 0), {
      emissive: "#4d0d16",
      emissiveIntensity: 0.3,
    });
  } else {
    addBox(head, 0.58, 0.16, 0.54, style.hair, new THREE.Vector3(0, 0.28, -0.02), {
      roughness: 0.78,
    });
    addBox(head, 0.2, 0.18, 0.16, style.hair, new THREE.Vector3(-0.19, 0.15, 0.22), {
      roughness: 0.78,
    });
  }

  const faceZ = 0.262;
  const eyeColor = isRobot ? "#f7fbff" : style.face;
  const leftEye = addBox(head, 0.055, 0.08, 0.02, eyeColor, new THREE.Vector3(-0.12, 0.05, faceZ), {
    emissive: isRobot ? "#e9f8ff" : "#000000",
    emissiveIntensity: isRobot ? 0.45 : 0,
  });
  const rightEye = addBox(head, 0.055, 0.08, 0.02, eyeColor, new THREE.Vector3(0.12, 0.05, faceZ), {
    emissive: isRobot ? "#e9f8ff" : "#000000",
    emissiveIntensity: isRobot ? 0.45 : 0,
  });
  const mouth = addBox(head, 0.17, 0.03, 0.022, style.mouth, new THREE.Vector3(0, -0.12, faceZ + 0.004), {
    emissive: isRobot ? "#6f111b" : "#000000",
    emissiveIntensity: isRobot ? 0.25 : 0,
  });

  const armColor = isRobot ? "#8c96aa" : style.skin;
  const leftArm = addPivotedLimb(
    rigRoot,
    new THREE.Vector3(-0.43, 1.2, 0),
    new THREE.Vector3(0.18, 0.68, 0.22),
    armColor,
    { roughness: isRobot ? 0.48 : 0.75, metalness: isRobot ? 0.18 : 0.02 },
  );
  const rightArm = addPivotedLimb(
    rigRoot,
    new THREE.Vector3(0.43, 1.2, 0),
    new THREE.Vector3(0.18, 0.68, 0.22),
    armColor,
    { roughness: isRobot ? 0.48 : 0.75, metalness: isRobot ? 0.18 : 0.02 },
  );

  if (!isRobot) {
    addBox(leftArm.pivot, 0.2, 0.24, 0.24, agent.color, new THREE.Vector3(0, -0.1, 0), {
      roughness: 0.68,
    });
    addBox(rightArm.pivot, 0.2, 0.24, 0.24, agent.color, new THREE.Vector3(0, -0.1, 0), {
      roughness: 0.68,
    });
  }

  const legColor = isRobot ? "#666f84" : style.pants;
  const leftLeg = addPivotedLimb(
    rigRoot,
    new THREE.Vector3(-0.18, 0.58, 0),
    new THREE.Vector3(0.22, 0.68, 0.25),
    legColor,
    { roughness: isRobot ? 0.5 : 0.72, metalness: isRobot ? 0.12 : 0.02 },
  );
  const rightLeg = addPivotedLimb(
    rigRoot,
    new THREE.Vector3(0.18, 0.58, 0),
    new THREE.Vector3(0.22, 0.68, 0.25),
    legColor,
    { roughness: isRobot ? 0.5 : 0.72, metalness: isRobot ? 0.12 : 0.02 },
  );

  addBox(leftLeg.pivot, 0.27, 0.12, 0.34, style.shoes, new THREE.Vector3(0, -0.72, 0.06), {
    roughness: 0.72,
  });
  addBox(rightLeg.pivot, 0.27, 0.12, 0.34, style.shoes, new THREE.Vector3(0, -0.72, 0.06), {
    roughness: 0.72,
  });

  return {
    root: rigRoot,
    torso,
    body,
    head,
    leftArm: leftArm.pivot,
    rightArm: rightArm.pivot,
    leftLeg: leftLeg.pivot,
    rightLeg: rightLeg.pivot,
    leftEye,
    rightEye,
    mouth,
  };
}

function createAgentModel(agent) {
  const holder = new THREE.Group();
  const index = agents.indexOf(agent);
  holder.userData.agentIndex = index;
  holder.position.copy(slots[agent.slot]);
  holder.userData.target = slots[agent.slot].clone();
  holder.userData.faceTarget = workStations[agent.slot]?.desk?.clone() || null;
  scene.add(holder);
  agent.group = holder;
  agent.room = "open";
  agent.activity = agent.state === "working" ? "typing" : "focused";

  const hit = new THREE.Mesh(
    new THREE.CylinderGeometry(0.72, 0.72, 2.15, 16),
    new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }),
  );
  hit.position.y = 1;
  hit.userData.agentIndex = index;
  holder.add(hit);
  clickTargets.push(hit);

  const selectionAura = new THREE.Mesh(
    new THREE.CircleGeometry(0.92, 32),
    new THREE.MeshBasicMaterial({
      color: agent.color,
      transparent: true,
      opacity: 0,
      depthWrite: false,
      side: THREE.DoubleSide,
    }),
  );
  selectionAura.rotation.x = -Math.PI / 2;
  selectionAura.position.y = 0.025;
  selectionAura.renderOrder = 3;
  holder.add(selectionAura);

  const selectionRing = new THREE.Mesh(
    new THREE.RingGeometry(0.64, 0.82, 36),
    new THREE.MeshBasicMaterial({
      color: agent.color,
      transparent: true,
      opacity: 0,
      depthWrite: false,
      side: THREE.DoubleSide,
    }),
  );
  selectionRing.rotation.x = -Math.PI / 2;
  selectionRing.position.y = 0.045;
  selectionRing.renderOrder = 4;
  holder.add(selectionRing);

  const rig = createAgentRig(agent, index);
  holder.add(rig.root);
  holder.userData.rig = rig;
  holder.userData.rigScale = rig.root.scale.x;
  holder.userData.selectionAura = selectionAura;
  holder.userData.selectionRing = selectionRing;
}

function clearAgentModels() {
  agents.forEach((agent) => {
    if (agent.group) {
      scene.remove(agent.group);
      agent.group = null;
    }
  });
  clickTargets.length = 0;
  hoveredAgentIndex = -1;
  cameraTransition = null;
}

function clearSpeechBubbles() {
  bubbles.forEach((element) => element.remove());
  bubbles.clear();
  bubblePresentation.clear();
}

function applyOfficeTeam(rawTeam) {
  const team = normalizeTeamPayload(rawTeam);
  if (!team) return;
  const restoredChatId = selectedChatId;

  window.clearTimeout(teamWorkTimer);
  teamWorkActive = false;

  clearAgentModels();
  clearSpeechBubbles();
  setOfficeLayout(team.id);
  agents = team.agents;
  assignOfficeSeats(team.id);
  if (officeConversationTeamId === "default-team") {
    officeConversationTeamId = team.id;
  }
  officeConversationTeamName = team.name;
  selectedChatId = validChatId(restoredChatId) ? restoredChatId : "all";
  selectedIndex = selectedChatId === "all" ? 0 : Math.max(0, agents.findIndex((agent) => agentChatId(agent) === selectedChatId));
  focusName.textContent = selectedChatId === "all" ? "Team" : agents[selectedIndex]?.name || "Team";

  teamProfile.name = team.name;
  teamProfile.role = `${agents.length} agents`;
  teamProfile.color = agents[0]?.color || "#1f2933";
  teamProfile.bubble = "Ready";
  teamStatus.textContent = `${agents.length} agents online`;
  if (officeTitle) {
    officeTitle.textContent = activeOfficeLayout === "team-house" ? `${team.name} House` : "Teamora AI Office";
    document.title = officeTitle.textContent;
  }

  if (renderer) {
    agents.forEach(createAgentModel);
    initializeAgentDestinations();
  }

  saveChatState();
  renderRoster();
  renderChatTargets();
  renderChatMessages();
  addActivity(
    agents[0],
    "team loaded",
    `${team.name} is now in the ${activeOfficeLayout === "team-house" ? "Team House" : "3D office"}.`,
  );

  if (window.agentOfficeDebug) {
    window.agentOfficeDebug.agents = agents;
  }
}

function colorForState(state) {
  if (state === "working") return "working";
  if (state === "happy") return "happy";
  if (state === "focused") return "focused";
  return "";
}

function renderRoster() {
  rosterList.innerHTML = "";
  const visible = agents.filter((agent) => agent.active).length;
  activeCount.textContent = `${visible} / ${agents.length}`;
  teamStatus.textContent = `${visible} agents online`;

  rosterList.appendChild(createRosterRow(teamProfile, {
    active: selectedChatId === "all",
    onClick: selectTeam,
    team: true,
  }));

  agents.forEach((agent, index) => {
    const row = createRosterRow(agent, {
      active: selectedChatId === agentChatId(agent),
      onClick: () => selectAgent(index),
    });
    if (!agent.active) row.style.opacity = "0.45";
    rosterList.appendChild(row);
  });
}

function createRosterRow(item, { active = false, onClick, team = false } = {}) {
  const row = document.createElement("button");
  row.className = `agent-row ${team ? "team-row" : ""} ${active ? "active" : ""}`;
  row.type = "button";
  row.disabled = !item.active;
  row.addEventListener("click", onClick);

  const token = document.createElement("span");
  token.className = `agent-token ${team ? "team-token" : ""}`;
  token.style.setProperty("--agent-color", item.color);
  if (team) {
    agents.slice(0, 4).forEach((agent) => {
      const image = document.createElement("img");
      image.src = agent.avatar;
      image.alt = "";
      token.appendChild(image);
    });
  } else {
    const image = document.createElement("img");
    image.src = item.avatar;
    image.alt = "";
    token.appendChild(image);
  }

  const meta = document.createElement("span");
  meta.className = "agent-meta";
  const name = document.createElement("span");
  name.className = "agent-name";
  name.textContent = item.name;
  const role = document.createElement("span");
  role.className = "agent-role";
  role.textContent = item.role;
  meta.append(name, role);

  const status = document.createElement("span");
  status.className = `status-dot ${colorForState(item.state)}`;
  row.append(token, meta, status);
  return row;
}

function agentChatId(agent) {
  return agent.id;
}

function agentByChatId(chatId) {
  if (chatId === "all") return null;
  return agents.find((agent) => agentChatId(agent) === chatId) || null;
}

function agentByAuthor(author) {
  const mappedId = legacyAuthorToAgentId[author];
  return mappedId ? agentByChatId(mappedId) : agents.find((item) => item.name === author);
}

function chatColor(chatId, author) {
  if (chatId === "user") return "#4f5bd5";
  if (chatId === "all" && author === "Team") return teamProfile.color;
  const agent = agentByChatId(chatId) || agentByAuthor(author);
  return agent?.color || "#4f5bd5";
}

function chatInitial(author) {
  return author === "You" ? "You" : author.slice(0, 1);
}

function chatAvatar(chatId, author) {
  if (chatId === "user") return "";
  if (chatId === "all" && author === "Team") return "";
  const agent = agentByChatId(chatId) || agentByAuthor(author);
  return agent?.avatar || "";
}

function currentChatTime() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function validChatId(chatId) {
  return chatId === "all" || agents.some((agent) => agentChatId(agent) === chatId);
}

function createEmptyChatThreads() {
  return new Map([["all", []]]);
}

function safeStorageGet(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeStorageSet(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage can be unavailable in strict/private browser modes.
  }
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), Math.max(min, max));
}

function maxChatPanelWidth() {
  if (!workspace) return CHAT_WIDTH_MAX;
  const available = workspace.getBoundingClientRect().width - MAIN_WIDTH_MIN - 8;
  return Math.max(CHAT_WIDTH_MIN, Math.min(CHAT_WIDTH_MAX, available));
}

function setChatPanelWidth(value, { persist = false } = {}) {
  if (!workspace) return;
  const width = Math.round(clamp(value, CHAT_WIDTH_MIN, maxChatPanelWidth()));
  workspace.style.setProperty("--chat-panel-width", `${width}px`);
  if (persist) {
    safeStorageSet(CHAT_WIDTH_STORAGE_KEY, String(width));
  }
  resize();
}

function loadChatPanelWidth() {
  const saved = Number.parseInt(safeStorageGet(CHAT_WIDTH_STORAGE_KEY) || "", 10);
  if (Number.isFinite(saved)) {
    setChatPanelWidth(saved);
  }
}

function setupChatResize() {
  if (!workspace || !chatResizeHandle) return;
  loadChatPanelWidth();

  chatResizeHandle.addEventListener("pointerdown", (event) => {
    if (window.matchMedia("(max-width: 1040px)").matches) return;
    event.preventDefault();
    chatResizeHandle.setPointerCapture?.(event.pointerId);
    chatResizeHandle.classList.add("dragging");
    document.body.classList.add("resizing-chat");

    const move = (moveEvent) => {
      const rect = workspace.getBoundingClientRect();
      setChatPanelWidth(rect.right - moveEvent.clientX, { persist: true });
    };
    const stop = () => {
      chatResizeHandle.classList.remove("dragging");
      document.body.classList.remove("resizing-chat");
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };

    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop, { once: true });
  });

  chatResizeHandle.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const current = Number.parseInt(
      getComputedStyle(workspace).getPropertyValue("--chat-panel-width"),
      10,
    );
    const delta = event.key === "ArrowLeft" ? 24 : -24;
    setChatPanelWidth((Number.isFinite(current) ? current : CHAT_WIDTH_MIN) + delta, {
      persist: true,
    });
  });
}

function randomStorageId() {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function getGuestAccountKey() {
  const key = "rebly-office-guest-account";
  const existing = safeStorageGet(key);
  if (existing) return existing;
  const next = `guest-${randomStorageId()}`;
  safeStorageSet(key, next);
  return next;
}

function getOrCreateChatSessionId(nextAccountKey, nextConversationId = officeConversationId) {
  const key = `rebly-office-session:${nextAccountKey}:${nextConversationId}`;
  const existing = safeStorageGet(key);
  if (existing) return existing;
  const next = `office-${nextAccountKey}-${nextConversationId}-${randomStorageId()}`;
  safeStorageSet(key, next);
  return next;
}

function chatStorageKey(nextAccountKey = accountKey, nextConversationId = officeConversationId) {
  return `rebly-office-chat-v${CHAT_STORAGE_VERSION}:${nextAccountKey}:${nextConversationId}`;
}

function serializeChatThreads() {
  return Object.fromEntries(
    [...chatThreads.entries()].map(([chatId, thread]) => [
      chatId,
      thread
        .filter((message) => message?.text && message.text !== "Thinking...")
        .slice(-120)
        .map(({ images, animate, ...message }) => ({
          ...message,
          pendingPublish: message.pendingPublish
            ? { ...message.pendingPublish, mediaDataUrl: "" }
            : message.pendingPublish,
          // Gmail and Sheets results can contain private workspace data. Keep a
          // completed card visible for this session, but never write its result
          // into local storage.
          pendingGoogleAction: message.pendingGoogleAction
            ? { ...message.pendingGoogleAction, result: null }
            : message.pendingGoogleAction,
        })),
    ]),
  );
}

function hydrateChatThreads(value) {
  const next = createEmptyChatThreads();
  if (!value || typeof value !== "object") return next;
  Object.entries(value).forEach(([chatId, thread]) => {
    if (!validChatId(chatId) || !Array.isArray(thread)) return;
    next.set(
      chatId,
      thread
        .filter((message) => message && typeof message.text === "string")
        .map((message) => ({
          author: displayAuthor(String(message.author || "Agent")),
          type: message.type === "user" ? "user" : "agent",
          from: String(message.from || ""),
          text: String(message.text || ""),
          time: String(message.time || ""),
          savedAt: String(message.savedAt || ""),
          phase: String(message.phase || ""),
          audience: String(message.audience || ""),
          to: String(message.to || ""),
          isFinal: Boolean(message.isFinal),
          runId: String(message.runId || ""),
          taskId: String(message.taskId || ""),
          agentStatus: message.agentStatus || null,
          animate: false,
          pendingPublish: normalizePendingPublish(message.pendingPublish),
          pendingGoogleAction: normalizePendingGoogleAction(message.pendingGoogleAction),
        })),
    );
  });
  return next;
}

function explicitPublishPlatformHints(value) {
  const text = String(value || "").toLowerCase();
  const platforms = [];
  if (/(?:youtube|youtu\.be|youtube\.com|you\s+tube|yuotube|yotube|\u044e\u0442\u0443\u0431|\u044e\u0442\u044c\u044e\u0431)/i.test(text)) {
    platforms.push("youtube");
  }
  if (/(?:telegram|(?:^|\W)tg(?:$|\W)|\u0442\u0435\u043b\u0435\u0433\u0440\u0430\u043c|(?:^|\W)\u0442\u0433(?:$|\W))/i.test(text)) {
    platforms.push("telegram");
  }
  if (/(?:instagram|insta|\u0438\u043d\u0441\u0442\u0430\u0433\u0440\u0430\u043c)/i.test(text)) {
    platforms.push("instagram");
  }
  return [...new Set(platforms)];
}

function reconcilePendingPublishWithContext(pending, contextText = "") {
  if (!pending) return pending;
  const contextPlatforms = explicitPublishPlatformHints(contextText);
  const wasTelegramAutoRoute = pending.platforms.length === 1
    && pending.platforms[0] === "telegram"
    && (pending.autoPublish || pending.status === "auto_publish_pending" || pending.status === "error");
  const contextIsYoutubeOnly = contextPlatforms.includes("youtube") && !contextPlatforms.includes("telegram");
  if (!wasTelegramAutoRoute || !contextIsYoutubeOnly) return pending;
  return {
    ...pending,
    platform: "youtube",
    platforms: ["youtube"],
    status: "approval_required",
    autoPublish: false,
    mediaDataUrl: "",
    error: "",
    notice: pending.notice || (
      "YouTube API cannot publish text-only Community posts automatically. "
      + "Add a public HTTPS video URL, or copy this text into YouTube Studio manually."
    ),
  };
}

function normalizePendingPublish(value, contextText = "") {
  if (!value || typeof value !== "object" || typeof value.text !== "string") return null;
  const platforms = normalizePublishPlatforms(value.platforms || value.platform);
  const isYoutube = platforms.includes("youtube");
  const pending = {
    platform: platforms[0] || "telegram",
    platforms,
    status: isYoutube && value.status === "auto_publish_pending" ? "approval_required" : String(value.status || "approval_required"),
    text: String(value.text || ""),
    mediaUrl: String(value.mediaUrl || value.media_url || ""),
    mediaDataUrl: isYoutube ? "" : String(value.mediaDataUrl || value.media_data_url || ""),
    mediaType: String(value.mediaType || value.media_type || ""),
    mediaName: String(value.mediaName || value.media_name || ""),
    youtubeTitle: String(value.youtubeTitle || value.youtube_title || defaultYoutubeTitle(value.text)).slice(0, 100),
    youtubeDescription: String(value.youtubeDescription || value.youtube_description || value.text || "").slice(0, 5000),
    privacyStatus: normalizeYoutubePrivacyStatus(value.privacyStatus || value.privacy_status),
    resultUrl: safeExternalHttpsUrl(value.resultUrl || value.result_url || value.publishedUrl || value.published_url),
    runId: String(value.runId || ""),
    taskId: value.taskId || value.task_id || null,
    source: String(value.source || "team"),
    autoPublish: isYoutube ? false : Boolean(value.autoPublish),
    separateActionRequired: Boolean(value.separateActionRequired || value.separate_action_required),
    separatePlatforms: [...new Set(
      (Array.isArray(value.separatePlatforms || value.separate_platforms)
        ? (value.separatePlatforms || value.separate_platforms)
        : [])
        .map((platform) => String(platform || "").toLowerCase())
        .filter((platform) => platform === "telegram" || platform === "instagram"),
    )],
    notice: String(value.notice || "").slice(0, 500),
    error: String(value.error || ""),
  };
  return reconcilePendingPublishWithContext(pending, contextText);
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function limitedGoogleActionText(value, maxLength = 20_000) {
  return typeof value === "string" ? value.slice(0, maxLength) : "";
}

function normalizePendingGoogleAction(value) {
  if (!isPlainObject(value)) return null;
  const tool = String(value.tool || "");
  if (!GOOGLE_ACTION_LABELS[tool]) return null;

  const rawArguments = isPlainObject(value.arguments) ? value.arguments : {};
  const rawRecipients = rawArguments.to ?? rawArguments.recipients ?? "";
  const recipients = Array.isArray(rawRecipients)
    ? rawRecipients.filter((item) => typeof item === "string").join(", ")
    : limitedGoogleActionText(rawRecipients, 5_000);
  const rawResult = isPlainObject(value.result) || Array.isArray(value.result) ? value.result : null;
  const argumentsByTool = {
    search_gmail: {
      query: limitedGoogleActionText(rawArguments.query ?? rawArguments.q, 1_000),
    },
    create_gmail_draft: {
      to: recipients,
      subject: limitedGoogleActionText(rawArguments.subject, 255),
      body: limitedGoogleActionText(rawArguments.body ?? rawArguments.text),
    },
    send_gmail: {
      to: recipients,
      subject: limitedGoogleActionText(rawArguments.subject, 255),
      body: limitedGoogleActionText(rawArguments.body ?? rawArguments.text),
    },
    list_calendar_events: {
      timeMin: limitedGoogleActionText(rawArguments.timeMin ?? rawArguments.time_min ?? rawArguments.start, 64),
      timeMax: limitedGoogleActionText(rawArguments.timeMax ?? rawArguments.time_max ?? rawArguments.end, 64),
    },
    create_calendar_event: {
      summary: limitedGoogleActionText(rawArguments.summary ?? rawArguments.title, 1_024),
      start: limitedGoogleActionText(rawArguments.start ?? rawArguments.startAt ?? rawArguments.start_at, 64),
      end: limitedGoogleActionText(rawArguments.end ?? rawArguments.endAt ?? rawArguments.end_at, 64),
    },
    read_google_sheet: {
      spreadsheetId: limitedGoogleActionText(rawArguments.spreadsheetId ?? rawArguments.spreadsheet_id, 200),
      range: limitedGoogleActionText(rawArguments.range ?? rawArguments.sheetRange ?? rawArguments.sheet_range, 500),
    },
    append_google_sheet_row: {
      spreadsheetId: limitedGoogleActionText(rawArguments.spreadsheetId ?? rawArguments.spreadsheet_id, 200),
      range: limitedGoogleActionText(rawArguments.range ?? rawArguments.sheetRange ?? rawArguments.sheet_range, 500),
      valuesText: limitedGoogleActionText(rawArguments.valuesText),
    },
  };

  return {
    tool,
    arguments: argumentsByTool[tool],
    requiresApproval: GOOGLE_WRITE_ACTION_TOOLS.has(tool),
    status: ["ready", "approval_required", "running", "completed", "error"].includes(String(value.status))
      ? String(value.status)
      : (GOOGLE_WRITE_ACTION_TOOLS.has(tool) ? "approval_required" : "ready"),
    title: limitedGoogleActionText(value.title, 160) || GOOGLE_ACTION_LABELS[tool],
    detail: limitedGoogleActionText(value.detail, 500),
    runId: limitedGoogleActionText(value.runId ?? value.run_id, 80),
    source: limitedGoogleActionText(value.source, 80) || "office",
    agent: limitedGoogleActionText(value.agent, 80) || "mika",
    result: rawResult,
    error: limitedGoogleActionText(value.error, 500),
  };
}

function normalizePublishPlatforms(value) {
  const raw = Array.isArray(value) ? value : [value];
  const platforms = raw
    .map((item) => String(item || "").toLowerCase())
    .filter((item) => item === "telegram" || item === "instagram" || item === "youtube");
  const unique = [...new Set(platforms)];
  return unique.includes("youtube") ? ["youtube"] : (unique.length ? unique : ["telegram"]);
}

function defaultYoutubeTitle(text) {
  const firstLine = String(text || "").split(/\r?\n/).find((line) => line.trim()) || "";
  const title = firstLine.replace(/https?:\/\/[^\s]+/gi, "").replace(/\s+/g, " ").trim();
  return (title || "New video").slice(0, 100);
}

function normalizeYoutubePrivacyStatus(value) {
  const privacy = String(value || "private").toLowerCase();
  return ["private", "unlisted", "public"].includes(privacy) ? privacy : "private";
}

function safeExternalHttpsUrl(value) {
  try {
    const url = new URL(String(value || "").trim());
    if (url.protocol !== "https:" || !url.hostname || url.username || url.password) return "";
    return url.href;
  } catch {
    return "";
  }
}

function publicYoutubeVideoUrl(value) {
  const url = safeExternalHttpsUrl(value);
  if (!url) return "";
  const hostname = new URL(url).hostname.toLowerCase();
  if (hostname === "localhost" || hostname.endsWith(".local") || hostname === "127.0.0.1" || hostname === "::1") return "";
  return url;
}

function extractPublishMediaFromText(text) {
  const urls = String(text || "").match(/https?:\/\/[^\s<>"')]+/gi) || [];
  const mediaUrl = urls.find((url) => /\.(avif|gif|jpe?g|png|webp|m4v|mov|mp4|mpeg|mpg|webm)(?:[?#].*)?$/i.test(url));
  if (!mediaUrl) return null;
  const isVideo = /\.(m4v|mov|mp4|mpeg|mpg|webm)(?:[?#].*)?$/i.test(mediaUrl);
  return {
    mediaUrl,
    mediaType: isVideo ? "video/mp4" : "image/jpeg",
    mediaName: mediaUrl.split("/").pop()?.split(/[?#]/)[0] || (isVideo ? "video.mp4" : "image.jpg"),
  };
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result || "")));
    reader.addEventListener("error", () => reject(reader.error || new Error("Could not read media file")));
    reader.readAsDataURL(file);
  });
}

function allPersistedMessages() {
  return [...chatThreads.values()]
    .flat()
    .filter((message) => message?.text && message.text !== "Thinking...")
    .sort((a, b) => {
      const aTime = Date.parse(a.savedAt || "");
      const bTime = Date.parse(b.savedAt || "");
      if (Number.isNaN(aTime) || Number.isNaN(bTime)) return 0;
      return aTime - bTime;
    });
}

function notifyConversationUpdated() {
  if (!isDashboardEmbed || window.parent === window) return;
  const messages = allPersistedMessages();
  const lastMessage = messages[messages.length - 1];
  window.parent.postMessage(
    {
      type: "rebly-office-conversation-updated",
      conversation: {
        id: officeConversationId,
        teamId: officeConversationTeamId,
        teamName: officeConversationTeamName,
        source: officeConversationSource,
        lastMessage: lastMessage?.text || "",
        updatedAt: new Date().toISOString(),
        unreadCount: 0,
        messageCount: messages.length,
      },
    },
    window.location.origin,
  );
}

function applyOfficeConversation(rawConversation) {
  const conversation = rawConversation && typeof rawConversation === "object" ? rawConversation : {};
  const nextId = String(conversation.id || "default");
  const changed = nextId !== officeConversationId;
  officeConversationId = nextId;
  officeConversationTeamId = String(conversation.teamId || officeConversationTeamId || "default-team");
  officeConversationTeamName = String(conversation.teamName || officeConversationTeamName || "Teamora AI Office");
  officeConversationSource = conversation.source === "mine" ? "mine" : "ready";
  if (changed) {
    loadChatState(accountKey);
  } else {
    chatSessionId = getOrCreateChatSessionId(accountKey, officeConversationId);
  }
}

function saveChatState() {
  if (!storageReady) return;
  safeStorageSet(
    chatStorageKey(),
    JSON.stringify({
      selectedChatId,
      threads: serializeChatThreads(),
    }),
  );
  notifyConversationUpdated();
}

function loadChatState(nextAccountKey) {
  accountKey = nextAccountKey;
  chatSessionId = getOrCreateChatSessionId(accountKey, officeConversationId);
  storageReady = false;

  const raw = safeStorageGet(chatStorageKey(accountKey));
  let parsed = null;
  try {
    parsed = raw ? JSON.parse(raw) : null;
  } catch {
    parsed = null;
  }

  chatThreads = hydrateChatThreads(parsed?.threads);
  selectedChatId = validChatId(parsed?.selectedChatId) ? parsed.selectedChatId : "all";
  storageReady = true;
}

async function resolveAccountContext() {
  try {
    const response = await fetch(`${AUTH_API}/api/auth/me`, { credentials: "include" });
    if (!response.ok) return;
    const payload = await response.json();
    const userId = payload?.user?.id;
    if (!userId) return;
    const nextAccountKey = `user-${userId}`;
    if (nextAccountKey === accountKey) return;
    loadChatState(nextAccountKey);
    renderChatTargets();
    renderChatMessages();
  } catch {
    // Keep guest-local persistence if the auth backend is not reachable.
  }
}

function selectedThread() {
  if (!chatThreads.has(selectedChatId)) {
    chatThreads.set(selectedChatId, []);
  }
  return chatThreads.get(selectedChatId);
}

function renderChatTargets() {
  if (!chatTarget) return;
  chatTarget.innerHTML = "";
  const targets = [
    { id: "all", label: "Team" },
    ...agents.map((agent) => ({ id: agentChatId(agent), label: agent.name })),
  ];
  targets.forEach((target) => {
    const option = document.createElement("option");
    option.value = target.id;
    option.textContent = target.label;
    chatTarget.appendChild(option);
  });
  chatTarget.value = selectedChatId;
}

function createMessageImageGrid(images = []) {
  const validImages = images.filter((image) => image?.url);
  if (!validImages.length) return null;

  const media = document.createElement("div");
  media.className = `chat-message-media ${validImages.length === 1 ? "single" : "many"}`;
  media.dataset.count = String(Math.min(validImages.length, 6));

  validImages.forEach((image) => {
    const frame = document.createElement("span");
    frame.className = "chat-message-image-frame";

    const img = document.createElement("img");
    img.src = image.url;
    img.alt = image.name || "Attached image";
    img.loading = "lazy";

    frame.appendChild(img);
    media.appendChild(frame);
  });

  return media;
}

function renderChatMessages() {
  const thread = selectedThread();
  chatMessages.innerHTML = "";

  if (thread.length === 0) {
    const empty = document.createElement("div");
    empty.className = "chat-bubble";
    empty.textContent =
      selectedChatId === "all"
        ? "Team is ready. Send a task and Atlas will route it."
        : `${agentByChatId(selectedChatId)?.name || "Agent"} is ready.`;
    chatMessages.appendChild(empty);
    scrollChatToBottom();
    return;
  }

  thread.forEach((message) => {
    const row = document.createElement("article");
    row.className = `chat-message ${message.type === "user" ? "user" : "agent"} ${
      message.animate ? "message-enter" : ""
    } ${message.phase ? `phase-${message.phase}` : ""}`;

    const avatar = document.createElement("span");
    avatar.className = "chat-avatar";
    const avatarImage = chatAvatar(message.type === "user" ? "user" : message.from, message.author);
    if (avatarImage) {
      avatar.style.setProperty("--agent-color", chatColor(message.from, message.author));
      const image = document.createElement("img");
      image.src = avatarImage;
      image.alt = "";
      avatar.appendChild(image);
    } else {
      avatar.style.background = chatColor(message.type === "user" ? "user" : message.from, message.author);
      avatar.textContent = chatInitial(message.author);
    }

    const body = document.createElement("div");
    body.className = "chat-message-body";

    const head = document.createElement("div");
    head.className = "chat-message-head";
    const author = document.createElement("strong");
    author.textContent = message.author;
    const time = document.createElement("time");
    time.textContent = message.time || currentChatTime();
    head.append(author, time);

    const bubble = document.createElement("p");
    bubble.className = "chat-bubble";
    bubble.textContent = message.text;

    body.append(head);
    const media = createMessageImageGrid(message.images);
    if (media) {
      body.append(media);
    }
    if (message.text) {
      body.append(bubble);
    }
    if (message.pendingPublish) {
      body.append(createPublishCard(selectedChatId, message));
    }
    if (message.pendingGoogleAction) {
      body.append(createGoogleActionCard(selectedChatId, message));
    }
    row.append(avatar, body);
    chatMessages.appendChild(row);
    if (message.animate) {
      window.requestAnimationFrame(() => {
        message.animate = false;
      });
    }
  });

  scrollChatToBottom();
}

function scrollChatToBottom() {
  const scroll = () => {
    chatMessages.scrollTop = chatMessages.scrollHeight;
  };
  scroll();
  requestAnimationFrame(() => {
    scroll();
    requestAnimationFrame(scroll);
  });
}

function isImageFile(file) {
  return Boolean(file?.type?.startsWith("image/") || /\.(avif|gif|jpe?g|png|webp)$/i.test(file?.name || ""));
}

function addSelectedChatImages(fileList) {
  const files = Array.from(fileList || []).filter(isImageFile);
  files.forEach((file) => {
    selectedChatImages.push({
      id: randomStorageId(),
      file,
      url: URL.createObjectURL(file),
      name: file.name,
      size: file.size,
      type: file.type,
    });
  });
  renderSelectedChatImages();
}

function removeSelectedChatImage(id) {
  const index = selectedChatImages.findIndex((image) => image.id === id);
  if (index < 0) return;
  URL.revokeObjectURL(selectedChatImages[index].url);
  selectedChatImages.splice(index, 1);
  renderSelectedChatImages();
}

function clearSelectedChatImages({ revoke = true } = {}) {
  if (revoke) {
    selectedChatImages.forEach((image) => URL.revokeObjectURL(image.url));
  }
  selectedChatImages = [];
  if (chatFileInput) {
    chatFileInput.value = "";
  }
  renderSelectedChatImages();
}

function renderSelectedChatImages() {
  if (!chatAttachmentPreview) return;
  chatAttachmentPreview.innerHTML = "";
  chatComposer.classList.toggle("has-attachments", selectedChatImages.length > 0);
  chatAttachmentPreview.hidden = selectedChatImages.length === 0;

  selectedChatImages.forEach((image) => {
    const item = document.createElement("span");
    item.className = "chat-preview-item";

    const thumb = document.createElement("img");
    thumb.src = image.url;
    thumb.alt = image.name || "Selected image";

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "chat-preview-remove";
    remove.setAttribute("aria-label", `Remove ${image.name || "image"}`);
    remove.textContent = "x";
    remove.addEventListener("click", () => removeSelectedChatImage(image.id));

    item.append(thumb, remove);
    chatAttachmentPreview.appendChild(item);
  });

  updateChatSendState();
}

function updateChatSendState() {
  if (!chatSend) return;
  const hasText = Boolean(chatInput?.value.trim());
  chatSend.disabled = chatBusy || (!hasText && selectedChatImages.length === 0);
  chatComposer.classList.toggle("has-active-run", Boolean(activeChatRun));
  if (chatStop) {
    chatStop.hidden = !activeChatRun;
    chatStop.disabled = Boolean(activeChatRun?.cancelRequested);
    chatStop.setAttribute(
      "aria-label",
      activeChatRun?.cancelRequested ? "Stopping current task" : "Stop current task",
    );
  }
}

function createClientRunId() {
  return `run-${randomStorageId()}`.replace(/[^A-Za-z0-9_.-]+/g, "-").slice(0, 80);
}

function cancelUrlsForRun(runId) {
  return AGENT_CHAT_API_CANDIDATES.map((apiUrl) =>
    apiUrl.replace(AGENT_CHAT_API_PATH, `/api/agents/runs/${encodeURIComponent(runId)}/cancel`),
  );
}

async function stopActiveChatRun() {
  const run = activeChatRun;
  if (!run || run.cancelRequested) return;
  run.cancelRequested = true;
  updateChatSendState();

  const cancelRequests = cancelUrlsForRun(run.runId).map((url) =>
    fetch(url, { method: "POST" }).catch(() => null),
  );
  await Promise.race([Promise.allSettled(cancelRequests), sleep(900)]);
  run.controller?.abort();
}

function stoppedAgentReply(runId = "") {
  return {
    author: "System",
    from: "system",
    text: "Task stopped by user.",
    phase: "final",
    audience: "user",
    isFinal: true,
    runId,
  };
}

function createPublishCard(chatId, message) {
  const runId = String(message.pendingPublish?.runId || "");
  const contextText = (chatThreads.get(chatId) || [])
    .filter((entry) => !runId || String(entry.runId || entry.pendingPublish?.runId || "") === runId)
    .map((entry) => entry.text || "")
    .join("\n");
  const pending = reconcilePendingPublishWithContext(message.pendingPublish, contextText);
  message.pendingPublish = pending;
  const card = document.createElement("div");
  card.className = `publish-card ${pending.status}`;

  const title = document.createElement("strong");
  const platforms = normalizePublishPlatforms(pending.platforms || pending.platform);
  const isYoutube = platforms.includes("youtube");
  title.textContent = `Publish to ${platforms.map(platformLabel).join(" + ")}`;
  const preview = document.createElement("p");
  preview.textContent = pending.text;

  card.append(title, preview);

  if (pending.notice) {
    const notice = document.createElement("small");
    notice.className = "publish-notice";
    notice.textContent = pending.notice;
    card.appendChild(notice);
  }

  if (pending.mediaDataUrl || pending.mediaUrl) {
    const mediaChip = document.createElement("div");
    mediaChip.className = "publish-media-chip";
    if (pending.mediaDataUrl && pending.mediaType?.startsWith("image/")) {
      const image = document.createElement("img");
      image.src = pending.mediaDataUrl;
      image.alt = "";
      mediaChip.appendChild(image);
    }
    const mediaText = document.createElement("span");
    mediaText.textContent = pending.mediaUrl || pending.mediaName || "Uploaded media";
    mediaChip.appendChild(mediaText);
    card.appendChild(mediaChip);
  }

  if (isYoutube) {
    appendYoutubeApprovalFields(card, pending);
  } else {
    const mediaField = document.createElement("label");
    mediaField.className = "publish-media-field";
    const mediaLabel = document.createElement("span");
    mediaLabel.textContent = platforms.includes("instagram") ? "Photo/video URL for Instagram" : "Photo/video URL";
    const mediaInput = document.createElement("input");
    mediaInput.type = "url";
    mediaInput.placeholder = "https://.../image.jpg or video.mp4";
    mediaInput.value = pending.mediaUrl || "";
    mediaInput.addEventListener("input", () => {
      pending.mediaUrl = mediaInput.value;
      const inferred = extractPublishMediaFromText(mediaInput.value);
      if (inferred) {
        pending.mediaType = inferred.mediaType;
        pending.mediaName = inferred.mediaName;
      }
      saveChatState();
    });
    mediaField.append(mediaLabel, mediaInput);
    card.appendChild(mediaField);
  }

  const action = document.createElement("button");
  action.type = "button";
  action.textContent = publishButtonText(pending.status, platforms[0]);
  action.disabled = pending.status === "auto_publish_pending" || pending.status === "publishing" || pending.status === "published";
  action.addEventListener("click", () => publishPendingMessage(chatId, message));

  card.appendChild(action);
  const resultUrl = isYoutube ? safeExternalHttpsUrl(pending.resultUrl) : "";
  if (resultUrl) {
    const result = document.createElement("a");
    result.href = resultUrl;
    result.target = "_blank";
    result.rel = "noreferrer noopener";
    result.textContent = "Open published video";
    card.appendChild(result);
  }
  if (pending.error) {
    const error = document.createElement("small");
    error.textContent = pending.error;
    card.appendChild(error);
  }
  return card;
}

function createGoogleActionCard(chatId, message) {
  const pending = message.pendingGoogleAction;
  const card = document.createElement("div");
  card.className = `google-action-card ${pending.status}`;

  const title = document.createElement("strong");
  title.textContent = pending.title || GOOGLE_ACTION_LABELS[pending.tool] || "Google action";
  card.appendChild(title);

  if (pending.detail) {
    const detail = document.createElement("p");
    detail.textContent = pending.detail;
    card.appendChild(detail);
  }

  appendGoogleActionFields(card, pending);

  const action = document.createElement("button");
  action.type = "button";
  action.textContent = googleActionButtonText(pending);
  action.disabled = pending.status === "running" || pending.status === "completed";
  action.addEventListener("click", () => executeGoogleAction(chatId, message));
  card.appendChild(action);

  if (pending.result !== null && pending.result !== undefined) {
    const result = document.createElement("pre");
    result.className = "google-action-result";
    result.textContent = formatGoogleActionResult(pending.result);
    card.appendChild(result);
  }
  if (pending.error) {
    const error = document.createElement("small");
    error.textContent = pending.error;
    card.appendChild(error);
  }
  return card;
}

function appendGoogleActionFields(card, pending) {
  const fields = {
    search_gmail: [
      { key: "query", label: "Gmail search", placeholder: "from:client@example.com newer_than:30d", maxLength: 1_000 },
    ],
    create_gmail_draft: [
      { key: "to", label: "To", placeholder: "person@example.com", maxLength: 5_000, inputMode: "email" },
      { key: "subject", label: "Subject", placeholder: "Project update", maxLength: 255 },
      { key: "body", label: "Message", placeholder: "Write the email message...", maxLength: 20_000, textarea: true },
    ],
    send_gmail: [
      { key: "to", label: "To", placeholder: "person@example.com", maxLength: 5_000, inputMode: "email" },
      { key: "subject", label: "Subject", placeholder: "Project update", maxLength: 255 },
      { key: "body", label: "Message", placeholder: "Write the email message...", maxLength: 20_000, textarea: true },
    ],
    list_calendar_events: [
      { key: "timeMin", label: "From (optional RFC3339)", placeholder: "2026-07-13T09:00:00Z", maxLength: 64 },
      { key: "timeMax", label: "To (optional RFC3339)", placeholder: "2026-07-13T18:00:00Z", maxLength: 64 },
    ],
    create_calendar_event: [
      { key: "summary", label: "Event title", placeholder: "Planning meeting", maxLength: 1_024 },
      { key: "start", label: "Start (RFC3339)", placeholder: "2026-07-13T09:00:00Z", maxLength: 64 },
      { key: "end", label: "End (RFC3339)", placeholder: "2026-07-13T10:00:00Z", maxLength: 64 },
    ],
    read_google_sheet: [
      { key: "spreadsheetId", label: "Spreadsheet ID", placeholder: "From the Google Sheets URL", maxLength: 200 },
      { key: "range", label: "Range", placeholder: "Leads!A1:F50", maxLength: 500 },
    ],
    append_google_sheet_row: [
      { key: "spreadsheetId", label: "Spreadsheet ID", placeholder: "From the Google Sheets URL", maxLength: 200 },
      { key: "range", label: "Range", placeholder: "Leads!A:B", maxLength: 500 },
      { key: "valuesText", label: "Row values", placeholder: "Ada Lovelace, ada@example.com", maxLength: 20_000, textarea: true },
    ],
  };
  (fields[pending.tool] || []).forEach((field) => appendGoogleActionField(card, pending, field));
}

function appendGoogleActionField(card, pending, field) {
  const container = document.createElement("label");
  container.className = "google-action-field";
  const label = document.createElement("span");
  label.textContent = field.label;
  const input = document.createElement(field.textarea ? "textarea" : "input");
  if (!field.textarea) input.type = "text";
  if (field.textarea) input.rows = 3;
  input.placeholder = field.placeholder || "";
  input.maxLength = field.maxLength || 20_000;
  input.value = String(pending.arguments?.[field.key] || "");
  if (field.inputMode) input.inputMode = field.inputMode;
  input.disabled = pending.status === "running" || pending.status === "completed";
  input.addEventListener("input", () => {
    pending.arguments[field.key] = input.value.slice(0, field.maxLength || 20_000);
    pending.error = "";
    if (pending.status === "error") pending.status = pending.requiresApproval ? "approval_required" : "ready";
    saveChatState();
  });
  container.append(label, input);
  card.appendChild(container);
}

function googleActionButtonText(pending) {
  if (pending.status === "running") return "Running...";
  if (pending.status === "completed") return "Completed";
  if (pending.status === "error") return pending.requiresApproval ? "Review and confirm again" : "Retry action";
  if (!pending.requiresApproval) return "Run action";
  return {
    create_gmail_draft: "Confirm and create draft",
    send_gmail: "Confirm and send email",
    create_calendar_event: "Confirm and create event",
    append_google_sheet_row: "Confirm and append row",
  }[pending.tool] || "Confirm action";
}

function requiredGoogleText(value, label) {
  const text = String(value || "").trim();
  if (!text) throw new Error(`${label} is required.`);
  return text;
}

function googleSheetRowValues(value) {
  const text = requiredGoogleText(value, "Row values");
  if (text.startsWith("[")) {
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch {
      throw new Error("Row values must be a comma-separated list or a JSON array.");
    }
    if (!Array.isArray(parsed) || !parsed.length || parsed.some((cell) => Array.isArray(cell) || (typeof cell === "object" && cell !== null))) {
      throw new Error("Row values must be a single non-empty JSON array.");
    }
    return parsed;
  }
  const cells = text.split(",").map((cell) => cell.trim());
  if (!cells.length || cells.some((cell) => !cell)) {
    throw new Error("Enter one or more comma-separated row values.");
  }
  return cells;
}

function buildGoogleActionArguments(pending) {
  const values = pending.arguments || {};
  const common = {
    source: String(pending.source || "office").slice(0, 80),
    runId: String(pending.runId || "").slice(0, 80) || undefined,
    agent: String(pending.agent || "mika").slice(0, 80),
  };
  let toolArguments;

  switch (pending.tool) {
    case "search_gmail":
      toolArguments = { query: requiredGoogleText(values.query, "Gmail search") };
      break;
    case "create_gmail_draft":
    case "send_gmail": {
      const recipients = requiredGoogleText(values.to, "Recipient")
        .split(/[;,]/)
        .map((item) => item.trim())
        .filter(Boolean);
      toolArguments = {
        to: recipients,
        subject: requiredGoogleText(values.subject, "Subject"),
        body: requiredGoogleText(values.body, "Message"),
      };
      break;
    }
    case "list_calendar_events": {
      const timeMin = String(values.timeMin || "").trim();
      const timeMax = String(values.timeMax || "").trim();
      if (Boolean(timeMin) !== Boolean(timeMax)) {
        throw new Error("Enter both calendar times or leave both empty for upcoming events.");
      }
      toolArguments = timeMin && timeMax ? { timeMin, timeMax } : {};
      break;
    }
    case "create_calendar_event":
      toolArguments = {
        summary: requiredGoogleText(values.summary, "Event title"),
        start: requiredGoogleText(values.start, "Start time"),
        end: requiredGoogleText(values.end, "End time"),
      };
      break;
    case "read_google_sheet":
      toolArguments = {
        spreadsheet_id: requiredGoogleText(values.spreadsheetId, "Spreadsheet ID"),
        range: requiredGoogleText(values.range, "Range"),
      };
      break;
    case "append_google_sheet_row":
      toolArguments = {
        spreadsheet_id: requiredGoogleText(values.spreadsheetId, "Spreadsheet ID"),
        range: requiredGoogleText(values.range, "Range"),
        row: googleSheetRowValues(values.valuesText),
      };
      break;
    default:
      throw new Error("This Google action is not supported by the Office client.");
  }

  if (pending.requiresApproval) toolArguments.approved = true;
  return { ...toolArguments, ...common };
}

function formatGoogleActionResult(value) {
  try {
    const text = JSON.stringify(value, null, 2);
    return text.length > 12_000 ? `${text.slice(0, 12_000)}\n…Result truncated in this view.` : text;
  } catch {
    return "Google completed the action.";
  }
}

async function executeGoogleAction(chatId, message) {
  const pending = message.pendingGoogleAction;
  if (!pending || pending.status === "running" || pending.status === "completed") return;
  try {
    const toolArguments = buildGoogleActionArguments(pending);
    if (pending.requiresApproval) {
      const accepted = window.confirm(
        `Confirm ${GOOGLE_ACTION_LABELS[pending.tool] || "Google action"}? This will make a change in your connected Google account.`,
      );
      if (!accepted) return;
    }

    pending.status = "running";
    pending.error = "";
    saveChatState();
    renderChatMessages();

    const response = await fetch(`${AUTH_API}/api/agent-tools/execute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ tool: pending.tool, arguments: toolArguments }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload?.ok === false) {
      throw new Error(safePublishError(payload, response.status));
    }
    pending.result = payload?.result ?? {};
    pending.status = "completed";
    saveChatState();
    renderChatMessages();
  } catch (error) {
    pending.status = "error";
    pending.error = safeClientPublishError(error, "Google action failed");
    saveChatState();
    renderChatMessages();
  }
}

function appendYoutubeApprovalFields(card, pending) {
  const mediaField = document.createElement("label");
  mediaField.className = "publish-media-field";
  const mediaLabel = document.createElement("span");
  mediaLabel.textContent = "Public HTTPS video URL";
  const mediaInput = document.createElement("input");
  mediaInput.type = "url";
  mediaInput.inputMode = "url";
  mediaInput.placeholder = "https://cdn.example.com/video.mp4";
  mediaInput.value = pending.mediaUrl || "";
  mediaInput.addEventListener("input", () => {
    pending.mediaUrl = mediaInput.value.trim();
    pending.mediaType = "video/mp4";
    pending.mediaName = pending.mediaUrl.split("/").pop()?.split(/[?#]/)[0] || "video";
    saveChatState();
  });
  mediaField.append(mediaLabel, mediaInput);

  const titleField = document.createElement("label");
  titleField.className = "publish-media-field";
  const titleLabel = document.createElement("span");
  titleLabel.textContent = "Video title";
  const titleInput = document.createElement("input");
  titleInput.type = "text";
  titleInput.maxLength = 100;
  titleInput.value = pending.youtubeTitle || defaultYoutubeTitle(pending.text);
  titleInput.addEventListener("input", () => {
    pending.youtubeTitle = titleInput.value.slice(0, 100);
    saveChatState();
  });
  titleField.append(titleLabel, titleInput);

  const descriptionField = document.createElement("label");
  descriptionField.className = "publish-media-field";
  const descriptionLabel = document.createElement("span");
  descriptionLabel.textContent = "Video description";
  const descriptionInput = document.createElement("textarea");
  descriptionInput.rows = 4;
  descriptionInput.maxLength = 5000;
  descriptionInput.value = pending.youtubeDescription || pending.text || "";
  descriptionInput.addEventListener("input", () => {
    pending.youtubeDescription = descriptionInput.value.slice(0, 5000);
    saveChatState();
  });
  descriptionField.append(descriptionLabel, descriptionInput);

  const privacyField = document.createElement("label");
  privacyField.className = "publish-media-field";
  const privacyLabel = document.createElement("span");
  privacyLabel.textContent = "Privacy";
  const privacyInput = document.createElement("select");
  ["private", "unlisted", "public"].forEach((privacy) => {
    const option = document.createElement("option");
    option.value = privacy;
    option.textContent = privacy[0].toUpperCase() + privacy.slice(1);
    privacyInput.appendChild(option);
  });
  privacyInput.value = normalizeYoutubePrivacyStatus(pending.privacyStatus);
  privacyInput.addEventListener("change", () => {
    pending.privacyStatus = normalizeYoutubePrivacyStatus(privacyInput.value);
    saveChatState();
  });
  privacyField.append(privacyLabel, privacyInput);
  card.append(mediaField, titleField, descriptionField, privacyField);
}

function platformLabel(platform) {
  if (platform === "instagram") return "Instagram";
  if (platform === "youtube") return "YouTube";
  return "Telegram";
}

function publishButtonText(status, platform = "") {
  if (status === "auto_publish_pending") return "Auto publishing...";
  if (status === "publishing") return "Publishing...";
  if (status === "published") return "Published";
  if (status === "error") return "Retry publish";
  if (platform === "youtube") return "Publish video";
  return "Publish";
}

function appendChatMessage(chatId, message, { save = true } = {}) {
  if (!chatThreads.has(chatId)) {
    chatThreads.set(chatId, []);
  }
  const entry = {
    savedAt: new Date().toISOString(),
    time: currentChatTime(),
    animate: message.type !== "user",
    ...message,
  };
  chatThreads.get(chatId).push(entry);
  if (save) saveChatState();
  if (chatId === selectedChatId) renderChatMessages();
  return entry;
}

function replaceChatMessage(chatId, current, next, { save = true } = {}) {
  const thread = chatThreads.get(chatId) || [];
  const index = thread.indexOf(current);
  if (index >= 0) {
    thread.splice(index, 1, { savedAt: new Date().toISOString(), time: currentChatTime(), animate: true, ...next });
    if (save) saveChatState();
  }
  if (chatId === selectedChatId) renderChatMessages();
}

function normalizeAgentMessages(result, fallbackChatId) {
  const source = Array.isArray(result.messages) && result.messages.length
    ? result.messages
    : [{ author: agentByChatId(fallbackChatId)?.name || "Atlas", text: result.reply || "" }];

  return source
    .filter((message) => message?.text)
    .map((message) => ({
      author: displayAuthor(message.author || agentByChatId(message.from)?.name || "Atlas"),
      type: "agent",
      from: message.from || fallbackChatId,
      text: message.text,
      phase: message.phase || "",
      audience: message.audience || "",
      to: message.to || "",
      isFinal: Boolean(message.isFinal),
      runId: message.runId || "",
      taskId: message.taskId || result.task?.id || "",
      agentStatus: message.agentStatus || null,
      pendingPublish: normalizePendingPublish(message.pendingPublish),
      pendingGoogleAction: normalizePendingGoogleAction(message.pendingGoogleAction),
    }));
}

function displayAuthor(author) {
  return {
    Coordinator: "Atlas",
    Mika: "Ava",
    Dev: "Dex",
    Nova: "Echo",
  }[author] || author;
}

function agentErrorReply(_error) {
  return {
    author: "System",
    from: "system",
    text: "AI сервис временно недоступен. Попробуйте ещё раз через минуту.",
  };
}

function setPanelTab(tab) {
  const showChat = tab === "chat";
  chatTab.classList.toggle("active", showChat);
  activityTab.classList.toggle("active", !showChat);
  chatTab.setAttribute("aria-selected", String(showChat));
  activityTab.setAttribute("aria-selected", String(!showChat));
  chatView.hidden = !showChat;
  activityView.hidden = showChat;
  if (showChat) scrollChatToBottom();
}

async function requestAgentChat(chatId, text, files = [], runId = createClientRunId()) {
  const history = selectedThread()
    .filter((message) => message.text !== "Thinking...")
    .slice(-12)
    .map((message) => ({
      role: message.type === "user" ? "user" : "assistant",
      author: message.author,
      text: message.text,
    }));
  const payload = {
    agentId: chatId,
    message: text,
    history,
    sessionId: chatSessionId,
    accountId: accountKey,
    runId,
    teamId: officeConversationTeamId,
    teamName: officeConversationTeamName,
  };
  let lastError = null;
  for (const [index, apiUrl] of AGENT_CHAT_API_CANDIDATES.entries()) {
    const controller = new AbortController();
    if (activeChatRun?.runId === runId) {
      activeChatRun.controller = controller;
    }
    const timeout = window.setTimeout(() => controller.abort(), AGENT_CHAT_TIMEOUT_MS);
    const request = files.length
      ? {
          method: "POST",
          body: multipartAgentChatPayload(payload, files),
          signal: controller.signal,
        }
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: controller.signal,
        };
    try {
      const response = await fetch(apiUrl, request);
      const responsePayload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(responsePayload.error || `HTTP ${response.status}`);
      }
      return responsePayload;
    } catch (error) {
      const timedOut = error instanceof DOMException && error.name === "AbortError";
      lastError = timedOut
        ? new Error(activeChatRun?.runId === runId && activeChatRun.cancelRequested
          ? "Task stopped by user."
          : "Team request timed out. The AI backend is still too slow.")
        : error;
      const canRetryLoopback = error instanceof TypeError && index < AGENT_CHAT_API_CANDIDATES.length - 1;
      if (!canRetryLoopback) {
        throw lastError;
      }
    } finally {
      window.clearTimeout(timeout);
      if (activeChatRun?.runId === runId && activeChatRun.controller === controller) {
        activeChatRun.controller = null;
      }
    }
  }
  throw lastError || new Error("AI backend request failed");
}

function multipartAgentChatPayload(payload, files) {
  const body = new FormData();
  body.append("payload", JSON.stringify(payload));
  files.forEach((file) => body.append("files", file, file.name));
  return body;
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function detectUserLanguage(text) {
  const clean = text.trim();
  if (!clean) return "en";
  const cyrillic = (clean.match(/[А-Яа-яЁё]/g) || []).length;
  const latin = (clean.match(/[A-Za-z]/g) || []).length;
  if (latin > cyrillic * 1.5) return "en";
  return "ru";
}

function uiText(key, lang = "ru") {
  const copy = {
    accepted: {
      ru: "Принял задачу. Определяю маршрут команды...",
      en: "Task received. Choosing the team route...",
    },
    directAccepted: {
      ru: "Принял сообщение. Готовлю ответ...",
      en: "Message received. Preparing the reply...",
    },
    teamActivity: {
      ru: "Задача получена в Team-чате.",
      en: "User task received in Team chat.",
    },
    directActivity: {
      ru: "Прямое сообщение получено.",
      en: "Direct message received.",
    },
    empty: {
      ru: "AI вернул пустой ответ.",
      en: "AI returned an empty response.",
    },
  };
  return copy[key]?.[lang] || copy[key]?.ru || key;
}

function messageAgentId(message, fallbackChatId = "coordinator") {
  if (message.from && message.from !== "team" && message.from !== "user") return message.from;
  const mapped = legacyAuthorToAgentId[message.author];
  if (mapped) return mapped;
  return fallbackChatId === "all" ? "coordinator" : fallbackChatId;
}

function phaseActivity(message, chatId) {
  const phase = message.phase || "";
  const agentId = messageAgentId(message, chatId);
  const agent = agentByChatId(agentId) || agents[0];
  if (message.from === "system") {
    return { agent, state: "focused", action: "error", bubble: "Needs attention", detail: message.text };
  }
  if (phase === "routing") {
    return {
      agent,
      state: "working",
      action: "routing",
      bubble: "Routing task",
      detail: "Sets the route, assigns specialists, and frames the next step.",
    };
  }
  if (phase === "internal") {
    return {
      agent,
      state: "working",
      action: message.to ? `to ${displayTargetName(message.to)}` : "reporting",
      bubble: message.to ? `Report to ${displayTargetName(message.to)}` : "Reporting",
      detail: message.text,
    };
  }
  if (phase === "question") {
    return {
      agent,
      state: "focused",
      action: "asking",
      bubble: "Question",
      detail: message.text,
    };
  }
  if (phase === "final" || message.isFinal) {
    return {
      agent,
      state: "happy",
      action: "final",
      bubble: "Final ready",
      detail: "Final answer assembled for the user.",
    };
  }
  return {
    agent,
    state: "focused",
    action: "replying",
    bubble: "Replying",
    detail: message.text,
  };
}

function displayTargetName(target) {
  if (!target || target === "team") return "Team";
  if (target === "coordinator") return "Atlas";
  return agentByChatId(target)?.name || displayAuthor(target);
}

function setAgentLiveState(agent, state, bubble) {
  if (!agent) return;
  agent.state = state;
  agent.bubble = bubble;
  renderRoster();
}

function officeStateForTaskStatus(status) {
  const value = String(status || "").toLowerCase();
  if (value === "working" || value === "planning" || value === "assigned") return "working";
  if (value === "completed") return "happy";
  if (value === "failed") return "focused";
  if (value === "waiting") return "focused";
  return "idle";
}

function bubbleForTaskStatus(status) {
  const value = String(status || "").toLowerCase();
  return {
    ready: "Ready",
    planning: "Planning",
    assigned: "Waiting",
    waiting: "Waiting",
    working: "Working",
    completed: "Completed",
    failed: "Failed",
  }[value] || "Ready";
}

function applyAgentStatus(status) {
  if (!status?.id) return;
  const agent = agentByChatId(status.id);
  if (!agent) return;
  setAgentLiveState(agent, officeStateForTaskStatus(status.status), bubbleForTaskStatus(status.status));
}

function applyAgentStatuses(statuses) {
  if (!Array.isArray(statuses)) return;
  statuses.forEach(applyAgentStatus);
}

function markTeamAccepted(chatId, text) {
  const lang = detectUserLanguage(text);
  const agent = chatId === "all" ? agentByChatId("coordinator") : agentByChatId(chatId);
  const bubble = chatId === "all" ? "Reading task" : "Reading";
  setAgentLiveState(agent, "working", bubble);
  addActivity(
    agent || agents[0],
    chatId === "all" ? "accepted" : "direct",
    chatId === "all" ? uiText("teamActivity", lang) : uiText("directActivity", lang),
  );
  return appendChatMessage(chatId, {
    author: chatId === "all" ? "Atlas" : agent?.name || "Agent",
    type: "agent",
    from: chatId === "all" ? "coordinator" : chatId,
    phase: "routing",
    audience: "team",
    text: chatId === "all" ? uiText("accepted", lang) : uiText("directAccepted", lang),
  });
}

async function playAgentMessages(chatId, loadingEntry, replies, run = null) {
  if (run?.cancelRequested) throw new Error("Task stopped by user.");
  const first = replies[0] || agentErrorReply(new Error(uiText("empty", "ru")));
  const firstActivity = phaseActivity(first, chatId);
  setAgentLiveState(firstActivity.agent, firstActivity.state, firstActivity.bubble);
  applyAgentStatus(first.agentStatus);
  addActivity(firstActivity.agent, firstActivity.action, firstActivity.detail);
  if (loadingEntry) {
    replaceChatMessage(chatId, loadingEntry, first);
  } else {
    appendChatMessage(chatId, first);
  }
  await sleep(520);

  for (const reply of replies.slice(1)) {
    if (run?.cancelRequested) throw new Error("Task stopped by user.");
    const activity = phaseActivity(reply, chatId);
    setAgentLiveState(activity.agent, activity.state, activity.bubble);
    applyAgentStatus(reply.agentStatus);
    addActivity(activity.agent, activity.action, activity.detail);
    appendChatMessage(chatId, reply);
    await sleep(reply.phase === "final" ? 220 : 680);
  }
}

async function sendChatMessage(event) {
  event.preventDefault();
  const text = chatInput.value.trim();
  const selectedImages = selectedChatImages.slice();
  if ((!text && selectedImages.length === 0) || chatBusy) return;

  const chatId = selectedChatId;
  const runId = createClientRunId();
  const messageText = text || "Проанализируй фото.";
  const filesForRequest = selectedImages.map((image) => image.file);
  const messageImages = selectedImages.map((image) => ({
    id: image.id,
    url: image.url,
    name: image.name,
    size: image.size,
    type: image.type,
  }));

  chatInput.value = "";
  clearSelectedChatImages({ revoke: false });
  appendChatMessage(chatId, {
    author: "You",
    type: "user",
    from: "user",
    text: messageText,
    images: messageImages,
    runId,
  });
  let loading = null;
  if (chatId === "all") {
    loading = markTeamAccepted(chatId, messageText);
  } else {
    const lang = detectUserLanguage(messageText);
    const agent = agentByChatId(chatId);
    setAgentLiveState(agent, "working", "Reading");
    addActivity(agent || agents[0], "direct", uiText("directActivity", lang));
  }

  chatBusy = true;
  activeChatRun = { runId, chatId, controller: null, cancelRequested: false };
  updateChatSendState();

  try {
    const result = await requestAgentChat(chatId, messageText, filesForRequest, runId);
    if (activeChatRun?.runId === runId && activeChatRun.cancelRequested) {
      throw new Error("Task stopped by user.");
    }
    const replies = normalizeAgentMessages(result, chatId);
    await playAgentMessages(chatId, loading, replies, activeChatRun);
    applyAgentStatuses(result.agentStatuses);
    if (result.pendingPublish?.text) {
      const pendingContext = [messageText, result.reply, ...replies.map((reply) => reply.text || "")].join("\n");
      const pendingPublish = normalizePendingPublish(result.pendingPublish, pendingContext);
      const linkedMedia = extractPublishMediaFromText(messageText);
      if (linkedMedia && !pendingPublish.mediaUrl) {
        pendingPublish.mediaUrl = linkedMedia.mediaUrl;
        pendingPublish.mediaType = linkedMedia.mediaType;
        pendingPublish.mediaName = linkedMedia.mediaName;
      }
      if (!pendingPublish.platforms.includes("youtube") && selectedImages[0] && !pendingPublish.mediaUrl && !pendingPublish.mediaDataUrl) {
        pendingPublish.mediaDataUrl = await fileToDataUrl(selectedImages[0].file);
        pendingPublish.mediaType = selectedImages[0].type || "image/jpeg";
        pendingPublish.mediaName = selectedImages[0].name || "uploaded-image.jpg";
      }
      const publishMessage = {
        author: "Echo",
        type: "agent",
        from: "nova",
        phase: "internal",
        to: "coordinator",
        text: pendingPublish.platforms.includes("youtube") && !pendingPublish.mediaUrl
          ? "Текст для YouTube подготовлен. Автоматически можно загрузить только видео; Community-пост нужно вставить в YouTube Studio вручную."
          : pendingPublish.autoPublish
            ? "Публикация готова. Echo отправляет ее автоматически через подключенные apps."
            : "Публикация готова. Проверь текст и нажми Publish, когда можно отправлять.",
        pendingPublish,
      };
      const activity = phaseActivity(publishMessage, chatId);
      setAgentLiveState(activity.agent, activity.state, "Publish ready");
      addActivity(
        activity.agent,
        pendingPublish.autoPublish ? "auto-publish" : "publish-ready",
        pendingPublish.autoPublish
          ? "Sending the approved social post automatically."
          : "Prepared a social publish card for approval.",
      );
      const entry = appendChatMessage(chatId, publishMessage);
      if (pendingPublish.autoPublish) {
        await publishPendingMessage(chatId, entry);
      }
    }
    if (result.pendingGoogleAction?.tool) {
      const pendingGoogleAction = normalizePendingGoogleAction(result.pendingGoogleAction);
      if (pendingGoogleAction) {
        const agent = agentByChatId(pendingGoogleAction.agent) || agentByChatId("mika") || agents[0];
        const actionMessage = {
          author: agent?.name || "Atlas",
          type: "agent",
          from: pendingGoogleAction.agent || "mika",
          phase: "internal",
          to: "coordinator",
          text: pendingGoogleAction.requiresApproval
            ? `${pendingGoogleAction.title} is ready for your explicit approval.`
            : `${pendingGoogleAction.title} is ready to run.`,
          pendingGoogleAction,
        };
        const activity = phaseActivity(actionMessage, chatId);
        setAgentLiveState(activity.agent, activity.state, "Google action ready");
        addActivity(
          activity.agent,
          pendingGoogleAction.requiresApproval ? "google-approval" : "google-read",
          pendingGoogleAction.requiresApproval
            ? "Prepared a Google action that needs confirmation."
            : "Prepared a read-only Google action.",
        );
        appendChatMessage(chatId, actionMessage);
      }
    }
  } catch (error) {
    const wasCancelled = activeChatRun?.runId === runId && activeChatRun.cancelRequested;
    const errorReply = wasCancelled ? stoppedAgentReply(runId) : agentErrorReply(error);
    const activity = phaseActivity(errorReply, chatId);
    setAgentLiveState(activity.agent, activity.state, activity.bubble);
    addActivity(activity.agent, activity.action, activity.detail);
    if (loading) {
      replaceChatMessage(chatId, loading, errorReply);
    } else {
      appendChatMessage(chatId, errorReply);
    }
  } finally {
    if (activeChatRun?.runId === runId) {
      activeChatRun = null;
    }
    chatBusy = false;
    updateChatSendState();
  }
}

function safePublishError(payload, status) {
  const detail = typeof payload?.detail === "string" ? payload.detail : "";
  return (detail || `HTTP ${status}`).replace(/\s+/g, " ").trim().slice(0, 500);
}

function safeClientPublishError(error, fallback) {
  const detail = error instanceof Error ? error.message : "";
  return (detail || fallback).replace(/\s+/g, " ").trim().slice(0, 500);
}

async function publishYoutubeVideo(pending) {
  const mediaUrl = publicYoutubeVideoUrl(pending.mediaUrl);
  if (!mediaUrl) {
    throw new Error("Enter a public HTTPS video URL before publishing to YouTube.");
  }
  const title = String(pending.youtubeTitle || "").trim();
  if (!title) {
    throw new Error("Enter a video title before publishing to YouTube.");
  }
  if (title.length > 100) {
    throw new Error("YouTube video titles can be at most 100 characters.");
  }
  const description = String(pending.youtubeDescription || "").trim();
  if (description.length > 5000) {
    throw new Error("YouTube video descriptions can be at most 5,000 characters.");
  }
  const response = await fetch(`${AUTH_API}/api/agent-tools/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({
      tool: "upload_youtube_video",
      arguments: {
        approved: true,
        mediaUrl,
        title,
        description,
        privacyStatus: normalizeYoutubePrivacyStatus(pending.privacyStatus),
        source: pending.source || "team",
        runId: pending.runId || undefined,
        taskId: pending.taskId || undefined,
      },
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.ok === false) {
    throw new Error(safePublishError(payload, response.status));
  }
  const result = payload?.result;
  if (!result || result.platform !== "youtube" || !result.videoId) {
    throw new Error("YouTube did not confirm the uploaded video.");
  }
  return {
    url: safeExternalHttpsUrl(result.url),
    privacyStatus: normalizeYoutubePrivacyStatus(result.privacyStatus || pending.privacyStatus),
  };
}

async function publishPendingMessage(chatId, message) {
  const pending = message.pendingPublish;
  if (!pending?.text) return;
  pending.status = "publishing";
  pending.error = "";
  pending.resultUrl = "";
  saveChatState();
  renderChatMessages();
  try {
    const platforms = normalizePublishPlatforms(pending.platforms || pending.platform);
    if (platforms.includes("youtube")) {
      if (platforms.length !== 1) {
        throw new Error("Publish YouTube as a separate approved action.");
      }
      const result = await publishYoutubeVideo(pending);
      pending.status = "published";
      pending.privacyStatus = result.privacyStatus;
      pending.resultUrl = result.url;
      saveChatState();
      appendChatMessage(chatId, {
        author: "Echo",
        type: "agent",
        from: "nova",
        text: result.url ? `Published to YouTube: ${result.url}` : "Published to YouTube.",
      });
      return;
    }

    const response = await fetch(`${AUTH_API}/api/publish/social`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({
        text: pending.text,
        platforms,
        media_url: pending.mediaUrl || null,
        media_data_url: pending.mediaDataUrl || null,
        media_type: pending.mediaType || null,
        media_name: pending.mediaName || null,
        run_id: pending.runId,
        task_id: pending.taskId || null,
        source: pending.source,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(safePublishError(payload, response.status));
    }
    if (Array.isArray(payload.results)) {
      const failed = payload.results.filter((result) => !result.ok);
      if (failed.length) {
        throw new Error(failed.map((result) => `${platformLabel(result.platform)}: ${result.error || "failed"}`).join(" | "));
      }
    }
    pending.status = "published";
    saveChatState();
    const publishedText = `Published to ${platforms.map(platformLabel).join(" + ")}.`;
    appendChatMessage(chatId, {
      author: "Echo",
      type: "agent",
      from: "nova",
      text: publishedText,
    });
  } catch (error) {
    pending.status = "error";
    pending.error = safeClientPublishError(error, "Social publish failed");
    saveChatState();
    renderChatMessages();
  }
}

function addActivity(agent, action, detail) {
  if (!agent || !activityFeed) return;
  const item = document.createElement("article");
  item.className = "activity-item";
  item.style.borderLeftColor = agent.color;
  const now = new Date();
  const title = document.createElement("strong");
  title.textContent = `${agent.name} · ${action}`;
  const body = document.createElement("p");
  body.textContent = detail;
  const time = document.createElement("small");
  time.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  item.append(title, body, time);
  activityFeed.prepend(item);
  while (activityFeed.children.length > 12) {
    activityFeed.lastElementChild.remove();
  }
}

function selectTeam() {
  selectedChatId = "all";
  selectedIndex = 0;
  cameraTransition = null;
  focusName.textContent = "Team";
  teamProfile.state = "focused";
  agents.forEach((agent) => {
    if (agent.state !== "working") {
      agent.state = agent.id === "coordinator" ? "focused" : "idle";
      agent.bubble = agent.id === "coordinator" ? "Team ready" : "Ready";
    }
  });
  saveChatState();
  renderRoster();
  renderChatMessages();
  notifyOfficeSelection("all");
}

function selectAgent(index) {
  if (!agents[index]?.active) return;
  selectedIndex = index;
  const agent = agents[index];
  focusName.textContent = agent.name;
  selectedChatId = agentChatId(agent);
  saveChatState();
  agent.state = agent.state === "working" ? "working" : "focused";
  agent.bubble = agent.state === "working" ? agent.bubble : "Focused";
  addActivity(agent, "selected", `${agent.name} is now in focus.`);
  renderRoster();
  renderChatTargets();
  renderChatMessages();
  notifyOfficeSelection(agentChatId(agent));
  focusCameraOnAgent(agent);
}

function selectAgentById(agentId) {
  if (agentId === "all") {
    setPanelTab("chat");
    selectTeam();
    return true;
  }
  const index = agents.findIndex((agent) => agentChatId(agent) === agentId);
  if (index < 0) return false;
  setPanelTab("chat");
  selectAgent(index);
  return true;
}

function notifyOfficeSelection(agentId) {
  if (!isDashboardEmbed || window.parent === window) return;
  window.parent.postMessage(
    {
      type: "rebly-office-agent-selected",
      agentId,
    },
    window.location.origin,
  );
}

function handleParentMessage(event) {
  if (event.origin !== window.location.origin) return;
  const data = event.data || {};
  if (data.type === "rebly-office-open-conversation") {
    applyOfficeConversation(data.conversation);
    applyOfficeTeam(data.team);
    notifyConversationUpdated();
    return;
  }
  if (data.type === "rebly-office-set-team") {
    applyOfficeTeam(data.team);
    return;
  }
  if (data.type !== "rebly-office-select-agent") return;
  const agentId = String(data.agentId || "").toLowerCase();
  selectAgentById(agentId);
}

function bubbleForDestination(destination, index) {
  const bubblesForDestination = destination.bubbles || [destination.activity || "Moving"];
  return bubblesForDestination[index % bubblesForDestination.length];
}

function routeToDestination(agent, destination) {
  const targetRoom = destination.room || "open";
  const sourceRoom = agent.room || "open";
  const route = [];

  if (sourceRoom !== targetRoom) {
    if (sourceRoom !== "open" && roomGateways[sourceRoom]) {
      route.push(roomGateways[sourceRoom].clone());
    }
    if (targetRoom !== "open" && roomGateways[targetRoom]) {
      route.push(roomGateways[targetRoom].clone());
    } else if (sourceRoom !== "open") {
      route.push(roomGateways.open.clone());
    }
  }

  route.push(destination.point.clone());
  return route;
}

function applyAgentRoute(agent, route, finalFace, instant = false) {
  if (!agent.group || !route.length) return;
  const target = agent.group.userData.target;
  agent.group.userData.route = [];
  agent.group.userData.faceTarget = finalFace?.clone() || null;

  if (instant) {
    const last = route[route.length - 1];
    agent.group.position.copy(last);
    target.copy(last);
    return;
  }

  const [next, ...rest] = route;
  target.copy(next);
  agent.group.userData.route = rest;
}

function setAgentDestination(agent, destination, options = {}) {
  const index = agents.indexOf(agent);
  const route = routeToDestination(agent, destination);
  agent.room = destination.room || "open";
  agent.activity = destination.kind || "focused";
  agent.destinationId = destination.id || `${agent.room}-${agent.activity}`;
  agent.state = options.state || "focused";
  agent.bubble = options.bubble || bubbleForDestination(destination, Math.max(index, 0));
  applyAgentRoute(agent, route, destination.face || null, options.instant);
}

function workDestination(slotIndex) {
  const normalizedIndex = ((slotIndex % workStations.length) + workStations.length) % workStations.length;
  const station = workStations[normalizedIndex];
  return {
    id: `work-${normalizedIndex}`,
    room: station.room || "open",
    kind: "typing",
    point: station.point,
    face: station.desk,
    bubbles: [station.activity],
  };
}

function setAgentTarget(agent, slotIndex, options = {}) {
  const normalizedIndex = ((slotIndex % workStations.length) + workStations.length) % workStations.length;
  agent.slot = normalizedIndex;
  setAgentDestination(agent, workDestination(normalizedIndex), {
    state: options.state || "working",
    bubble: options.bubble,
    instant: options.instant,
  });
}

function pickIdleDestination(agent, index, preferSpread = false) {
  const destinationsForTeam = idleDestinations.filter(
    (destination) => !destination.teams || destination.teams.includes(activeOfficeTeamId),
  );
  const destinations = destinationsForTeam.length ? destinationsForTeam : idleDestinations;
  const classicSpread = ["open-whiteboard", "kitchen-coffee", "relax-sofa", "open-plants", "kitchen-table"];
  const teamHouseSpread =
    activeOfficeTeamId === "sales-team"
      ? ["sales-crm-wall", "sales-huddle", "central-team-pulse", "coordinator-table", "research-wall", "support-queue", "automation-rack", "team-house-cafe", "team-house-recreation"]
      : ["marketing-screen", "marketing-studio", "central-team-pulse", "coordinator-table", "research-wall", "support-queue", "automation-rack", "team-house-cafe", "team-house-recreation"];
  const spread = activeOfficeLayout === "team-house" ? teamHouseSpread : classicSpread;
  if (preferSpread) {
    return (
      destinations.find((destination) => destination.id === spread[index % spread.length]) ||
      destinations[index % destinations.length]
    );
  }

  const candidates = destinations.filter((destination) => destination.id !== agent.destinationId);
  return candidates[Math.floor(Math.random() * candidates.length)] || destinations[index % destinations.length];
}

function assignIdleDestination(agent, index = agents.indexOf(agent), instant = false) {
  if (!agent.active || teamWorkActive) return;
  const destination = pickIdleDestination(agent, Math.max(index, 0), instant);
  setAgentDestination(agent, destination, {
    state: destination.kind === "rest" ? "idle" : "focused",
    instant,
  });
}

function initializeAgentDestinations() {
  agents.forEach((agent, index) => {
    if (!agent.active) return;
    if (agent.state === "working") {
      setAgentTarget(agent, agent.slot ?? index, {
        state: "working",
        bubble: agent.bubble || "Working",
        instant: true,
      });
      return;
    }
    assignIdleDestination(agent, index, true);
  });
}

function assignTask(index = selectedIndex) {
  const lead = agents[index];
  if (!lead || !lead.active || teamWorkActive) return;
  const task = tasks[Math.floor(Math.random() * tasks.length)];
  teamWorkActive = true;
  queued = Math.max(0, queued - 1);
  queueCount.textContent = String(queued).padStart(2, "0");

  const supportBubbles = ["Joining", "Researching", "Building", "Checking", "Publishing"];
  agents.forEach((agent, agentIndex) => {
    if (!agent.active) return;
    setAgentTarget(agent, agent.slot ?? agentIndex, {
      state: "working",
      bubble: agentIndex === index ? task : supportBubbles[agentIndex % supportBubbles.length],
    });
  });

  addActivity(lead, "working", `${task}: team moved to Open Space.`);
  renderRoster();
  window.clearTimeout(teamWorkTimer);

  teamWorkTimer = window.setTimeout(() => {
    agents.forEach((agent, agentIndex) => {
      if (!agent.active) return;
      agent.state = "happy";
      agent.activity = "celebrate";
      agent.bubble = agentIndex === index ? "Done" : "Synced";
    });
    queued += 1;
    queueCount.textContent = String(queued).padStart(2, "0");
    addActivity(lead, "completed", `${task} moved to review.`);
    renderRoster();

    window.setTimeout(() => {
      teamWorkActive = false;
      agents.forEach((agent, agentIndex) => assignIdleDestination(agent, agentIndex));
      renderRoster();
    }, 2400);
  }, 7600);
}

function randomAdjacentSlot(current) {
  const candidates = slots.map((_, index) => index).filter((index) => index !== current);
  return candidates[Math.floor(Math.random() * candidates.length)];
}

function shuffleTeam() {
  agents.forEach((agent, index) => {
    if (!agent.active) return;
    agent.state = "focused";
    assignIdleDestination(agent, index);
  });
  addActivity(agents[selectedIndex], "moved", "Agents started roaming between rooms.");
  renderRoster();
}

function celebrateTeam() {
  agents.forEach((agent) => {
    if (!agent.active) return;
    agent.state = "happy";
    agent.activity = "celebrate";
    agent.bubble = "Nice";
  });
  addActivity(agents[selectedIndex], "win", "Team milestone recorded.");
  renderRoster();
}

function hireAgent() {
  const inactive = agents.find((agent) => !agent.active);
  if (inactive) {
    inactive.active = true;
    inactive.state = "focused";
    inactive.bubble = "Joined";
    if (inactive.group) {
      inactive.group.visible = true;
      inactive.group.position.set(6.8, 0, 3.2);
    }
    assignIdleDestination(inactive, agents.indexOf(inactive));
    addActivity(inactive, "hired", `${inactive.role} joined the team.`);
  } else {
    const target = agents[selectedIndex];
    target.state = "focused";
    target.bubble = "Capacity full";
    addActivity(target, "capacity", "All seats are already filled.");
  }
  renderRoster();
}

function setOrthographicViewHeight(viewHeight, aspect) {
  camera.top = viewHeight / 2;
  camera.bottom = -viewHeight / 2;
  camera.left = (-viewHeight * aspect) / 2;
  camera.right = (viewHeight * aspect) / 2;
  camera.updateProjectionMatrix();
}

function teamHouseProjectedSpan() {
  camera.updateMatrixWorld(true);
  const corners = [];
  [TEAM_HOUSE_SIZE.minX, TEAM_HOUSE_SIZE.maxX].forEach((x) => {
    [TEAM_HOUSE_SIZE.minY, TEAM_HOUSE_SIZE.maxY].forEach((y) => {
      [TEAM_HOUSE_SIZE.minZ, TEAM_HOUSE_SIZE.maxZ].forEach((z) => {
        corners.push(new THREE.Vector3(x, y, z).applyMatrix4(camera.matrixWorldInverse));
      });
    });
  });
  const minX = Math.min(...corners.map((corner) => corner.x));
  const maxX = Math.max(...corners.map((corner) => corner.x));
  const minY = Math.min(...corners.map((corner) => corner.y));
  const maxY = Math.max(...corners.map((corner) => corner.y));
  return { width: maxX - minX, height: maxY - minY };
}

function updateTeamHouseCameraFrustum() {
  if (!renderer) return;
  const { clientWidth, clientHeight } = canvas.parentElement;
  const aspect = clientWidth / Math.max(clientHeight, 1);
  const projected = teamHouseProjectedSpan();
  const coverage = 0.88;
  const viewHeight = Math.max(
    projected.height / coverage,
    projected.width / Math.max(aspect * coverage, 0.34),
  );
  setOrthographicViewHeight(viewHeight, aspect);
}

function fitTeamHouseCamera() {
  if (!controls) return;
  cameraTransition = null;
  camera.position.set(23.5, 20.5, 25.5);
  camera.zoom = 1;
  controls.target.set(0, 0.72, -0.15);
  controls.minZoom = 0.58;
  controls.maxZoom = 1.72;
  controls.update();
  updateTeamHouseCameraFrustum();
}

function focusCameraOnAgent(agent) {
  if (!controls || !agent?.group) return;
  const target = agent.group.position.clone();
  target.y = 0.72;
  const offset = camera.position.clone().sub(controls.target);
  const maxZoom = activeOfficeLayout === "team-house" ? 1.34 : 1.22;
  cameraTransition = {
    target,
    position: target.clone().add(offset),
    zoom: Math.min(controls.maxZoom, maxZoom),
  };
}

function updateCameraTransition(delta) {
  if (!cameraTransition || !controls) return;
  const amount = 1 - Math.exp(-delta * 5.2);
  camera.position.lerp(cameraTransition.position, amount);
  controls.target.lerp(cameraTransition.target, amount);
  camera.zoom = THREE.MathUtils.lerp(camera.zoom, cameraTransition.zoom, amount);
  camera.updateProjectionMatrix();
  if (
    camera.position.distanceTo(cameraTransition.position) < 0.02 &&
    controls.target.distanceTo(cameraTransition.target) < 0.02 &&
    Math.abs(camera.zoom - cameraTransition.zoom) < 0.005
  ) {
    camera.position.copy(cameraTransition.position);
    controls.target.copy(cameraTransition.target);
    camera.zoom = cameraTransition.zoom;
    cameraTransition = null;
  }
}

function resetView() {
  if (!controls) return;
  const isTeamHouse = activeOfficeLayout === "team-house";
  if (isTeamHouse) {
    fitTeamHouseCamera();
    return;
  }
  cameraTransition = null;
  camera.position.set(9.8, 8.1, 10.8);
  camera.zoom = 1;
  controls.target.set(0, 0.7, 0.2);
  controls.minZoom = 0.5;
  controls.maxZoom = 2.05;
  resize();
  controls.update();
}

function refreshBubblePresentation() {
  const selectedAgentIndex = selectedChatId === "all" ? -1 : selectedIndex;
  const candidates = agents
    .map((agent, index) => ({
      agent,
      index,
      selected: index === selectedAgentIndex,
      working: agent.state === "working" || agent.state === "happy",
    }))
    .filter(({ agent, selected, working }) => agent.active && agent.group && (selected || working))
    .sort((a, b) => Number(b.selected) - Number(a.selected) || Number(b.working) - Number(a.working) || a.index - b.index)
    .slice(0, MAX_FULL_AGENT_CARDS);
  const fullIndexes = new Set(candidates.map(({ index }) => index));

  agents.forEach((agent, index) => {
    const selected = index === selectedAgentIndex;
    const working = agent.state === "working" || agent.state === "happy";
    bubblePresentation.set(agent, {
      full: fullIndexes.has(index),
      selected,
      working,
      priority: selected ? 30 : working ? 20 : 10,
    });
  });
}

function renderBubbleContent(element, agent, presentation) {
  const contentKey = `${presentation.full ? "full" : "compact"}|${agent.name}|${agent.bubble}`;
  if (element.dataset.contentKey === contentKey) return;
  element.dataset.contentKey = contentKey;
  element.replaceChildren();
  const name = document.createElement("strong");
  name.textContent = agent.name;
  element.appendChild(name);
  if (presentation.full) {
    const detail = document.createElement("span");
    detail.textContent = agent.bubble;
    element.appendChild(detail);
  }
}

function clampBubbleToLayer(element, bounds) {
  const rect = element.getBoundingClientRect();
  let x = Number.parseFloat(element.style.left) || 0;
  let y = Number.parseFloat(element.style.top) || 0;
  if (rect.left < bounds.left + BUBBLE_EDGE_PADDING) x += bounds.left + BUBBLE_EDGE_PADDING - rect.left;
  if (rect.right > bounds.right - BUBBLE_EDGE_PADDING) x -= rect.right - (bounds.right - BUBBLE_EDGE_PADDING);
  if (rect.top < bounds.top + BUBBLE_EDGE_PADDING) y += bounds.top + BUBBLE_EDGE_PADDING - rect.top;
  if (rect.bottom > bounds.bottom - BUBBLE_EDGE_PADDING) y -= rect.bottom - (bounds.bottom - BUBBLE_EDGE_PADDING);
  element.style.left = `${x}px`;
  element.style.top = `${y}px`;
}

function elementsOverlap(a, b) {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

function updateBubble(agent) {
  let element = bubbles.get(agent.name);
  if (!element) {
    element = document.createElement("div");
    element.className = "speech-bubble";
    bubbleLayer.appendChild(element);
    bubbles.set(agent.name, element);
  }

  if (!agent.active || !agent.group) {
    element.classList.remove("visible");
    return;
  }

  const presentation = bubblePresentation.get(agent) || { full: false, priority: 10 };
  renderBubbleContent(element, agent, presentation);
  element.classList.toggle("full-card", presentation.full);
  element.classList.toggle("compact", !presentation.full);
  element.dataset.priority = String(presentation.priority);

  const point = agent.group.position.clone();
  point.y += presentation.full ? 2.3 : 2.05;
  point.project(camera);
  const insideCanvas = point.z >= -1 && point.z <= 1 && point.x >= -1.08 && point.x <= 1.08 && point.y >= -1.08 && point.y <= 1.08;
  if (!insideCanvas) {
    element.classList.remove("visible");
    return;
  }

  const width = Math.max(element.offsetWidth, presentation.full ? 126 : 58);
  const height = Math.max(element.offsetHeight, presentation.full ? 44 : 18);
  const rawX = (point.x * 0.5 + 0.5) * bubbleLayer.clientWidth;
  const rawY = (-point.y * 0.5 + 0.5) * bubbleLayer.clientHeight;
  const x = THREE.MathUtils.clamp(rawX, width / 2 + BUBBLE_EDGE_PADDING, bubbleLayer.clientWidth - width / 2 - BUBBLE_EDGE_PADDING);
  const y = THREE.MathUtils.clamp(rawY, height + BUBBLE_EDGE_PADDING, bubbleLayer.clientHeight - BUBBLE_EDGE_PADDING);

  element.style.left = `${x}px`;
  element.style.top = `${y}px`;
  element.style.setProperty("--bubble-lift", `${presentation.full ? 12 : 5}px`);
  element.classList.add("visible");
}

function resolveBubbleCollisions() {
  const bounds = bubbleLayer.getBoundingClientRect();
  const visible = [...bubbles.values()]
    .filter((element) => element.classList.contains("visible"))
    .sort((a, b) => Number(b.dataset.priority || 0) - Number(a.dataset.priority || 0));

  visible.forEach((element) => clampBubbleToLayer(element, bounds));
  for (let pass = 0; pass < 4; pass += 1) {
    let changed = false;
    for (let index = 1; index < visible.length; index += 1) {
      const movable = visible[index];
      for (let anchorIndex = 0; anchorIndex < index; anchorIndex += 1) {
        const anchor = visible[anchorIndex];
        const movableRect = movable.getBoundingClientRect();
        const anchorRect = anchor.getBoundingClientRect();
        if (!elementsOverlap(movableRect, anchorRect)) continue;

        const overlapX = Math.min(movableRect.right, anchorRect.right) - Math.max(movableRect.left, anchorRect.left);
        const overlapY = Math.min(movableRect.bottom, anchorRect.bottom) - Math.max(movableRect.top, anchorRect.top);
        const direction = movableRect.left + movableRect.width / 2 < anchorRect.left + anchorRect.width / 2 ? -1 : 1;
        const currentLeft = Number.parseFloat(movable.style.left) || 0;
        movable.style.left = `${currentLeft + direction * (overlapX + 12)}px`;
        clampBubbleToLayer(movable, bounds);

        if (elementsOverlap(movable.getBoundingClientRect(), anchorRect)) {
          const currentLift = Number.parseFloat(movable.style.getPropertyValue("--bubble-lift")) || 5;
          movable.style.setProperty("--bubble-lift", `${currentLift + overlapY + 10}px`);
          clampBubbleToLayer(movable, bounds);
        }
        changed = true;
      }
    }
    if (!changed) break;
  }
}

function animateRig(rig, agent, moving, elapsed, index) {
  const gait = Math.sin(elapsed * (moving ? 10 : 6) + index * 0.7);
  const smallGait = Math.sin(elapsed * 7.2 + index);
  const idle = Math.sin(elapsed * 2.1 + index * 0.9);
  const working = agent.state === "working";
  const happy = agent.state === "happy";
  const focused = agent.state === "focused";
  const activity = agent.activity || "";
  const coffee = activity === "coffee";
  const talking = activity === "talk";
  const resting = activity === "rest";
  const reading = activity === "read" || activity === "screen";
  const typing = activity === "typing" || working;

  rig.root.rotation.z = happy ? Math.sin(elapsed * 7 + index) * 0.055 : idle * 0.012;
  rig.torso.rotation.z = moving ? gait * 0.035 : idle * 0.018;
  rig.head.rotation.x = typing || reading ? -0.12 + smallGait * 0.035 : idle * 0.035;
  rig.head.rotation.z = happy ? Math.sin(elapsed * 8 + index) * 0.09 : idle * 0.025;

  const stride = moving ? 0.62 : typing ? 0.12 : 0;
  rig.leftLeg.rotation.x = gait * stride;
  rig.rightLeg.rotation.x = -gait * stride;
  rig.leftLeg.rotation.z = moving ? 0.02 : 0;
  rig.rightLeg.rotation.z = moving ? -0.02 : 0;

  if (happy) {
    rig.leftArm.rotation.x = -0.45 + smallGait * 0.18;
    rig.rightArm.rotation.x = -0.45 - smallGait * 0.18;
    rig.leftArm.rotation.z = 0.88 + smallGait * 0.12;
    rig.rightArm.rotation.z = -0.88 - smallGait * 0.12;
  } else if (moving) {
    rig.leftArm.rotation.x = -gait * 0.58;
    rig.rightArm.rotation.x = gait * 0.58;
    rig.leftArm.rotation.z = 0.08;
    rig.rightArm.rotation.z = -0.08;
  } else if (typing) {
    rig.leftArm.rotation.x = -0.48 + smallGait * 0.2;
    rig.rightArm.rotation.x = 0.34 - smallGait * 0.22;
    rig.leftArm.rotation.z = 0.12;
    rig.rightArm.rotation.z = -0.16;
  } else if (coffee) {
    rig.leftArm.rotation.x = -0.08 + idle * 0.08;
    rig.rightArm.rotation.x = -0.86 + smallGait * 0.08;
    rig.leftArm.rotation.z = 0.1;
    rig.rightArm.rotation.z = -0.28;
  } else if (talking) {
    rig.leftArm.rotation.x = -0.22 + smallGait * 0.16;
    rig.rightArm.rotation.x = -0.08 - smallGait * 0.16;
    rig.leftArm.rotation.z = 0.36 + idle * 0.08;
    rig.rightArm.rotation.z = -0.34 - idle * 0.08;
  } else if (resting) {
    rig.leftArm.rotation.x = 0.18 + idle * 0.04;
    rig.rightArm.rotation.x = -0.12 - idle * 0.04;
    rig.leftArm.rotation.z = 0.18;
    rig.rightArm.rotation.z = -0.18;
  } else if (reading) {
    rig.leftArm.rotation.x = -0.42 + idle * 0.04;
    rig.rightArm.rotation.x = -0.36 - idle * 0.04;
    rig.leftArm.rotation.z = 0.16;
    rig.rightArm.rotation.z = -0.16;
  } else {
    rig.leftArm.rotation.x = focused ? -0.18 + idle * 0.06 : idle * 0.045;
    rig.rightArm.rotation.x = focused ? 0.18 - idle * 0.06 : -idle * 0.045;
    rig.leftArm.rotation.z = 0.08;
    rig.rightArm.rotation.z = -0.08;
  }

  const blink = Math.sin(elapsed * 3.3 + index * 1.7) > 0.965;
  rig.leftEye.scale.y = blink ? 0.16 : 1;
  rig.rightEye.scale.y = blink ? 0.16 : 1;

  if (happy) {
    rig.mouth.scale.x = 1.45 + Math.sin(elapsed * 6 + index) * 0.12;
    rig.mouth.scale.y = 1.45;
  } else if (typing || talking || coffee) {
    rig.mouth.scale.x = 0.75 + Math.sin(elapsed * 9 + index) * 0.08;
    rig.mouth.scale.y = 0.72;
  } else {
    rig.mouth.scale.x = 1 + idle * 0.06;
    rig.mouth.scale.y = 1;
  }
}

function updateAgentSelectionVisual(agent, index, elapsed) {
  const group = agent.group;
  if (!group) return;
  const selected = selectedChatId !== "all" && index === selectedIndex;
  const hovered = index === hoveredAgentIndex;
  const ring = group.userData.selectionRing;
  const aura = group.userData.selectionAura;
  const emphasis = selected ? 1 : hovered ? 0.68 : 0;
  const pulse = 1 + Math.sin(elapsed * 4.4 + index) * 0.06;

  if (ring) {
    ring.visible = emphasis > 0;
    ring.material.opacity = selected ? 0.82 : hovered ? 0.48 : 0;
    ring.scale.setScalar((selected ? 1.12 : 1) * pulse);
  }
  if (aura) {
    aura.visible = emphasis > 0;
    aura.material.opacity = selected ? 0.18 : hovered ? 0.1 : 0;
    aura.scale.setScalar((selected ? 1.26 : 1.12) * pulse);
  }

  const rig = group.userData.rig;
  if (rig?.root) {
    const baseScale = group.userData.rigScale || 1;
    rig.root.scale.setScalar(baseScale * (selected ? 1.045 : hovered ? 1.025 : 1));
  }
}

function updateAgents(delta, elapsed) {
  refreshBubblePresentation();
  agents.forEach((agent, index) => {
    const group = agent.group;
    if (!group) return;
    group.visible = agent.active;
    if (!agent.active) return;

    const target = group.userData.target;
    const previousX = group.position.x;
    const previousZ = group.position.z;
    const lerpAmount = 1 - Math.exp(-delta * 2.8);
    group.position.x = THREE.MathUtils.lerp(group.position.x, target.x, lerpAmount);
    group.position.z = THREE.MathUtils.lerp(group.position.z, target.z, lerpAmount);

    if (Math.abs(group.position.x - target.x) < 0.004) group.position.x = target.x;
    if (Math.abs(group.position.z - target.z) < 0.004) group.position.z = target.z;

    const travelDistance = Math.hypot(group.position.x - previousX, group.position.z - previousZ);
    let distanceToTarget = Math.hypot(group.position.x - target.x, group.position.z - target.z);
    if (distanceToTarget < 0.045 && group.userData.route?.length) {
      target.copy(group.userData.route.shift());
      distanceToTarget = Math.hypot(group.position.x - target.x, group.position.z - target.z);
    }
    const moving = travelDistance > 0.001 || distanceToTarget > 0.035;

    const faceTarget = group.userData.faceTarget;
    const desiredAngle = moving
      ? Math.atan2(target.x - group.position.x, target.z - group.position.z)
      : faceTarget
        ? Math.atan2(faceTarget.x - group.position.x, faceTarget.z - group.position.z)
      : Math.atan2(camera.position.x - group.position.x, camera.position.z - group.position.z);
    const turnSpeed = moving ? 8 : 2.4;
    group.rotation.y = lerpAngle(
      group.rotation.y,
      desiredAngle,
      1 - Math.exp(-delta * turnSpeed),
    );

    const bobPower =
      moving ? 0.14 : agent.state === "working" ? 0.08 : agent.state === "happy" ? 0.17 : 0.045;
    const bobSpeed =
      moving ? 10 : agent.state === "working" ? 8.5 : agent.state === "happy" ? 9 : 3.2;
    group.position.y = Math.sin(elapsed * bobSpeed + index) * bobPower;

    const rig = group.userData.rig;
    if (rig) animateRig(rig, agent, moving, elapsed, index);
    updateAgentSelectionVisual(agent, index, elapsed);

    updateBubble(agent);
  });
  resolveBubbleCollisions();
}

function agentHitFromEvent(event) {
  if (!renderer) return;
  const rect = canvas.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObjects(clickTargets, false);
  return hits[0]?.object?.userData?.agentIndex;
}

function onCanvasPointerMove(event) {
  const nextHoveredIndex = agentHitFromEvent(event);
  if (hoveredAgentIndex === (Number.isInteger(nextHoveredIndex) ? nextHoveredIndex : -1)) return;
  hoveredAgentIndex = Number.isInteger(nextHoveredIndex) ? nextHoveredIndex : -1;
  canvas.style.cursor = hoveredAgentIndex >= 0 ? "pointer" : "grab";
}

function onCanvasPointerLeave() {
  hoveredAgentIndex = -1;
  canvas.style.cursor = "grab";
}

function onCanvasClick(event) {
  const agentIndex = agentHitFromEvent(event);
  if (Number.isInteger(agentIndex)) {
    selectAgent(agentIndex);
  }
}

function resize() {
  if (!renderer) return;
  const { clientWidth, clientHeight } = canvas.parentElement;
  renderer.setSize(clientWidth, clientHeight, false);
  if (activeOfficeLayout === "team-house") {
    updateTeamHouseCameraFrustum();
    return;
  }
  const aspect = clientWidth / Math.max(clientHeight, 1);
  const viewHeight = aspect < 0.9 ? 18.2 : clientWidth < 720 ? 15.8 : 13.4;
  setOrthographicViewHeight(viewHeight, aspect);
}

function updateClock() {
  clock.textContent = new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function startAutomation() {
  roamingTimer = window.setInterval(() => {
    if (teamWorkActive) return;
    agents.forEach((agent, index) => {
      if (!agent.active || Math.random() < 0.48) return;
      assignIdleDestination(agent, index);
    });
    renderRoster();
  }, 6800);

  window.setInterval(() => {
    if (teamWorkActive) return;
    const active = agents
      .map((agent, index) => ({ agent, index }))
      .filter(({ agent }) => agent.active);
    const pick = active[Math.floor(Math.random() * active.length)];
    if (pick) assignTask(pick.index);
  }, 24000);
}

function animate() {
  if (!renderer || !controls) return;
  const delta = Math.min(clockTimer.getDelta(), 0.05);
  const elapsed = clockTimer.elapsedTime;
  updateCameraTransition(delta);
  updateAgents(delta, elapsed);
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(animate);
}

const clockTimer = new THREE.Clock();

if (renderer) {
  addOffice();
  agents.forEach(createAgentModel);
}
loadChatState(accountKey);
if (selectedChatId === "all") {
  focusName.textContent = "Team";
  agents[0].state = "focused";
  agents[0].bubble = "Team ready";
} else {
  const restoredAgent = agentByChatId(selectedChatId);
  const restoredIndex = agents.findIndex((agent) => agent.id === restoredAgent?.id);
  if (restoredIndex >= 0) {
    selectedIndex = restoredIndex;
    focusName.textContent = restoredAgent.name;
    restoredAgent.state = "focused";
    restoredAgent.bubble = "Focused";
  }
}
if (renderer) {
  initializeAgentDestinations();
}

document.querySelector("#assignBtn")?.addEventListener("click", () => assignTask());
document.querySelector("#shuffleBtn")?.addEventListener("click", shuffleTeam);
document.querySelector("#celebrateBtn")?.addEventListener("click", celebrateTeam);
document.querySelector("#hireBtn")?.addEventListener("click", hireAgent);
viewBtn?.addEventListener("click", resetView);
canvas.addEventListener("click", onCanvasClick);
canvas.addEventListener("pointermove", onCanvasPointerMove);
canvas.addEventListener("pointerleave", onCanvasPointerLeave);
window.addEventListener("resize", resize);
chatTab.addEventListener("click", () => setPanelTab("chat"));
activityTab.addEventListener("click", () => setPanelTab("activity"));
chatTarget?.addEventListener("change", () => {
  const nextChatId = chatTarget.value;
  if (nextChatId !== "all" && selectAgentById(nextChatId)) {
    return;
  }
  selectTeam();
});
chatComposer.addEventListener("submit", sendChatMessage);
chatInput?.addEventListener("input", updateChatSendState);
chatStop?.addEventListener("click", () => {
  stopActiveChatRun();
});
chatFileInput?.addEventListener("change", () => {
  addSelectedChatImages(chatFileInput.files);
  chatFileInput.value = "";
});

window.addEventListener("message", handleParentMessage);
setupChatResize();
renderRoster();
renderChatTargets();
renderChatMessages();
updateChatSendState();
resolveAccountContext();
addActivity(agents[0], "online", "Team workspace is ready.");
updateClock();
window.setInterval(updateClock, 15000);
resize();
startAutomation();
animate();

window.agentOfficeDebug = {
  agents,
  camera,
  controls,
  renderer,
  scene,
  rooms,
  workStations,
  idleDestinations,
  loadedAssetNames,
  assignTask,
  assignIdleDestination,
  routeToDestination,
  setAgentDestination,
  selectAgent,
  fitTeamHouseCamera,
  resetView,
};
