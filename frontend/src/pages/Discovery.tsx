import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

interface Discovered {
  entity_id: string;
  domain: string;
  friendly_name: string;
  suggested_category: string;
  likely_room?: string;
  risk_level: string;
  suggested_aliases: string[];
  is_available: boolean;
  is_duplicate_candidate: boolean;
  reason: string;
}

const RISK_COLORS: Record<string, string> = {
  low: "bg-emerald-500/20 text-emerald-300",
  medium: "bg-amber-500/20 text-amber-300",
  high: "bg-orange-500/20 text-orange-300",
  critical: "bg-rose-500/20 text-rose-300",
};

const MAP_TARGETS = [
  "device",
  "personal_device",
  "speaker",
  "display",
  "camera",
  "security_sensor",
  "lock",
  "climate",
];

export default function Discovery() {
  const [pending, setPending] = useState<Discovered[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const p = await api.discoveryPending();
      setPending(p.pending || []);
      setSummary(await api.discoverySummary());
    } catch (e: any) {
      setError(e.message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const scan = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api.discoveryScan();
      setSummary(r.summary);
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const approve = async (d: Discovered, target: string) => {
    setBusy(d.entity_id);
    try {
      if (target === "device") {
        await api.approve({
          entity_id: d.entity_id,
          room: d.likely_room,
          friendly_name: d.friendly_name,
          aliases: d.suggested_aliases,
        });
      } else {
        await api.mapEntity({
          entity_id: d.entity_id,
          target,
          room: d.likely_room,
          friendly_name: d.friendly_name,
          aliases: d.suggested_aliases,
        });
      }
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const ignore = async (d: Discovered) => {
    setBusy(d.entity_id);
    try {
      await api.ignore(d.entity_id, d.is_duplicate_candidate ? "duplicate" : "ignored by user");
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <PageHeader
        title="Discovery"
        subtitle="Find, classify, and approve Home Assistant entities"
        actions={
          <button className="btn" onClick={scan} disabled={loading}>
            {loading ? "Scanning…" : "Scan now"}
          </button>
        }
      />

      {error && <div className="mb-4 text-rose-300">{error}</div>}

      {summary && (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          <Stat label="Pending" value={summary.pending_count ?? summary?.new_entities?.count} />
          <Stat label="Known" value={summary.known_count} />
          <Stat label="Unavailable" value={summary.unavailable_count} />
          <Stat label="Last scan" value={summary.last_scan_ts ? "done" : "never"} />
        </div>
      )}

      <div className="card">
        <div className="mb-3 text-sm font-medium text-slate-300">Pending approvals ({pending.length})</div>
        {pending.length === 0 && <div className="text-slate-500">No new entities. Run a scan to discover devices.</div>}
        <div className="space-y-3">
          {pending.map((d) => (
            <div key={d.entity_id} className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-sm text-brand">{d.entity_id}</span>
                <span className={`badge ${RISK_COLORS[d.risk_level] || ""}`}>{d.risk_level}</span>
                <span className="badge bg-slate-700/50 text-slate-300">{d.suggested_category}</span>
                {!d.is_available && <span className="badge bg-slate-700/50 text-slate-400">unavailable</span>}
                {d.is_duplicate_candidate && (
                  <span className="badge bg-orange-500/20 text-orange-300">duplicate?</span>
                )}
              </div>
              <div className="mt-1 text-sm text-slate-300">{d.friendly_name}</div>
              <div className="mt-1 text-xs text-slate-500">
                Room: {d.likely_room || "—"} · Aliases: {(d.suggested_aliases || []).join(", ") || "—"}
              </div>
              <div className="mt-1 text-xs text-slate-600">{d.reason}</div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {MAP_TARGETS.map((t) => (
                  <button
                    key={t}
                    className="btn-ghost text-xs"
                    disabled={busy === d.entity_id}
                    onClick={() => approve(d, t)}
                  >
                    {t === "device" ? "Approve" : `Map as ${t.replace("_", " ")}`}
                  </button>
                ))}
                <button
                  className="btn-ghost text-xs text-rose-300"
                  disabled={busy === d.entity_id}
                  onClick={() => ignore(d)}
                >
                  Ignore
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: any }) {
  return (
    <div className="card">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-slate-100">{value ?? 0}</div>
    </div>
  );
}
