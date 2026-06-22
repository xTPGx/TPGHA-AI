import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

export default function Users() {
  const [cfg, setCfg] = useState<any>(null);
  useEffect(() => {
    api.config().then(setCfg);
  }, []);

  const users = cfg?.assistants?.users ?? [];
  const accounts = cfg?.devices?.music_accounts ?? {};
  const defaults = cfg?.permissions?.defaults ?? {};

  return (
    <div>
      <PageHeader title="Users" subtitle="People in the household, their permissions and music provider." />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {users.map((u: any) => {
          const acct = u.music_account ? accounts[u.music_account] : null;
          const perms = { ...defaults, ...u.permissions };
          return (
            <div key={u.id} className="card">
              <div className="text-xl font-bold">{u.name}</div>
              <div className="mt-1 text-sm text-slate-400">
                Music: {acct ? acct.name : u.music_account ?? "none"}
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                {(u.aliases ?? []).map((a: string) => (
                  <span key={a} className="badge bg-slate-700 text-slate-300">
                    {a}
                  </span>
                ))}
              </div>
              <div className="mt-4 grid grid-cols-2 gap-2 text-sm">
                {Object.entries(perms)
                  .filter(([, v]) => v !== null && v !== undefined)
                  .map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between rounded bg-slate-900/50 px-2 py-1">
                      <span className="text-slate-400">{k.replace(/_/g, " ")}</span>
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
