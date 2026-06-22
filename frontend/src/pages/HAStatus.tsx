import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

export default function HAStatus() {
  const [state, setState] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      setState(await api.state());
      setHealth(await api.health());
    } catch (e: any) {
      setError(e.message);
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, []);

  return (
    <div>
      <PageHeader
        title="Home Assistant Integration"
        subtitle="The operational state the custom integration mirrors into Home Assistant"
        actions={<button className="btn" onClick={load}>Refresh</button>}
      />
      {error && <div className="mb-4 text-rose-300">{error}</div>}

      {state && (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <Stat label="Status" value={health?.status} bad={health?.status !== "ok"} />
          <Stat label="Config" value={state.config_ok ? "ok" : "error"} bad={!state.config_ok} />
          <Stat label="Pending approvals" value={state.pending_approvals} bad={state.pending_approvals > 0} />
          <Stat label="Unavailable" value={state.unavailable_devices} />
          <Stat
            label="Needs attention"
            value={state.needs_attention ? "yes" : "no"}
            bad={state.needs_attention}
          />
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="card">
          <div className="mb-2 text-sm font-medium text-slate-300">Pending confirmations</div>
          {(state?.pending_confirmations || []).length === 0 && (
            <div className="text-slate-500">None.</div>
          )}
          {(state?.pending_confirmations || []).map((c: any) => (
            <div key={c.token} className="mb-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-2 text-sm">
              <div className="text-amber-200">{c.message}</div>
              <div className="text-xs text-slate-500">
                {c.intent} · expires in {c.expires_in}s
              </div>
            </div>
          ))}
        </div>

        <div className="card">
          <div className="mb-2 text-sm font-medium text-slate-300">Last command</div>
          <pre className="overflow-auto rounded-lg bg-slate-950/70 p-3 text-xs text-slate-300">
            {JSON.stringify(state?.last_command ?? null, null, 2)}
          </pre>
        </div>
      </div>

      <div className="card mt-6">
        <div className="mb-2 text-sm font-medium text-slate-300">Exposed in Home Assistant</div>
        <ul className="list-disc pl-5 text-sm text-slate-400">
          <li>sensor.tpg_homeai_status, pending_approvals, unavailable_devices, last_command</li>
          <li>binary_sensor.tpg_homeai_needs_attention</li>
          <li>button.tpg_homeai_scan_devices, reload_config, test_connection</li>
          <li>Services: scan_devices, approve_discovered_entity, ignore_discovered_entity, map_entity, confirm_action, cancel_confirmation</li>
          <li>Persistent notifications + Repairs for approvals, confirmations, config errors, offline backend</li>
        </ul>
      </div>
    </div>
  );
}

function Stat({ label, value, bad }: { label: string; value: any; bad?: boolean }) {
  return (
    <div className="card">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${bad ? "text-rose-300" : "text-slate-100"}`}>
        {value ?? "—"}
      </div>
    </div>
  );
}
