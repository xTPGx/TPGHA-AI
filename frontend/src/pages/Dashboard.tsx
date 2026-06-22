import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";
import StatusDot from "../components/StatusDot";

export default function Dashboard() {
  const [health, setHealth] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloading, setReloading] = useState(false);

  const load = () => {
    api
      .health()
      .then(setHealth)
      .catch((e) => setError(e.message));
  };

  useEffect(load, []);

  const reload = async () => {
    setReloading(true);
    try {
      await api.reloadConfig();
      load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setReloading(false);
    }
  };

  const ha = health?.home_assistant;

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle="System status for the HomeAI Orchestrator"
        actions={
          <button className="btn-ghost" onClick={reload} disabled={reloading}>
            {reloading ? "Reloading…" : "Reload config"}
          </button>
        }
      />

      {error && (
        <div className="card mb-4 border-rose-700/60 bg-rose-900/20 text-rose-200">
          Could not reach backend: {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="card">
          <div className="mb-2 text-sm text-slate-400">Backend</div>
          <StatusDot ok={!!health} label={health ? `Online (v${health.version})` : "Offline"} />
        </div>

        <div className="card">
          <div className="mb-2 text-sm text-slate-400">Home Assistant</div>
          <StatusDot
            ok={ha?.connected}
            label={ha?.connected ? "Connected" : ha?.configured ? "Not reachable" : "Not configured"}
          />
          {ha?.url && <div className="mt-2 break-all text-xs text-slate-500">{ha.url}</div>}
          {ha?.message && !ha?.connected && (
            <div className="mt-1 text-xs text-amber-300">{ha.message}</div>
          )}
        </div>

        <div className="card">
          <div className="mb-2 text-sm text-slate-400">OpenAI</div>
          <StatusDot
            ok={health?.openai_configured}
            label={
              health?.openai_configured
                ? `Configured (${health?.settings?.openai_model})`
                : "Fallback parser"
            }
          />
          <div className="mt-2 text-xs text-slate-500">Mode: {health?.openai_mode ?? "—"}</div>
        </div>
      </div>

      <div className="card mt-6">
        <div className="mb-2 text-sm font-medium text-slate-300">Raw health</div>
        <pre className="overflow-auto rounded-lg bg-slate-950/70 p-3 text-xs text-slate-300">
          {JSON.stringify(health, null, 2)}
        </pre>
      </div>
    </div>
  );
}
