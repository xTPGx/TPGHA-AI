import { useEffect, useMemo, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { api } from "./api";
import { homeAssistantSessionHints, startHomeAssistantUserBridge } from "./haAuth";
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
import DashboardBuilder from "./pages/DashboardBuilder";
import Setup from "./pages/Setup";
import IdentityDebug from "./pages/IdentityDebug";
import HouseKnowledge from "./pages/HouseKnowledge";
import HouseBrain from "./pages/HouseBrain";
import OwnerConsole from "./pages/OwnerConsole";

type Role = "admin" | "manager" | "resident" | "kiosk" | "guest";

const navGroups: NavGroupDef[] = [
  {
    label: "Main",
    items: [
      { to: "/chat", label: "Chat", roles: ["admin", "manager", "resident", "kiosk", "guest"] },
      { to: "/home", label: "House", roles: ["admin", "manager", "resident", "kiosk"] },
    ],
  },
  {
    label: "Personal",
    items: [
      { to: "/music", label: "Music", roles: ["admin", "manager", "resident", "kiosk"] },
      { to: "/assistants", label: "My Assistant", roles: ["admin", "manager", "resident"] },
      { to: "/memory-center", label: "Memory", roles: ["admin", "manager", "resident"] },
    ],
  },
  {
    label: "Owner Console",
    collapsible: true,
    items: [
      { to: "/owner", label: "Overview", roles: ["admin", "manager"] },
      { to: "/dashboard", label: "System Status", roles: ["admin", "manager"] },
      { to: "/jarvis", label: "Brain", roles: ["admin", "manager"] },
      { to: "/suggestions", label: "Suggestions", roles: ["admin", "manager"] },
      { to: "/dashboard-builder", label: "Dashboard Builder", roles: ["admin", "manager"] },
      { to: "/house-knowledge", label: "House Knowledge", roles: ["admin", "manager"] },
      { to: "/setup", label: "Setup", roles: ["admin", "manager"] },
      { to: "/discovery", label: "Discovery", roles: ["admin", "manager"] },
      { to: "/rooms", label: "Rooms", roles: ["admin", "manager"] },
      { to: "/users", label: "Users", roles: ["admin"] },
      { to: "/permissions", label: "Permissions", roles: ["admin"] },
      { to: "/entities", label: "Entities", roles: ["admin"] },
      { to: "/profiles", label: "Device Profiles", roles: ["admin"] },
      { to: "/ha", label: "HA Integration", roles: ["admin"] },
      { to: "/tester", label: "Command Tester", roles: ["admin"] },
      { to: "/capabilities", label: "Capability Map", roles: ["admin"] },
      { to: "/identity-debug", label: "Identity Debug", roles: ["admin", "manager"] },
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
    api.uiSession(homeAssistantSessionHints()).then((result) => {
      setSession(result);
    }).catch(() => setSession({ role: "guest", users: [] }));
    return startHomeAssistantUserBridge((user) => {
      api.uiSession({ accessToken: homeAssistantSessionHints().accessToken, clientUser: user })
        .then((result) => setSession(result))
        .catch(() => {
          /* keep current session */
        });
    });
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
    paths.add("/identity-debug");
    return paths;
  }, [role]);

  const canAccess = (path: string) => accessiblePaths.has(path);
  const fallbackPath = canAccess("/chat") ? "/chat" : "/home";
  return (
    <AppShell
      navGroups={navGroups}
      role={role}
      sessionRole={sessionRole}
      sessionUser={sessionUser}
      haUserCandidates={session?.ha_user_candidates || []}
      unknownHaUser={session?.unknown_ha_user || ""}
      identityWarning={session?.identity_warning || ""}
      previewRole={previewRole}
      canPreviewRoles={canPreviewRoles}
      onPreviewRoleChange={setPreviewRole}
    >
      <Routes>
          <Route path="/" element={<Navigate to={fallbackPath} replace />} />
          <Route path="/chat" element={canAccess("/chat") ? <Chat /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/home" element={canAccess("/home") ? <HouseBrain /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/notebook" element={<Navigate to="/chat" replace />} />
          <Route path="/owner" element={canAccess("/owner") ? <OwnerConsole /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/dashboard" element={canAccess("/dashboard") ? <Dashboard /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/jarvis" element={canAccess("/jarvis") ? <Brain /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/setup" element={canAccess("/setup") ? <Setup /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/house-brain" element={<Navigate to="/home" replace />} />
          <Route path="/profiles" element={canAccess("/profiles") ? <DeviceProfiles /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/memory-center" element={canAccess("/memory-center") ? <MemoryCenter /> : <Navigate to={fallbackPath} replace />} />
          <Route path="/house-knowledge" element={canAccess("/house-knowledge") ? <HouseKnowledge /> : <Navigate to={fallbackPath} replace />} />
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
          <Route path="/identity-debug" element={<IdentityDebug />} />
          <Route path="*" element={<Navigate to={fallbackPath} replace />} />
      </Routes>
    </AppShell>
  );
}
