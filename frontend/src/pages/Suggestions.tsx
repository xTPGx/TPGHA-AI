import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

export default function Suggestions() {
  const [items, setItems] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const load = async () => {
    try {
      const r = await api.suggestions();
      setItems(r.suggestions || []);
    } catch (e: any) {
      setError(e.message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const act = async (id: number, fn: "approve" | "ignore") => {
    setBusy(id);
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

  return (
    <div>
      <PageHeader title="Suggestions" subtitle="Review timers, routines, and automation drafts before anything permanent happens" />

      {error && <div className="mb-4 rounded border border-rose-500/40 bg-rose-500/10 p-3 text-rose-200">{error}</div>}

      <div className="space-y-4">
        {items.length === 0 && <div className="card text-slate-500">No pending suggestions.</div>}
        {items.map((d) => (
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
              <button className="btn" disabled={busy === d.id} onClick={() => act(d.id, "approve")}>
                Approve
              </button>
              <button className="btn-ghost text-rose-300" disabled={busy === d.id} onClick={() => act(d.id, "ignore")}>
                Ignore
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
