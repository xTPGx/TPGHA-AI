import { Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";

type ConsoleItem = {
  title: string;
  description: string;
  to: string;
  tag: string;
};

const sections: { title: string; description: string; items: ConsoleItem[] }[] = [
  {
    title: "Run The House",
    description: "The owner-level surfaces used after installation.",
    items: [
      { title: "System Status", description: "Backend, Home Assistant, OpenAI, release status, and owner recommendations.", to: "/dashboard", tag: "ops" },
      { title: "Jarvis Brain", description: "Completion, live acceptance, role proof, release gates, and readiness layers.", to: "/jarvis", tag: "brain" },
      { title: "Suggestions", description: "Review and approve proactive automations, repairs, and device learning.", to: "/suggestions", tag: "approve" },
      { title: "Dashboard Builder", description: "Draft Home Assistant dashboards, tablet views, room panels, and Browser Mod routes.", to: "/dashboard-builder", tag: "create" },
    ],
  },
  {
    title: "Configure Intelligence",
    description: "Identity, memory, rooms, voice, and house context.",
    items: [
      { title: "Assistants", description: "Edit assistant personality, voice, wake words, owner, music account, and source deployment.", to: "/assistants", tag: "profile" },
      { title: "Users", description: "Sync HA users, assign owner/resident/shared profiles, and inspect role policy.", to: "/users", tag: "access" },
      { title: "Memory", description: "Approve persistent memories and user/house preferences.", to: "/memory-center", tag: "memory" },
      { title: "House Knowledge", description: "Upload floor plans, photos, layout notes, and spatial context.", to: "/house-knowledge", tag: "spatial" },
      { title: "Rooms", description: "Map rooms, aliases, lights, fans, displays, speakers, cameras, locks, and climate.", to: "/rooms", tag: "rooms" },
      { title: "Music", description: "Map music accounts, speakers, Music Assistant, and playback defaults.", to: "/music", tag: "media" },
    ],
  },
  {
    title: "Install + Diagnose",
    description: "Used when deploying, testing, or fixing the system.",
    items: [
      { title: "Setup", description: "Guided blocker checklist, acceptance evidence, sidebar checks, and recovery runbook.", to: "/setup", tag: "setup" },
      { title: "Discovery", description: "Classify and approve Home Assistant entities.", to: "/discovery", tag: "map" },
      { title: "Entities", description: "Inspect live HA entities and availability.", to: "/entities", tag: "ha" },
      { title: "Device Profiles", description: "Review learned adapters, quirks, and repair strategies.", to: "/profiles", tag: "learn" },
      { title: "Permissions", description: "Configure guarded action permissions and security PIN behavior.", to: "/permissions", tag: "safety" },
      { title: "Command Tester", description: "Dry-run command routing, resolution, services, and policy outcomes.", to: "/tester", tag: "test" },
      { title: "Capability Map", description: "Service/domain control surface for supported Home Assistant capabilities.", to: "/capabilities", tag: "map" },
      { title: "HA Integration", description: "Custom integration status, services, sensors, and HA-native wiring.", to: "/ha", tag: "bridge" },
      { title: "Identity Debug", description: "Inspect active HA user detection and TPG profile matching.", to: "/identity-debug", tag: "debug" },
    ],
  },
];

export default function OwnerConsole() {
  return (
    <div className="page-stack">
      <PageHeader
        title="Owner Console"
        subtitle="Configuration, diagnostics, and production-readiness tools grouped away from the everyday Jarvis experience."
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <SummaryCard label="Everyday Mode" value="Chat + House" detail="Residents and panels stay in Jarvis surfaces." />
        <SummaryCard label="Admin Mode" value="Owner Console" detail="Setup, maps, release, and diagnostics live here." />
        <SummaryCard label="Rule" value="HA decides identity" detail="TPG HomeAI scopes UI by synced HA role/profile." />
      </div>

      <div className="space-y-6">
        {sections.map((section) => (
          <section key={section.title} className="card">
            <div className="mb-4">
              <div className="text-xl font-semibold text-slate-100">{section.title}</div>
              <div className="mt-1 text-sm text-slate-400">{section.description}</div>
            </div>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              {section.items.map((item) => (
                <Link
                  key={item.to}
                  to={item.to}
                  className="group min-h-[9rem] rounded-2xl border border-white/10 bg-black/20 p-4 transition hover:-translate-y-0.5 hover:border-white/25 hover:bg-white/[0.06] focus:outline-none focus:ring-2 focus:ring-white/30"
                >
                  <div className="mb-3 inline-flex rounded-full border border-white/10 bg-white/[0.05] px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400 group-hover:text-slate-200">
                    {item.tag}
                  </div>
                  <div className="text-base font-semibold text-slate-100">{item.title}</div>
                  <div className="mt-2 text-sm leading-relaxed text-slate-400">{item.description}</div>
                </Link>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function SummaryCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="card">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-100">{value}</div>
      <div className="mt-2 text-sm leading-relaxed text-slate-400">{detail}</div>
    </div>
  );
}
