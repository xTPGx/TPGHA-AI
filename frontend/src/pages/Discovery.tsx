import { useEffect, useState } from "react";
import { api } from "../api";
import Badge from "../components/Badge";
import Button from "../components/Button";
import DeveloperDetails from "../components/DeveloperDetails";
import PageHeader from "../components/PageHeader";

interface Discovered {
  entity_id: string;
  domain: string;
  friendly_name: string;
  suggested_name?: string;
  device_name?: string;
  source?: string;
  source_detail?: string;
  semantic_category?: string;
  suggested_category: string;
  suggested_mapping?: string;
  likely_room?: string;
  room?: string;
  risk_level: string;
  suggested_aliases: string[];
  is_available: boolean;
  is_duplicate_candidate: boolean;
  reason: string;
  approval_label?: string;
  auto_approvable?: boolean;
  confidence?: number;
  smart_aliases?: string[];
  rename_recommended?: boolean;
  rename_reason?: string;
  health?: Record<string, any>;
  unavailable_reason?: string;
  recommended_action?: string;
  browser_mod_role?: string;
}

const RISK_COLORS: Record<string, string> = {
  low: "bg-emerald-500/20 text-emerald-300",
  medium: "bg-amber-500/20 text-amber-300",
  high: "bg-orange-500/20 text-orange-300",
  critical: "bg-rose-500/20 text-rose-300",
};

const TARGET_LABELS: Record<string, string> = {
  device: "Approve as status",
  light: "Approve as light",
  fan: "Approve as fan",
  person: "Approve as person",
  personal_device: "Map as personal device",
  speaker: "Map as speaker",
  display: "Map as display",
  camera: "Map as camera",
  security_sensor: "Map as security sensor",
  lock: "Map as lock",
  climate: "Map as climate",
};

function prettyCategory(value?: string) {
  return (value || "other").replace(/_/g, " ");
}

function categoryOf(d: Discovered) {
  return d.semantic_category || d.suggested_category || "other";
}

function roomOf(d: Discovered) {
  return d.likely_room || d.room || "";
}

function mapTargets(d: Discovered) {
  const category = categoryOf(d);
  const domain = d.domain;
  if (domain === "light") return ["light", "device"];
  if (domain === "fan") return ["fan", "device"];
  if (domain === "person") return ["person", "device"];
  if (domain === "device_tracker") return ["personal_device", "device"];
  if (category === "personal_device") return ["personal_device", "device"];
  if (category === "personal_device_sensor") return ["device"];
  if (["system_backup", "diagnostic_sensor", "network", "person"].includes(category)) {
    return ["device"];
  }
  if (domain === "camera") return ["camera", "device"];
  if (domain === "lock") return ["lock", "device"];
  if (domain === "climate") return ["climate", "device"];
  if (domain === "binary_sensor") return ["security_sensor", "device"];
  if (domain === "media_player") return ["speaker", "display", "device"];
  if (domain === "switch") return ["device"];
  return ["device", "speaker", "display", "camera", "security_sensor", "lock", "climate"];
}

