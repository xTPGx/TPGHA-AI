const APP_ROUTES = new Set([
  "",
  "chat",
  "suggestions",
  "jarvis",
  "house-brain",
  "profiles",
  "memory-center",
  "dashboard-builder",
  "voice-settings",
  "voice-sources",
  "ha",
  "discovery",
  "tester",
  "entities",
  "rooms",
  "assistants",
  "users",
  "music",
  "capabilities",
  "permissions",
  "dashboard",
]);

export function ingressBasePath(): string {
  const parts = window.location.pathname.split("/").filter(Boolean);
  if (parts[0] === "api" && parts[1] === "hassio_ingress" && parts[2]) {
    return `/${parts.slice(0, 3).join("/")}`;
  }
  const first = parts[0] || "";
  if (!first || APP_ROUTES.has(first)) {
    return "";
  }
  // HA Supervisor ingress paths look like /3e5a55d6_tpg_homeai. Treat any
  // unknown first segment as a mount prefix so the same build also works if the
  // add-on slug/hash changes.
  return `/${first}`;
}
