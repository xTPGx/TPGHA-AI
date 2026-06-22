import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

export default function Music() {
  const [cfg, setCfg] = useState<any>(null);
  useEffect(() => {
    api.config().then(setCfg);
  }, []);

  const accounts: Record<string, any> = cfg?.devices?.music_accounts ?? {};
  const speakers = cfg?.devices?.speakers ?? [];
  const avoid: string[] = cfg?.devices?.avoid ?? [];

  return (
    <div>
      <PageHeader
        title="Music"
        subtitle="Music Assistant providers per user, and speaker → room mapping. The resolver prefers available speakers over the avoided duplicates."
      />

      <div className="card mb-6">
        <div className="mb-3 text-sm font-medium text-slate-300">Music Assistant providers</div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {Object.entries(accounts).map(([key, a]) => (
            <div key={key} className="rounded-lg border border-slate-700 bg-slate-900/40 p-3">
              <div className="font-semibold text-brand">{a.name}</div>
              <div className="mt-1 text-xs text-slate-400">
                provider: {a.provider} · account: {a.account} · owner: {a.owner}
              </div>
              <div className="mt-1 font-mono text-[10px] text-slate-500">{key}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="card mb-6">
        <div className="mb-3 text-sm font-medium text-slate-300">Speakers → rooms</div>
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-700 text-slate-400">
            <tr>
              <th className="py-2">Speaker</th>
              <th className="py-2">Entity</th>
              <th className="py-2">Room</th>
            </tr>
          </thead>
          <tbody>
            {speakers.map((s: any) => (
              <tr key={s.id} className="border-b border-slate-800/70">
                <td className="py-2">{s.name}</td>
                <td className="py-2 font-mono text-xs text-brand">{s.entity_id}</td>
                <td className="py-2 text-slate-400">{s.room ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {avoid.length > 0 && (
        <div className="card">
          <div className="mb-2 text-sm font-medium text-rose-300">Avoided (dead/duplicate) players</div>
          <div className="flex flex-wrap gap-2">
            {avoid.map((e) => (
              <span key={e} className="badge bg-rose-500/15 font-mono text-rose-300">
                {e}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
