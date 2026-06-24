import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

const PERMISSION_KEYS = [
  "can_unlock_doors",
  "can_open_garage",
  "can_disarm_alarm",
  "can_lock_doors",
  "can_control_lights",
  "can_control_fans",
  "can_control_climate",
  "can_control_music",
  "can_control_covers",
  "can_view_cameras",
];

const emptyUser = {
  id: "",
  name: "",
  role: "resident",
  aliases: "",
  music_account: "",
  permissions: {} as Record<string, boolean | "inherit">,
};

export default function Users() {
  const [cfg, setCfg] = useState<any>(null);
  const [editor, setEditor] = useState<any | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  const load = async () => setCfg(await api.config());
  useEffect(() => { void load(); }, []);

  const users = cfg?.assistants?.users ?? [];
  const accounts = cfg?.devices?.music_accounts ?? {};
  const defaults = cfg?.permissions?.defaults ?? {};

  const editUser = (user?: any) => {
    setMessage("");
    const permissions: Record<string, boolean | "inherit"> = {};
    for (const key of PERMISSION_KEYS) {
      permissions[key] = user?.permissions?.[key] ?? "inherit";
    }
    setEditor(user ? {
      ...emptyUser,
      ...user,
      aliases: (user.aliases ?? []).join(", "),
      music_account: user.music_account || "",
      permissions,
    } : { ...emptyUser, permissions });
  };

  const saveUser = async () => {
    setSaving(true);
    setMessage("");
    try {
      const permissions: Record<string, boolean> = {};
      for (const [key, value] of Object.entries(editor.permissions || {})) {
        if (value !== "inherit") permissions[key] = Boolean(value);
      }
      await api.saveUser({
        id: slug(editor.id || editor.name),
        name: editor.name,
        role: editor.role || "resident",
        aliases: csv(editor.aliases),
        music_account: editor.music_account || null,
        permissions,
      });
      await load();
      setEditor(null);
      setMessage("User saved.");
    } catch (e: any) {
      setMessage(e.message || String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Users"
        subtitle="Manage household people, aliases, music accounts, and per-user control permissions."
        actions={<button className="btn" onClick={() => editUser()}>Add User</button>}
      />

      {message && <div className="mb-4 rounded border border-slate-700 bg-slate-950/40 p-3 text-sm text-slate-300">{message}</div>}

      {editor && (
        <div className="card mb-6">
          <div className="mb-3 text-lg font-semibold">{editor.id ? "Edit User" : "Add User"}</div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <Field label="ID" value={editor.id} onChange={(v) => setEditor({ ...editor, id: slug(v) })} placeholder="shawn" />
            <Field label="Name" value={editor.name} onChange={(v) => setEditor({ ...editor, name: v })} placeholder="Shawn" />
            <label>
              <div className="mb-1 text-xs uppercase text-slate-500">Role</div>
              <select className="input" value={editor.role || "resident"} onChange={(e) => setEditor({ ...editor, role: e.target.value })}>
                <option value="admin">Admin</option>
                <option value="manager">Manager</option>
                <option value="resident">Resident</option>
                <option value="kiosk">Kiosk / Shared</option>
                <option value="guest">Guest</option>
              </select>
            </label>
            <Field label="Aliases" value={editor.aliases} onChange={(v) => setEditor({ ...editor, aliases: v })} placeholder="shawn, boss, owner" />
            <label>
              <div className="mb-1 text-xs uppercase text-slate-500">Music Account</div>
              <select className="input" value={editor.music_account} onChange={(e) => setEditor({ ...editor, music_account: e.target.value })}>
                <option value="">None</option>
                {Object.entries(accounts).map(([id, account]: [string, any]) => (
                  <option key={id} value={id}>{account.name}</option>
                ))}
              </select>
            </label>
          </div>

          <div className="mt-5">
            <div className="mb-2 text-sm font-semibold text-slate-200">Permissions</div>
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
              {PERMISSION_KEYS.map((key) => (
                <label key={key} className="flex items-center justify-between gap-3 rounded border border-slate-800 bg-slate-950/30 px-3 py-2">
                  <span className="text-sm text-slate-300">{label(key)}</span>
                  <select
                    className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
                    value={String(editor.permissions[key] ?? "inherit")}
                    onChange={(e) => setEditor({
                      ...editor,
                      permissions: { ...editor.permissions, [key]: e.target.value === "inherit" ? "inherit" : e.target.value === "true" },
                    })}
                  >
                    <option value="inherit">Inherit ({defaults[key] ? "allowed" : "denied"})</option>
                    <option value="true">Allowed</option>
                    <option value="false">Denied</option>
                  </select>
                </label>
              ))}
            </div>
          </div>

          <div className="mt-4 flex gap-2">
            <button className="btn" onClick={saveUser} disabled={saving || !editor.name}>Save User</button>
            <button className="btn-ghost" onClick={() => setEditor(null)}>Cancel</button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {users.map((u: any) => {
          const acct = u.music_account ? accounts[u.music_account] : null;
          const perms = { ...defaults, ...u.permissions };
          return (
            <div key={u.id} className="card">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-xl font-bold">{u.name}</div>
                  <div className="mt-1 text-sm text-slate-400">
                    Role: {u.role || "resident"} · Music: {acct ? acct.name : u.music_account ?? "none"}
                  </div>
                </div>
                <button className="btn-ghost" onClick={() => editUser(u)}>Edit</button>
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {(u.aliases ?? []).map((a: string) => <span key={a} className="badge bg-slate-700 text-slate-300">{a}</span>)}
              </div>
              <div className="mt-4 grid grid-cols-2 gap-2 text-sm">
                {Object.entries(perms)
                  .filter(([, v]) => v !== null && v !== undefined)
                  .map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between rounded bg-slate-900/50 px-2 py-1">
                      <span className="text-slate-400">{label(k)}</span>
                      <span className={v ? "text-emerald-400" : "text-rose-400"}>{v ? "yes" : "no"}</span>
                    </div>
                  ))}
              </div>
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

function csv(value: string) {
  return String(value || "").split(",").map((v) => v.trim()).filter(Boolean);
}

function slug(value: string) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

function label(value: string) {
  return value.replace(/^can_/, "").replace(/_/g, " ");
}
