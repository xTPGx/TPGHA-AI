import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

const STATUS_COLORS: Record<string, string> = {
  ready: "text-emerald-300",
  partial: "text-amber-300",
  degraded: "text-rose-300",
  building: "text-sky-300",
};

export default function Brain() {
  const [brain, setBrain] = useState<any>(null);
  const [providers, setProviders] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const [brainResult, providerResult] = await Promise.all([
        api.brainLayers(),
        api.aiProviders(),
      ]);
      setBrain(brainResult);
      setProviders(providerResult);
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
        title="Jarvis Brain"
        subtitle="Live readiness map for the house intelligence layers"
        actions={<button className="btn-ghost" onClick={() => void load()}>Refresh</button>}
      />

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
