import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

function Pill({ children, tone = "slate" }: { children: ReactNode; tone?: "slate" | "green" | "amber" | "rose" | "cyan" }) {
  const map = {
    slate: "border-slate-600 bg-slate-800 text-slate-200",
    green: "border-emerald-500/40 bg-emerald-500/10 text-emerald-200",
    amber: "border-amber-500/40 bg-amber-500/10 text-amber-200",
    rose: "border-rose-500/40 bg-rose-500/10 text-rose-200",
    cyan: "border-cyan-500/40 bg-cyan-500/10 text-cyan-200",
  };
  return <span className={`rounded-full border px-2 py-1 text-xs ${map[tone]}`}>{children}</span>;
}

export default function HouseBrain() {
  const [state, setState] = useState<any>(null);
  const [assistants, setAssistants] = useState<any>(null);
  const [tablets, setTablets] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setBusy(true);
    setError(null);
    try {
      const [house, assistantData, tabletData] = await Promise.all([
        api.houseState(),
        api.assistantIntelligence(),
        api.tabletProfiles(),
      ]);
      setState(house);
      setAssistants(assistantData);
      setTablets(tabletData);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const attention = state?.attention || {};
  return (
    <div>
      <PageHeader
        title="House Brain"
        subtitle="Situational awareness, assistant identity, tablet profiles, and proactive next moves"
        actions={<button className="btn-ghost" onClick={() => void load()} disabled={busy}>Refresh</button>}
      />

      {error && <div className="mb-4 rounded border border-rose-500/40 bg-rose-500/10 p-3 text-rose-200">{error}</div>}

      <div className="mb-5 grid gap-4 md:grid-cols-4">
        <div className="card">
          <div className="text-xs uppercase text-slate-400">Status</div>
          <div className="mt-2 text-2xl font-semibold">{state?.status || "loading"}</div>
        </div>
        <div className="card">
          <div className="text-xs uppercase text-slate-400">Modes</div>
          <div className="mt-2 flex flex-wrap gap-2">{(state?.modes || []).map((m: string) => <Pill key={m} tone="cyan">{m}</Pill>)}</div>
        </div>
        <div className="card">
          <div className="text-xs uppercase text-slate-400">Presence</div>
          <div className="mt-2 text-2xl font-semibold">{state?.presence?.away ? "away" : "home"}</div>
          <div className="text-sm text-slate-400">{(state?.presence?.home || []).join(", ") || "no one tracked home"}</div>
        </div>
        <div className="card">
          <div className="text-xs uppercase text-slate-400">Recommendations</div>
          <div className="mt-2 text-2xl font-semibold">{state?.recommendations?.length || 0}</div>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <section className="card">
          <h2 className="mb-3 text-xl font-semibold">Attention</h2>
          {[
            ["Security", attention.security || [], "rose"],
            ["Energy", attention.energy || [], "amber"],
            ["Media", attention.media || [], "cyan"],
            ["Maintenance", attention.maintenance || [], "slate"],
          ].map(([label, items, tone]: any) => (
            <div key={label} className="mb-4">
              <div className="mb-2 flex items-center gap-2">
                <span className="font-semibold">{label}</span>
                <Pill tone={tone}>{items.length}</Pill>
              </div>
              <div className="space-y-2">
                {items.slice(0, 5).map((item: any) => (
                  <div key={`${label}-${item.entity_id}`} className="rounded border border-slate-700 bg-slate-950/40 p-3">
                    <div className="font-semibold">{item.name}</div>
                    <div className="text-sm text-slate-400">{item.message}</div>
                    <div className="mt-1 text-xs text-brand">{item.entity_id}</div>
                  </div>
                ))}
                {items.length === 0 && <div className="text-sm text-slate-500">Clear</div>}
              </div>
            </div>
          ))}
        </section>

        <section className="card">
          <h2 className="mb-3 text-xl font-semibold">Rooms</h2>
          <div className="space-y-2">
            {(state?.rooms || []).map((room: any) => (
              <div key={room.id} className="rounded border border-slate-700 bg-slate-950/40 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="font-semibold">{room.name}</div>
                    <div className="text-sm text-slate-400">{room.available_count}/{room.entity_count} available</div>
                  </div>
                  <div className="flex gap-2">
                    {room.has_voice_source && <Pill tone="green">voice</Pill>}
                    {room.active_entities.length > 0 && <Pill tone="cyan">active</Pill>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="card">
          <h2 className="mb-3 text-xl font-semibold">Assistants</h2>
          <div className="space-y-3">
            {(assistants?.assistants || []).map((assistant: any) => (
              <div key={assistant.id} className="rounded border border-slate-700 bg-slate-950/40 p-3">
                <div className="flex items-center justify-between">
                  <div className="text-lg font-semibold">{assistant.name}</div>
                  <Pill tone="green">{assistant.voice?.voice || assistant.voice}</Pill>
                </div>
                <div className="mt-1 text-sm text-slate-400">{assistant.owner_name} · {assistant.tone}</div>
                <div className="mt-2 text-sm text-slate-300">{assistant.personality}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="card">
          <h2 className="mb-3 text-xl font-semibold">Tablets + Panels</h2>
          <div className="space-y-3">
            {(tablets?.tablet_profiles || []).map((tablet: any) => (
              <div key={tablet.id} className="rounded border border-slate-700 bg-slate-950/40 p-3">
                <div className="font-semibold">{tablet.name}</div>
                <div className="text-sm text-slate-400">{tablet.type} · {tablet.room || "unassigned"}</div>
                <div className="mt-1 text-xs text-brand">{tablet.dashboard_path}</div>
              </div>
            ))}
            {(tablets?.tablet_profiles || []).length === 0 && <div className="text-sm text-slate-500">No display profiles configured yet.</div>}
          </div>
        </section>
      </div>
    </div>
  );
}
