import { useEffect, useMemo, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api";
import Dashboard from "./pages/Dashboard";
import Entities from "./pages/Entities";
import Rooms from "./pages/Rooms";
import Assistants from "./pages/Assistants";
import Users from "./pages/Users";
import Music from "./pages/Music";
import Permissions from "./pages/Permissions";
import CommandTester from "./pages/CommandTester";
import Discovery from "./pages/Discovery";
import HAStatus from "./pages/HAStatus";
import CapabilityMap from "./pages/CapabilityMap";
import Chat from "./pages/Chat";
import Suggestions from "./pages/Suggestions";
import Brain from "./pages/Brain";
import DeviceProfiles from "./pages/DeviceProfiles";
import MemoryCenter from "./pages/MemoryCenter";
import Notebook from "./pages/Notebook";
import DashboardBuilder from "./pages/DashboardBuilder";
import Setup from "./pages/Setup";

type Role = "admin" | "manager" | "resident" | "guest";
type NavItem = { to: string; label: string; end?: boolean; roles: Role[] };

const navGroups: Array<{ label: string; items: NavItem[]; collapsible?: boolean }> = [
  {
    label: "Operate",
    items: [
      { to: "/", label: "Dashboard", end: true, roles: ["admin", "manager", "resident"] },
      { to: "/chat", label: "Chat", roles: ["admin", "manager", "resident", "guest"] },
      { to: "/notebook", label: "Notebook", roles: ["admin", "manager", "resident"] },
      { to: "/jarvis", label: "Brain", roles: ["admin", "manager", "resident"] },
      { to: "/suggestions", label: "Suggestions", roles: ["admin", "manager"] },
    ],
  },
  {
    label: "Configure",
    items: [
      { to: "/setup", label: "Setup", roles: ["admin", "manager"] },
      { to: "/dashboard-builder", label: "Dashboard Builder", roles: ["admin", "manager"] },
      { to: "/discovery", label: "Discovery", roles: ["admin", "manager"] },
      { to: "/rooms", label: "Rooms", roles: ["admin", "manager"] },
      { to: "/assistants", label: "Assistants", roles: ["admin"] },
      { to: "/users", label: "Users", roles: ["admin"] },
      { to: "/music", label: "Music", roles: ["admin", "manager"] },
    ],
  },
  {
    label: "Advanced",
    collapsible: true,
    items: [
      { to: "/ha", label: "HA Integration", roles: ["admin"] },
      { to: "/profiles", label: "Device Profiles", roles: ["admin"] },
      { to: "/memory-center", label: "Memory", roles: ["admin"] },
      { to: "/tester", label: "Command Tester", roles: ["admin"] },
      { to: "/entities", label: "Entities", roles: ["admin"] },
      { to: "/capabilities", label: "Capability Map", roles: ["admin"] },
      { to: "/permissions", label: "Permissions", roles: ["admin"] },
    ],
  },
];

export default function App() {
  const location = useLocation();
  const [session, setSession] = useState<any>(null);
  const [previewRole, setPreviewRole] = useState<Role | "">("");
  const users = session?.users || [];
  const sessionUser = session?.detected_user || users[0];
  const sessionRole: Role = sessionUser?.role || session?.role || "guest";
  const role: Role = previewRole || sessionRole;
  const canPreviewRoles = sessionRole === "admin";

  useEffect(() => {
    api.uiSession().then((result) => {
      setSession(result);
    }).catch(() => setSession({ role: "guest", users: [] }));
  }, []);

  const accessiblePaths = useMemo(() => {
    const paths = new Set<string>();
    for (const group of navGroups) {
      for (const item of group.items) {
        if (item.roles.includes(role)) paths.add(item.to);
      }
    }
    paths.add("/house-brain");
    paths.add("/voice-settings");
    paths.add("/voice-sources");
    return paths;
  }, [role]);

  const canAccess = (path: string) => accessiblePaths.has(path);
  const fallbackPath = canAccess("/") ? "/" : "/chat";
  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    `rounded-lg px-3 py-2 text-sm transition ${
      isActive
        ? "bg-brand-dark/30 text-brand"
        : "text-slate-300 hover:bg-slate-800"
    }`;

  const renderItems = (items: NavItem[]) =>
    items.filter((n) => n.roles.includes(role)).map((n) => (
      <NavLink key={n.to} to={n.to} end={n.end} className={navLinkClass}>
        {n.label}
      </NavLink>
    ));

  return (
    <div className="flex min-h-screen bg-slate-900 text-slate-100">
      <aside className="w-60 shrink-0 border-r border-slate-800 bg-slate-950/60 p-4">
        <div className="mb-6">
          <div className="text-lg font-bold text-brand">TPG HomeAI</div>
          <div className="text-xs text-slate-400">Orchestrator</div>
        </div>
        {sessionUser && (
          <div className="mb-5 rounded-lg border border-slate-800 bg-slate-900/50 p-2">
            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-slate-500">
              Signed In
            </label>
            <div className="rounded-md bg-slate-950/70 px-2 py-1.5 text-sm text-slate-200">
              {sessionUser.name} · {sessionRole}
            </div>
            {canPreviewRoles && (
              <>
                <label className="mb-1 mt-3 block text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                  Preview Menu
                </label>
                <select
                  className="input py-1.5 text-sm"
                  value={previewRole}
                  onChange={(e) => setPreviewRole(e.target.value as Role | "")}
                >
                  <option value="">Full admin</option>
                  <option value="manager">Manager</option>
                  <option value="resident">Resident</option>
                  <option value="guest">Guest</option>
                </select>
              </>
            )}
          </div>
        )}
        <nav className="flex flex-col gap-4">
          {navGroups.map((group) => {
            const visible = group.items.filter((item) => item.roles.includes(role));
            if (!visible.length) return null;
            const active = visible.some((item) =>
              item.end ? location.pathname === item.to : location.pathname.startsWith(item.to),
            );
            if (group.collapsible) {
              return (
                <details key={group.label} className="group" open={active}>
                  <summary className="cursor-pointer list-none px-3 text-[10px] font-semibold uppercase tracking-wide text-slate-500 group-open:text-slate-400">
                    {group.label}
                  </summary>
                  <div className="mt-2 flex flex-col gap-1">{renderItems(visible)}</div>
                </details>
              );
            }
            return (
              <div key={group.label}>
                <div className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                  {group.label}
                </div>
                <div className="flex flex-col gap-1">{renderItems(visible)}</div>
              </div>
            );
          })}
        </nav>
        <div className="mt-8 text-[10px] leading-relaxed text-slate-500">
          Sits on top of Home Assistant. HA remains the device backend.
        </div>
      </aside>

      <main className="flex-1 overflow-auto p-6">
        <Routes>
          <Route path="/" element={canAccess("/") ? <Dashboard /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/chat" element={canAccess("/chat") ? <Chat /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/notebook" element={canAccess("/notebook") ? <Notebook /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/jarvis" element={canAccess("/jarvis") ? <Brain /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/setup" element={canAccess("/setup") ? <Setup /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/house-brain" element={<Navigate to="/jarvis" replace />} />
          <Route path="/profiles" element={canAccess("/profiles") ? <DeviceProfiles /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/memory-center" element={canAccess("/memory-center") ? <MemoryCenter /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/dashboard-builder" element={canAccess("/dashboard-builder") ? <DashboardBuilder /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/voice-settings" element={<Navigate to="/assistants" replace />} />
          <Route path="/voice-sources" element={<Navigate to="/assistants" replace />} />
          <Route path="/suggestions" element={canAccess("/suggestions") ? <Suggestions /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/ha" element={canAccess("/ha") ? <HAStatus /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/discovery" element={canAccess("/discovery") ? <Discovery /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/tester" element={canAccess("/tester") ? <CommandTester /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/entities" element={canAccess("/entities") ? <Entities /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/rooms" element={canAccess("/rooms") ? <Rooms /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/assistants" element={canAccess("/assistants") ? <Assistants /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/users" element={canAccess("/users") ? <Users /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/music" element={canAccess("/music") ? <Music /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/capabilities" element={canAccess("/capabilities") ? <CapabilityMap /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/permissions" element={canAccess("/permissions") ? <Permissions /> : <Navigate to={fallbackPath} replace />} />
          <Route path="*" element={<Navigate to={fallbackPath} replace />} />
        </Routes>
      </main>
    </div>
  );
}
