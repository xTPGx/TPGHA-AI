import { useEffect, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import ChatFab from "./ChatFab";

type Role = "admin" | "manager" | "resident" | "kiosk" | "guest";
type ThemeMode = "dark" | "black" | "light" | "white";
export type NavItemDef = { to: string; label: string; end?: boolean; roles: Role[] };
export type NavGroupDef = { label: string; items: NavItemDef[]; collapsible?: boolean };

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
            <div className="tpg-glow-text truncate text-sm font-bold">TPG HomeAI</div>
            <div className="truncate text-xs text-slate-500">{sessionUser?.name || "House"} · {roleLabel(role)}</div>
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
        <aside className="wide-sidebar tpg-sidebar hidden w-[16rem] shrink-0 border-r p-3 xl:block">
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
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <div className="tpg-glow-text text-lg font-bold">TPG HomeAI</div>
                  <div className="text-xs text-slate-500">Smart-home AI</div>
                </div>
                <button className="btn-ghost min-h-11" onClick={() => setOpen(false)}>Close</button>
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
              />
            </aside>
          </div>
        )}

        <main className="min-w-0 flex-1 overflow-x-hidden">
          <div className={isChatWorkspace
            ? "h-[calc(100vh-4.0625rem)] w-full overflow-hidden xl:h-screen"
            : "mx-auto w-full max-w-[96rem] px-3 py-4 sm:px-5 lg:px-6 xl:py-6"
          }>
            {canGoBack && !isChatWorkspace && (
              <button
                className="tpg-ghost-button mb-4 hidden min-h-11 xl:inline-flex"
                onClick={() => navigate(-1)}
              >
                Back
              </button>
            )}
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
}) {
  const location = useLocation();
  return (
    <div className="flex min-h-full flex-col">
      <div className="mb-5 hidden xl:block">
        <div className="tpg-glow-text text-base font-bold">TPG HomeAI</div>
        <div className="text-xs text-slate-500">Jarvis command center</div>
      </div>

      {sessionUser && (
        <div className="tpg-panel-flat mb-5 p-3">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-cyan-300/25 bg-cyan-300/10 text-xs font-bold text-cyan-100">
              {(sessionUser.name || "H").slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-slate-100">{sessionUser.name}</div>
              <div className="text-xs text-slate-500">{roleLabel(sessionRole)}</div>
            </div>
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
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `min-h-10 rounded-lg px-3 py-2 text-sm font-medium transition focus:outline-none focus:ring-2 focus:ring-cyan-300/35 ${
                      isActive
                        ? "border border-cyan-300/35 bg-cyan-300/[0.10] text-cyan-50 shadow-[inset_3px_0_0_rgba(25,211,230,0.9)]"
                        : "border border-transparent text-slate-400 hover:border-cyan-300/15 hover:bg-cyan-300/[0.04] hover:text-white"
                    }`
                  }
                >
                  {item.label}
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

      <div className="mt-auto pt-8 text-[10px] leading-relaxed text-slate-500">
        Chat is the everyday surface. Owner Console holds setup and diagnostics.
      </div>
    </div>
  );
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
