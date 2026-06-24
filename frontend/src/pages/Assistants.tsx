import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

const emptyAssistant = {
  id: "",
  name: "",
  owner: "",
  aliases: "",
  tone: "confident",
  personality: "",
  voice_provider: "openai",
  voice: "cedar",
  voice_instructions: "",
};

export default function Assistants() {
  const [cfg, setCfg] = useState<any>(null);
  const [editor, setEditor] = useState<any | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  const load = async () => setCfg(await api.config());
  useEffect(() => { void load(); }, []);

  const assistants = cfg?.assistants?.assistants ?? [];
  const users = cfg?.assistants?.users ?? [];
  const accounts = cfg?.devices?.music_accounts ?? {};
  const userById = (id: string) => users.find((u: any) => u.id === id);

  const editAssistant = (assistant?: any) => {
    const voice = typeof assistant?.voice === "object" ? assistant.voice : {};
    setMessage("");
    setEditor(assistant ? {
      ...emptyAssistant,
      ...assistant,
      aliases: (assistant.aliases ?? []).join(", "),
      voice_provider: voice.provider || "openai",
      voice: voice.voice || (assistant.id === "chatty" ? "coral" : "cedar"),
      voice_instructions: voice.instructions || "",
    } : emptyAssistant);
  };

  const saveAssistant = async () => {
    setSaving(true);
    setMessage("");
    try {
      const payload = {
        id: slug(editor.id || editor.name),
        name: editor.name,
        owner: editor.owner,
        aliases: csv(editor.aliases),
        tone: editor.tone,
        personality: editor.personality,
        voice: {
          provider: editor.voice_provider,
          model: "gpt-4o-mini-tts",
          voice: editor.voice,
          response_format: "mp3",
          output: "browser",
          fallback_provider: "browser",
          instructions: editor.voice_instructions,
        },
      };
      await api.saveAssistant(payload);
      await load();
      setEditor(null);
      setMessage("Assistant saved.");
    } catch (e: any) {
      setMessage(e.message || String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Assistants"
        subtitle="Create and tune assistant identity, ownership, personality, and voice."
        actions={<button className="btn" onClick={() => editAssistant()}>Add Assistant</button>}
      />

      {message && <div className="mb-4 rounded border border-slate-700 bg-slate-950/40 p-3 text-sm text-slate-300">{message}</div>}

      {editor && (
        <div className="card mb-6">
          <div className="mb-3 text-lg font-semibold">{editor.id ? "Edit Assistant" : "Add Assistant"}</div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <Field label="ID" value={editor.id} onChange={(v) => setEditor({ ...editor, id: slug(v) })} placeholder="atlas" />
            <Field label="Name" value={editor.name} onChange={(v) => setEditor({ ...editor, name: v })} placeholder="Atlas" />
            <label>
              <div className="mb-1 text-xs uppercase text-slate-500">Owner</div>
              <select className="input" value={editor.owner} onChange={(e) => setEditor({ ...editor, owner: e.target.value })}>
                <option value="">Select owner</option>
                {users.map((u: any) => <option key={u.id} value={u.id}>{u.name}</option>)}
              </select>
            </label>
            <Field label="Tone" value={editor.tone} onChange={(v) => setEditor({ ...editor, tone: v })} placeholder="confident" />
            <Field label="Aliases" value={editor.aliases} onChange={(v) => setEditor({ ...editor, aliases: v })} placeholder="atlas, house" />
            <label>
              <div className="mb-1 text-xs uppercase text-slate-500">Voice</div>
              <select className="input" value={editor.voice} onChange={(e) => setEditor({ ...editor, voice: e.target.value })}>
                {["cedar", "coral", "nova", "onyx", "marin", "sage", "verse", "ballad", "ash", "echo", "fable", "shimmer"].map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            </label>
            <label className="md:col-span-2">
              <div className="mb-1 text-xs uppercase text-slate-500">Personality</div>
              <textarea className="input min-h-24" value={editor.personality} onChange={(e) => setEditor({ ...editor, personality: e.target.value })} />
            </label>
            <label className="md:col-span-2">
              <div className="mb-1 text-xs uppercase text-slate-500">Voice instructions</div>
              <textarea className="input min-h-20" value={editor.voice_instructions} onChange={(e) => setEditor({ ...editor, voice_instructions: e.target.value })} />
            </label>
          </div>
          <div className="mt-4 flex gap-2">
            <button className="btn" onClick={saveAssistant} disabled={saving || !editor.name || !editor.owner}>Save Assistant</button>
            <button className="btn-ghost" onClick={() => setEditor(null)}>Cancel</button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {assistants.map((a: any) => {
          const owner = userById(a.owner);
          const acct = owner?.music_account ? accounts[owner.music_account] : null;
          const voice = typeof a.voice === "object" ? a.voice : { voice: a.voice };
          return (
            <div key={a.id} className="card">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-xl font-bold text-brand">{a.name}</div>
                  <span className="badge bg-slate-700 text-slate-300">{a.tone}</span>
                </div>
                <button className="btn-ghost" onClick={() => editAssistant(a)}>Edit</button>
              </div>
              <p className="mt-2 text-sm text-slate-300">{a.personality}</p>
              <dl className="mt-4 space-y-1 text-sm">
                <Row label="Owner" value={owner ? owner.name : a.owner} />
                <Row label="Voice" value={`${voice.provider || "browser"} / ${voice.voice || "default"}`} />
                <Row label="Music account" value={acct ? acct.name : owner?.music_account} />
                <Row label="Aliases" value={(a.aliases ?? []).join(", ")} />
              </dl>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Field({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  return (
    <label>
      <div className="mb-1 text-xs uppercase text-slate-500">{label}</div>
      <input className="input" value={value || ""} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
    </label>
  );
}

function Row({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-slate-200">{value}</dd>
    </div>
  );
}

function csv(value: string) {
  return String(value || "").split(",").map((v) => v.trim()).filter(Boolean);
}

function slug(value: string) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}
