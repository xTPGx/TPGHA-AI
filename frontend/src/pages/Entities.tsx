import { useEffect, useMemo, useState } from "react";
import { api, HAEntity } from "../api";
import PageHeader from "../components/PageHeader";

export default function Entities() {
  const [entities, setEntities] = useState<HAEntity[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [domain, setDomain] = useState("all");
  const [onlyAvailable, setOnlyAvailable] = useState(false);

  const load = () => {
    setLoading(true);
    api
      .entities()
      .then((e) => {
        setEntities(e);
        setError(null);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const domains = useMemo(() => {
    return ["all", ...Array.from(new Set(entities.map((e) => e.domain))).sort()];
  }, [entities]);

  const filtered = useMemo(() => {
    const needle = q.toLowerCase();
    return entities.filter((e) => {
      if (domain !== "all" && e.domain !== domain) return false;
      if (onlyAvailable && !e.available) return false;
      if (!needle) return true;
      return (
        e.entity_id.toLowerCase().includes(needle) ||
        (e.friendly_name ?? "").toLowerCase().includes(needle)
      );
    });
  }, [entities, q, domain, onlyAvailable]);

  return (
    <div>
      <PageHeader
        title="Entities"
        subtitle="Live entities pulled from Home Assistant"
        actions={
          <button className="btn-ghost" onClick={load}>
            Refresh
          </button>
        }
      />

      {error && (
        <div className="card mb-4 border-rose-700/60 bg-rose-900/20 text-rose-200">
          {error} — check HOME_ASSISTANT_URL / token on the backend.
        </div>
      )}

      <div className="card mb-4 flex flex-wrap items-center gap-3">
        <input
          className="input max-w-xs"
          placeholder="Search id or name…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select className="input max-w-[12rem]" value={domain} onChange={(e) => setDomain(e.target.value)}>
          {domains.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input type="checkbox" checked={onlyAvailable} onChange={(e) => setOnlyAvailable(e.target.checked)} />
          Available only
        </label>
        <span className="ml-auto text-sm text-slate-500">
          {loading ? "Loading…" : `${filtered.length} / ${entities.length}`}
        </span>
      </div>

      <div className="card overflow-auto p-0">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-700 text-slate-400">
            <tr>
              <th className="px-4 py-2">Entity ID</th>
              <th className="px-4 py-2">Friendly name</th>
              <th className="px-4 py-2">Domain</th>
              <th className="px-4 py-2">State</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((e) => (
              <tr key={e.entity_id} className="border-b border-slate-800/70 hover:bg-slate-800/40">
                <td className="px-4 py-2 font-mono text-xs text-brand">{e.entity_id}</td>
                <td className="px-4 py-2">{e.friendly_name ?? "—"}</td>
                <td className="px-4 py-2 text-slate-400">{e.domain}</td>
                <td className="px-4 py-2">
                  <span
                    className={`badge ${
                      e.available ? "bg-emerald-500/15 text-emerald-300" : "bg-rose-500/15 text-rose-300"
                    }`}
                  >
                    {e.state}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
