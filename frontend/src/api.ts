// Thin API client for the TPG HomeAI backend.
// Base URL comes from VITE_API_BASE; in dev we default to the Vite proxy "/api".

const BASE = (import.meta as any).env?.VITE_API_BASE ?? "/api";

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
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
};
