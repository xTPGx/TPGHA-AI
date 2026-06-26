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
  const [acceptance, setAcceptance] = useState<any>(null);
  const [acceptanceReport, setAcceptanceReport] = useState<any>(null);
  const [acceptanceBusy, setAcceptanceBusy] = useState<string | null>(null);
  const [reportMessage, setReportMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const [brainResult, providerResult, completionResult, acceptanceResult, reportResult] = await Promise.all([
        api.brainLayers(),
        api.aiProviders(),
        api.completionStatus(),
        api.liveAcceptance(),
        api.liveAcceptanceReport(),
      ]);
      setBrain(brainResult);
      setProviders(providerResult);
      setCompletion(completionResult);
      setAcceptance(acceptanceResult);
      setAcceptanceReport(reportResult);
      setError(null);
    } catch (e: any) {
      setError(e.message || String(e));
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const recordAcceptance = async (testId: string, status: "passed" | "failed" | "blocked" | "skipped") => {
    setAcceptanceBusy(`${testId}:${status}`);
    try {
      await api.recordLiveAcceptanceResult({
        test_id: testId,
        status,
        notes: `Marked ${status} from the Brain acceptance UI.`,
        evidence: { source: "brain_ui", mutating: false },
      });
      await load();
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setAcceptanceBusy(null);
    }
  };

  const copyAcceptanceReport = async () => {
    const markdown = acceptanceReport?.markdown || "";
    if (!markdown) return;
    try {
      await navigator.clipboard.writeText(markdown);
      setReportMessage("Acceptance report copied.");
    } catch {
      setReportMessage("Clipboard unavailable. Use Download Markdown instead.");
    }
  };

  const downloadAcceptanceReport = () => {
    const markdown = acceptanceReport?.markdown || "";
    if (!markdown) return;
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const version = acceptanceReport?.version || "report";
    link.href = url;
    link.download = `tpg-homeai-live-acceptance-${version}.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setReportMessage("Acceptance report downloaded.");
  };

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

      {acceptance && (
        <LiveAcceptancePanel
          acceptance={acceptance}
          report={acceptanceReport}
          busy={acceptanceBusy}
          reportMessage={reportMessage}
          onRecord={recordAcceptance}
          onCopyReport={copyAcceptanceReport}
          onDownloadReport={downloadAcceptanceReport}
        />
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

function LiveAcceptancePanel({
  acceptance,
  report,
  busy,
  reportMessage,
  onRecord,
  onCopyReport,
  onDownloadReport,
}: {
  acceptance: any;
  report: any;
  busy: string | null;
  reportMessage: string | null;
  onRecord: (testId: string, status: "passed" | "failed" | "blocked" | "skipped") => void;
  onCopyReport: () => void;
  onDownloadReport: () => void;
}) {
  const tests = acceptance.tests || [];
  const evidence = acceptance.evidence || {};
  const latestByTest = evidence.latest_by_test || {};
  const roleAcceptance = report?.role_acceptance || {};
  const repairSummary = report?.acceptance_repairs?.summary || {};
  const resolutionSummary = report?.acceptance_resolutions?.summary || {};
  const unrepairedTests = report?.acceptance_repairs?.unrepaired_test_ids || [];
  const [filter, setFilter] = useState<
    "all" | "attention" | "missing" | "passed" | "owner" | "resident" | "dry_run" | "read_only"
  >("attention");
  const needsAttention = (test: any) => {
    const latestStatus = latestByTest[test.id]?.status;
    return test.status === "blocked" || !latestStatus || ["failed", "blocked"].includes(latestStatus);
  };
  const filterOptions = [
    { id: "all", label: "All", count: tests.length },
    { id: "attention", label: "Attention", count: tests.filter(needsAttention).length },
    { id: "missing", label: "Missing evidence", count: tests.filter((test: any) => !latestByTest[test.id]?.status).length },
    { id: "passed", label: "Passed", count: tests.filter((test: any) => latestByTest[test.id]?.status === "passed").length },
    { id: "owner", label: "Owner", count: tests.filter((test: any) => test.required_role === "owner").length },
    { id: "resident", label: "Resident", count: tests.filter((test: any) => test.required_role === "resident").length },
    { id: "dry_run", label: "Dry-run", count: tests.filter((test: any) => test.mode === "dry_run_required").length },
    { id: "read_only", label: "Read-only", count: tests.filter((test: any) => test.mode === "read_only_probe").length },
  ];
  const filteredTests = tests.filter((test: any) => {
    if (filter === "attention") return needsAttention(test);
    if (filter === "missing") return !latestByTest[test.id]?.status;
    if (filter === "passed") return latestByTest[test.id]?.status === "passed";
    if (filter === "owner") return test.required_role === "owner";
    if (filter === "resident") return test.required_role === "resident";
    if (filter === "dry_run") return test.mode === "dry_run_required";
    if (filter === "read_only") return test.mode === "read_only_probe";
    return true;
  });
  return (
    <div className="card mb-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-lg font-semibold text-slate-100">Live Acceptance</div>
          <div className="text-sm text-slate-400">
            Read-only readiness checks plus human-run evidence for the real house.
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="badge bg-emerald-500/10 text-emerald-200">
            read only
          </span>
          {report && (
            <span className={report.status === "ready" ? "badge bg-emerald-500/10 text-emerald-200" : "badge bg-amber-500/10 text-amber-200"}>
              report: {report.status}
            </span>
          )}
          <span className="badge bg-cyan-500/10 text-cyan-200">
            {acceptance.summary?.ready ?? 0}/{acceptance.summary?.total ?? tests.length} ready
          </span>
          <span className="badge bg-slate-800 text-slate-200">
            {evidence.count || 0} evidence
          </span>
        </div>
      </div>

      <div className="mb-3 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <MiniStat label="Read-only probes" value={acceptance.summary?.read_only ?? 0} />
        <MiniStat label="Dry-run checks" value={acceptance.summary?.dry_run_required ?? 0} />
        <MiniStat label="Blocked" value={acceptance.summary?.blocked ?? 0} />
        <MiniStat label="Sensitive" value={acceptance.summary?.sensitive ?? 0} />
        <MiniStat label="Recorded" value={evidence.count || 0} />
      </div>

      {report && (
        <div className="mb-3 rounded border border-slate-800 bg-slate-950/30 p-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="font-semibold text-slate-100">Acceptance report</div>
              <div className="text-sm text-slate-400">
                {report.summary?.passed ?? 0}/{report.summary?.required_passes ?? 0} required checks passed,
                {" "}{report.summary?.failed_or_blocked ?? 0} failed or blocked.
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button className="btn-ghost" onClick={onCopyReport}>Copy report</button>
              <button className="btn" onClick={onDownloadReport}>Download Markdown</button>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <MiniStat label="Role acceptance" value={`${roleAcceptance.score ?? 0}%`} />
            <MiniStat label="Active repairs" value={repairSummary.active_repairs ?? 0} />
            <MiniStat label="Unrepaired" value={repairSummary.unrepaired ?? 0} />
            <MiniStat label="Resolved repairs" value={resolutionSummary.resolved_repairs ?? 0} />
          </div>
          {unrepairedTests.length > 0 && (
            <div className="mt-3 rounded border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100">
              <div className="font-semibold">Unrepaired acceptance blockers</div>
              <div className="mt-1 text-amber-100/80">{unrepairedTests.join(", ")}</div>
            </div>
          )}
          {reportMessage && <div className="mt-2 text-sm text-slate-300">{reportMessage}</div>}
        </div>
      )}

      {acceptance.policy?.executes_actions === false && (
        <div className="mb-3 rounded border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100">
          This runner never executes device actions. Mutating checks must be performed intentionally by a human.
        </div>
      )}

      <div className="mb-3 rounded border border-slate-800 bg-slate-950/30 p-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-slate-100">Acceptance triage filters</div>
            <div className="text-xs text-slate-500">
              Start with attention, then drill into role, mode, or evidence status before release.
            </div>
          </div>
          <span className="badge bg-slate-800 text-slate-200">
            showing {filteredTests.length}/{tests.length}
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          {filterOptions.map((option) => (
            <button
              key={option.id}
              className={filter === option.id ? "btn" : "btn-ghost"}
              onClick={() => setFilter(option.id as typeof filter)}
            >
              {option.label} ({option.count})
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        {filteredTests.length === 0 && (
          <div className="rounded border border-slate-800 bg-slate-950/30 p-3 text-sm text-slate-400">
            No acceptance checks match this filter.
          </div>
        )}
        {filteredTests.map((test: any) => {
          const latest = latestByTest[test.id];
          return (
            <div key={test.id} className="rounded border border-slate-800 bg-slate-950/30 p-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="font-semibold text-slate-100">{test.title}</div>
                  <div className="mt-1 text-xs text-slate-500">
                    {test.domain} · {test.mode} · {test.required_role}
                    {test.sample_entity_id ? ` · ${test.sample_entity_id}` : ""}
                  </div>
                  <div className="mt-2 text-sm text-slate-300">{test.command_example}</div>
                  {latest && (
                    <div className="mt-2 text-xs text-slate-400">
                      Latest evidence: <span className="text-slate-200">{latest.status}</span>
                      {latest.user ? ` by ${latest.user}` : ""} on {latest.version || "unknown version"}
                    </div>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  {(["passed", "failed", "blocked", "skipped"] as const).map((status) => (
                    <button
                      key={status}
                      className={status === "passed" ? "btn" : "btn-ghost"}
                      disabled={busy === `${test.id}:${status}`}
                      onClick={() => onRecord(test.id, status)}
                    >
                      {busy === `${test.id}:${status}` ? "Saving" : status}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          );
        })}
      </div>
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
