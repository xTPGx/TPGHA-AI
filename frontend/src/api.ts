// Thin API client for the TPG HomeAI backend.
//
// Base URL resolution (PART 1):
//   - VITE_API_BASE wins if explicitly set at build time.
//   - In the Vite dev server we use the "/api" proxy (see vite.config.ts).
//   - In a production build (e.g. served by the add-on backend) we use
//     same-origin relative URLs so /health hits the backend directly.
const env = (import.meta as any).env ?? {};
const BASE: string = env.VITE_API_BASE ?? (env.DEV ? "/api" : "");

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  // The backend always returns JSON for API routes. If we got HTML, the SPA
  // fallback intercepted the call — i.e. API routing is misconfigured.
  const ctype = res.headers.get("content-type") || "";
  if (ctype.includes("text/html")) {
    throw new Error(
      "API endpoint returned HTML. Add-on API routing is misconfigured."
    );
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || body.message || detail;
    } catch {
      /* ignore */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export interface CommandResponse {
  success: boolean;
  assistant?: string;
  user?: string;
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
  health: () => http<any>("/health"),
  config: () => http<any>("/config"),
  reloadConfig: () => http<any>("/config/reload", { method: "POST" }),
  entities: () => http<HAEntity[]>("/ha/entities"),
  entity: (id: string) => http<HAEntity>(`/ha/entity/${id}`),
  command: (assistant: string, user: string, message: string) =>
    http<CommandResponse>("/command", {
      method: "POST",
      body: JSON.stringify({ assistant, user, message }),
    }),
  chat: (assistant: string, user: string, message: string, conversation_id?: string) =>
    http<any>("/chat", {
      method: "POST",
      body: JSON.stringify({ assistant, user, message, conversation_id }),
    }),
  confirm: (confirmation_token: string) =>
    http<CommandResponse>("/confirm", {
      method: "POST",
      body: JSON.stringify({ confirmation_token }),
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
