import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

export default function Setup() {
  const [health, setHealth] = useState<any>(null);
  const [cfg, setCfg] = useState<any>(null);
  const [completion, setCompletion] = useState<any>(null);
  const [voice, setVoice] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    try {
      const [h, c, done, v] = await Promise.all([
        api.health(),
        api.config(),
        api.completionStatus(),
        api.voiceDeployment(),
      ]);
      setHealth(h);
      setCfg(c);
      setCompletion(done);
      setVoice(v);
      setError("");
    } catch (e: any) {
      setError(e.message || String(e));
    }
  };

  useEffect(() => { void load(); }, []);

  const scan = async () => {
    setBusy(true);
    try {
      await api.discoveryScan();
      await load();
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const checks = [
    {
      title: "Backend online",
      ok: health?.backend?.online,
      detail: `Version ${health?.backend?.version || "unknown"} · ${health?.status || "unknown"}`,
      to: "/",
    },
    {
      title: "Home Assistant reachable",
      ok: health?.home_assistant?.reachable,
      detail: health?.home_assistant?.configured ? health?.home_assistant?.url : "Configure add-on HA URL/token",
      to: "/ha",
    },
    {
      title: "OpenAI configured",
      ok: health?.openai?.configured,
      detail: health?.openai?.mode || "fallback parser",
      to: "/assistants",
    },
    {
      title: "Users and assistants",
      ok: (cfg?.assistants?.users?.length || 0) > 0 && (cfg?.assistants?.assistants?.length || 0) > 0,
      detail: `${cfg?.assistants?.users?.length || 0} users · ${cfg?.assistants?.assistants?.length || 0} assistants`,
      to: "/users",
    },
    {
      title: "Rooms mapped",
      ok: (cfg?.devices?.rooms?.length || 0) > 0,
      detail: `${cfg?.devices?.rooms?.length || 0} rooms configured`,
      to: "/rooms",
    },
    {
      title: "Music accounts and speakers",
      ok: Object.keys(cfg?.devices?.music_accounts || {}).length > 0 && (cfg?.devices?.speakers?.length || 0) > 0,
      detail: `${Object.keys(cfg?.devices?.music_accounts || {}).length} accounts · ${cfg?.devices?.speakers?.length || 0} speakers`,
      to: "/music",
    },
    {
      title: "Wake words and voice sources",
      ok: (cfg?.devices?.voice_sources?.length || 0) > 0,
      detail: `${voice?.counts?.assistants_ready || 0}/${voice?.counts?.assistants || 0} assistants ready · ${voice?.counts?.ready || 0} sources ready`,
      to: "/assistants",
    },
    {
      title: "Permissions policy",
      ok: (cfg?.permissions?.sensitive_actions?.length || 0) > 0,
      detail: `${cfg?.permissions?.sensitive_actions?.length || 0} sensitive actions gated`,
      to: "/permissions",
    },
  ];

  const ready = checks.filter((check) => check.ok).length;

  return (
    <div>
      <PageHeader
        title="Setup"
        subtitle="First-run checklist for turning Home Assistant entities into a usable house brain."
        actions={<div className="flex gap-2"><button className="btn-ghost" onClick={() => void load()}>Refresh</button><button className="btn" onClick={scan} disabled={busy}>Scan HA</button></div>}
      />

      {error && <div className="mb-4 rounded border border-rose-500/40 bg-rose-500/10 p-3 text-rose-200">{error}</div>}

      <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-4">
        <Stat label="Readiness" value={`${ready}/${checks.length}`} />
        <Stat label="Software" value={completion?.software_ship_complete ? "ready" : "building"} />
        <Stat label="House" value={completion?.house_deployment_complete ? "ready" : "needs setup"} />
        <Stat label="Pending discovery" value={health?.discovery?.pending_count ?? "—"} />
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        {checks.map((check) => (
          <Link key={check.title} to={check.to} className="card block hover:border-brand/60">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-lg font-semibold text-slate-100">{check.title}</div>
                <div className="mt-1 text-sm text-slate-400">{check.detail}</div>
              </div>
              <span className={`badge ${check.ok ? "bg-emerald-500/10 text-emerald-200" : "bg-amber-500/10 text-amber-200"}`}>
                {check.ok ? "ready" : "setup"}
              </span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: any }) {
  return (
    <div className="card">
      <div className="mb-1 text-xs uppercase text-slate-500">{label}</div>
      <div className="text-2xl font-semibold text-slate-100">{value}</div>
    </div>
  );
}
