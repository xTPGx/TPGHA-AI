import { useEffect, useState } from "react";
import { api } from "../api";
import Badge from "../components/Badge";
import Button from "../components/Button";
import PageHeader from "../components/PageHeader";

const emptyAccount = {
  id: "",
  name: "",
  provider: "spotify",
  account: "",
  owner: "",
  default_media_id: "",
  default_media_type: "playlist",
};

const emptySpeaker = {
  id: "",
  name: "",
  entity_id: "",
  music_assistant_entity_id: "",
  room: "",
  aliases: "",
};

export default function Music() {
  const [cfg, setCfg] = useState<any>(null);
  const [accountEditor, setAccountEditor] = useState<any | null>(null);
  const [speakerEditor, setSpeakerEditor] = useState<any | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  const load = async () => setCfg(await api.config());
  useEffect(() => { void load(); }, []);

  const accounts: Record<string, any> = cfg?.devices?.music_accounts ?? {};
  const speakers = cfg?.devices?.speakers ?? [];
  const users = cfg?.assistants?.users ?? [];
  const rooms = cfg?.devices?.rooms ?? [];
  const avoid: string[] = cfg?.devices?.avoid ?? [];

  const editAccount = (id?: string, account?: any) => {
    setMessage("");
    setAccountEditor(account ? {
      ...emptyAccount,
      ...account,
      id,
      default_media_id: account.default_media?.media_id || "",
      default_media_type: account.default_media?.media_type || "playlist",
    } : emptyAccount);
  };

  const editSpeaker = (speaker?: any) => {
    setMessage("");
    setSpeakerEditor(speaker ? {
      ...emptySpeaker,
      ...speaker,
      aliases: (speaker.aliases || []).join(", "),
    } : emptySpeaker);
  };

  const saveAccount = async () => {
    setSaving(true);
    setMessage("");
    try {
      const payload: Record<string, any> = {
        id: slug(accountEditor.id || accountEditor.name),
        name: accountEditor.name,
        provider: accountEditor.provider,
        account: accountEditor.account,
        owner: accountEditor.owner,
      };
      if (accountEditor.default_media_id) {
        payload.default_media = {
          media_id: accountEditor.default_media_id,
          media_type: accountEditor.default_media_type || "music",
        };
      }
      await api.saveMusicAccount(payload);
      await load();
      setAccountEditor(null);
      setMessage("Music account saved.");
    } catch (e: any) {
      setMessage(e.message || String(e));
    } finally {
      setSaving(false);
    }
  };

  const saveSpeaker = async () => {
    setSaving(true);
    setMessage("");
    try {
      await api.saveSpeaker({
        id: slug(speakerEditor.id || speakerEditor.name),
        name: speakerEditor.name,
        entity_id: speakerEditor.entity_id,
        music_assistant_entity_id: speakerEditor.music_assistant_entity_id || null,
        room: speakerEditor.room || null,
        aliases: csv(speakerEditor.aliases),
      });
      await load();
      setSpeakerEditor(null);
      setMessage("Speaker saved.");
    } catch (e: any) {
      setMessage(e.message || String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page-stack">
      <PageHeader
        title="Music"
        subtitle="Manage Music Assistant provider profiles, user ownership, defaults, and speaker room mapping."
        actions={<div className="flex flex-wrap gap-2"><Button variant="ghost" onClick={() => editSpeaker()}>Add Speaker</Button><Button onClick={() => editAccount()}>Add Account</Button></div>}
      />

      {message && <div className="mb-4 rounded border border-slate-700 bg-slate-950/40 p-3 text-sm text-slate-300">{message}</div>}

      {accountEditor && (
        <div className="card mb-6">
          <div className="mb-3 text-lg font-semibold">{accountEditor.id ? "Edit Music Account" : "Add Music Account"}</div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <Field label="ID" value={accountEditor.id} onChange={(v) => setAccountEditor({ ...accountEditor, id: slug(v) })} placeholder="spotify_shawn" />
            <Field label="Name" value={accountEditor.name} onChange={(v) => setAccountEditor({ ...accountEditor, name: v })} placeholder="Spotify [Shawn]" />
            <Field label="Provider" value={accountEditor.provider} onChange={(v) => setAccountEditor({ ...accountEditor, provider: v })} placeholder="spotify" />
            <Field label="Account" value={accountEditor.account} onChange={(v) => setAccountEditor({ ...accountEditor, account: v })} placeholder="spotify username/profile" />
            <Select label="Owner" value={accountEditor.owner} onChange={(v) => setAccountEditor({ ...accountEditor, owner: v })} options={users.map((u: any) => [u.id, u.name])} />
            <Field label="Default Media ID" value={accountEditor.default_media_id} onChange={(v) => setAccountEditor({ ...accountEditor, default_media_id: v })} placeholder="This Is Mitchell Tenpenny" />
            <Field label="Default Media Type" value={accountEditor.default_media_type} onChange={(v) => setAccountEditor({ ...accountEditor, default_media_type: v })} placeholder="playlist" />
          </div>
          <div className="mt-4 flex gap-2">
            <Button onClick={saveAccount} disabled={saving || !accountEditor.name || !accountEditor.owner || !accountEditor.account}>Save Account</Button>
            <Button variant="ghost" onClick={() => setAccountEditor(null)}>Cancel</Button>
          </div>
        </div>
      )}

      {speakerEditor && (
        <div className="card mb-6">
          <div className="mb-3 text-lg font-semibold">{speakerEditor.id ? "Edit Speaker" : "Add Speaker"}</div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <Field label="ID" value={speakerEditor.id} onChange={(v) => setSpeakerEditor({ ...speakerEditor, id: slug(v) })} placeholder="office_speaker" />
            <Field label="Name" value={speakerEditor.name} onChange={(v) => setSpeakerEditor({ ...speakerEditor, name: v })} placeholder="Office Speaker" />
            <Field label="Media Player Entity" value={speakerEditor.entity_id} onChange={(v) => setSpeakerEditor({ ...speakerEditor, entity_id: v })} placeholder="media_player.office_speaker" />
            <Field label="Music Assistant Entity" value={speakerEditor.music_assistant_entity_id} onChange={(v) => setSpeakerEditor({ ...speakerEditor, music_assistant_entity_id: v })} placeholder="optional override" />
            <Select label="Room" value={speakerEditor.room} onChange={(v) => setSpeakerEditor({ ...speakerEditor, room: v })} options={rooms.map((r: any) => [r.id, r.name])} optional />
            <Field label="Aliases" value={speakerEditor.aliases} onChange={(v) => setSpeakerEditor({ ...speakerEditor, aliases: v })} placeholder="office speaker, office audio" />
          </div>
          <div className="mt-4 flex gap-2">
            <Button onClick={saveSpeaker} disabled={saving || !speakerEditor.name || !speakerEditor.entity_id}>Save Speaker</Button>
            <Button variant="ghost" onClick={() => setSpeakerEditor(null)}>Cancel</Button>
          </div>
        </div>
      )}

      <div className="card mb-6">
        <div className="mb-3 text-lg font-semibold text-slate-100">Music Assistant accounts</div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {Object.entries(accounts).map(([key, a]) => (
            <div key={key} className="rounded-2xl border border-slate-700 bg-slate-950/40 p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="font-semibold text-brand">{a.name}</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Badge>{a.provider}</Badge>
                    <Badge>owner: {a.owner}</Badge>
                  </div>
                  <div className="mt-2 break-all text-xs text-slate-400">account: {a.account}</div>
                  {a.default_media?.media_id && <div className="mt-1 text-xs text-slate-400">default: {a.default_media.media_type} · {a.default_media.media_id}</div>}
                  <div className="mt-1 break-all font-mono text-[10px] text-slate-500">{key}</div>
                </div>
                <Button variant="ghost" onClick={() => editAccount(key, a)}>Edit</Button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="card mb-6">
        <div className="mb-3 text-lg font-semibold text-slate-100">Speakers to rooms</div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[42rem] text-left text-sm">
            <thead className="border-b border-slate-700 text-slate-400">
              <tr>
                <th className="py-2">Speaker</th>
                <th className="py-2">Entity</th>
                <th className="py-2">Room</th>
                <th className="py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {speakers.map((s: any) => (
                <tr key={s.id} className="border-b border-slate-800/70">
                  <td className="py-2">{s.name}</td>
                  <td className="break-all py-2 font-mono text-xs text-brand">{s.music_assistant_entity_id || s.entity_id}</td>
                  <td className="py-2 text-slate-400">{s.room ?? "none"}</td>
                  <td className="py-2"><Button variant="ghost" onClick={() => editSpeaker(s)}>Edit</Button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {avoid.length > 0 && (
        <div className="card">
          <div className="mb-2 text-sm font-medium text-rose-300">Avoided dead or duplicate players</div>
          <div className="flex flex-wrap gap-2">
            {avoid.map((e) => <Badge key={e} tone="danger" className="font-mono">{e}</Badge>)}
          </div>
        </div>
      )}
    </div>
  );
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
        {!optional && <option value="">Select</option>}
        {options.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
      </select>
    </label>
  );
}

function csv(value: string) {
  return String(value || "").split(",").map((v) => v.trim()).filter(Boolean);
}

function slug(value: string) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}
