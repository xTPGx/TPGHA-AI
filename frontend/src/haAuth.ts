export interface HomeAssistantSessionHints {
  accessToken: string;
  clientUser: Record<string, any>;
}

export function homeAssistantSessionHints(): HomeAssistantSessionHints {
  return {
    accessToken: homeAssistantAccessToken(),
    clientUser: liveHomeAssistantUser(),
  };
}

export function homeAssistantAccessToken(): string {
  if (typeof window === "undefined") return "";
  const candidates = [
    "hassTokens",
    "home-assistant-auth-token",
  ];
  for (const key of candidates) {
    const token = tokenFromRaw(safeStorageGet(window.localStorage, key)) || tokenFromRaw(safeStorageGet(window.sessionStorage, key));
    if (token) return token;
  }
  return "";
}

function liveHomeAssistantUser(): Record<string, any> {
  if (typeof window === "undefined") return {};
  const parentWindow = window.parent;
  if (!parentWindow || parentWindow === window) return {};
  try {
    const doc = parentWindow.document;
    const roots = [
      doc.documentElement,
      doc.body,
      ...Array.from(doc.querySelectorAll("home-assistant, home-assistant-main, ha-sidebar, partial-panel-resolver")),
    ].filter(Boolean) as Element[];
    const found = findHassUser(roots);
    return found ? sanitizeHaUser(found) : {};
  } catch {
    return {};
  }
}

function safeStorageGet(storage: Storage | undefined, key: string): string | null {
  try {
    return storage?.getItem(key) || null;
  } catch {
    return null;
  }
}

function tokenFromRaw(raw: string | null): string {
  if (!raw) return "";
  const trimmed = raw.trim();
  if (!trimmed) return "";
  if (trimmed.startsWith("ey") || trimmed.startsWith("Bearer ")) {
    return trimmed.replace(/^Bearer\s+/i, "");
  }
  try {
    const parsed = JSON.parse(trimmed);
    return String(parsed.access_token || parsed.accessToken || parsed.token || "").trim();
  } catch {
    return "";
  }
}

function findHassUser(roots: Element[]): Record<string, any> | null {
  const seen = new Set<Element | ShadowRoot>();
  const stack: Array<Element | ShadowRoot> = [...roots];
  while (stack.length) {
    const node = stack.shift();
    if (!node || seen.has(node)) continue;
    seen.add(node);
    const candidate = ((node as any).hass?.user || (node as any).hass?.auth?.user) as Record<string, any> | undefined;
    if (candidate && (candidate.id || candidate.name || candidate.username)) return candidate;
    const shadow = (node as Element).shadowRoot;
    if (shadow) stack.push(shadow);
    const children = (node as Element | ShadowRoot).children;
    if (children) stack.push(...Array.from(children));
  }
  return null;
}

function sanitizeHaUser(user: Record<string, any>): Record<string, any> {
  const sanitized: Record<string, any> = {};
  for (const key of ["id", "name", "username", "display_name", "is_admin", "is_owner"]) {
    if (user[key] !== undefined && user[key] !== null) sanitized[key] = user[key];
  }
  return sanitized;
}
