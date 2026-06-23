import { NavLink, Route, Routes } from "react-router-dom";
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

const nav = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/chat", label: "Chat" },
  { to: "/jarvis", label: "Jarvis Brain" },
  { to: "/house-brain", label: "House Brain" },
  { to: "/profiles", label: "Device Profiles" },
  { to: "/memory-center", label: "Memory" },
  { to: "/dashboard-builder", label: "Dashboard Builder" },
  { to: "/voice-settings", label: "Voice Settings" },
  { to: "/voice-sources", label: "Voice Sources" },
  { to: "/suggestions", label: "Suggestions" },
  { to: "/ha", label: "HA Integration" },
  { to: "/discovery", label: "Discovery" },
  { to: "/tester", label: "Command Tester" },
  { to: "/entities", label: "Entities" },
  { to: "/rooms", label: "Rooms" },
  { to: "/assistants", label: "Assistants" },
  { to: "/users", label: "Users" },
  { to: "/music", label: "Music" },
  { to: "/capabilities", label: "Capability Map" },
  { to: "/permissions", label: "Permissions" },
];

export default function App() {
  return (
    <div className="flex min-h-screen bg-slate-900 text-slate-100">
      <aside className="w-60 shrink-0 border-r border-slate-800 bg-slate-950/60 p-4">
        <div className="mb-6">
          <div className="text-lg font-bold text-brand">TPG HomeAI</div>
          <div className="text-xs text-slate-400">Orchestrator</div>
        </div>
        <nav className="flex flex-col gap-1">
          {nav.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                `rounded-lg px-3 py-2 text-sm transition ${
                  isActive
                    ? "bg-brand-dark/30 text-brand"
                    : "text-slate-300 hover:bg-slate-800"
                }`
              }
            >
              {n.label}
            </NavLink>
          ))}
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
