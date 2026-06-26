import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

export default function Setup() {
  const [health, setHealth] = useState<any>(null);
  const [cfg, setCfg] = useState<any>(null);
  const [completion, setCompletion] = useState<any>(null);
  const [release, setRelease] = useState<any>(null);
  const [runbook, setRunbook] = useState<any>(null);
  const [diagnostics, setDiagnostics] = useState<any>(null);
  const [diagnosticsMessage, setDiagnosticsMessage] = useState("");
  const [voice, setVoice] = useState<any>(null);
  const [voiceRuntime, setVoiceRuntime] = useState<any>(null);
  const [houseAssets, setHouseAssets] = useState<any>(null);
  const [clientVoice, setClientVoice] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    try {
      const [h, c, done, releaseChecklist, releaseRunbook, supportPack, v, runtime, assets] = await Promise.all([
        api.health(),
        api.config(),
        api.completionStatus(),
        api.releaseChecklist(),
        api.releaseRunbook(),
        api.opsDiagnostics(),
        api.voiceDeployment(),
        api.voiceRuntime(),
        api.houseAssets("approved"),
      ]);
      setHealth(h);
      setCfg(c);
      setCompletion(done);
      setRelease(releaseChecklist);
      setRunbook(releaseRunbook);
      setDiagnostics(supportPack);
      setVoice(v);
      setVoiceRuntime(runtime);
      setHouseAssets(assets);
      setClientVoice(localVoiceEnvironment());
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
      detail: `${voice?.counts?.assistants_with_wake_words || 0}/${voice?.counts?.assistants || 0} assistants have wake words · ${voice?.counts?.assistants_with_linked_sources || 0}/${voice?.counts?.assistants || 0} linked to sources · ${voice?.counts?.ready || 0} sources ready`,
      to: "/assistants",
    },
    {
      title: "Voice runtime",
      ok: (voiceRuntime?.counts?.runtime_assistants_ready || 0) > 0 && (voiceRuntime?.counts?.runtime_sources_ready || 0) > 0,
      detail: `${voiceRuntime?.counts?.runtime_assistants_ready || 0}/${voiceRuntime?.counts?.runtime_assistants || 0} assistants online · ${voiceRuntime?.counts?.runtime_sources_ready || 0}/${voiceRuntime?.counts?.runtime_sources || 0} sources routable`,
      to: "/assistants",
    },
    {
      title: "This browser/app mic",
      ok: Boolean(clientVoice?.secureEnough && clientVoice?.captureSupported),
      detail: clientVoice
        ? `${clientVoice.secureEnough ? "secure" : "HTTP/insecure"} · ${clientVoice.captureSupported ? "capture available" : "capture blocked"} · ${clientVoice.host}`
        : "Checking local browser/app voice support",
      to: "/chat",
    },
    {
      title: "Permissions policy",
      ok: (cfg?.permissions?.sensitive_actions?.length || 0) > 0,
      detail: `${cfg?.permissions?.sensitive_actions?.length || 0} sensitive actions gated`,
      to: "/permissions",
    },
    {
      title: "House knowledge assets",
      ok: (houseAssets?.assets?.length || 0) > 0,
      detail: `${houseAssets?.assets?.length || 0} approved floor plans, blueprints, photos, or notes`,
      to: "/house-knowledge",
    },
  ];

  const ready = checks.filter((check) => check.ok).length;

  const copyDiagnostics = async () => {
    if (!diagnostics) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(diagnostics, null, 2));
      setDiagnosticsMessage("Diagnostics copied.");
    } catch {
      setDiagnosticsMessage("Clipboard unavailable.");
    }
  };

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

      <ReleaseBlockersPanel release={release} completion={completion} />
      <OperationalRunbookPanel runbook={runbook} />
      <DiagnosticsPanel diagnostics={diagnostics} message={diagnosticsMessage} onCopy={copyDiagnostics} />

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

function DiagnosticsPanel({
  diagnostics,
  message,
  onCopy,
}: {
  diagnostics: any;
  message: string;
  onCopy: () => void;
}) {
  if (!diagnostics) return null;
  const counts = diagnostics.counts || {};
  const routes = diagnostics.routes || {};
  const degraded = diagnostics.degraded_reasons || [];
  return (
    <div className="card mb-6">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-lg font-semibold text-slate-100">Support diagnostics</div>
          <div className="text-sm text-slate-400">
            Redacted status pack for release troubleshooting and support handoff.
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className={`badge ${diagnostics.safe_for_support ? "bg-emerald-500/10 text-emerald-200" : "bg-amber-500/10 text-amber-200"}`}>
            {diagnostics.safe_for_support ? "safe for support" : "review before sharing"}
          </span>
          <button className="btn-ghost" onClick={onCopy}>Copy JSON</button>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <DiagStat label="Mode" value={diagnostics.mode || "unknown"} />
        <DiagStat label="Status" value={diagnostics.status || "unknown"} />
        <DiagStat label="HA states" value={counts.states_visible ?? "—"} />
        <DiagStat label="Pending" value={counts.discovery_pending ?? "—"} />
      </div>
      {(degraded.length > 0 || diagnostics.config_error) && (
        <div className="mt-3 rounded border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100">
          <div className="font-semibold">Needs attention</div>
          {diagnostics.config_error && <div className="mt-1">{diagnostics.config_error}</div>}
          {degraded.map((reason: string) => <div key={reason} className="mt-1">{reason}</div>)}
        </div>
      )}
      <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-3">
        {Object.entries(routes).map(([label, route]) => (
          <a key={label} href={String(route)} className="rounded border border-slate-800 bg-slate-950/30 px-3 py-2 text-sm text-slate-300 hover:border-brand/60">
            {label.replace(/_/g, " ")} · {String(route)}
          </a>
        ))}
      </div>
      {message && <div className="mt-3 text-sm text-slate-400">{message}</div>}
    </div>
  );
}

