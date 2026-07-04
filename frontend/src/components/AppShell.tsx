import { useEffect, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import ChatFab from "./ChatFab";

type Role = "admin" | "manager" | "resident" | "kiosk" | "guest";
type ThemeMode = "dark" | "black" | "light" | "white";
export type NavItemDef = { to: string; label: string; end?: boolean; roles: Role[] };
export type NavGroupDef = { label: string; items: NavItemDef[]; collapsible?: boolean };
type ShellStatus = {
  health: any;
  setup: any;
  providers: any;
};

const THEME_KEY = "tpg.themeMode";
const THEMES: { id: ThemeMode; label: string }[] = [
  { id: "dark", label: "Dark" },
  { id: "black", label: "Black" },
  { id: "light", label: "Light" },
  { id: "white", label: "White" },
];

function readTheme(): ThemeMode {
  try {
    const saved = localStorage.getItem(THEME_KEY) as ThemeMode | null;
    if (saved && THEMES.some((theme) => theme.id === saved)) return saved;
  } catch {
    /* ignore */
  }
  return "dark";
}

export default function AppShell({
  children,
  navGroups,
  role,
  sessionRole,
  sessionUser,
  haUserCandidates,
  unknownHaUser,
  identityWarning,
  previewRole,
  canPreviewRoles,
  onPreviewRoleChange,
}: {
  children: React.ReactNode;
  navGroups: NavGroupDef[];
  role: Role;
  sessionRole: Role;
  sessionUser: any;
  haUserCandidates: string[];
  unknownHaUser: string;
  identityWarning: string;
  previewRole: Role | "";
  canPreviewRoles: boolean;
  onPreviewRoleChange: (role: Role | "") => void;
}) {
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useState<ThemeMode>(() => readTheme());
  const [status, setStatus] = useState<ShellStatus>({ health: null, setup: null, providers: null });
  const location = useLocation();
  const navigate = useNavigate();
  const canGoBack = location.pathname !== "/";
  const isChatWorkspace = location.pathname === "/chat" || location.pathname === "/notebook";
  const canUseChat = navGroups.some((group) => group.items.some((item) => item.to === "/chat" && item.roles.includes(role)));

  useEffect(() => setOpen(false), [location.pathname]);

  useEffect(() => {
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([api.health(), api.setupStatus(), api.aiProviders()])
      .then(([health, setup, providers]) => {
        if (cancelled) return;
        setStatus({
          health: health.status === "fulfilled" ? health.value : null,
          setup: setup.status === "fulfilled" ? setup.value : null,
          providers: providers.status === "fulfilled" ? providers.value : null,
        });
      })
      .catch(() => {
        if (!cancelled) setStatus({ health: null, setup: null, providers: null });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open]);

  return (
    <div className="app-shell tpg-console min-h-screen overflow-x-hidden" data-theme={theme}>
      <header className="compact-header tpg-chrome sticky top-0 z-40 border-b px-3 py-2 xl:hidden">
        <div className="flex min-h-12 items-center justify-between gap-3">
          {canGoBack && (
            <button
              className="tpg-shell-button"
              onClick={() => navigate(-1)}
              aria-label="Go back"
            >
              <span className="text-2xl leading-none">&lsaquo;</span>
            </button>
          )}
          <button
            className="tpg-shell-button"
            onClick={() => setOpen(true)}
            aria-label="Open navigation"
          >
            <span className="flex flex-col gap-1">
              <span className="block h-0.5 w-5 rounded bg-current" />
              <span className="block h-0.5 w-5 rounded bg-current" />
              <span className="block h-0.5 w-5 rounded bg-current" />
            </span>
          </button>
          <div className="min-w-0 flex-1">
            <div className="tpg-glow-text truncate text-sm font-bold">Atlas Console</div>
            <div className="truncate text-xs text-slate-500">{sessionUser?.name || "House"} / {roleLabel(role)} / {haStatusLabel(status.health)}</div>
          </div>
          <button
            className="tpg-ai-chip h-9 px-3 text-xs"
            onClick={() => setTheme(nextTheme(theme))}
            title={`Theme: ${theme}. Tap to cycle.`}
          >
            AI
          </button>
        </div>
      </header>

      <div className="flex min-h-screen min-w-0">
        <aside className="wide-sidebar tpg-sidebar hidden w-[18rem] shrink-0 border-r p-3 xl:block">
          <ShellNav
            navGroups={navGroups}
            role={role}
            sessionRole={sessionRole}
            sessionUser={sessionUser}
            haUserCandidates={haUserCandidates}
            unknownHaUser={unknownHaUser}
            identityWarning={identityWarning}
            previewRole={previewRole}
            canPreviewRoles={canPreviewRoles}
            onPreviewRoleChange={onPreviewRoleChange}
            theme={theme}
            onThemeChange={setTheme}
            status={status}
          />
        </aside>

        {open && (
          <div className="fixed inset-0 z-50 xl:hidden">
            <button
              className="absolute inset-0 bg-black/60"
              onClick={() => setOpen(false)}
              aria-label="Close navigation"
            />
            <aside className="tpg-sidebar relative h-full w-[min(22rem,88vw)] overflow-y-auto border-r p-4 shadow-2xl">
              <div className="mb-4 flex items-center justify-between gap-3">
                <BrandLockup />
                <button className="chat-icon-btn min-h-11 min-w-11 px-0" onClick={() => setOpen(false)} aria-label="Close navigation">x</button>
              </div>
              <ShellNav
                navGroups={navGroups}
                role={role}
                sessionRole={sessionRole}
                sessionUser={sessionUser}
                haUserCandidates={haUserCandidates}
                unknownHaUser={unknownHaUser}
                identityWarning={identityWarning}
                previewRole={previewRole}
                canPreviewRoles={canPreviewRoles}
                onPreviewRoleChange={onPreviewRoleChange}
                theme={theme}
                onThemeChange={setTheme}
                status={status}
              />
            </aside>
          </div>
        )}

        <main className="min-w-0 flex-1 overflow-x-hidden">
          {!isChatWorkspace && (
            <AssistantTopBar
              sessionUser={sessionUser}
              role={role}
              status={status}
              canGoBack={canGoBack}
              onBack={() => navigate(-1)}
            />
          )}
          <div className={isChatWorkspace
            ? "h-[calc(100vh-4.0625rem)] w-full overflow-hidden xl:h-screen"
            : "mx-auto w-full max-w-[96rem] px-3 py-4 sm:px-5 lg:px-6 xl:py-6"
          }>
            {!isChatWorkspace && <SetupStatusBanner status={status} />}
            {children}
          </div>
        </main>
      </div>
      <ChatFab canUseChat={canUseChat} />
    </div>
  );
}

function ShellNav({
  navGroups,
  role,
  sessionRole,
  sessionUser,
  haUserCandidates,
  unknownHaUser,
  identityWarning,
  previewRole,
  canPreviewRoles,
  onPreviewRoleChange,
  theme,
  onThemeChange,
  status,
}: {
  navGroups: NavGroupDef[];
  role: Role;
  sessionRole: Role;
  sessionUser: any;
  haUserCandidates: string[];
  unknownHaUser: string;
  identityWarning: string;
  previewRole: Role | "";
  canPreviewRoles: boolean;
  onPreviewRoleChange: (role: Role | "") => void;
  theme: ThemeMode;
  onThemeChange: (theme: ThemeMode) => void;
  status: ShellStatus;
}) {
  const location = useLocation();
  return (
    <div className="flex min-h-full flex-col">
      <div className="mb-5 hidden xl:block">
        <BrandLockup />
      </div>

      {sessionUser && (
        <div className="tpg-panel-flat mb-4 p-3">
          <div className="flex items-center gap-2">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-cyan-300/25 bg-cyan-300/10 text-xs font-bold text-cyan-100">
              {(sessionUser.name || "H").slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-slate-100">{sessionUser.name}</div>
              <div className="text-xs text-slate-500">{roleLabel(sessionRole)}</div>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <StatusPill label="HA" state={haOnline(status.health) ? "good" : "warn"} value={haStatusLabel(status.health)} />
            <StatusPill label="Setup" state={status.setup?.setup_completed ? "good" : "warn"} value={status.setup?.setup_completed ? "Complete" : "Open"} />
          </div>
          {haUserCandidates.length > 0 && (
            <div className="mt-2 rounded-md border border-cyan-300/15 bg-black/20 px-2 py-1 text-[11px] text-slate-400">
              HA login: {haUserCandidates.join(", ")}
            </div>
          )}
          {unknownHaUser && (
            <div className="mt-2 rounded-md border border-amber-400/30 bg-amber-400/10 px-2 py-1 text-[11px] text-amber-200">
              Add this HA username as an alias to the right TPG user.
            </div>
          )}
          {identityWarning && (
            <div className="mt-2 rounded-md border border-amber-400/30 bg-amber-400/10 px-2 py-1 text-[11px] text-amber-200">
              {identityWarning}
            </div>
          )}
          {canPreviewRoles && (
            <div className="mt-3">
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-slate-500">Preview menu</label>
              <select className="input py-2 text-sm" value={previewRole} onChange={(e) => onPreviewRoleChange(e.target.value as Role | "")}>
                <option value="">Full admin</option>
                <option value="manager">Manager</option>
                <option value="resident">Resident</option>
                <option value="kiosk">Kiosk / Shared</option>
                <option value="guest">Guest</option>
              </select>
            </div>
          )}
          <div className="mt-3">
            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-slate-500">Theme</label>
            <div className="tpg-theme-switch">
              {THEMES.map((option) => (
                <button
                  key={option.id}
                  className={`tpg-theme-choice ${theme === option.id ? "tpg-theme-choice-active" : ""}`}
                  onClick={() => onThemeChange(option.id)}
                  type="button"
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {!sessionUser && (
        <ThemePicker
          theme={theme}
          onThemeChange={onThemeChange}
          className="tpg-panel-flat mb-5 p-3"
        />
      )}

      <nav className="flex flex-col gap-4">
        {navGroups.map((group) => {
          const visible = group.items.filter((item) => item.roles.includes(role));
          if (!visible.length) return null;
          const active = visible.some((item) => item.end ? location.pathname === item.to : location.pathname.startsWith(item.to));
          const content = (
            <div className="mt-2 flex flex-col gap-1">
              {visible.map((item) => (
                <NavLink
                  key={`${group.label}-${item.to}-${item.label}`}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `tpg-nav-row min-h-10 rounded-lg px-3 py-2 text-sm font-medium transition focus:outline-none focus:ring-2 focus:ring-cyan-300/35 ${
                      isActive
                        ? "tpg-nav-row-active border border-cyan-300/35 bg-cyan-300/[0.10] text-cyan-50"
                        : "border border-transparent text-slate-400 hover:border-cyan-300/15 hover:bg-cyan-300/[0.04] hover:text-white"
                    }`
                  }
                >
                  <span className="tpg-nav-icon" aria-hidden="true">{navIcon(item.label)}</span>
                  <span className="truncate">{item.label}</span>
                </NavLink>
              ))}
            </div>
          );
          if (group.collapsible) {
            return (
              <details key={group.label} open={active} className="group">
                <summary className="cursor-pointer list-none px-3 text-[10px] font-bold uppercase tracking-wide text-slate-500 group-open:text-slate-300">
                  {group.label}
                </summary>
                {content}
              </details>
            );
          }
          return (
            <div key={group.label}>
              <div className="px-3 text-[10px] font-bold uppercase tracking-wide text-slate-500">{group.label}</div>
              {content}
            </div>
          );
        })}
      </nav>

      <div className="mt-auto pt-8">
        <div className="tpg-panel-flat p-3 text-xs">
          <div className="mb-2 flex items-center justify-between gap-3">
            <span className="font-semibold text-slate-300">Connection</span>
            <span className={`h-2.5 w-2.5 rounded-full ${haOnline(status.health) ? "bg-emerald-400" : "bg-amber-300"}`} />
          </div>
          <div className="truncate text-slate-500">{providerLabel(status.providers)}</div>
          <div className="mt-1 truncate text-slate-500">{smartOpsLabel(status.setup)}</div>
        </div>
      </div>
    </div>
  );
}

function BrandLockup() {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <div className="tpg-brand-mark" aria-hidden="true">A</div>
      <div className="min-w-0">
        <div className="tpg-glow-text truncate text-base font-bold">TPG HomeAI</div>
        <div className="truncate text-xs text-slate-500">Atlas smart-home console</div>
      </div>
    </div>
  );
}

function AssistantTopBar({
  sessionUser,
  role,
  status,
  canGoBack,
  onBack,
}: {
  sessionUser: any;
  role: Role;
  status: ShellStatus;
  canGoBack: boolean;
  onBack: () => void;
}) {
  return (
    <header className="tpg-assistant-topbar hidden min-h-[4.5rem] items-center justify-between gap-4 border-b px-5 xl:flex">
      <div className="flex min-w-0 items-center gap-3">
        {canGoBack && (
          <button className="chat-icon-btn h-10 min-h-10 w-10 px-0" onClick={onBack} aria-label="Go back">
            <span className="text-xl leading-none">&lsaquo;</span>
          </button>
        )}
        <div className="min-w-0">
          <div className="tpg-glow-text truncate text-sm font-semibold">Atlas</div>
          <div className="truncate text-xs text-slate-500">{sessionUser?.name || "Home"} profile / {roleLabel(role)}</div>
        </div>
      </div>
      <div className="flex min-w-0 items-center justify-end gap-2">
        <StatusPill label="SmartOps" state={status.setup?.activation_status === "activated" ? "good" : "warn"} value={smartOpsLabel(status.setup)} />
        <StatusPill label="HA" state={haOnline(status.health) ? "good" : "warn"} value={haStatusLabel(status.health)} />
        <StatusPill label="AI" state={status.health?.openai?.configured ? "good" : "neutral"} value={providerLabel(status.providers)} />
        <Link className="chat-pill" to="/setup">Setup</Link>
        <Link className="chat-pill" to="/ha">Diagnostics</Link>
      </div>
    </header>
  );
}

function SetupStatusBanner({ status }: { status: ShellStatus }) {
  const chips = setupChips(status);
  if (!chips.length) return null;
  return (
    <div className="tpg-setup-banner mb-4 flex flex-wrap items-center gap-2 p-3 text-sm">
      <span className="font-semibold text-slate-100">Setup needs attention</span>
      {chips.map((chip) => (
        <Link key={chip.label} to={chip.to} className={`tpg-mini-chip tpg-mini-chip-${chip.tone}`}>
          {chip.label}
        </Link>
      ))}
    </div>
  );
}

function StatusPill({ label, value, state }: { label: string; value: string; state: "good" | "warn" | "neutral" }) {
  return (
    <span className={`tpg-status-pill tpg-status-${state}`}>
      <span className="tpg-status-dot" aria-hidden="true" />
      <span className="hidden 2xl:inline text-slate-500">{label}</span>
      <span className="truncate">{value}</span>
    </span>
  );
}

function setupChips(status: ShellStatus) {
  const setup = status.setup || {};
  const detection = setup.detection || {};
  const sync = setup.smartops_sync || {};
  const out: { label: string; to: string; tone: "warn" | "info" }[] = [];
  if (setup.setup_completed === false || (!setup.setup_completed && setup.activation_status !== "activated")) {
    out.push({ label: "Setup incomplete", to: "/setup", tone: "warn" });
  }
  if (setup.activation_status && setup.activation_status !== "activated") {
    out.push({ label: "SmartOps not linked", to: "/setup", tone: "info" });
  }
  if (detection.kokoro && detection.kokoro.reachable === false) {
    out.push({ label: "Kokoro not detected", to: "/setup", tone: "info" });
  }
  if (sync && !sync.lastSyncAt && setup.activation_status === "activated") {
    out.push({ label: "Device sync pending", to: "/discovery", tone: "warn" });
  }
  if (!haOnline(status.health)) {
    out.push({ label: "HA connection check", to: "/ha", tone: "warn" });
  }
  return out.slice(0, 4);
}

function haOnline(health: any) {
  return Boolean(health?.home_assistant?.reachable || health?.ha?.reachable || health?.status === "ok");
}

function haStatusLabel(health: any) {
  if (!health) return "Checking";
  if (haOnline(health)) return "Connected";
  return health?.status || "Degraded";
}

function providerLabel(providers: any) {
  const active = providers?.active || providers?.mode || providers?.provider || providers?.default_provider;
  if (active) return String(active).replace(/_/g, " ");
  return "AI provider";
}

function smartOpsLabel(setup: any) {
  if (!setup) return "SmartOps checking";
  if (setup.activation_status === "activated") return "SmartOps linked";
  return "SmartOps local";
}

function navIcon(label: string) {
  const key = label.toLowerCase();
  if (key.includes("chat")) return "AI";
  if (key.includes("house") || key.includes("room")) return "HM";
  if (key.includes("music")) return "MU";
  if (key.includes("assistant") || key.includes("brain")) return "A";
  if (key.includes("memory") || key.includes("knowledge")) return "KB";
  if (key.includes("setup")) return "ST";
  if (key.includes("discovery") || key.includes("entities") || key.includes("profiles")) return "DS";
  if (key.includes("permission") || key.includes("identity")) return "ID";
  if (key.includes("status") || key.includes("integration") || key.includes("diagnostic")) return "OK";
  if (key.includes("dashboard") || key.includes("console")) return "UI";
  return "--";
}

function ThemePicker({
  theme,
  onThemeChange,
  className = "",
}: {
  theme: ThemeMode;
  onThemeChange: (theme: ThemeMode) => void;
  className?: string;
}) {
  return (
    <div className={className}>
      <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-slate-500">Theme</label>
      <div className="tpg-theme-switch">
        {THEMES.map((option) => (
          <button
            key={option.id}
            className={`tpg-theme-choice ${theme === option.id ? "tpg-theme-choice-active" : ""}`}
            onClick={() => onThemeChange(option.id)}
            type="button"
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function roleLabel(role: Role) {
  if (role === "admin") return "Owner";
  if (role === "kiosk") return "Kiosk / Shared";
  return role.charAt(0).toUpperCase() + role.slice(1);
}

function nextTheme(theme: ThemeMode): ThemeMode {
  const index = THEMES.findIndex((item) => item.id === theme);
  return THEMES[(index + 1) % THEMES.length].id;
}
