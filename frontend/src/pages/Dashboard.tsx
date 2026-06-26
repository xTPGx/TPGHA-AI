import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { homeAssistantSessionHints } from "../haAuth";
import Badge from "../components/Badge";
import Button from "../components/Button";
import DeveloperDetails from "../components/DeveloperDetails";
import PageHeader from "../components/PageHeader";
import StatusDot from "../components/StatusDot";

type Phase = "connecting" | "ok" | "degraded" | "initializing" | "offline" | "misconfigured";

export default function Dashboard() {
  const [health, setHealth] = useState<any>(null);
  const [summary, setSummary] = useState<any>(null);
  const [session, setSession] = useState<any>(null);
  const [actionPlan, setActionPlan] = useState<any>(null);
  const [roleSummary, setRoleSummary] = useState<any>(null);
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
      try {
        const currentSession = await api.uiSession(homeAssistantSessionHints());
        setSession(currentSession);
        const role = currentSession?.role || "guest";
        const userId = currentSession?.detected_user?.id || "";
        setRoleSummary(await api.roleDashboardSummary(role, userId));
        if (["admin", "manager"].includes(role)) {
          setActionPlan(await api.setupActionPlan());
        } else {
          setActionPlan(null);
        }
      } catch {
        setSession(null);
        setRoleSummary(null);
        setActionPlan(null);
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

      <DashboardRoleSummary summary={roleSummary} session={session} />

      {roleSummary?.permissions?.admin_actions_visible && (
        <DashboardActionPlan actionPlan={actionPlan} />
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

function DashboardRoleSummary({ summary, session }: { summary: any; session: any }) {
  if (!summary) return null;
  const cards = summary.cards || [];
  const role = summary.role || session?.role || "guest";
  const assistantName = summary.assistant?.name || session?.default_assistant?.name || "Jarvis";
  return (
    <div className="card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-lg font-semibold text-slate-100">{assistantName} dashboard</div>
          <div className="mt-1 text-sm text-slate-400">
            {summary.mode || "role"} · {summary.user?.name || session?.detected_user?.name || "House"}
          </div>
        </div>
        <Badge tone={summary.permissions?.admin_actions_visible ? "good" : "brand"}>{role}</Badge>
      </div>
      <div className="mt-4 grid grid-cols-1 gap-3 xl:grid-cols-3">
        {cards.map((card: any) => (
          <Link key={card.id || card.title} to={card.target || "/chat"} className="rounded border border-slate-800 bg-slate-950/30 p-3 hover:border-brand/60">
            <div className="flex items-start justify-between gap-2">
              <div className="font-semibold text-slate-100">{card.title}</div>
              <Badge tone={card.tone || "slate"}>{card.target || "/chat"}</Badge>
            </div>
            <div className="mt-1 text-sm text-slate-400">{card.detail}</div>
          </Link>
        ))}
      </div>
      {summary.acceptance && (
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <MiniEvidence label="Acceptance scope" value={summary.acceptance.scope || "profile"} />
          <MiniEvidence label="Passed checks" value={summary.acceptance.passed ?? 0} />
          <MiniEvidence label="Failed/blocked" value={summary.acceptance.failed_or_blocked ?? 0} warn={summary.acceptance.failed_or_blocked > 0} />
        </div>
      )}
      {summary.action_policy?.highlights?.length > 0 && (
        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          {summary.action_policy.highlights.map((item: any) => (
            <div key={item.id} className="rounded border border-slate-800 bg-slate-950/30 p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="font-semibold text-slate-100">{item.label}</div>
                <Badge tone={item.allowed ? "good" : "slate"}>{item.allowed ? "allowed" : "owner"}</Badge>
              </div>
              <div className="mt-1 text-sm text-slate-400">{item.detail}</div>
            </div>
          ))}
        </div>
      )}
      {!summary.permissions?.admin_actions_visible && (
        <div className="mt-4 rounded border border-slate-800 bg-slate-950/30 p-3 text-sm text-slate-400">
          Owner setup, discovery mapping, dashboards, users, and system configuration stay hidden unless Home Assistant grants admin/manager access.
        </div>
      )}
    </div>
  );
}

function MiniEvidence({ label, value, warn }: { label: string; value: any; warn?: boolean }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-950/30 p-3">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${warn ? "text-amber-300" : "text-slate-100"}`}>
        {value}
      </div>
    </div>
  );
}

function DashboardActionPlan({ actionPlan }: { actionPlan: any }) {
  const actions = actionPlan?.top_actions || [];
  if (!actions.length) return null;
  const counts = actionPlan.counts || {};
  return (
    <div className="card border-brand/30">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-lg font-semibold text-slate-100">Owner action plan</div>
          <div className="mt-1 text-sm text-slate-400">
            {counts.release_blockers || 0} release blockers · {counts.capability_gaps || 0} capability gaps · {counts.onboarding || 0} onboarding item
          </div>
        </div>
        <Link to="/setup" className="btn-ghost">Open Setup</Link>
      </div>
      <div className="mt-4 grid grid-cols-1 gap-3 xl:grid-cols-3">
        {actions.slice(0, 3).map((action: any) => (
          <Link key={action.id || `${action.source}-${action.title}`} to={action.target || "/setup"} className="rounded border border-slate-800 bg-slate-950/30 p-3 hover:border-brand/60">
            <div className="flex items-start justify-between gap-2">
              <div className="font-semibold text-slate-100">{action.title}</div>
              <Badge tone={action.severity === "high" || action.severity === "critical" ? "warn" : "slate"}>{action.source}</Badge>
            </div>
            <div className="mt-1 text-sm text-slate-400">{action.detail}</div>
          </Link>
        ))}
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
