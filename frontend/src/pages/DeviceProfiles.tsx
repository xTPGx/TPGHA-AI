import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

export default function DeviceProfiles() {
  const [data, setData] = useState<any>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const [profiles, adapters] = await Promise.all([
        api.deviceProfiles(),
        api.deviceAdapters(),
      ]);
      setData({ ...profiles, adapters: adapters.adapters || [], adapter_counts: adapters.counts || {} });
      setError(null);
    } catch (e: any) {
      setError(e.message || String(e));
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const profiles = useMemo(() => {
    const q = query.trim().toLowerCase();
    const all = data?.profiles || [];
    if (!q) return all;
    return all.filter((p: any) =>
      [p.name, p.area, p.device_type, ...(p.entity_ids || []), ...(p.capabilities || []), ...(p.quirks || [])]
        .filter(Boolean)
        .some((v: string) => String(v).toLowerCase().includes(q)),
    );
  }, [data, query]);

  const adapterByDevice = useMemo(() => {
    const map: Record<string, any> = {};
    for (const adapter of data?.adapters || []) {
      if (adapter.device_id) map[adapter.device_id] = adapter;
    }
    return map;
  }, [data]);

  return (
    <div>
      <PageHeader
        title="Device Profiles"
        subtitle="Operational memory for real devices, capabilities, quirks, and action history"
        actions={<button className="btn-ghost" onClick={() => void load()}>Refresh</button>}
      />

      {error && (
        <div className="mb-4 rounded border border-rose-500/40 bg-rose-500/10 p-3 text-rose-200">
          {error}
        </div>
      )}

      <div className="mb-4 grid grid-cols-1 gap-4 md:grid-cols-4">
        <Stat label="Profiles" value={data?.counts?.profiles ?? "—"} />
        <Stat label="With quirks" value={data?.counts?.with_quirks ?? "—"} />
        <Stat label="Needs attention" value={data?.counts?.needs_attention ?? "—"} />
        <Stat label="Adapters" value={data?.adapter_counts?.devices ?? "—"} />
        <Stat label="Visible" value={profiles.length} />
        <input
          className="input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter profiles"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {profiles.map((profile: any) => (
          <ProfileCard key={profile.id} profile={profile} adapter={adapterByDevice[profile.id]} />
        ))}
      </div>

      {!data && !error && <div className="card text-slate-400">Loading device profiles...</div>}
      {data && profiles.length === 0 && <div className="card text-slate-500">No matching profiles.</div>}
    </div>
  );
}

function ProfileCard({ profile, adapter }: { profile: any; adapter?: any }) {
  return (
    <div className="card">
            <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-lg font-semibold text-slate-100">{profile.name || profile.id}</div>
                <div className="text-sm text-slate-400">
                  {profile.device_type || "device"}{profile.area ? ` • ${profile.area}` : ""}
                </div>
              </div>
              {profile.quirks?.length > 0 && (
                <span className="badge bg-amber-500/15 text-amber-200">quirks</span>
              )}
              {profile.reliability && (
                <span className={`badge ${profile.reliability.grade === "needs_attention" ? "bg-rose-500/15 text-rose-200" : profile.reliability.grade === "watch" ? "bg-amber-500/15 text-amber-200" : "bg-emerald-500/15 text-emerald-200"}`}>
                  reliability {Math.round((profile.reliability.score ?? 1) * 100)}%
                </span>
              )}
            </div>

            <Pills label="Capabilities" items={profile.capabilities || []} />
            <Pills label="Quirks" items={profile.quirks || []} mutedFallback="No known quirks" />
            <Pills label="Entities" items={profile.entity_ids || []} mono />
            <Pills label="Service strategy" items={serviceStrategyItems(profile.service_strategy || {})} mutedFallback="No learned strategy yet" mono />
            {profile.reliability?.last_outcome && (
              <div className="mt-3 rounded border border-slate-800 bg-slate-950/30 p-3 text-sm">
                <div className="text-xs uppercase text-slate-500">Last reliability outcome</div>
                <div className="mt-1 text-slate-200">{profile.reliability.last_outcome.summary || profile.reliability.last_outcome.status}</div>
                {(profile.reliability.last_outcome.diagnostics || []).map((item: string) => (
                  <div key={item} className="mt-1 text-xs text-amber-200">{item}</div>
                ))}
              </div>
            )}
            {adapter && (
              <>
                <Pills
                  label="Adapters"
                  items={(adapter.entities || []).map((item: any) => `${item.entity_id}: ${item.adapter}`)}
                  mono
                />
                <Pills label="Recovery" items={adapter.recovery || []} mutedFallback="No recovery hints" />
              </>
            )}

            <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
              <History label="Successes" value={profile.history?.successful_actions ?? 0} detail={profile.history?.last_success} />
              <History label="Failures" value={profile.history?.failed_actions ?? 0} detail={profile.history?.last_failure} />
            </div>
          </div>
  );
}

function serviceStrategyItems(strategy: Record<string, any>) {
  return Object.entries(strategy || {}).map(([entityId, value]) => {
    const bits = Object.entries(value || {})
      .filter(([, v]) => v !== undefined && v !== null && v !== "" && (!Array.isArray(v) || v.length > 0))
      .map(([k, v]) => `${k}=${formatStrategyValue(v)}`);
    return `${entityId}: ${bits.join(", ")}`;
  });
}

function formatStrategyValue(value: any) {
  if (Array.isArray(value)) return value.join("|");
  if (value && typeof value === "object") {
    return Object.entries(value)
      .filter(([, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v]) => `${k}:${Array.isArray(v) ? v.join("|") : String(v)}`)
      .join(";");
  }
  return String(value);
}

function Stat({ label, value }: { label: string; value: any }) {
  return (
    <div className="card">
      <div className="mb-1 text-xs uppercase text-slate-500">{label}</div>
      <div className="text-2xl font-semibold text-slate-100">{value}</div>
    </div>
  );
}

function Pills({ label, items, mono = false, mutedFallback = "None" }: {
  label: string;
  items: string[];
  mono?: boolean;
  mutedFallback?: string;
}) {
  return (
    <div className="mt-3">
      <div className="mb-1 text-xs uppercase text-slate-500">{label}</div>
      {items.length === 0 ? (
        <div className="text-sm text-slate-500">{mutedFallback}</div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {items.map((item) => (
            <span key={item} className={`badge bg-slate-700/50 text-slate-300 ${mono ? "font-mono" : ""}`}>
              {item}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function History({ label, value, detail }: { label: string; value: any; detail?: any }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-950/30 p-3">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className="text-xl font-semibold text-slate-100">{value}</div>
      {detail && (
        <div className="mt-2 text-xs text-slate-400">
          {detail.intent || "command"}{detail.created_at ? ` • ${detail.created_at}` : ""}
        </div>
      )}
    </div>
  );
}
