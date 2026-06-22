import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

export default function Permissions() {
  const [cfg, setCfg] = useState<any>(null);
  useEffect(() => {
    api.config().then(setCfg);
  }, []);

  const p = cfg?.permissions ?? {};
  const sensitive: string[] = p.sensitive_actions ?? [];
  const messages: Record<string, string> = p.confirmation_messages ?? {};

  return (
    <div>
      <PageHeader
        title="Permissions"
        subtitle="Sensitive actions require explicit confirmation before the backend executes them."
      />

      <div className="card mb-6">
        <div className="mb-2 text-sm font-medium text-slate-300">Sensitive actions (require confirmation)</div>
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
          <div className="mb-2 text-sm font-medium text-slate-300">Defaults</div>
          <div className="grid grid-cols-1 gap-2 text-sm">
            {Object.entries(p.defaults ?? {})
              .filter(([, v]) => v !== null && v !== undefined)
              .map(([k, v]) => (
                <div key={k} className="flex items-center justify-between rounded bg-slate-900/50 px-2 py-1">
                  <span className="text-slate-400">{k.replace(/_/g, " ")}</span>
                  <span className={v ? "text-emerald-400" : "text-rose-400"}>{v ? "allowed" : "denied"}</span>
                </div>
              ))}
          </div>
        </div>
        <div className="card">
          <div className="mb-2 text-sm font-medium text-slate-300">Policy</div>
          <dl className="space-y-1 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-500">Confirmation TTL</dt>
              <dd className="text-slate-200">{p.confirmation_ttl_seconds}s</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Music account ownership</dt>
              <dd className="text-slate-200">{p.enforce_music_account_ownership ? "enforced" : "off"}</dd>
            </div>
          </dl>
          <p className="mt-3 text-xs text-slate-500">
            The AI can only select from the defined tool allowlist; it can never issue arbitrary Home
            Assistant service calls.
          </p>
        </div>
      </div>
    </div>
  );
}
