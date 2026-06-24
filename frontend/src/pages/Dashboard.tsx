import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import Badge from "../components/Badge";
import Button from "../components/Button";
import DeveloperDetails from "../components/DeveloperDetails";
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
    <div className="page-stack">
      <PageHeader
        title="Dashboard"
        subtitle="Live overview for the smart-home AI brain, Home Assistant connection, and discovery pipeline."
        actions={
          <Button variant="ghost" onClick={runScan} disabled={scanning}>
            {scanning ? "Scanning…" : "Run scan now"}
          </Button>
        }
      />

      {phase === "connecting" && (
        <div className="card text-slate-300">Connecting to backend...</div>
      )}

      {phase === "misconfigured" && (
        <div className="card border-rose-700/60 bg-rose-900/20 text-rose-200">
          API routing is misconfigured: the backend returned HTML for an API
          call. Make sure the add-on is up to date and reachable on port 8088.
        </div>
      )}

      {phase === "offline" && (
        <div className="card border-rose-700/60 bg-rose-900/20 text-rose-200">
          Could not reach backend: {error}
        </div>
      )}

      {phase === "degraded" && health?.reasons?.length > 0 && (
        <div className="card border-amber-700/60 bg-amber-900/20 text-amber-200">
          <div className="font-medium">Backend is running but needs attention:</div>
          <ul className="mt-1 list-disc pl-5 text-sm">
            {health.reasons.map((r: string) => <li key={r}>{r}</li>)}
          </ul>
        </div>
      )}

      {scanRunning && (
        <div className="card border-sky-700/60 bg-sky-900/20 text-sky-200">
          Initial discovery scan is still running... device counts will populate shortly.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="card">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div className="text-sm font-semibold text-slate-300">Backend</div>
            <Badge tone={health ? "good" : "danger"}>{phase}</Badge>
          </div>
          <StatusDot
            ok={!!health}
            label={health ? `Online (v${health.backend?.version})` : "Offline"}
          />
          {health?.backend?.mode && (
            <div className="mt-2 text-xs text-slate-500">Mode: {health.backend.mode}</div>
          )}
        </div>

        <div className="card">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div className="text-sm font-semibold text-slate-300">Home Assistant</div>
            <Badge tone={ha?.reachable ? "good" : ha?.configured ? "warn" : "danger"}>
              {ha?.reachable ? "connected" : ha?.configured ? "check" : "setup"}
            </Badge>
          </div>
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
          <div className="mb-3 flex items-center justify-between gap-2">
            <div className="text-sm font-semibold text-slate-300">AI Brain</div>
            <Badge tone={health?.openai?.configured ? "good" : "warn"}>
              {health?.openai?.configured ? "openai" : "fallback"}
            </Badge>
          </div>
          <StatusDot
            ok={health?.openai?.configured}
            label={health?.openai?.configured ? "Configured" : "Fallback parser"}
          />
          <div className="mt-2 text-xs text-slate-500">Mode: {health?.openai?.mode ?? "—"}</div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Known devices" value={disc.known_count} />
        <Stat label="Pending approvals" value={disc.pending_count} warn={disc.pending_count > 0} />
        <Stat label="Unavailable" value={disc.unavailable_count} warn={disc.unavailable_count > 0} />
        <Stat label="Last scan" value={fmtTs(disc.last_scan_ts)} />
      </div>

      {summary?.message && (
        <div className="card text-sm text-slate-400">{summary.message}</div>
      )}

      <DeveloperDetails title="Raw health" data={health} />
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
