import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";
import { homeAssistantSessionHints } from "../haAuth";

const SCOPES = ["house", "user", "room", "device"];

export default function MemoryCenter() {
  const [items, setItems] = useState<any[]>([]);
  const [session, setSession] = useState<any>(null);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    scope: "house",
    owner: "",
    subject: "",
    key: "",
    value: "",
  });

  const load = async () => {
    if (!session) return;
    try {
      const role = session?.role || "guest";
      const owner = ["admin", "manager"].includes(role) ? undefined : session?.detected_user?.id || "__none__";
      const result = await api.memories(status || undefined, owner);
      setItems(result.memories || []);
      setError(null);
    } catch (e: any) {
      setError(e.message || String(e));
    }
  };

  useEffect(() => {
    api.uiSession(homeAssistantSessionHints()).then((result) => {
      setSession(result);
      setForm((current) => ({ ...current, owner: result.detected_user?.id || "" }));
    }).catch(() => {
      setSession({ role: "guest" });
    });
  }, []);

  useEffect(() => {
    void load();
  }, [status, session?.role, session?.detected_user?.id]);

  const act = async (id: number, action: "approve" | "ignore") => {
    setBusy(`${action}:${id}`);
    setError(null);
    try {
      if (action === "approve") await api.approveMemory(id);
      else await api.ignoreMemory(id);
      await load();
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(null);
    }
  };

  const draft = async () => {
    setBusy("draft");
    setError(null);
    try {
      const role = session?.role || "guest";
      const owner = ["admin", "manager"].includes(role) ? form.owner : session?.detected_user?.id || form.owner;
      await api.draftMemory({ ...form, owner, source: "web_ui" });
      setForm({ scope: "user", owner: owner || "", subject: "", key: "", value: "" });
      await load();
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="page-stack">
      <PageHeader
        title="Memory Center"
        subtitle={["admin", "manager"].includes(session?.role) ? "Approval-first house memory for preferences, device quirks, and corrections" : "Your AI memory preferences, corrections, and notes"}
        actions={<button className="btn-ghost" onClick={() => void load()}>Refresh</button>}
      />

      {error && <div className="mb-4 rounded border border-rose-500/40 bg-rose-500/10 p-3 text-rose-200">{error}</div>}

      {!["admin", "manager"].includes(session?.role) && (
        <div className="rounded-xl border border-sky-400/30 bg-sky-400/10 p-3 text-sm text-sky-100">
          Showing memory for {session?.detected_user?.name || "your profile"}. Admin-only household memory is hidden.
        </div>
      )}

      <div className="card mb-4">
        <div className="mb-3 text-lg font-semibold text-slate-100">Draft Memory</div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-5">
          <select className="input" value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })}>
            {SCOPES.map((scope) => <option key={scope} value={scope}>{scope}</option>)}
          </select>
          <input className="input" value={form.owner} disabled={!["admin", "manager"].includes(session?.role)} onChange={(e) => setForm({ ...form, owner: e.target.value })} placeholder="Owner" />
          <input className="input" value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} placeholder="Subject" />
          <input className="input" value={form.key} onChange={(e) => setForm({ ...form, key: e.target.value })} placeholder="Key" />
          <button className="btn" disabled={busy === "draft" || !form.subject || !form.key || !form.value} onClick={() => void draft()}>
            Draft
          </button>
        </div>
        <textarea
          className="input mt-3 min-h-[5rem]"
          value={form.value}
          onChange={(e) => setForm({ ...form, value: e.target.value })}
          placeholder="Memory value, e.g. Office fan uses preset modes low/medium/high."
        />
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select className="input max-w-[12rem]" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All</option>
          <option value="draft">Draft</option>
          <option value="approved">Approved</option>
          <option value="ignored">Ignored</option>
        </select>
        <Stat label="Visible" value={items.length} />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {items.map((item) => (
          <div key={item.id} className="card">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="font-mono text-brand">memory #{item.id}</span>
              <span className="badge bg-slate-700/50 text-slate-300">{item.status}</span>
              <span className="badge bg-cyan-500/10 text-cyan-200">{item.scope}</span>
            </div>
            <div className="text-sm text-slate-400">{item.owner || "house"} • {item.subject}</div>
            <div className="mt-2 font-mono text-sm text-slate-200">{item.key}</div>
            <div className="mt-1 rounded border border-slate-800 bg-slate-950/40 p-3 text-sm text-slate-300">{item.value}</div>
            {item.status === "draft" && (
              <div className="mt-3 flex gap-2">
                <button className="btn" disabled={busy === `approve:${item.id}`} onClick={() => void act(item.id, "approve")}>Approve</button>
                <button className="btn-ghost text-rose-300" disabled={busy === `ignore:${item.id}`} onClick={() => void act(item.id, "ignore")}>Ignore</button>
              </div>
            )}
          </div>
        ))}
      </div>

      {items.length === 0 && <div className="card text-slate-500">No memory items found.</div>}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: any }) {
  return (
    <div className="rounded border border-slate-700 px-3 py-2 text-sm text-slate-300">
      <span className="text-slate-500">{label}:</span> {value}
    </div>
  );
}
