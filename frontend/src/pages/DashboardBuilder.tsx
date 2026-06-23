import { useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

export default function DashboardBuilder() {
  const [form, setForm] = useState({
    title: "TPG Home",
    style: "native",
    room: "",
    include_browser_mod: true,
    include_unavailable: false,
    tablet_mode: true,
    voice_panel: true,
  });
  const [draft, setDraft] = useState<any>(null);
  const [install, setInstall] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const body = () => ({
    ...form,
    room: form.room.trim() || null,
  });

  const generate = async () => {
    setBusy(true);
    setError(null);
    setInstall(null);
    try {
      setDraft(await api.dashboardDraft(body()));
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const installDraft = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.dashboardInstall(body());
      setDraft(result.draft);
      setInstall(result.install);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader title="Dashboard Builder" subtitle="Generate Home Assistant dashboards from the approved house graph" />

      {error && <div className="mb-4 rounded border border-rose-500/40 bg-rose-500/10 p-3 text-rose-200">{error}</div>}

      <div className="card mb-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4 xl:grid-cols-7">
          <input className="input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Title" />
          <select className="input" value={form.style} onChange={(e) => setForm({ ...form, style: e.target.value })}>
            <option value="native">Native</option>
            <option value="mushroom">Mushroom</option>
          </select>
          <input className="input" value={form.room} onChange={(e) => setForm({ ...form, room: e.target.value })} placeholder="Optional room" />
          <label className="flex min-h-[2.75rem] items-center gap-2 rounded-lg border border-slate-600 px-3 text-sm text-slate-200">
            <input
              type="checkbox"
              checked={form.include_browser_mod}
              onChange={(e) => setForm({ ...form, include_browser_mod: e.target.checked })}
            />
            Browser Mod
          </label>
          <label className="flex min-h-[2.75rem] items-center gap-2 rounded-lg border border-slate-600 px-3 text-sm text-slate-200">
            <input
              type="checkbox"
              checked={form.include_unavailable}
              onChange={(e) => setForm({ ...form, include_unavailable: e.target.checked })}
            />
            Unavailable
          </label>
          <label className="flex min-h-[2.75rem] items-center gap-2 rounded-lg border border-slate-600 px-3 text-sm text-slate-200">
            <input
              type="checkbox"
              checked={form.tablet_mode}
              onChange={(e) => setForm({ ...form, tablet_mode: e.target.checked })}
            />
            Tablets
          </label>
          <label className="flex min-h-[2.75rem] items-center gap-2 rounded-lg border border-slate-600 px-3 text-sm text-slate-200">
            <input
              type="checkbox"
              checked={form.voice_panel}
              onChange={(e) => setForm({ ...form, voice_panel: e.target.checked })}
            />
            Voice Panel
          </label>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button className="btn" disabled={busy || !form.title} onClick={() => void generate()}>
            Generate Draft
          </button>
          <button className="btn-ghost" disabled={busy || !form.title} onClick={() => void installDraft()}>
            Install YAML
          </button>
        </div>
      </div>

      {install && (
        <div className="mb-4 rounded border border-emerald-500/40 bg-emerald-500/10 p-3 text-emerald-100">
          Installed: {install.path || "dashboard YAML written"} {install.dashboard_key ? `(${install.dashboard_key})` : ""}
        </div>
      )}

      {draft && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[20rem_1fr]">
          <div className="card">
            <div className="mb-2 text-lg font-semibold text-slate-100">{draft.title}</div>
            <div className="space-y-2 text-sm text-slate-300">
              <Row label="Style" value={draft.style} />
              <Row label="Views" value={draft.view_count} />
              <Row label="Room" value={draft.room || "all"} />
            </div>
            <div className="mt-4 space-y-2">
              {(draft.notes || []).map((note: string) => (
                <div key={note} className="rounded border border-slate-800 bg-slate-950/30 px-3 py-2 text-sm text-slate-400">
                  {note}
                </div>
              ))}
            </div>
          </div>
          <pre className="card max-h-[42rem] overflow-auto whitespace-pre-wrap font-mono text-xs text-slate-300">
            {draft.yaml}
          </pre>
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: any }) {
  return (
    <div className="flex justify-between gap-3 border-b border-slate-800 py-2">
      <span className="text-slate-500">{label}</span>
      <span>{value}</span>
    </div>
  );
}