function primaryTarget(d: Discovered) {
  if (d.domain === "light") return "light";
  if (d.domain === "fan") return "fan";
  if (d.domain === "person") return "person";
  if (d.domain === "device_tracker" || categoryOf(d) === "personal_device") return "personal_device";
  return "device";
}

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
          room: roomOf(d),
          friendly_name: d.suggested_name || d.friendly_name,
          aliases: d.smart_aliases?.length ? d.smart_aliases : d.suggested_aliases,
        });
      } else {
        await api.mapEntity({
          entity_id: d.entity_id,
          target,
          room: roomOf(d),
          friendly_name: d.suggested_name || d.friendly_name,
          aliases: d.smart_aliases?.length ? d.smart_aliases : d.suggested_aliases,
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
    <div className="page-stack">
      <PageHeader
        title="Discovery"
        subtitle="Review, categorize, and approve Home Assistant entities into the smart-home brain."
        actions={
          <Button onClick={scan} disabled={loading}>
            {loading ? "Scanning…" : "Scan now"}
          </Button>
        }
      />

      {error && <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-rose-200">{error}</div>}

      {summary && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Pending" value={summary.pending_count ?? summary?.new_entities?.count} />
          <Stat label="Known" value={summary.known_count} />
          <Stat label="Unavailable" value={summary.unavailable_count} />
          <Stat label="Last scan" value={summary.last_scan_ts ? "done" : "never"} />
        </div>
      )}

      <section className="card">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-lg font-semibold text-slate-100">Needs approval</div>
            <div className="mt-1 text-sm text-slate-500">Source: Home Assistant entity registry and states. This is not a raw LAN scan.</div>
          </div>
          <Badge tone={pending.length ? "warn" : "good"}>{pending.length} pending</Badge>
        </div>
        {pending.length === 0 && <div className="mt-4 text-slate-500">No new entities. Run a scan to discover devices.</div>}
        <EntityGrid items={pending} busy={busy} approve={approve} ignore={ignore} />
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ReviewSection title="Unavailable" tone="warn" items={pending.filter((d) => !d.is_available)} busy={busy} approve={approve} ignore={ignore} />
        <ReviewSection title="Risky devices" tone="danger" items={pending.filter((d) => ["high", "critical"].includes(d.risk_level))} busy={busy} approve={approve} ignore={ignore} />
      </section>
    </div>
  );
}

function ReviewSection({
  title,
  items,
  busy,
  approve,
  ignore,
  tone,
}: {
  title: string;
  items: Discovered[];
  busy: string | null;
  approve: (d: Discovered, target: string) => void;
  ignore: (d: Discovered) => void;
  tone: "warn" | "danger";
}) {
  return (
    <section className="card">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="text-lg font-semibold text-slate-100">{title}</div>
        <Badge tone={tone}>{items.length}</Badge>
      </div>
      {items.length ? (
        <EntityGrid items={items} busy={busy} approve={approve} ignore={ignore} compact />
      ) : (
        <div className="text-sm text-slate-500">Nothing to review here.</div>
      )}
    </section>
  );
}

function EntityGrid({
  items,
  busy,
  approve,
  ignore,
  compact = false,
}: {
  items: Discovered[];
  busy: string | null;
  approve: (d: Discovered, target: string) => void;
  ignore: (d: Discovered) => void;
  compact?: boolean;
}) {
  if (!items.length) return null;
  return (
    <div className={`mt-4 grid grid-cols-1 gap-3 ${compact ? "" : "2xl:grid-cols-2"}`}>
      {items.map((d) => (
        <EntityCard key={d.entity_id} d={d} busy={busy} approve={approve} ignore={ignore} />
      ))}
    </div>
  );
}

function EntityCard({
  d,
  busy,
  approve,
  ignore,
}: {
  d: Discovered;
  busy: string | null;
  approve: (d: Discovered, target: string) => void;
  ignore: (d: Discovered) => void;
}) {
  return (
    <article className="min-w-0 rounded-2xl border border-slate-800 bg-slate-950/45 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="break-all font-mono text-sm text-brand">{d.entity_id}</span>
        <span className={`badge ${RISK_COLORS[d.risk_level] || ""}`}>{d.risk_level}</span>
        <Badge>{prettyCategory(categoryOf(d))}</Badge>
        {d.auto_approvable && <Badge tone="good">smart map</Badge>}
        {d.rename_recommended && <Badge tone="brand">smart name</Badge>}
        {!d.is_available && <Badge tone="warn">unavailable</Badge>}
        {d.is_duplicate_candidate && <Badge tone="warn">duplicate?</Badge>}
      </div>
      <div className="mt-2 text-base font-semibold text-slate-100">{d.suggested_name || d.friendly_name}</div>
      {d.suggested_name && d.suggested_name !== d.friendly_name && (
        <div className="mt-1 text-xs text-slate-500">HA name: {d.friendly_name}</div>
      )}
      <div className="mt-2 grid gap-1 text-xs text-slate-500 sm:grid-cols-2">
        <div>Device: <span className="text-slate-300">{d.device_name || "-"}</span></div>
        <div>Room: <span className="text-slate-300">{roomOf(d) || "-"}</span></div>
        <div>Domain: <span className="text-slate-300">{d.domain}</span></div>
        <div>Mapping: <span className="text-slate-300">{prettyCategory(d.suggested_mapping || "device_aliases")}</span></div>
      </div>
      <div className="mt-2 text-xs text-slate-500">
        Aliases: {(d.smart_aliases?.length ? d.smart_aliases : d.suggested_aliases || []).join(", ") || "-"}
      </div>
      {d.rename_reason && <div className="mt-2 text-xs text-sky-200">{d.rename_reason}</div>}
      {!d.is_available && d.unavailable_reason && (
        <div className="mt-2 rounded-xl border border-amber-400/20 bg-amber-400/10 p-3 text-xs leading-relaxed text-amber-100">
          <div>{d.unavailable_reason}</div>
          {d.recommended_action && <div className="mt-1 text-amber-200/80">{d.recommended_action}</div>}
        </div>
      )}
      <div className="mt-2 text-xs leading-relaxed text-slate-500">{d.reason}</div>
      <div className="mt-3 flex flex-wrap gap-2">
        {mapTargets(d).map((t) => (
          <Button key={t} variant="ghost" className="px-3 py-1.5 text-xs" disabled={busy === d.entity_id} onClick={() => approve(d, t)}>
            {t === primaryTarget(d) && d.approval_label ? d.approval_label : TARGET_LABELS[t] || `Map as ${t.replace("_", " ")}`}
          </Button>
        ))}
        <Button variant="ghost" className="px-3 py-1.5 text-xs text-rose-200" disabled={busy === d.entity_id} onClick={() => ignore(d)}>
          Ignore
        </Button>
      </div>
      <div className="mt-3">
        <DeveloperDetails title="Raw classification" data={d} />
      </div>
    </article>
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