function DiagStat({ label, value }: { label: string; value: any }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-950/30 p-3">
      <div className="mb-1 text-xs uppercase text-slate-500">{label}</div>
      <div className="text-xl font-semibold text-slate-100">{value}</div>
    </div>
  );
}

function OperationalRunbookPanel({ runbook }: { runbook: any }) {
  const steps = runbook?.runbook || [];
  if (!steps.length) return null;
  return (
    <div className="card mb-6">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-lg font-semibold text-slate-100">Owner runbook</div>
          <div className="text-sm text-slate-400">
            Update, acceptance, recovery, and feature-freeze steps from the release runbook.
          </div>
        </div>
        <span className="badge bg-cyan-500/10 text-cyan-200">{steps.length} sections</span>
      </div>
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        {steps.map((step: any) => (
          <div key={step.id} className="rounded border border-slate-800 bg-slate-950/30 p-3">
            <div className="font-semibold text-slate-100">{step.title}</div>
            <ul className="mt-2 space-y-1 text-sm text-slate-300">
              {(step.actions || []).map((action: string) => (
                <li key={action} className="flex gap-2">
                  <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-brand" />
                  <span>{action}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

function ReleaseBlockersPanel({ release, completion }: { release: any; completion: any }) {
  const failedChecks = (release?.checks || []).filter((check: any) => !check.pass);
  const liveBlockers = completion?.blockers || [];
  const ready = failedChecks.length === 0 && liveBlockers.length === 0;
  const targetForCheck = (checkId: string) => {
    const targets: Record<string, string> = {
      ha_connected: "/ha",
      openai_configured: "/assistants",
      security_pin: "/permissions",
      voice_acceptance: "/assistants",
      device_acceptance: "/discovery",
      interaction_quality: "/dashboard",
      version_aligned: "/",
    };
    return targets[checkId] || "/brain";
  };
  const targetForBlocker = (blocker: string) => {
    const text = blocker.toLowerCase();
    if (text.includes("voice")) return "/assistants";
    if (text.includes("pin") || text.includes("security")) return "/permissions";
    if (text.includes("pending") || text.includes("approval") || text.includes("entity")) return "/discovery";
    if (text.includes("openai")) return "/assistants";
    if (text.includes("home assistant") || text.includes("ha ")) return "/ha";
    return "/brain";
  };

  return (
    <div className={`card mb-6 ${ready ? "border-emerald-500/30" : "border-amber-500/30"}`}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-lg font-semibold text-slate-100">Release blockers</div>
          <div className="text-sm text-slate-400">
            Setup now mirrors the formal release checklist so owners can clear the exact gates blocking Jarvis.
          </div>
        </div>
        <span className={`badge ${ready ? "bg-emerald-500/10 text-emerald-200" : "bg-amber-500/10 text-amber-200"}`}>
          {ready ? "ready" : `${failedChecks.length + liveBlockers.length} to clear`}
        </span>
      </div>

      {ready ? (
        <div className="rounded border border-emerald-500/20 bg-emerald-500/10 p-3 text-sm text-emerald-100">
          No release blockers are currently reported. Keep acceptance evidence current before calling the live house complete.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {failedChecks.map((check: any) => (
            <Link key={check.id} to={targetForCheck(check.id)} className="rounded border border-slate-800 bg-slate-950/30 p-3 hover:border-brand/60">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="font-semibold text-slate-100">{check.title}</div>
                  <div className="mt-1 text-sm text-slate-400">{check.detail}</div>
                </div>
                <span className="badge bg-amber-500/10 text-amber-200">release gate</span>
              </div>
            </Link>
          ))}
          {liveBlockers.map((blocker: string) => (
            <Link key={blocker} to={targetForBlocker(blocker)} className="rounded border border-slate-800 bg-slate-950/30 p-3 hover:border-brand/60">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="font-semibold text-slate-100">{blocker}</div>
                  <div className="mt-1 text-sm text-slate-400">Live-house deployment blocker from the Jarvis completion gate.</div>
                </div>
                <span className="badge bg-amber-500/10 text-amber-200">live house</span>
              </div>
            </Link>
          ))}
        </div>
      )}

      {release?.ship_rule && (
        <div className="mt-3 rounded border border-slate-800 bg-slate-950/30 p-3 text-sm text-slate-300">
          {release.ship_rule}
        </div>
      )}
    </div>
  );
}

function localVoiceEnvironment() {
  const host = window.location.hostname;
  const localhost = ["localhost", "127.0.0.1", "::1"].includes(host);
  const secureEnough = window.isSecureContext || localhost;
  const recorder = Boolean(typeof navigator.mediaDevices?.getUserMedia === "function" && typeof MediaRecorder !== "undefined");
  const speech = Boolean((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition);
  return {
    host,
    localhost,
    secureEnough,
    recorder,
    speech,
    captureSupported: recorder || speech,
  };
}

function Stat({ label, value }: { label: string; value: any }) {
  return (
    <div className="card">
      <div className="mb-1 text-xs uppercase text-slate-500">{label}</div>
      <div className="text-2xl font-semibold text-slate-100">{value}</div>
    </div>
  );
}
