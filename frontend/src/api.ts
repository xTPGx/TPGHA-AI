// Thin API client for the TPG HomeAI backend.
import { ingressBasePath } from "./ingress";
//
// Base URL resolution (PART 1):
//   - VITE_API_BASE wins if explicitly set at build time.
//   - In the Vite dev server we use the "/api" proxy (see vite.config.ts).
//   - In a production build (e.g. served by the add-on backend) we use
//     same-origin relative URLs so /health hits the backend directly.
const env = (import.meta as any).env ?? {};
const ingressBase = ingressBasePath();
const BASES: string[] = env.VITE_API_BASE
  ? [env.VITE_API_BASE]
  : env.DEV
    ? ["/api"]
    : ingressBase
      ? [`${ingressBase}/api`, ingressBase]
      : ["/api", ""];

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  let lastError: Error | null = null;
  for (const base of BASES) {
    try {
      return await requestOnce<T>(base, path, init);
    } catch (err: any) {
      lastError = err;
      if (!err?.retryWithNextBase) {
        throw err;
      }
    }
  }
  throw lastError || new Error("Could not reach backend.");
}

async function requestOnce<T>(base: string, path: string, init?: RequestInit): Promise<T> {
  const url = `${base}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  // The backend always returns JSON for API routes. If we got HTML, the SPA
  // fallback intercepted the call — i.e. API routing is misconfigured.
  const ctype = res.headers.get("content-type") || "";
  if (ctype.includes("text/html")) {
    const error: any = new Error(`API endpoint returned HTML at ${url}.`);
    error.retryWithNextBase = true;
    throw error;
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || body.message || detail;
    } catch {
      /* ignore */
    }
    const error: any = new Error(`${res.status}: ${detail} (${url})`);
    error.retryWithNextBase = res.status === 404;
    throw error;
  }
  return res.json() as Promise<T>;
}

export interface CommandResponse {
  success: boolean;
  assistant?: string;
  user?: string;
  conversation_id?: string;
  intent?: string;
  resolved: Record<string, any>;
  executed: boolean;
  requires_confirmation: boolean;
  confirmation_message?: string;
  confirmation_token?: string;
  message: string;
  tool_call?: Record<string, any>;
  data: Record<string, any>;
  error?: string;
}

export interface HAEntity {
  entity_id: string;
  state: string;
  friendly_name?: string;
  domain: string;
  available: boolean;
  attributes: Record<string, any>;
}

export const api = {
  uiSession: () => http<any>("/ui/session"),
  health: () => http<any>("/health"),
  config: () => http<any>("/config"),
  reloadConfig: () => http<any>("/config/reload", { method: "POST" }),
  saveRoom: (body: Record<string, any>) =>
    http<any>("/config/rooms", { method: "POST", body: JSON.stringify(body) }),
  saveAssistant: (body: Record<string, any>) =>
    http<any>("/config/assistants", { method: "POST", body: JSON.stringify(body) }),
  saveUser: (body: Record<string, any>) =>
    http<any>("/config/users", { method: "POST", body: JSON.stringify(body) }),
  saveMusicAccount: (body: Record<string, any>) =>
    http<any>("/config/music-accounts", { method: "POST", body: JSON.stringify(body) }),
  saveSpeaker: (body: Record<string, any>) =>
    http<any>("/config/speakers", { method: "POST", body: JSON.stringify(body) }),
  savePermissions: (body: Record<string, any>) =>
    http<any>("/config/permissions", { method: "POST", body: JSON.stringify(body) }),
  saveVoiceSource: (body: Record<string, any>) =>
    http<any>("/config/voice-sources", { method: "POST", body: JSON.stringify(body) }),
  entities: () => http<HAEntity[]>("/ha/entities"),
  entity: (id: string) => http<HAEntity>(`/ha/entity/${id}`),
  command: (assistant: string, user: string, message: string) =>
    http<CommandResponse>("/command", {
      method: "POST",
      body: JSON.stringify({ assistant, user, message }),
    }),
  commandPreview: (assistant: string, user: string, message: string, conversation_id?: string) =>
    http<CommandResponse>("/command/preview", {
      method: "POST",
      body: JSON.stringify({ assistant, user, message, conversation_id }),
    }),
  chat: (assistant: string, user: string, message: string, conversation_id?: string, room?: string) =>
    http<any>("/chat", {
      method: "POST",
      body: JSON.stringify({ assistant, user, message, conversation_id, room }),
    }),
  chatPreview: (assistant: string, user: string, message: string, conversation_id?: string, room?: string) =>
    http<any>("/chat/preview", {
      method: "POST",
      body: JSON.stringify({ assistant, user, message, conversation_id, room }),
    }),
  confirm: (confirmation_token: string, security_pin?: string) =>
    http<CommandResponse>("/confirm", {
      method: "POST",
      body: JSON.stringify({ confirmation_token, security_pin }),
    }),
  cancelConfirm: (confirmation_token: string) =>
    http<CommandResponse>("/confirm/cancel", {
      method: "POST",
      body: JSON.stringify({ confirmation_token }),
    }),
  // Discovery + operational state
  state: () => http<any>("/state"),
  discoveryScan: () => http<any>("/discovery/scan", { method: "POST", body: JSON.stringify({}) }),
  discoveryPending: () => http<any>("/discovery/pending"),
  discoverySummary: () => http<any>("/discovery/summary"),
  approve: (body: Record<string, any>) =>
    http<any>("/discovery/approve", { method: "POST", body: JSON.stringify(body) }),
  ignore: (entity_id: string, reason?: string) =>
    http<any>("/discovery/ignore", { method: "POST", body: JSON.stringify({ entity_id, reason }) }),
  mapEntity: (body: Record<string, any>) =>
    http<any>("/discovery/map", { method: "POST", body: JSON.stringify(body) }),
  resolve: (kind: string, name: string, user?: string) =>
    http<any>("/test/resolve", {
      method: "POST",
      body: JSON.stringify({ kind, name, user }),
    }),
  testAction: (action: string, assistant: string, user: string, params: Record<string, any>) =>
    http<CommandResponse>("/test/action", {
      method: "POST",
      body: JSON.stringify({ action, assistant, user, params }),
    }),
  drafts: () => http<any>("/automation/drafts"),
  suggestions: () => http<any>("/suggestions"),
  proactiveSuggestions: (status?: string) =>
    http<any>(`/suggestions/proactive${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  approveProactiveSuggestion: (id: number) =>
    http<any>(`/suggestions/proactive/${id}/approve`, { method: "POST" }),
  ignoreProactiveSuggestion: (id: number) =>
    http<any>(`/suggestions/proactive/${id}/ignore`, { method: "POST" }),
  brainLayers: () => http<any>("/brain/layers"),
  completionStatus: () => http<any>("/brain/completion"),
  houseState: () => http<any>("/brain/house-state"),
  modeBrain: () => http<any>("/brain/modes"),
  assistantIntelligence: () => http<any>("/brain/assistants"),
  tabletProfiles: () => http<any>("/dashboards/tablet-profiles"),
  deviceProfiles: () => http<any>("/knowledge/device-profiles"),
  deviceAdapters: () => http<any>("/knowledge/device-adapters"),
  voiceSources: () => http<any>("/knowledge/voice-sources"),
  voiceProfiles: () => http<any>("/voice/profiles"),
  voiceVoices: () => http<any>("/voice/voices"),
  voiceDeployment: () => http<any>("/voice/deployment"),
  voicePreview: (body: Record<string, any>) =>
    http<any>("/voice/preview", { method: "POST", body: JSON.stringify(body) }),
  voiceSpeak: (body: Record<string, any>) =>
    http<any>("/voice/speak", { method: "POST", body: JSON.stringify(body) }),
  aiProviders: () => http<any>("/ai/providers"),
  memories: (status?: string) =>
    http<any>(`/memory${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  draftMemory: (body: Record<string, any>) =>
    http<any>("/memory/draft", { method: "POST", body: JSON.stringify(body) }),
  approveMemory: (id: number) =>
    http<any>(`/memory/${id}/approve`, { method: "POST" }),
  ignoreMemory: (id: number) =>
    http<any>(`/memory/${id}/ignore`, { method: "POST" }),
  conversations: (limit = 50, filters?: { assistant?: string; user?: string }) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (filters?.assistant) params.set("assistant", filters.assistant);
    if (filters?.user) params.set("user", filters.user);
    return http<any>(`/conversations?${params.toString()}`);
  },
  conversation: (conversationId: string) =>
    http<any>(`/conversations/${encodeURIComponent(conversationId)}`),
  addConversationNote: (conversationId: string, body: Record<string, any>) =>
    http<any>(`/conversations/${encodeURIComponent(conversationId)}/notes`, {
      method: "POST",
      body: JSON.stringify({ ...body, conversation_id: conversationId }),
    }),
  exportConversation: (conversationId: string) =>
    http<any>(`/conversations/${encodeURIComponent(conversationId)}/export`),
  researchSearch: (query: string, maxResults = 5) =>
    http<any>("/research/search", {
      method: "POST",
      body: JSON.stringify({ query, max_results: maxResults }),
    }),
  dashboardDraft: (body: Record<string, any>) =>
    http<any>("/dashboards/draft", { method: "POST", body: JSON.stringify(body) }),
  dashboardInstall: (body: Record<string, any>) =>
    http<any>("/dashboards/install", { method: "POST", body: JSON.stringify(body) }),
  approveDraft: (id: number) =>
    http<any>(`/automation/drafts/${id}/approve`, { method: "POST" }),
  ignoreDraft: (id: number) =>
    http<any>(`/automation/drafts/${id}/ignore`, { method: "POST" }),
  editDraft: (id: number, body: Record<string, any>) =>
    http<any>(`/automation/drafts/${id}/edit`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
