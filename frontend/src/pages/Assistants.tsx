import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

export default function Assistants() {
  const [cfg, setCfg] = useState<any>(null);
  useEffect(() => {
    api.config().then(setCfg);
  }, []);

  const assistants = cfg?.assistants?.assistants ?? [];
  const users = cfg?.assistants?.users ?? [];
  const accounts = cfg?.devices?.music_accounts ?? {};

  const userById = (id: string) => users.find((u: any) => u.id === id);

  return (
    <div>
      <PageHeader
        title="Assistants"
        subtitle="Per-assistant personality, owner, and music account. Edit in config/assistants.yaml."
      />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {assistants.map((a: any) => {
          const owner = userById(a.owner);
          const acct = owner?.music_account ? accounts[owner.music_account] : null;
          return (
            <div key={a.id} className="card">
              <div className="flex items-center justify-between">
                <div className="text-xl font-bold text-brand">{a.name}</div>
                <span className="badge bg-slate-700 text-slate-300">{a.tone}</span>
              </div>
              <p className="mt-2 text-sm text-slate-300">{a.personality}</p>
              <dl className="mt-4 space-y-1 text-sm">
                <Row label="Owner" value={owner ? owner.name : a.owner} />
                <Row label="Voice" value={a.voice} />
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

function Row({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-slate-200">{value}</dd>
    </div>
  );
}
