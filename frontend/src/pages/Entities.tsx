import { useEffect, useMemo, useState } from "react";
import { api, HAEntity } from "../api";
import Badge from "../components/Badge";
import Button from "../components/Button";
import PageHeader from "../components/PageHeader";
import ToggleRow from "../components/ToggleRow";

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
    <div className="page-stack">
      <PageHeader
        title="Entities"
        subtitle="Live entities pulled from Home Assistant"
        actions={
          <Button variant="ghost" onClick={load}>
            Refresh
          </Button>
        }
      />

      {error && (
        <div className="card mb-4 border-rose-700/60 bg-rose-900/20 text-rose-200">
          {error} — check HOME_ASSISTANT_URL / token on the backend.
        </div>
      )}

      <div className="card grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_12rem_18rem_auto] lg:items-end">
        <input
          className="input"
          placeholder="Search id or name..."
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select className="input" value={domain} onChange={(e) => setDomain(e.target.value)}>
          {domains.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        <ToggleRow label="Available only" checked={onlyAvailable} onChange={setOnlyAvailable} />
        <span className="rounded-xl border border-slate-800 bg-slate-950/35 px-3 py-2 text-sm text-slate-400">
          {loading ? "Loading..." : `${filtered.length} / ${entities.length}`}
        </span>
      </div>

      <div className="card p-0">
        <div className="overflow-x-auto">
        <table className="w-full min-w-[42rem] text-left text-sm">
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
                  <Badge tone={e.available ? "good" : "danger"}>{e.state}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>
    </div>
  );
}
