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

export default function HouseBrain({ embedded = false }: { embedded?: boolean }) {
  const [state, setState] = useState<any>(null);
  const [assistants, setAssistants] = useState<any>(null);
  const [tablets, setTablets] = useState<any>(null);
  const [modes, setModes] = useState<any>(null);
  const [deployment, setDeployment] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setBusy(true);
    setError(null);
    try {
      const [house, assistantData, tabletData, modeData, deploymentData] = await Promise.all([
        api.houseState(),
        api.assistantIntelligence(),
        api.tabletProfiles(),
        api.modeBrain(),
        api.voiceDeployment(),
      ]);
      setState(house);
      setAssistants(assistantData);
      setTablets(tabletData);
      setModes(modeData);
      setDeployment(deploymentData);
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
      {!embedded && (
        <PageHeader
          title="House Brain"
          subtitle="Situational awareness, assistant identity, tablet profiles, and proactive next moves"
          actions={<button className="btn-ghost" onClick={() => void load()} disabled={busy}>Refresh</button>}
        />
      )}

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

      <div className="mb-5 grid gap-5 xl:grid-cols-2">
        <section className="card">
          <div className="mb-3 flex items-start justify-between gap-3">
            <div>
              <h2 className="text-xl font-semibold">Mode Brain</h2>
              <div className="text-sm text-slate-400">Active behavior profile, reply route, and confirmation posture</div>
            </div>
            <Pill tone={modes?.quiet_hours_active ? "amber" : "green"}>
              {modes?.quiet_hours_active ? "quiet hours" : "normal hours"}
            </Pill>
          </div>
          <div className="mb-3 rounded border border-slate-700 bg-slate-950/40 p-3">
            <div className="text-xs uppercase text-slate-400">Primary mode</div>
            <div className="mt-1 text-lg font-semibold">{modes?.primary_mode?.name || "Loading"}</div>
            <div className="mt-1 text-sm text-slate-400">{modes?.primary_mode?.description || ""}</div>
          </div>
          <div className="mb-3 grid gap-3 md:grid-cols-3">
            <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
              <div className="text-xs uppercase text-slate-400">Reply</div>
              <div className="mt-1 font-semibold">{modes?.policy?.reply_mode || "auto"}</div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
              <div className="text-xs uppercase text-slate-400">Safe auto-run</div>
              <div className="mt-1 font-semibold">{modes?.policy?.safe_actions_auto_execute ? "enabled" : "paused"}</div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
              <div className="text-xs uppercase text-slate-400">Confirm gates</div>
              <div className="mt-1 font-semibold">{modes?.policy?.confirmation_keywords?.length || 0}</div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {(modes?.active_modes || []).map((mode: any) => (
              <Pill key={mode.id} tone={mode.id === "security" ? "rose" : mode.quiet_hours ? "amber" : "cyan"}>
                {mode.name}
              </Pill>
            ))}
          </div>
          <div className="mt-4 space-y-2">
            {(modes?.recommendations || []).slice(0, 3).map((rec: any) => (
              <div key={rec.title} className="rounded border border-slate-700 bg-slate-950/40 p-3">
                <div className="font-semibold">{rec.title}</div>
                <div className="text-sm text-slate-400">{rec.reason}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="card">
          <div className="mb-3 flex items-start justify-between gap-3">
            <div>
              <h2 className="text-xl font-semibold">Wake Word Deployment</h2>
              <div className="text-sm text-slate-400">Room-aware source mapping for satellites, panels, and microphones</div>
            </div>
            <Pill tone={(deployment?.counts?.rooms_without_voice_source || 0) ? "amber" : "green"}>
              {deployment?.counts?.ready || 0}/{deployment?.counts?.total || 0} ready
            </Pill>
          </div>
          <div className="mb-3 grid gap-3 md:grid-cols-4">
            <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
              <div className="text-xs uppercase text-slate-400">Sources</div>
              <div className="mt-1 text-lg font-semibold">{deployment?.counts?.total || 0}</div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
              <div className="text-xs uppercase text-slate-400">Trusted</div>
              <div className="mt-1 text-lg font-semibold">{deployment?.counts?.trusted || 0}</div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
              <div className="text-xs uppercase text-slate-400">Missing IDs</div>
              <div className="mt-1 text-lg font-semibold">{deployment?.counts?.missing_source_identity || 0}</div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
              <div className="text-xs uppercase text-slate-400">Rooms left</div>
              <div className="mt-1 text-lg font-semibold">{deployment?.counts?.rooms_without_voice_source || 0}</div>
            </div>
          </div>
          <div className="space-y-2">
            {(deployment?.sources || []).slice(0, 5).map((source: any) => (
              <div key={source.id} className="rounded border border-slate-700 bg-slate-950/40 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="font-semibold">{source.name}</div>
                    <div className="text-sm text-slate-400">{source.room} · {source.trust_level} · {source.default_reply}</div>
                  </div>
                  <Pill tone={source.setup_status === "ready" ? "green" : "amber"}>{source.setup_status}</Pill>
                </div>
                {source.missing?.length > 0 && <div className="mt-2 text-sm text-amber-200">{source.next_step}</div>}
              </div>
            ))}
          </div>
        </section>
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
