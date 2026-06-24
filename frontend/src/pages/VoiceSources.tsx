import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

const emptySource = {
  id: "",
  name: "",
  room: "",
  assistant: "",
  user: "",
  trust_level: "household",
  default_reply: "room_speaker",
  speaker: "",
  source_device_id: "",
  source_entity_id: "",
  aliases: "",
};

export default function VoiceSources() {
  const [items, setItems] = useState<any[]>([]);
  const [cfg, setCfg] = useState<any>(null);
  const [editor, setEditor] = useState<any | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const [result, config] = await Promise.all([api.voiceSources(), api.config()]);
      setItems(result.voice_sources || []);
      setCfg(config);
      setError(null);
    } catch (e: any) {
      setError(e.message || String(e));
    }
  };

  useEffect(() => { void load(); }, []);

  const editSource = (source?: any) => {
    setError(null);
    setEditor(source ? { ...emptySource, ...source, aliases: (source.aliases || []).join(", ") } : emptySource);
  };

  const saveSource = async () => {
    setSaving(true);
    setError(null);
    try {
      const payload = { ...editor, id: slug(editor.id || editor.name), aliases: csv(editor.aliases) };
      await api.saveVoiceSource(payload);
      await load();
      setEditor(null);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setSaving(false);
    }
  };

  const rooms = cfg?.devices?.rooms || [];
  const users = cfg?.assistants?.users || [];
  const assistants = cfg?.assistants?.assistants || [];
  const speakers = cfg?.devices?.speakers || [];

  return (
    <div>
      <PageHeader
        title="Voice Sources"
        subtitle="Deploy assistant wake words onto microphones, tablets, panels, and HA Assist satellites."
        actions={<div className="flex gap-2"><button className="btn-ghost" onClick={() => void load()}>Refresh</button><button className="btn" onClick={() => editSource()}>Add Voice Source</button></div>}
      />

      {error && <div className="mb-4 rounded border border-rose-500/40 bg-rose-500/10 p-3 text-rose-200">{error}</div>}

      {editor && (
        <div className="card mb-6">
          <div className="mb-3 text-lg font-semibold">{editor.id ? "Edit Voice Source" : "Add Voice Source"}</div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <Field label="ID" value={editor.id} onChange={(v) => setEditor({ ...editor, id: slug(v) })} placeholder="office_panel" />
            <Field label="Name" value={editor.name} onChange={(v) => setEditor({ ...editor, name: v })} placeholder="Office Voice Panel" />
            <Select label="Room" value={editor.room} onChange={(v) => setEditor({ ...editor, room: v })} options={rooms.map((r: any) => [r.id, r.name])} />
            <Select label="Assistant" value={editor.assistant} onChange={(v) => setEditor({ ...editor, assistant: v })} options={assistants.map((a: any) => [a.id, a.name])} optional />
            <Select label="User" value={editor.user} onChange={(v) => setEditor({ ...editor, user: v })} options={users.map((u: any) => [u.id, u.name])} optional />
            <Select label="Trust" value={editor.trust_level} onChange={(v) => setEditor({ ...editor, trust_level: v })} options={[["trusted", "Trusted"], ["household", "Household"], ["guest", "Guest"], ["outside", "Outside"]]} />
            <Select label="Reply" value={editor.default_reply} onChange={(v) => setEditor({ ...editor, default_reply: v })} options={[["browser", "Browser"], ["room_speaker", "Room speaker"], ["quiet", "Quiet"], ["none", "None"]]} />
            <Select label="Speaker" value={editor.speaker} onChange={(v) => setEditor({ ...editor, speaker: v })} options={speakers.map((s: any) => [s.id, s.name])} optional />
            <Field label="Source Device ID" value={editor.source_device_id} onChange={(v) => setEditor({ ...editor, source_device_id: v })} placeholder="HA Assist device id" />
            <Field label="Source Entity ID" value={editor.source_entity_id} onChange={(v) => setEditor({ ...editor, source_entity_id: v })} placeholder="media_player.kitchen_display" />
            <Field label="Aliases" value={editor.aliases} onChange={(v) => setEditor({ ...editor, aliases: v })} placeholder="office mic, office panel" />
          </div>
          <div className="mt-4 flex gap-2">
            <button className="btn" onClick={saveSource} disabled={saving || !editor.name || !editor.room}>Save Voice Source</button>
            <button className="btn-ghost" onClick={() => setEditor(null)}>Cancel</button>
          </div>
        </div>
      )}

      <div className="mb-4 grid grid-cols-1 gap-4 md:grid-cols-3">
        <Stat label="Configured sources" value={items.length} />
        <Stat label="Deployment" value="assistant -> source -> room" />
        <Stat label="Generic command" value="room scoped" />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {items.map((source) => (
          <div key={source.id} className="card">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <div>
                <span className="text-lg font-semibold text-slate-100">{source.name}</span>
                <span className="badge ml-2 bg-cyan-500/10 text-cyan-200">{source.room}</span>
              </div>
              <button className="btn-ghost" onClick={() => editSource(source)}>Edit</button>
            </div>
            <div className="space-y-2 text-sm text-slate-300">
              <Row label="Source device" value={source.source_device_id || "not set"} />
              <Row label="Source entity" value={source.source_entity_id || "not set"} />
              <Row label="Assistant" value={source.assistant || "owner default"} />
              <Row label="User" value={source.user || "not set"} />
              <Row label="Trust" value={source.trust_level} />
              <Row label="Reply" value={source.default_reply} />
              <Row label="Speaker" value={source.speaker || source.resolved_reply_route?.target_entity_id || "not set"} />
              <Row label="Aliases" value={(source.aliases || []).join(", ") || "none"} />
            </div>
          </div>
        ))}
      </div>

      {items.length === 0 && <div className="card text-slate-500">No voice sources configured yet.</div>}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: any }) {
  return <div className="card"><div className="mb-1 text-xs uppercase text-slate-500">{label}</div><div className="text-xl font-semibold text-slate-100">{value}</div></div>;
}

function Field({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  return <label><div className="mb-1 text-xs uppercase text-slate-500">{label}</div><input className="input" value={value || ""} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} /></label>;
}

function Select({ label, value, onChange, options, optional = false }: { label: string; value: string; onChange: (value: string) => void; options: any[]; optional?: boolean }) {
  return (
    <label>
      <div className="mb-1 text-xs uppercase text-slate-500">{label}</div>
      <select className="input" value={value || ""} onChange={(e) => onChange(e.target.value)}>
        {optional && <option value="">None</option>}
        {options.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
      </select>
    </label>
  );
}

function Row({ label, value }: { label: string; value: any }) {
  return <div className="rounded border border-slate-800 bg-slate-950/30 px-3 py-2"><span className="text-slate-500">{label}:</span> <span className="font-mono">{value}</span></div>;
}

function csv(value: string) {
  return String(value || "").split(",").map((v) => v.trim()).filter(Boolean);
}

function slug(value: string) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}
