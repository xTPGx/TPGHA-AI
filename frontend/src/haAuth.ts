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
  const storage = window.localStorage;
  const length = safeStorageLength(storage);
  for (let i = 0; i < length; i += 1) {
    const key = safeStorageKey(storage, i);
    if (!key.toLowerCase().includes("hass")) continue;
    const token = tokenFromRaw(safeStorageGet(storage, key));
    if (token) return token;
  }
  return "";
}

function safeStorageGet(storage: Storage | undefined, key: string): string | null {
  try {
    return storage?.getItem(key) || null;
  } catch {
    return null;
  }
}

function safeStorageLength(storage: Storage | undefined): number {
  try {
    return storage?.length || 0;
  } catch {
    return 0;
  }
}

function safeStorageKey(storage: Storage | undefined, index: number): string {
  try {
    return storage?.key(index) || "";
  } catch {
    return "";
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
