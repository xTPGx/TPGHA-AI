import { useEffect, useMemo, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { api } from "./api";
import AppShell, { NavGroupDef } from "./components/AppShell";
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

type Role = "admin" | "manager" | "resident" | "kiosk" | "guest";

const navGroups: NavGroupDef[] = [
  {
    label: "Main",
    items: [
      { to: "/chat", label: "Chat", roles: ["admin", "manager", "resident", "kiosk", "guest"] },
      { to: "/", label: "Dashboard", end: true, roles: ["admin", "manager", "resident", "kiosk"] },
    ],
  },
  {
    label: "Home",
    items: [
      { to: "/discovery", label: "Discovery", roles: ["admin", "manager"] },
      { to: "/entities", label: "Entities", roles: ["admin"] },
      { to: "/rooms", label: "Rooms", roles: ["admin", "manager"] },
      { to: "/music", label: "Music", roles: ["admin", "manager"] },
    ],
  },
  {
    label: "AI",
    items: [
      { to: "/notebook", label: "Notebook", roles: ["admin", "manager", "resident"] },
      { to: "/jarvis", label: "Brain", roles: ["admin", "manager", "resident"] },
      { to: "/assistants", label: "Assistants", roles: ["admin"] },
      { to: "/users", label: "Users", roles: ["admin"] },
      { to: "/permissions", label: "Permissions", roles: ["admin"] },
      { to: "/suggestions", label: "Suggestions", roles: ["admin", "manager"] },
    ],
  },
  {
    label: "Developer",
    collapsible: true,
    items: [
      { to: "/setup", label: "Setup", roles: ["admin", "manager"] },
      { to: "/dashboard-builder", label: "Dashboard Builder", roles: ["admin", "manager"] },
      { to: "/ha", label: "HA Integration", roles: ["admin"] },
      { to: "/profiles", label: "Device Profiles", roles: ["admin"] },
      { to: "/memory-center", label: "Memory", roles: ["admin"] },
      { to: "/tester", label: "Command Tester", roles: ["admin"] },
      { to: "/capabilities", label: "Capability Map", roles: ["admin"] },
    ],
  },
];

export default function App() {
  const [session, setSession] = useState<any>(null);
  const [previewRole, setPreviewRole] = useState<Role | "">("");
  const users = session?.users || [];
  const sessionUser = session?.detected_user || users[0];
  const sessionRole: Role = session?.role || sessionUser?.role || "guest";
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
  return (
    <AppShell
      navGroups={navGroups}
      role={role}
      sessionRole={sessionRole}
      sessionUser={sessionUser}
      haUserCandidates={session?.ha_user_candidates || []}
      unknownHaUser={session?.unknown_ha_user || ""}
      previewRole={previewRole}
      canPreviewRoles={canPreviewRoles}
      onPreviewRoleChange={setPreviewRole}
    >
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
    </AppShell>
  );
}
