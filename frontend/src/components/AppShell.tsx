import { useEffect, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

type Role = "admin" | "manager" | "resident" | "kiosk" | "guest";
export type NavItemDef = { to: string; label: string; end?: boolean; roles: Role[] };
export type NavGroupDef = { label: string; items: NavItemDef[]; collapsible?: boolean };

export default function AppShell({
  children,
  navGroups,
  role,
  sessionRole,
  sessionUser,
  haUserCandidates,
  unknownHaUser,
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
  previewRole: Role | "";
  canPreviewRoles: boolean;
  onPreviewRoleChange: (role: Role | "") => void;
}) {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const canGoBack = location.pathname !== "/";

  useEffect(() => setOpen(false), [location.pathname]);

  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open]);

  return (
    <div className="app-shell min-h-screen overflow-x-hidden bg-[radial-gradient(circle_at_top_left,rgba(14,165,233,0.12),transparent_28rem),#07111f] text-slate-100">
      <header className="compact-header sticky top-0 z-40 border-b border-slate-800/80 bg-slate-950/90 px-3 py-2 backdrop-blur xl:hidden">
        <div className="flex min-h-12 items-center justify-between gap-3">
          {canGoBack && (
            <button
              className="flex h-11 w-11 items-center justify-center rounded-xl border border-slate-700 bg-slate-900 text-slate-100 focus:outline-none focus:ring-2 focus:ring-sky-300"
              onClick={() => navigate(-1)}
              aria-label="Go back"
            >
              <span className="text-2xl leading-none">&lsaquo;</span>
            </button>
          )}
          <button
            className="flex h-11 w-11 items-center justify-center rounded-xl border border-slate-700 bg-slate-900 text-slate-100 focus:outline-none focus:ring-2 focus:ring-sky-300"
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
            <div className="truncate text-sm font-bold text-sky-300">TPG HomeAI</div>
            <div className="truncate text-xs text-slate-500">{sessionUser?.name || "House"} · {roleLabel(role)}</div>
          </div>
          <div className="rounded-full border border-sky-400/30 bg-sky-400/10 px-2.5 py-1 text-xs text-sky-200">
            AI
          </div>
        </div>
      </header>

      <div className="flex min-h-screen min-w-0">
        <aside className="wide-sidebar hidden w-[17.5rem] shrink-0 border-r border-slate-800/80 bg-slate-950/70 p-4 backdrop-blur xl:block">
          <ShellNav
            navGroups={navGroups}
            role={role}
            sessionRole={sessionRole}
            sessionUser={sessionUser}
            haUserCandidates={haUserCandidates}
            unknownHaUser={unknownHaUser}
            previewRole={previewRole}
            canPreviewRoles={canPreviewRoles}
            onPreviewRoleChange={onPreviewRoleChange}
          />
        </aside>

        {open && (
          <div className="fixed inset-0 z-50 xl:hidden">
            <button
              className="absolute inset-0 bg-black/60"
              onClick={() => setOpen(false)}
              aria-label="Close navigation"
            />
            <aside className="relative h-full w-[min(22rem,88vw)] overflow-y-auto border-r border-slate-800 bg-slate-950 p-4 shadow-2xl">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <div className="text-lg font-bold text-sky-300">TPG HomeAI</div>
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
                previewRole={previewRole}
                canPreviewRoles={canPreviewRoles}
                onPreviewRoleChange={onPreviewRoleChange}
              />
            </aside>
          </div>
        )}

        <main className="min-w-0 flex-1 overflow-x-hidden">
          <div className="mx-auto w-full max-w-[96rem] px-3 py-4 sm:px-5 lg:px-6 xl:py-6">
            {canGoBack && (
              <button
                className="mb-4 hidden min-h-11 rounded-xl border border-slate-700 bg-slate-900/70 px-4 py-2 text-sm font-semibold text-slate-100 transition hover:border-sky-400/50 hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-sky-300/70 xl:inline-flex"
                onClick={() => navigate(-1)}
              >
                Back
              </button>
            )}
            {children}
          </div>
        </main>
      </div>
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
  previewRole,
  canPreviewRoles,
  onPreviewRoleChange,
}: {
  navGroups: NavGroupDef[];
  role: Role;
  sessionRole: Role;
  sessionUser: any;
  haUserCandidates: string[];
  unknownHaUser: string;
  previewRole: Role | "";
  canPreviewRoles: boolean;
  onPreviewRoleChange: (role: Role | "") => void;
}) {
  const location = useLocation();
  return (
    <div className="flex min-h-full flex-col">
      <div className="mb-6 hidden xl:block">
        <div className="text-xl font-bold text-sky-300">TPG HomeAI</div>
        <div className="text-xs text-slate-500">Orchestrator</div>
      </div>

      {sessionUser && (
        <div className="mb-5 rounded-2xl border border-slate-800 bg-slate-900/50 p-3">
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Signed in</div>
          <div className="truncate text-sm font-semibold text-slate-100">{sessionUser.name}</div>
          <div className="text-xs text-slate-500">{roleLabel(sessionRole)}</div>
          {haUserCandidates.length > 0 && (
            <div className="mt-2 rounded-lg border border-slate-800 bg-slate-950/40 px-2 py-1 text-[11px] text-slate-400">
              HA login: {haUserCandidates.join(", ")}
            </div>
          )}
          {unknownHaUser && (
            <div className="mt-2 rounded-lg border border-amber-400/30 bg-amber-400/10 px-2 py-1 text-[11px] text-amber-200">
              Add this HA username as an alias to the right TPG user.
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
        </div>
      )}

      <nav className="flex flex-col gap-5">
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
                    `min-h-11 rounded-xl px-3 py-2.5 text-sm font-medium transition focus:outline-none focus:ring-2 focus:ring-sky-300/70 ${
                      isActive
                        ? "border border-sky-400/30 bg-sky-400/14 text-sky-100"
                        : "text-slate-300 hover:bg-slate-800/80 hover:text-white"
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
        Native-feeling Home Assistant panel. HA remains the device backend.
      </div>
    </div>
  );
}

function roleLabel(role: Role) {
  if (role === "admin") return "Owner";
  if (role === "kiosk") return "Kiosk / Shared";
  return role.charAt(0).toUpperCase() + role.slice(1);
}
