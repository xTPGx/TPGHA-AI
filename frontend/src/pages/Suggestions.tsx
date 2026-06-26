import { useEffect, useState } from "react";
import { api } from "../api";
import Badge from "../components/Badge";
import Button from "../components/Button";
import DeveloperDetails from "../components/DeveloperDetails";
import PageHeader from "../components/PageHeader";

export default function Suggestions() {
  const [drafts, setDrafts] = useState<any[]>([]);
  const [proactive, setProactive] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [editYaml, setEditYaml] = useState("");

  const load = async () => {
    try {
      const [draftResult, proactiveResult] = await Promise.all([
        api.suggestions(),
        api.proactiveSuggestions(),
      ]);
      setDrafts(draftResult.suggestions || []);
      setProactive(
        (proactiveResult.suggestions || []).filter((s: any) =>
          ["suggested", "draft", "edited"].includes(s.status || "suggested"),
        ),
      );
      setError(null);
    } catch (e: any) {
      setError(e.message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const actDraft = async (id: number, fn: "approve" | "ignore") => {
    setBusy(`draft:${id}`);
    setError(null);
    try {
      if (fn === "approve") await api.approveDraft(id);
      else await api.ignoreDraft(id);
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const startEdit = (draft: any) => {
    setEditing(draft.id);
    setEditYaml(draft.proposed_yaml || "");
  };

  const saveEdit = async (draft: any) => {
    setBusy(`edit:${draft.id}`);
    setError(null);
    try {
      await api.editDraft(draft.id, {
        proposed_yaml: editYaml,
        trigger_description: draft.trigger_description,
        action_description: draft.action_description,
        status: "edited",
      });
      setEditing(null);
      setEditYaml("");
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const actProactive = async (id: number, fn: "approve" | "ignore") => {
    setBusy(`proactive:${id}`);
    setError(null);
    try {
      if (fn === "approve") await api.approveProactiveSuggestion(id);
      else await api.ignoreProactiveSuggestion(id);
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="page-stack">
      <PageHeader title="Suggestions" subtitle="Review timers, routines, and automation drafts before anything permanent happens" />

      {error && <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-rose-200">{error}</div>}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Stat label="Automation drafts" value={drafts.length} />
        <Stat label="Proactive/repair" value={proactive.length} />
        <Stat label="Approval model" value="human gated" />
      </div>

      <div className="space-y-4">
        {drafts.length === 0 && proactive.length === 0 && <div className="card text-slate-500">No pending suggestions.</div>}

        {proactive.length > 0 && (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {proactive.map((s) => (
              <div key={s.id} className="card">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <span className="font-mono text-brand">suggestion #{s.id}</span>
                  <Badge>{s.status}</Badge>
                  <Badge tone={s.priority === "high" ? "danger" : "slate"}>
                    {s.priority || "normal"}
                  </Badge>
                  <Badge tone="brand">{s.category}</Badge>
                </div>
                <div className="text-sm font-semibold text-slate-100">{s.title}</div>
                <div className="mt-1 text-sm text-slate-300">{s.message}</div>
                <div className="mt-2 text-xs text-slate-500">Action: {s.action_type || "review"}</div>
                {s.action_type === "device_profile_fix" && s.payload?.proposed_memory && (
                  <RepairMemory memory={s.payload.proposed_memory} />
                )}
                <DeveloperDetails title="Suggestion payload" data={s.payload || {}} />
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button disabled={busy === `proactive:${s.id}`} onClick={() => actProactive(s.id, "approve")}>
                    Approve
                  </Button>
                  <Button variant="ghost" className="text-rose-300" disabled={busy === `proactive:${s.id}`} onClick={() => actProactive(s.id, "ignore")}>
                    Ignore
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}

        {drafts.map((d) => (
          <div key={d.id} className="card">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="font-mono text-brand">#{d.id}</span>
              <Badge>{d.status}</Badge>
              <span className="text-xs text-slate-500">{d.created_at || ""}</span>
            </div>
            <div className="text-sm text-slate-200">{d.action_description || d.trigger_description}</div>
            {d.summary && (
              <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-3">
                <MiniStat label="Triggers" value={d.summary.trigger_count ?? 0} />
                <MiniStat label="Conditions" value={d.summary.condition_count ?? 0} />
                <MiniStat label="Actions" value={d.summary.action_count ?? 0} />
                <div className="rounded-xl border border-slate-800 bg-slate-950/35 p-3 md:col-span-3">
                  <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Draft preview</div>
                  <div className="flex flex-wrap gap-2">
                    {(d.summary.trigger_labels || []).map((label: string) => <Badge key={`t:${label}`} tone="brand">{label}</Badge>)}
                    {(d.summary.action_labels || []).map((label: string) => <Badge key={`a:${label}`}>{label}</Badge>)}
                    {d.summary.ready_to_install ? <Badge tone="good">ready</Badge> : <Badge tone="warn">needs review</Badge>}
                  </div>
                  {(d.summary.warnings || []).length > 0 && (
                    <div className="mt-2 space-y-1 text-xs text-amber-200">
                      {d.summary.warnings.map((warning: string) => <div key={warning}>{warning}</div>)}
                    </div>
                  )}
                </div>
              </div>
            )}
            {editing === d.id ? (
              <div className="mt-3 space-y-2">
                <textarea
                  className="input min-h-[18rem] font-mono text-sm"
                  value={editYaml}
                  onChange={(e) => setEditYaml(e.target.value)}
                />
                <div className="flex flex-wrap gap-2">
                  <Button disabled={busy === `edit:${d.id}`} onClick={() => void saveEdit(d)}>Save edit</Button>
                  <Button variant="ghost" onClick={() => { setEditing(null); setEditYaml(""); }}>Cancel edit</Button>
                </div>
              </div>
            ) : (
              <DeveloperDetails title="Proposed YAML">
                <pre className="code-scroll max-h-80 whitespace-pre-wrap">{d.proposed_yaml}</pre>
              </DeveloperDetails>
            )}
            <div className="mt-3 flex flex-wrap gap-2">
              <Button disabled={busy === `draft:${d.id}`} onClick={() => actDraft(d.id, "approve")}>
                Approve
              </Button>
              <Button variant="ghost" disabled={busy === `edit:${d.id}`} onClick={() => startEdit(d)}>
                Edit YAML
              </Button>
              <Button variant="ghost" className="text-rose-300" disabled={busy === `draft:${d.id}`} onClick={() => actDraft(d.id, "ignore")}>
                Ignore
              </Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: any }) {
  return (
    <div className="card">
      <div className="mb-1 text-xs uppercase text-slate-500">{label}</div>
      <div className="text-xl font-semibold text-slate-100">{value}</div>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: any }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/35 p-3">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-semibold text-slate-100">{value}</div>
    </div>
  );
}

function RepairMemory({ memory }: { memory: any }) {
  const value = memory?.value || {};
  const strategy = typeof value === "object" ? value.strategy : value;
  return (
    <div className="mt-3 rounded-xl border border-cyan-400/30 bg-cyan-500/10 p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-cyan-200">Device learning approval</div>
      <div className="mt-1 text-sm text-slate-100">
        Teach this device <span className="font-mono text-cyan-100">{memory.subject}</span> to use{" "}
        <span className="font-mono text-cyan-100">{strategy || memory.key}</span>.
      </div>
      {value?.reason && <div className="mt-1 text-xs text-slate-400">{value.reason}</div>}
    </div>
  );
}
