import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

export default function Suggestions() {
  const [drafts, setDrafts] = useState<any[]>([]);
  const [proactive, setProactive] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = async () => {
    try {
      const [draftResult, proactiveResult] = await Promise.all([
        api.suggestions(),
        api.proactiveSuggestions(),
      ]);
      setDrafts(draftResult.suggestions || []);
      setProactive(
        (proactiveResult.suggestions || []).filter((s: any) =>
          ["suggested", "draft", "edited"].includes(s.status || "suggested"),
        ),
      );
      setError(null);
    } catch (e: any) {
      setError(e.message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const actDraft = async (id: number, fn: "approve" | "ignore") => {
    setBusy(`draft:${id}`);
    setError(null);
    try {
      if (fn === "approve") await api.approveDraft(id);
      else await api.ignoreDraft(id);
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const actProactive = async (id: number, fn: "approve" | "ignore") => {
    setBusy(`proactive:${id}`);
    setError(null);
    try {
      if (fn === "approve") await api.approveProactiveSuggestion(id);
      else await api.ignoreProactiveSuggestion(id);
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <PageHeader title="Suggestions" subtitle="Review timers, routines, and automation drafts before anything permanent happens" />

      {error && <div className="mb-4 rounded border border-rose-500/40 bg-rose-500/10 p-3 text-rose-200">{error}</div>}

      <div className="mb-4 grid grid-cols-1 gap-4 md:grid-cols-3">
        <Stat label="Automation drafts" value={drafts.length} />
        <Stat label="Proactive/repair" value={proactive.length} />
        <Stat label="Approval model" value="human gated" />
      </div>

      <div className="space-y-4">
        {drafts.length === 0 && proactive.length === 0 && <div className="card text-slate-500">No pending suggestions.</div>}

        {proactive.length > 0 && (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {proactive.map((s) => (
              <div key={s.id} className="card">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <span className="font-mono text-brand">suggestion #{s.id}</span>
                  <span className="badge bg-slate-700/50 text-slate-300">{s.status}</span>
                  <span className={`badge ${s.priority === "high" ? "bg-rose-500/20 text-rose-200" : "bg-slate-700/50 text-slate-300"}`}>
                    {s.priority || "normal"}
                  </span>
                  <span className="badge bg-cyan-500/10 text-cyan-200">{s.category}</span>
                </div>
                <div className="text-sm font-semibold text-slate-100">{s.title}</div>
                <div className="mt-1 text-sm text-slate-300">{s.message}</div>
                <div className="mt-2 text-xs text-slate-500">Action: {s.action_type || "review"}</div>
                <pre className="mt-3 max-h-56 overflow-auto rounded bg-slate-950 p-3 text-xs text-slate-300">
                  {JSON.stringify(s.payload || {}, null, 2)}
                </pre>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button className="btn" disabled={busy === `proactive:${s.id}`} onClick={() => actProactive(s.id, "approve")}>
                    Approve
                  </button>
                  <button className="btn-ghost text-rose-300" disabled={busy === `proactive:${s.id}`} onClick={() => actProactive(s.id, "ignore")}>
                    Ignore
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {drafts.map((d) => (
          <div key={d.id} className="card">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="font-mono text-brand">#{d.id}</span>
              <span className="badge bg-slate-700/50 text-slate-300">{d.status}</span>
              <span className="text-xs text-slate-500">{d.created_at || ""}</span>
            </div>
            <div className="text-sm text-slate-200">{d.action_description || d.trigger_description}</div>
            <pre className="mt-3 max-h-80 overflow-auto rounded bg-slate-950 p-3 text-xs text-slate-300">
              {d.proposed_yaml}
            </pre>
            <div className="mt-3 flex flex-wrap gap-2">
              <button className="btn" disabled={busy === `draft:${d.id}`} onClick={() => actDraft(d.id, "approve")}>
                Approve
              </button>
              <button className="btn-ghost text-rose-300" disabled={busy === `draft:${d.id}`} onClick={() => actDraft(d.id, "ignore")}>
                Ignore
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: any }) {
  return (
    <div className="card">
      <div className="mb-1 text-xs uppercase text-slate-500">{label}</div>
      <div className="text-xl font-semibold text-slate-100">{value}</div>
    </div>
  );
}
