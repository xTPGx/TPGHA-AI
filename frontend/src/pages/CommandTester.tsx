import { useEffect, useState } from "react";
import { api, CommandResponse } from "../api";
import PageHeader from "../components/PageHeader";

const SAMPLES = [
  "Is the front door locked?",
  "Show me the driveway.",
  "Show me the front door.",
  "Play my music in the office.",
  "Play my music in the kitchen.",
  "Play music everywhere.",
  "Unlock the front door.",
  "Lock up the house.",
  "Set the thermostat to cool 75.",
  "Turn off office fan.",
  "Turn on bedroom fan.",
  "Set office fan to 50%.",
  "What cameras are online?",
  "Turn off office light.",
  "Turn on office hex lights.",
  "What is the office light?",
  "At 7 AM turn on the kitchen lights.",
];

export default function CommandTester() {
  const [assistants, setAssistants] = useState<any[]>([]);
  const [users, setUsers] = useState<any[]>([]);
  const [assistant, setAssistant] = useState("atlas");
  const [user, setUser] = useState("shawn");
  const [message, setMessage] = useState("Show me the driveway.");
  const [loading, setLoading] = useState(false);
  const [resp, setResp] = useState<CommandResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.config().then((cfg) => {
      setAssistants(cfg.assistants.assistants || []);
      setUsers(cfg.assistants.users || []);
    });
  }, []);

  // When the assistant changes, default the user to its owner.
  useEffect(() => {
    const a = assistants.find((x) => x.id === assistant);
    if (a?.owner) setUser(a.owner);
  }, [assistant, assistants]);

  const send = async () => {
    setLoading(true);
    setError(null);
    setResp(null);
    try {
      const r = await api.command(assistant, user, message);
      setResp(r);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const confirm = async () => {
    if (!resp?.confirmation_token) return;
    setLoading(true);
    try {
      const r = await api.confirm(resp.confirmation_token);
      setResp(r);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const cancel = async () => {
    if (!resp?.confirmation_token) return;
    setLoading(true);
    try {
      const r = await api.cancelConfirm(resp.confirmation_token);
      setResp(r);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <PageHeader title="Command Tester" subtitle="Send natural language → see the tool call, resolution, and result" />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="card">
          <div className="grid grid-cols-2 gap-3">
            <label className="text-sm">
              <span className="mb-1 block text-slate-400">Assistant</span>
              <select className="input" value={assistant} onChange={(e) => setAssistant(e.target.value)}>
                {assistants.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-slate-400">User</span>
              <select className="input" value={user} onChange={(e) => setUser(e.target.value)}>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="mt-3 block text-sm">
            <span className="mb-1 block text-slate-400">Command</span>
            <textarea
              className="input h-24 resize-none"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send();
              }}
            />
          </label>

          <div className="mt-3 flex gap-2">
            <button className="btn" onClick={send} disabled={loading}>
              {loading ? "Working…" : "Send command"}
            </button>
            {resp?.requires_confirmation && resp.confirmation_token && (
              <>
                <button className="btn bg-amber-600 hover:bg-amber-500" onClick={confirm} disabled={loading}>
                  Confirm
                </button>
                <button className="btn-ghost" onClick={cancel} disabled={loading}>
                  Cancel
                </button>
              </>
            )}
          </div>

          <div className="mt-4">
            <div className="mb-2 text-xs uppercase tracking-wide text-slate-500">Samples</div>
            <div className="flex flex-wrap gap-2">
              {SAMPLES.map((s) => (
                <button key={s} className="btn-ghost text-xs" onClick={() => setMessage(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="card">
          <div className="mb-2 text-sm font-medium text-slate-300">Result</div>
          {error && <div className="text-rose-300">{error}</div>}
          {!resp && !error && <div className="text-slate-500">Send a command to see results.</div>}
          {resp && (
            <div className="space-y-3 text-sm">
              <div
                className={`badge ${
                  resp.requires_confirmation
                    ? "bg-amber-500/20 text-amber-300"
                    : resp.success
                    ? "bg-emerald-500/20 text-emerald-300"
                    : "bg-rose-500/20 text-rose-300"
                }`}
              >
                {resp.requires_confirmation
                  ? "needs confirmation"
                  : resp.success
                  ? resp.executed
                    ? "executed"
                    : "ok (not executed)"
                  : "failed"}
              </div>

              <div className="text-slate-200">{resp.message}</div>

              {resp.requires_confirmation && (
                <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-amber-200">
                  {resp.confirmation_message || "This action requires confirmation."}
                </div>
              )}

              <Field label="Intent" value={resp.intent} />
              <Field label="Resolved entity" value={resp.resolved?.entity_id} />
              <Block label="AI tool call" value={resp.tool_call} />
              <Block label="Resolved" value={resp.resolved} />
              {resp.data?.service_call && (
                <Block label="Home Assistant service call" value={resp.data.service_call} />
              )}
              {resp.data?.verification && (
                <Block label="Post-action verification" value={resp.data.verification} />
              )}
              {Object.keys(resp.data || {}).length > 0 && <Block label="Data" value={resp.data} />}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: any }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <div>
      <span className="text-slate-500">{label}: </span>
      <span className="font-mono text-brand">{String(value)}</span>
    </div>
  );
}

function Block({ label, value }: { label: string; value: any }) {
  if (!value || (typeof value === "object" && Object.keys(value).length === 0)) return null;
  return (
    <div>
      <div className="mb-1 text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <pre className="overflow-auto rounded-lg bg-slate-950/70 p-3 text-xs text-slate-300">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}
