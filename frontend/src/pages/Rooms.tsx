import { useEffect, useState } from "react";
import { api } from "../api";
import Button from "../components/Button";
import DeveloperDetails from "../components/DeveloperDetails";
import PageHeader from "../components/PageHeader";

const emptyRoom = {
  id: "",
  name: "",
  aliases: "",
  speaker: "",
  camera: "",
  display: "",
  lock: "",
  climate: "",
  lights: "",
  fans: "",
};

export default function Rooms() {
  const [cfg, setCfg] = useState<any>(null);
  const [test, setTest] = useState("driveway");
  const [result, setResult] = useState<any>(null);
  const [editor, setEditor] = useState<any | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  const load = async () => setCfg(await api.config());

  useEffect(() => {
    void load();
  }, []);

  const runResolve = async () => setResult(await api.resolve("room", test));
  const rooms = cfg?.devices?.rooms ?? [];

  const editRoom = (room?: any) => {
    setMessage("");
    setEditor(room ? {
      ...emptyRoom,
      ...room,
      aliases: (room.aliases ?? []).join(", "),
      lights: (room.lights ?? []).join(", "),
      fans: (room.fans ?? []).join(", "),
    } : emptyRoom);
  };

  const saveRoom = async () => {
    setSaving(true);
    setMessage("");
    try {
      const payload = {
        ...editor,
        id: slug(editor.id || editor.name),
        aliases: csv(editor.aliases),
        lights: csv(editor.lights),
        fans: csv(editor.fans),
      };
      await api.saveRoom(payload);
      await load();
      setEditor(null);
      setMessage("Room saved.");
    } catch (e: any) {
      setMessage(e.message || String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page-stack">
      <PageHeader
        title="Rooms"
        subtitle="Room aliases and their assigned speaker, camera, display, lock, lights, fans, and climate."
        actions={<Button onClick={() => editRoom()}>Add Room</Button>}
      />

      {message && <div className="mb-4 rounded border border-slate-700 bg-slate-950/40 p-3 text-sm text-slate-300">{message}</div>}

      {editor && (
        <div className="card mb-6">
          <div className="mb-3 text-lg font-semibold">{editor.id ? "Edit Room" : "Add Room"}</div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <Field label="ID" value={editor.id} onChange={(v) => setEditor({ ...editor, id: slug(v) })} placeholder="office" />
            <Field label="Name" value={editor.name} onChange={(v) => setEditor({ ...editor, name: v })} placeholder="Office" />
            <Field label="Aliases" value={editor.aliases} onChange={(v) => setEditor({ ...editor, aliases: v })} placeholder="office, my office, study" />
            <Field label="Speaker" value={editor.speaker} onChange={(v) => setEditor({ ...editor, speaker: v })} placeholder="media_player.office_speaker" />
            <Field label="Camera" value={editor.camera} onChange={(v) => setEditor({ ...editor, camera: v })} placeholder="camera.front_door" />
            <Field label="Display" value={editor.display} onChange={(v) => setEditor({ ...editor, display: v })} placeholder="media_player.office_tv" />
            <Field label="Lock" value={editor.lock} onChange={(v) => setEditor({ ...editor, lock: v })} placeholder="lock.front_door" />
            <Field label="Climate" value={editor.climate} onChange={(v) => setEditor({ ...editor, climate: v })} placeholder="climate.living_room" />
            <Field label="Lights" value={editor.lights} onChange={(v) => setEditor({ ...editor, lights: v })} placeholder="light.office, light.office_hex_lights" />
            <Field label="Fans" value={editor.fans} onChange={(v) => setEditor({ ...editor, fans: v })} placeholder="fan.office" />
          </div>
          <div className="mt-4 flex gap-2">
            <Button onClick={saveRoom} disabled={saving || !editor.name}>Save Room</Button>
            <Button variant="ghost" onClick={() => setEditor(null)}>Cancel</Button>
          </div>
        </div>
      )}

      <div className="card mb-6">
        <div className="mb-2 text-sm font-medium text-slate-300">Resolve a room</div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input className="input sm:max-w-xs" value={test} onChange={(e) => setTest(e.target.value)} />
          <Button onClick={runResolve}>Resolve</Button>
        </div>
        {result && <div className="mt-3"><DeveloperDetails title="Resolve details" data={result} /></div>}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {rooms.map((r: any) => (
          <div key={r.id} className="card">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-lg font-semibold">{r.name}</div>
                <span className="badge bg-slate-700 text-slate-300">{r.id}</span>
              </div>
              <Button variant="ghost" onClick={() => editRoom(r)}>Edit</Button>
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {(r.aliases ?? []).map((a: string) => <span key={a} className="badge bg-brand-dark/20 text-brand">{a}</span>)}
            </div>
            <dl className="mt-3 space-y-1 text-sm">
              <Row label="Speaker" value={r.speaker} />
              <Row label="Camera" value={r.camera} />
              <Row label="Display" value={r.display} />
              <Row label="Lock" value={r.lock} />
              <Row label="Lights" value={(r.lights ?? []).join(", ")} />
              <Row label="Fans" value={(r.fans ?? []).join(", ")} />
              <Row label="Climate" value={r.climate} />
            </dl>
          </div>
        ))}
      </div>
    </div>
  );
}

function Field({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  return (
    <label className="block">
      <div className="mb-1 text-xs uppercase text-slate-500">{label}</div>
      <input className="input" value={value || ""} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
    </label>
  );
}

function Row({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div className="flex min-w-0 justify-between gap-2">
      <dt className="text-slate-500">{label}</dt>
      <dd className="min-w-0 break-all text-right font-mono text-xs text-slate-300">{value}</dd>
    </div>
  );
}

function csv(value: string) {
  return String(value || "").split(",").map((v) => v.trim()).filter(Boolean);
}

function slug(value: string) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}
