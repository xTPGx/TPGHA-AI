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
  const [onlyIssues, setOnlyIssues] = useState(false);

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
      if (onlyIssues && e.available && !e.rename_recommended && !e.browser_mod_role) return false;
      if (!needle) return true;
      return (
        e.entity_id.toLowerCase().includes(needle) ||
        (e.friendly_name ?? "").toLowerCase().includes(needle) ||
        (e.smart_name ?? "").toLowerCase().includes(needle) ||
        (e.smart_aliases ?? []).join(" ").toLowerCase().includes(needle)
      );
    });
  }, [entities, q, domain, onlyAvailable, onlyIssues]);

  const stats = useMemo(() => {
    return {
      total: entities.length,
      unavailable: entities.filter((e) => !e.available).length,
      rename: entities.filter((e) => e.rename_recommended).length,
      browserMod: entities.filter((e) => e.browser_mod_role).length,
    };
  }, [entities]);

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

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Entities" value={stats.total} />
        <Stat label="Unavailable" value={stats.unavailable} tone={stats.unavailable ? "warn" : "good"} />
        <Stat label="Smart names" value={stats.rename} tone={stats.rename ? "brand" : "slate"} />
        <Stat label="Browser Mod" value={stats.browserMod} tone={stats.browserMod ? "brand" : "slate"} />
      </div>

      <div className="card grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_12rem_18rem_16rem_auto] lg:items-end">
        <input
          className="input"
          placeholder="Search id, HA name, smart name, or alias..."
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
        <ToggleRow label="Issues only" description="Offline, renamed, or panel diagnostics" checked={onlyIssues} onChange={setOnlyIssues} />
        <span className="rounded-xl border border-slate-800 bg-slate-950/35 px-3 py-2 text-sm text-slate-400">
          {loading ? "Loading..." : `${filtered.length} / ${entities.length}`}
        </span>
      </div>

      <div className="card p-0">
        <div className="overflow-x-auto">
        <table className="w-full min-w-[64rem] text-left text-sm">
          <thead className="border-b border-slate-700 text-slate-400">
            <tr>
              <th className="px-4 py-2">Entity ID</th>
              <th className="px-4 py-2">Jarvis name</th>
              <th className="px-4 py-2">HA name</th>
              <th className="px-4 py-2">Domain</th>
              <th className="px-4 py-2">State</th>
              <th className="px-4 py-2">Health / use</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((e) => (
              <tr key={e.entity_id} className="border-b border-slate-800/70 hover:bg-slate-800/40">
                <td className="px-4 py-2 font-mono text-xs text-brand">{e.entity_id}</td>
                <td className="px-4 py-2">
                  <div className="font-semibold text-slate-100">{e.smart_name || e.friendly_name || "—"}</div>
                  {!!e.smart_aliases?.length && (
                    <div className="mt-1 text-xs text-slate-500">{e.smart_aliases.slice(0, 4).join(", ")}</div>
                  )}
                  {e.rename_recommended && <div className="mt-1 text-xs text-sky-200">{e.rename_reason}</div>}
                </td>
                <td className="px-4 py-2 text-slate-400">{e.friendly_name ?? "—"}</td>
                <td className="px-4 py-2 text-slate-400">{e.domain}</td>
                <td className="px-4 py-2">
                  <Badge tone={e.available ? "good" : "danger"}>{e.state}</Badge>
                </td>
                <td className="max-w-[28rem] px-4 py-2">
                  <div className="flex flex-wrap gap-2">
                    {e.jarvis_use && <Badge tone="slate">{pretty(e.jarvis_use)}</Badge>}
                    {e.browser_mod_role && <Badge tone="brand">{pretty(e.browser_mod_role)}</Badge>}
                    {e.rename_recommended && <Badge tone="brand">smart rename</Badge>}
                  </div>
                  {!e.available && (
                    <div className="mt-2 rounded-xl border border-amber-400/20 bg-amber-400/10 p-2 text-xs leading-relaxed text-amber-100">
                      <div>{e.unavailable_reason || e.health?.reason || "Home Assistant reports this entity as unavailable."}</div>
                      {(e.recommended_action || e.health?.recommended_action) && (
                        <div className="mt-1 text-amber-200/80">{e.recommended_action || e.health?.recommended_action}</div>
                      )}
                    </div>
                  )}
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

function pretty(value?: string) {
  return (value || "").replace(/_/g, " ");
}

function Stat({
  label,
  value,
  tone = "slate",
}: {
  label: string;
  value: number;
  tone?: "brand" | "good" | "warn" | "danger" | "slate";
}) {
  return (
    <div className="card">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 flex items-center gap-2">
        <div className="text-2xl font-semibold text-slate-100">{value}</div>
        <Badge tone={tone}>{tone === "good" ? "clean" : tone}</Badge>
      </div>
    </div>
  );
}
