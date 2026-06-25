import { useState } from "react";
import { api } from "../api";
import Button from "../components/Button";
import DeveloperDetails from "../components/DeveloperDetails";
import PageHeader from "../components/PageHeader";
import ToggleRow from "../components/ToggleRow";

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
    <div className="page-stack">
      <PageHeader title="Dashboard Builder" subtitle="Generate Home Assistant dashboards from the approved house graph" />

      {error && <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-rose-200">{error}</div>}

      <div className="card">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          <input className="input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Title" />
          <select className="input" value={form.style} onChange={(e) => setForm({ ...form, style: e.target.value })}>
            <option value="native">Native</option>
            <option value="mushroom">Mushroom</option>
          </select>
          <input className="input" value={form.room} onChange={(e) => setForm({ ...form, room: e.target.value })} placeholder="Optional room" />
          <ToggleRow label="Browser Mod" checked={form.include_browser_mod} onChange={(checked) => setForm({ ...form, include_browser_mod: checked })} />
          <ToggleRow label="Unavailable devices" checked={form.include_unavailable} onChange={(checked) => setForm({ ...form, include_unavailable: checked })} />
          <ToggleRow label="Tablet mode" checked={form.tablet_mode} onChange={(checked) => setForm({ ...form, tablet_mode: checked })} />
          <ToggleRow label="Voice panel" checked={form.voice_panel} onChange={(checked) => setForm({ ...form, voice_panel: checked })} />
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button disabled={busy || !form.title} onClick={() => void generate()}>
            Generate Draft
          </Button>
          <Button variant="ghost" disabled={busy || !form.title} onClick={() => void installDraft()}>
            Install YAML
          </Button>
        </div>
      </div>

      {install && (
        <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-3 text-emerald-100">
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
            <DashboardPreview draft={draft} />
          </div>
          <div className="card">
            <div className="mb-3 text-lg font-semibold text-slate-100">Generated YAML</div>
            <DeveloperDetails title="View generated YAML">
              <pre className="code-scroll max-h-[42rem] whitespace-pre-wrap font-mono">
                {draft.yaml}
              </pre>
            </DeveloperDetails>
          </div>
        </div>
      )}
    </div>
  );
}

function DashboardPreview({ draft }: { draft: any }) {
  const views = draft?.dashboard?.views || [];
  const spatial = draft?.spatial_brain?.summary || {};
  if (!views.length) return null;
  return (
    <div className="mt-4 space-y-3">
      <div className="text-sm font-semibold uppercase tracking-wide text-slate-500">Preview</div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-2">
          <div className="text-slate-500">Spatial assets</div>
          <div className="mt-1 text-lg font-semibold text-slate-100">{spatial.approved_assets || 0}</div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-2">
          <div className="text-slate-500">Rooms mapped</div>
          <div className="mt-1 text-lg font-semibold text-slate-100">{spatial.rooms_with_assets || 0}</div>
        </div>
      </div>
      <div className="space-y-2">
        {views.map((view: any) => (
          <div key={view.path || view.title} className="rounded-xl border border-slate-800 bg-slate-950/35 p-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="font-semibold text-slate-100">{view.title}</div>
                <div className="text-xs text-slate-500">/{view.path || "view"}</div>
              </div>
              <span className="badge bg-slate-800 text-slate-300">{(view.cards || []).length} cards</span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(view.cards || []).slice(0, 6).map((card: any, index: number) => (
                <span key={`${view.path}:${index}`} className="rounded-md border border-slate-800 bg-black/20 px-2 py-1 text-[11px] text-slate-400">
                  {card.type || "card"}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
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
