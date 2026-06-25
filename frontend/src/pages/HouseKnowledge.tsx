import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";
import { homeAssistantSessionHints } from "../haAuth";
import { ingressBasePath } from "../ingress";

const ASSET_TYPES = ["floorplan", "blueprint", "photo", "note", "other"];
const STATUSES = ["", "draft", "approved", "ignored"];

export default function HouseKnowledge() {
  const [assets, setAssets] = useState<any[]>([]);
  const [cfg, setCfg] = useState<any>(null);
  const [session, setSession] = useState<any>(null);
  const [status, setStatus] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    title: "",
    asset_type: "floorplan",
    room: "",
    description: "",
  });

  const rooms = useMemo(() => cfg?.devices?.rooms || [], [cfg]);
  const basePath = ingressBasePath();

  const load = async () => {
    try {
      const [assetResult, configResult, sessionResult] = await Promise.all([
        api.houseAssets(status || undefined),
        api.config(),
        api.uiSession(homeAssistantSessionHints()),
      ]);
      setAssets(assetResult.assets || []);
      setCfg(configResult);
      setSession(sessionResult);
      setError("");
    } catch (e: any) {
      setError(e.message || String(e));
    }
  };

  useEffect(() => { void load(); }, [status]);

  const upload = async () => {
    if (!file) return;
    setBusy("upload");
    setError("");
    setMessage("");
    try {
      const uploadedBy = session?.detected_user?.id || "";
      const result = await api.uploadHouseAsset(file, { ...form, uploaded_by: uploadedBy });
      setMessage(`Uploaded ${result.asset?.title || file.name}. Review the analysis, then approve it when it is correct.`);
      setFile(null);
      setForm({ title: "", asset_type: "floorplan", room: "", description: "" });
      await load();
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy("");
    }
  };

  const setAssetStatus = async (id: number, action: "approve" | "ignore") => {
    setBusy(`${action}:${id}`);
    setError("");
    setMessage("");
    try {
      if (action === "approve") await api.approveHouseAsset(id);
      else await api.ignoreHouseAsset(id);
      setMessage(action === "approve" ? "Asset approved and added to AI house context." : "Asset ignored.");
      await load();
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="page-stack">
      <PageHeader
        title="House Knowledge"
        subtitle="Upload floor plans, blueprints, room photos, and layout notes so TPG HomeAI can reason about the physical house."
        actions={<button className="btn-ghost" onClick={() => void load()}>Refresh</button>}
      />

      {error && <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</div>}
      {message && <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-100">{message}</div>}

      <section className="card">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold text-white">Add House Asset</h2>
            <p className="mt-1 text-sm text-slate-400">Draft first, approve after review. Approved assets become context for room, dashboard, zone, and floor-plan conversations.</p>
          </div>
          <span className="badge bg-cyan-500/10 text-cyan-200">approval-first</span>
        </div>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-4">
          <input
            className="input lg:col-span-2"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            placeholder="Title, e.g. Office floor plan"
          />
          <select className="input" value={form.asset_type} onChange={(e) => setForm({ ...form, asset_type: e.target.value })}>
            {ASSET_TYPES.map((type) => <option key={type} value={type}>{label(type)}</option>)}
          </select>
          <select className="input" value={form.room} onChange={(e) => setForm({ ...form, room: e.target.value })}>
            <option value="">Whole house / unknown</option>
            {rooms.map((room: any) => <option key={room.id || room.name} value={room.name}>{room.name}</option>)}
          </select>
        </div>
        <textarea
          className="input mt-3 min-h-[6rem]"
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
          placeholder="Optional notes: what this shows, known rooms, where tablets/speakers/cameras should go, anything the AI should remember."
        />
        <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-[1fr_auto]">
          <label className="input flex cursor-pointer items-center gap-3">
            <input
              type="file"
              className="min-w-0 flex-1 text-sm text-slate-300 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-700 file:px-3 file:py-2 file:text-slate-100"
              accept="image/*,.pdf,.txt,.md,.json"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </label>
          <button className="btn" disabled={!file || busy === "upload"} onClick={() => void upload()}>
            {busy === "upload" ? "Uploading..." : "Upload"}
          </button>
        </div>
      </section>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          {STATUSES.map((item) => (
            <button
              key={item || "all"}
              className={status === item ? "btn" : "btn-ghost"}
              onClick={() => setStatus(item)}
            >
              {item ? label(item) : "All"}
            </button>
          ))}
        </div>
        <div className="text-sm text-slate-400">{assets.length} assets shown</div>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {assets.map((asset) => (
          <AssetCard
            key={asset.id}
            asset={asset}
            basePath={basePath}
            busy={busy}
            onApprove={() => void setAssetStatus(asset.id, "approve")}
            onIgnore={() => void setAssetStatus(asset.id, "ignore")}
          />
        ))}
      </div>
      {assets.length === 0 && <div className="card text-slate-500">No house assets found.</div>}
    </div>
  );
}

function AssetCard({
  asset,
  basePath,
  busy,
  onApprove,
  onIgnore,
}: {
  asset: any;
  basePath: string;
  busy: string;
  onApprove: () => void;
  onIgnore: () => void;
}) {
  const analysis = asset.analysis || {};
  return (
    <section className="card">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="break-words text-xl font-semibold text-white">{asset.title || asset.original_filename}</h2>
            <span className={`badge ${statusClass(asset.status)}`}>{asset.status}</span>
          </div>
          <div className="mt-1 text-sm text-slate-400">
            {label(asset.asset_type)} / {asset.room || "whole house"} / {asset.original_filename}
          </div>
        </div>
        <a className="btn-ghost text-center" href={`${basePath}/house/assets/${asset.id}/file`} target="_blank" rel="noreferrer">Open</a>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-3 text-sm leading-relaxed text-slate-200">
        {analysis.summary || asset.description || "No analysis summary yet."}
      </div>

      <InfoList title="Room candidates" items={analysis.room_candidates} />
      <InfoList title="Dashboard uses" items={analysis.dashboard_uses} />
      <InfoList title="Mapping questions" items={analysis.mapping_questions} />
      <InfoList title="Safety notes" items={analysis.safety_notes} />

      <div className="mt-4 flex flex-wrap gap-2">
        {asset.status !== "approved" && (
          <button className="btn" disabled={busy === `approve:${asset.id}`} onClick={onApprove}>Approve</button>
        )}
        {asset.status !== "ignored" && (
          <button className="btn-ghost text-rose-200" disabled={busy === `ignore:${asset.id}`} onClick={onIgnore}>Ignore</button>
        )}
      </div>
    </section>
  );
}

function InfoList({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;
  return (
    <div className="mt-3">
      <div className="mb-1 text-xs uppercase tracking-wide text-slate-500">{title}</div>
      <ul className="space-y-1 text-sm text-slate-300">
        {items.slice(0, 5).map((item) => <li key={item}>- {item}</li>)}
      </ul>
    </div>
  );
}

function label(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}

function statusClass(status: string) {
  if (status === "approved") return "bg-emerald-500/10 text-emerald-200";
  if (status === "ignored") return "bg-slate-700/60 text-slate-300";
  return "bg-amber-500/10 text-amber-200";
}
