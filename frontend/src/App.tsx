import { NavLink, Route, Routes, useLocation } from "react-router-dom";
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
import VoiceSources from "./pages/VoiceSources";
import VoiceSettings from "./pages/VoiceSettings";
import HouseBrain from "./pages/HouseBrain";

type NavItem = { to: string; label: string; end?: boolean };

const navGroups: Array<{ label: string; items: NavItem[]; collapsible?: boolean }> = [
  {
    label: "Operate",
    items: [
      { to: "/", label: "Dashboard", end: true },
      { to: "/chat", label: "Chat" },
      { to: "/jarvis", label: "Brain" },
      { to: "/suggestions", label: "Suggestions" },
    ],
  },
  {
    label: "Configure",
    items: [
      { to: "/dashboard-builder", label: "Dashboard Builder" },
      { to: "/discovery", label: "Discovery" },
      { to: "/rooms", label: "Rooms" },
      { to: "/assistants", label: "Assistants" },
      { to: "/voice-settings", label: "Voice Settings" },
      { to: "/voice-sources", label: "Voice Sources" },
      { to: "/users", label: "Users" },
      { to: "/music", label: "Music" },
    ],
  },
  {
    label: "Advanced",
    collapsible: true,
    items: [
      { to: "/ha", label: "HA Integration" },
      { to: "/profiles", label: "Device Profiles" },
      { to: "/memory-center", label: "Memory" },
      { to: "/tester", label: "Command Tester" },
      { to: "/entities", label: "Entities" },
      { to: "/capabilities", label: "Capability Map" },
      { to: "/permissions", label: "Permissions" },
    ],
  },
];

export default function App() {
  const location = useLocation();
  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    `rounded-lg px-3 py-2 text-sm transition ${
      isActive
        ? "bg-brand-dark/30 text-brand"
        : "text-slate-300 hover:bg-slate-800"
    }`;

  const renderItems = (items: NavItem[]) =>
    items.map((n) => (
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
        <nav className="flex flex-col gap-4">
          {navGroups.map((group) => {
            const active = group.items.some((item) =>
              item.end ? location.pathname === item.to : location.pathname.startsWith(item.to),
            );
            if (group.collapsible) {
              return (
                <details key={group.label} className="group" open={active}>
                  <summary className="cursor-pointer list-none px-3 text-[10px] font-semibold uppercase tracking-wide text-slate-500 group-open:text-slate-400">
                    {group.label}
                  </summary>
                  <div className="mt-2 flex flex-col gap-1">{renderItems(group.items)}</div>
                </details>
              );
            }
            return (
              <div key={group.label}>
                <div className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                  {group.label}
                </div>
                <div className="flex flex-col gap-1">{renderItems(group.items)}</div>
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
          <Route path="/" element={<Dashboard />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/jarvis" element={<Brain />} />
          <Route path="/house-brain" element={<HouseBrain />} />
          <Route path="/profiles" element={<DeviceProfiles />} />
          <Route path="/memory-center" element={<MemoryCenter />} />
          <Route path="/dashboard-builder" element={<DashboardBuilder />} />
          <Route path="/voice-settings" element={<VoiceSettings />} />
          <Route path="/voice-sources" element={<VoiceSources />} />
          <Route path="/suggestions" element={<Suggestions />} />
          <Route path="/ha" element={<HAStatus />} />
          <Route path="/discovery" element={<Discovery />} />
          <Route path="/tester" element={<CommandTester />} />
          <Route path="/entities" element={<Entities />} />
          <Route path="/rooms" element={<Rooms />} />
          <Route path="/assistants" element={<Assistants />} />
          <Route path="/users" element={<Users />} />
          <Route path="/music" element={<Music />} />
          <Route path="/capabilities" element={<CapabilityMap />} />
          <Route path="/permissions" element={<Permissions />} />
        </Routes>
      </main>
    </div>
  );
}
