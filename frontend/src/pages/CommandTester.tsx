import { useEffect, useState } from "react";
import { api, CommandResponse } from "../api";
import Badge from "../components/Badge";
import Button from "../components/Button";
import DeveloperDetails from "../components/DeveloperDetails";
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
    <div className="page-stack">
      <PageHeader title="Command Tester" subtitle="Send natural language and inspect the friendly result, policy, and optional developer payload." />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(20rem,0.9fr)_minmax(0,1.1fr)]">
        <div className="card">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
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

          <div className="mt-3 flex flex-wrap gap-2">
            <Button onClick={send} disabled={loading}>
              {loading ? "Working…" : "Send command"}
            </Button>
            {resp?.requires_confirmation && resp.confirmation_token && (
              <>
                <Button variant="warning" onClick={confirm} disabled={loading}>
                  Confirm
                </Button>
                <Button variant="ghost" onClick={cancel} disabled={loading}>
                  Cancel
                </Button>
              </>
            )}
          </div>

          <div className="mt-4">
            <div className="mb-2 text-xs uppercase tracking-wide text-slate-500">Samples</div>
            <div className="flex flex-wrap gap-2">
              {SAMPLES.map((s) => (
                <button key={s} className="btn-ghost min-h-9 px-3 py-1.5 text-xs" onClick={() => setMessage(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="card">
          <div className="mb-3 text-lg font-semibold text-slate-100">Result</div>
          {error && <div className="text-rose-300">{error}</div>}
          {!resp && !error && <div className="text-slate-500">Send a command to see results.</div>}
          {resp && (
            <div className="space-y-3 text-sm">
              <Badge tone={resp.requires_confirmation ? "warn" : resp.success ? "good" : "danger"}>
                {resp.requires_confirmation
                  ? "needs confirmation"
                  : resp.success
                  ? resp.executed
                    ? "executed"
                    : "ok (not executed)"
                  : "failed"}
              </Badge>

              <div className="rounded-2xl border border-slate-800 bg-slate-950/45 p-4 text-slate-100">{resp.message}</div>

              {resp.requires_confirmation && (
                <div className="rounded-2xl border border-amber-500/40 bg-amber-500/10 p-4 text-amber-100">
                  <div className="font-semibold">Confirm action</div>
                  <div className="mt-1 text-sm">{resp.confirmation_message || "This action requires confirmation."}</div>
                </div>
              )}

              <Field label="Intent" value={resp.intent} />
              <Field label="Resolved entity" value={resp.resolved?.entity_id} />
              <Field label="Resolved target" value={resp.resolved?.label || resp.resolved?.target} />
              <Field label="Service" value={resp.data?.service_call ? `${resp.data.service_call.domain}.${resp.data.service_call.service}` : undefined} />
              <DeveloperDetails title="AI tool call" data={resp.tool_call} />
              <DeveloperDetails title="Resolved" data={resp.resolved} />
              {resp.data?.service_call && (
                <DeveloperDetails title="Home Assistant service call" data={resp.data.service_call} />
              )}
              {resp.data?.verification && (
                <DeveloperDetails title="Post-action verification" data={resp.data.verification} />
              )}
              {Object.keys(resp.data || {}).length > 0 && <DeveloperDetails title="Raw response data" data={resp.data} />}
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
    <div className="rounded-xl border border-slate-800 bg-slate-950/35 px-3 py-2">
      <span className="text-slate-500">{label}: </span>
      <span className="break-all font-mono text-brand">{String(value)}</span>
    </div>
  );
}
