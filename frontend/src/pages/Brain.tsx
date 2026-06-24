import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";
import HouseBrain from "./HouseBrain";

const STATUS_COLORS: Record<string, string> = {
  ready: "text-emerald-300",
  partial: "text-amber-300",
  degraded: "text-rose-300",
  building: "text-sky-300",
};

export default function Brain() {
  const [tab, setTab] = useState<"jarvis" | "home">("jarvis");
  const [brain, setBrain] = useState<any>(null);
  const [providers, setProviders] = useState<any>(null);
  const [completion, setCompletion] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const [brainResult, providerResult, completionResult] = await Promise.all([
        api.brainLayers(),
        api.aiProviders(),
        api.completionStatus(),
      ]);
      setBrain(brainResult);
      setProviders(providerResult);
      setCompletion(completionResult);
      setError(null);
    } catch (e: any) {
      setError(e.message || String(e));
    }
  };

  useEffect(() => {
    void load();
  }, []);

  return (
    <div>
      <PageHeader
        title="Brain"
        subtitle="Jarvis readiness and live home intelligence"
        actions={<button className="btn-ghost" onClick={() => void load()}>Refresh</button>}
      />

      <div className="mb-5 flex flex-wrap gap-2 border-b border-slate-800 pb-3">
        <button className={tab === "jarvis" ? "btn" : "btn-ghost"} onClick={() => setTab("jarvis")}>Jarvis</button>
        <button className={tab === "home" ? "btn" : "btn-ghost"} onClick={() => setTab("home")}>Home</button>
      </div>

      {tab === "home" ? (
        <HouseBrain embedded />
      ) : (
        <>

      {error && (
        <div className="mb-4 rounded border border-rose-500/40 bg-rose-500/10 p-3 text-rose-200">
          {error}
        </div>
      )}

      <div className="mb-4 grid grid-cols-1 gap-4 md:grid-cols-4">
        <Stat label="Overall" value={brain ? `${brain.overall_score}%` : "—"} />
        <Stat label="Status" value={brain?.status || "—"} />
        <Stat label="Controllable" value={brain?.summary?.controllable_entities ?? "—"} />
        <Stat label="Pending" value={brain?.summary?.pending_approvals ?? "—"} />
      </div>

      {completion && (
        <div className="card mb-4">
          <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-lg font-semibold text-slate-100">Jarvis v1 Completion</div>
              <div className="text-sm text-slate-400">The stop line for feature work versus live-house deployment</div>
            </div>
            <div className="flex flex-wrap gap-2">
              <span className={`badge ${completion.software_ship_complete ? "bg-emerald-500/10 text-emerald-200" : "bg-amber-500/10 text-amber-200"}`}>
                software: {completion.software_ship_complete ? "ready" : "building"}
              </span>
              <span className={`badge ${completion.house_deployment_complete ? "bg-emerald-500/10 text-emerald-200" : "bg-amber-500/10 text-amber-200"}`}>
                house: {completion.house_deployment_complete ? "complete" : "needs setup"}
              </span>
            </div>
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
            <MiniStat label="Completion" value={`${completion.overall_score}%`} />
            <MiniStat label="Required Gates" value={`${completion.required_complete}/${completion.required_total}`} />
            <MiniStat label="Optional Gates" value={`${completion.optional_complete}/${completion.optional_total}`} />
            <MiniStat label="Blockers" value={completion.blockers?.length || 0} />
          </div>
          {completion.blockers?.length > 0 && (
            <div className="mt-3 rounded border border-amber-500/30 bg-amber-500/10 p-3">
              <div className="mb-2 text-sm font-semibold text-amber-200">Live-house blockers</div>
              <div className="space-y-1 text-sm text-amber-100">
                {completion.blockers.slice(0, 5).map((blocker: string) => (
                  <div key={blocker}>{blocker}</div>
                ))}
              </div>
            </div>
          )}
          <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-3">
            <StopLine label="Software stop" text={completion.complete_spot?.software} />
            <StopLine label="Deployment stop" text={completion.complete_spot?.deployment} />
            <StopLine label="After complete" text={completion.complete_spot?.after_complete} />
          </div>
        </div>
      )}

      {providers && (
        <div className="card mb-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-lg font-semibold text-slate-100">AI Router</div>
              <div className="text-sm text-slate-400">Cloud, local, and deterministic fallback readiness</div>
            </div>
            <span className="badge bg-cyan-500/10 text-cyan-200">
              active: {providers.active || providers.active_provider || providers.mode || "fallback"}
            </span>
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {Object.entries(providers.providers || {}).map(([id, provider]: [string, any]) => (
              <div key={id} className="rounded border border-slate-800 bg-slate-950/30 p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="font-semibold text-slate-100">{id}</div>
                  <span className={`h-2.5 w-2.5 rounded-full ${provider.available ? "bg-emerald-400" : provider.configured ? "bg-amber-400" : "bg-slate-600"}`} />
                </div>
                <div className="mt-1 text-xs text-slate-400">{provider.role || "provider"}</div>
                <div className="mt-1 font-mono text-xs text-slate-500">{provider.model || provider.base_url || "not configured"}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {(brain?.layers || []).map((layer: any) => (
          <div key={layer.id} className="card">
            <div className="mb-3 flex items-start justify-between gap-3">
              <div>
                <div className="text-lg font-semibold text-slate-100">{layer.title}</div>
                <div className={`mt-1 text-xs font-semibold uppercase ${STATUS_COLORS[layer.status] || "text-slate-300"}`}>
                  {layer.status}
                </div>
              </div>
              <div className="rounded-lg border border-slate-700 px-3 py-1 text-sm text-slate-200">
                {layer.score}%
              </div>
            </div>

            <div className="space-y-2 text-sm text-slate-300">
              {(layer.evidence || []).map((item: string) => (
                <div key={item} className="rounded border border-slate-800 bg-slate-950/30 px-3 py-2">
                  {item}
                </div>
              ))}
            </div>

            {layer.next && (
              <div className="mt-3 border-t border-slate-800 pt-3 text-sm text-slate-400">
                <span className="text-slate-500">Next:</span> {layer.next}
              </div>
            )}
          </div>
        ))}
      </div>

      {!brain && !error && <div className="card text-slate-400">Loading brain map…</div>}
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: any }) {
  return (
    <div className="card">
      <div className="mb-1 text-xs text-slate-400">{label}</div>
      <div className="text-2xl font-semibold text-slate-100">{value}</div>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: any }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-950/30 p-3">
      <div className="mb-1 text-xs text-slate-400">{label}</div>
      <div className="text-xl font-semibold text-slate-100">{value}</div>
    </div>
  );
}

function StopLine({ label, text }: { label: string; text: string }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-950/30 p-3">
      <div className="mb-1 text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="text-sm text-slate-300">{text}</div>
    </div>
  );
}
