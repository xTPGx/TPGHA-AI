export interface HomeAssistantSessionHints {
  accessToken: string;
  clientUser: Record<string, any>;
}

export function homeAssistantSessionHints(): HomeAssistantSessionHints {
  // Prefer the freshest identity. A wrapper hash (if a custom panel is used) and
  // the live parent hass.user reflect the *active* HA login. sessionStorage is a
  // debug cache only because it can hold a previous user's identity. Never send
  // cached storage as an identity hint; a stale shared-tablet cache is worse
  // than falling back safely to the shared profile.
  const freshUser = userFromWrapperHash() || liveHomeAssistantUser();
  return {
    accessToken: homeAssistantAccessToken(),
    clientUser: freshUser || {},
  };
}

export function debugClientHints(): Record<string, any> {
  if (typeof window === "undefined") {
    return { available: false };
  }
  return {
    locationHref: window.location.href,
    pathname: window.location.pathname,
    hash: window.location.hash,
    inIframe: window.parent && window.parent !== window,
    hashUser: userFromWrapperHash(),
    liveParentUser: liveHomeAssistantUser(),
    cachedStorageUserIgnored: userFromWrapperStorage(),
    accessTokenPresent: Boolean(homeAssistantAccessToken()),
  };
}

export function startHomeAssistantUserBridge(onUser: (user: Record<string, any>) => void): () => void {
  if (typeof window === "undefined") return () => {};
  const handler = (event: MessageEvent) => {
    if (event.origin !== window.location.origin) return;
    const data = event.data || {};
    if (data.type !== "tpg-homeai-ha-user" || !data.user) return;
    const user = sanitizeHaUser(data.user);
    if (!Object.keys(user).length) return;
    safeStorageSet(window.sessionStorage, "tpg-homeai-ha-user", JSON.stringify(user));
    onUser(user);
  };
  window.addEventListener("message", handler);
  return () => window.removeEventListener("message", handler);
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

function safeStorageSet(storage: Storage | undefined, key: string, value: string): void {
  try {
    storage?.setItem(key, value);
  } catch {
    /* ignored */
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

function userFromWrapperHash(): Record<string, any> | null {
  if (typeof window === "undefined" || !window.location.hash) return null;
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const encoded = params.get("tpg_ha_user");
  if (!encoded) return null;
  try {
    const raw = decodeURIComponent(escape(atob(encoded)));
    const user = sanitizeHaUser(JSON.parse(raw));
    if (Object.keys(user).length) {
      safeStorageSet(window.sessionStorage, "tpg-homeai-ha-user", JSON.stringify(user));
      return user;
    }
  } catch {
    return null;
  }
  return null;
}

function userFromWrapperStorage(): Record<string, any> | null {
  try {
    const raw = safeStorageGet(window.sessionStorage, "tpg-homeai-ha-user");
    if (!raw) return null;
    const user = sanitizeHaUser(JSON.parse(raw));
    return Object.keys(user).length ? user : null;
  } catch {
    return null;
  }
}
