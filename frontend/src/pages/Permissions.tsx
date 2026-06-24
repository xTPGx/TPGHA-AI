import { useEffect, useState } from "react";
import { api } from "../api";
import Button from "../components/Button";
import PageHeader from "../components/PageHeader";
import ToggleRow from "../components/ToggleRow";

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

const defaultSensitive = [
  "unlock_door",
  "open_garage",
  "disarm_alarm",
  "disable_camera",
  "disable_security",
  "change_lock_code",
  "disable_notifications",
  "remove_device",
  "delete_automation",
];

export default function Permissions() {
  const [cfg, setCfg] = useState<any>(null);
  const [editor, setEditor] = useState<any | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  const load = async () => setCfg(await api.config());
  useEffect(() => { void load(); }, []);

  const p = cfg?.permissions ?? {};
  const sensitive: string[] = p.sensitive_actions ?? [];
  const messages: Record<string, string> = p.confirmation_messages ?? {};

  const editPermissions = () => {
    const defaults: Record<string, boolean> = {};
    for (const key of PERMISSION_KEYS) defaults[key] = Boolean(p.defaults?.[key]);
    setMessage("");
    setEditor({
      sensitive_actions: (sensitive.length ? sensitive : defaultSensitive).join(", "),
      confirmation_messages: { ...messages },
      confirmation_ttl_seconds: p.confirmation_ttl_seconds ?? 60,
      defaults,
      enforce_music_account_ownership: p.enforce_music_account_ownership !== false,
      security_pin: "",
    });
  };

  const save = async () => {
    setSaving(true);
    setMessage("");
    try {
      const sensitiveActions = csv(editor.sensitive_actions);
      const confirmationMessages: Record<string, string> = {};
      for (const action of sensitiveActions) {
        confirmationMessages[action] = editor.confirmation_messages?.[action] || defaultMessage(action);
      }
      await api.savePermissions({
        sensitive_actions: sensitiveActions,
        confirmation_messages: confirmationMessages,
        confirmation_ttl_seconds: Number(editor.confirmation_ttl_seconds) || 60,
        defaults: editor.defaults,
        enforce_music_account_ownership: Boolean(editor.enforce_music_account_ownership),
        security_pin: editor.security_pin || p.security_pin || null,
      });
      await load();
      setEditor(null);
      setMessage("Permissions saved.");
    } catch (e: any) {
      setMessage(e.message || String(e));
    } finally {
      setSaving(false);
    }
  };

  const editorActions = csv(editor?.sensitive_actions || "");

  return (
    <div className="page-stack">
      <PageHeader
        title="Permissions"
        subtitle="Control what can execute immediately, what needs confirmation, and which security actions require extra trust."
        actions={<Button onClick={editPermissions}>Edit Policy</Button>}
      />

      {message && <div className="rounded-xl border border-slate-700 bg-slate-950/40 p-3 text-sm text-slate-300">{message}</div>}

      {editor && (
        <div className="card">
          <div className="mb-3 text-lg font-semibold">Edit Permissions Policy</div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <label className="md:col-span-2">
              <div className="mb-1 text-xs uppercase text-slate-500">Sensitive Actions</div>
              <textarea className="input min-h-24" value={editor.sensitive_actions} onChange={(e) => setEditor({ ...editor, sensitive_actions: e.target.value })} />
            </label>
            <Field label="Confirmation TTL seconds" value={String(editor.confirmation_ttl_seconds)} onChange={(v) => setEditor({ ...editor, confirmation_ttl_seconds: v })} />
            <label>
              <div className="mb-1 text-xs uppercase text-slate-500">Security PIN</div>
              <input className="input" type="password" value={editor.security_pin} onChange={(e) => setEditor({ ...editor, security_pin: e.target.value })} placeholder={p.security_pin ? "configured; leave blank to keep" : "optional"} />
            </label>
            <ToggleRow
              label="Music account ownership"
              description="Keep each assistant tied to its assigned music profile."
              checked={editor.enforce_music_account_ownership}
              onChange={(checked) => setEditor({ ...editor, enforce_music_account_ownership: checked })}
            />
          </div>

          <div className="mt-5">
            <div className="mb-2 text-sm font-semibold text-slate-200">Default Permissions</div>
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
              {PERMISSION_KEYS.map((key) => (
                <ToggleRow
                  key={key}
                  label={label(key)}
                  checked={Boolean(editor.defaults[key])}
                  onChange={(checked) => setEditor({ ...editor, defaults: { ...editor.defaults, [key]: checked } })}
                />
              ))}
            </div>
          </div>

          <div className="mt-5">
            <div className="mb-2 text-sm font-semibold text-slate-200">Confirmation Messages</div>
            <div className="space-y-2">
              {editorActions.map((action) => (
                <label key={action} className="grid grid-cols-1 gap-2 rounded border border-slate-800 bg-slate-950/30 p-3 md:grid-cols-[180px_1fr]">
                  <span className="font-mono text-sm text-amber-300">{action}</span>
                  <input
                    className="input"
                    value={editor.confirmation_messages[action] || defaultMessage(action)}
                    onChange={(e) => setEditor({ ...editor, confirmation_messages: { ...editor.confirmation_messages, [action]: e.target.value } })}
                  />
                </label>
              ))}
            </div>
          </div>

          <div className="mt-4 flex gap-2">
            <Button onClick={save} disabled={saving}>Save Policy</Button>
            <Button variant="ghost" onClick={() => setEditor(null)}>Cancel</Button>
          </div>
        </div>
      )}

      <div className="card">
        <div className="mb-2 text-sm font-medium text-slate-300">Sensitive actions requiring confirmation</div>
        <div className="space-y-2">
          {sensitive.map((a) => (
            <div key={a} className="flex items-center justify-between rounded-lg bg-slate-900/50 px-3 py-2">
              <span className="font-mono text-amber-300">{a}</span>
              <span className="text-sm text-slate-400">{messages[a] ?? "Confirm?"}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="card">
          <div className="mb-2 text-sm font-medium text-slate-300">Default permissions</div>
          <div className="grid grid-cols-1 gap-2 text-sm">
            {Object.entries(p.defaults ?? {})
              .filter(([, v]) => v !== null && v !== undefined)
              .map(([k, v]) => (
                <div key={k} className="flex items-center justify-between rounded bg-slate-900/50 px-2 py-1">
                  <span className="text-slate-400">{label(k)}</span>
                  <span className={v ? "text-emerald-400" : "text-rose-400"}>{v ? "allowed" : "denied"}</span>
                </div>
              ))}
          </div>
        </div>
        <div className="card">
          <div className="mb-2 text-sm font-medium text-slate-300">Policy</div>
          <dl className="space-y-1 text-sm">
            <Row label="Confirmation TTL" value={`${p.confirmation_ttl_seconds ?? 60}s`} />
            <Row label="Music account ownership" value={p.enforce_music_account_ownership !== false ? "enforced" : "off"} />
            <Row label="Security PIN" value={p.security_pin ? "configured" : "not configured"} />
          </dl>
          <p className="mt-3 text-xs text-slate-500">
            Low-risk, confident actions can execute immediately. Critical actions like unlock, garage open, and disarm stay gated.
          </p>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label><div className="mb-1 text-xs uppercase text-slate-500">{label}</div><input className="input" value={value || ""} onChange={(e) => onChange(e.target.value)} /></label>;
}

function Row({ label, value }: { label: string; value: string }) {
  return <div className="flex justify-between"><dt className="text-slate-500">{label}</dt><dd className="text-slate-200">{value}</dd></div>;
}

function csv(value: string) {
  return String(value || "").split(",").map((v) => v.trim()).filter(Boolean);
}

function label(value: string) {
  return value.replace(/^can_/, "").replace(/_/g, " ");
}

function defaultMessage(action: string) {
  return `Confirm: run ${action.replace(/_/g, " ")} on {target}?`;
}
