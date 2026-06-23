import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";
import StatusDot from "../components/StatusDot";

type Phase = "connecting" | "ok" | "degraded" | "initializing" | "offline" | "misconfigured";

export default function Dashboard() {
  const [health, setHealth] = useState<any>(null);
  const [summary, setSummary] = useState<any>(null);
  const [phase, setPhase] = useState<Phase>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const timer = useRef<number | null>(null);

  const load = async () => {
    try {
      const h = await api.health();
      setHealth(h);
      setError(null);
      setPhase(
        h.status === "degraded" ? "degraded"
          : h.status === "initializing" ? "initializing"
            : "ok"
      );
      try {
        setSummary(await api.discoverySummary());
      } catch {
        /* summary is best-effort */
      }
    } catch (e: any) {
      const msg = e?.message || String(e);
      setError(msg);
      setPhase(msg.includes("routing is misconfigured") ? "misconfigured" : "offline");
    }
  };

  useEffect(() => {
    load();
    // Poll while initializing so the dashboard updates once the scan finishes.
    timer.current = window.setInterval(load, 5000);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, []);

  const runScan = async () => {
    setScanning(true);
    try {
      await api.discoveryScan();
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setScanning(false);
    }
  };

  const ha = health?.home_assistant;
  const disc = health?.discovery ?? {};
  const scanRunning = disc.scan_in_progress || phase === "initializing";

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle="System status for the HomeAI Orchestrator"
        actions={
          <button className="btn-ghost" onClick={runScan} disabled={scanning}>
            {scanning ? "Scanning…" : "Run scan now"}
          </button>
        }
      />

      {phase === "connecting" && (
        <div className="card mb-4 text-slate-300">Connecting to backend…</div>
      )}

      {phase === "misconfigured" && (
        <div className="card mb-4 border-rose-700/60 bg-rose-900/20 text-rose-200">
          API routing is misconfigured: the backend returned HTML for an API
          call. Make sure the add-on is up to date and reachable on port 8088.
        </div>
      )}

      {phase === "offline" && (
        <div className="card mb-4 border-rose-700/60 bg-rose-900/20 text-rose-200">
          Could not reach backend: {error}
        </div>
      )}

      {phase === "degraded" && health?.reasons?.length > 0 && (
        <div className="card mb-4 border-amber-700/60 bg-amber-900/20 text-amber-200">
          <div className="font-medium">Backend is running but needs attention:</div>
          <ul className="mt-1 list-disc pl-5 text-sm">
            {health.reasons.map((r: string) => <li key={r}>{r}</li>)}
          </ul>
        </div>
      )}

      {scanRunning && (
        <div className="card mb-4 border-sky-700/60 bg-sky-900/20 text-sky-200">
          Initial discovery scan is still running… device counts will populate shortly.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="card">
          <div className="mb-2 text-sm text-slate-400">Backend</div>
          <StatusDot
            ok={!!health}
            label={health ? `Online (v${health.backend?.version})` : "Offline"}
          />
          {health?.backend?.mode && (
            <div className="mt-2 text-xs text-slate-500">Mode: {health.backend.mode}</div>
          )}
        </div>

        <div className="card">
          <div className="mb-2 text-sm text-slate-400">Home Assistant</div>
          <StatusDot
            ok={ha?.reachable}
            label={ha?.reachable ? "Connected" : ha?.configured ? "Not reachable" : "Not configured"}
          />
          {ha?.url && <div className="mt-2 break-all text-xs text-slate-500">{ha.url}</div>}
          {ha?.auth_mode && (
            <div className="mt-1 text-xs text-slate-500">Auth: {ha.auth_mode}</div>
          )}
        </div>

        <div className="card">
          <div className="mb-2 text-sm text-slate-400">OpenAI</div>
          <StatusDot
            ok={health?.openai?.configured}
            label={health?.openai?.configured ? "Configured" : "Fallback parser"}
          />
          <div className="mt-2 text-xs text-slate-500">Mode: {health?.openai?.mode ?? "—"}</div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-4">
        <Stat label="Known devices" value={disc.known_count} />
        <Stat label="Pending approvals" value={disc.pending_count} warn={disc.pending_count > 0} />
        <Stat label="Unavailable" value={disc.unavailable_count} warn={disc.unavailable_count > 0} />
        <Stat label="Last scan" value={fmtTs(disc.last_scan_ts)} />
      </div>

      {summary?.message && (
        <div className="card mt-4 text-sm text-slate-400">{summary.message}</div>
      )}

      <div className="card mt-6">
        <div className="mb-2 text-sm font-medium text-slate-300">Raw health</div>
        <pre className="overflow-auto rounded-lg bg-slate-950/70 p-3 text-xs text-slate-300">
          {JSON.stringify(health, null, 2)}
        </pre>
      </div>
    </div>
  );
}

function Stat({ label, value, warn }: { label: string; value: any; warn?: boolean }) {
  return (
    <div className="card">
      <div className="mb-1 text-xs text-slate-400">{label}</div>
      <div className={`text-2xl font-semibold ${warn ? "text-amber-300" : "text-slate-100"}`}>
        {value ?? "—"}
      </div>
    </div>
  );
}

function fmtTs(ts?: string | null): string {
  if (!ts) return "never";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return String(ts);
  }
}
