import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

export default function VoiceSources() {
  const [items, setItems] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const result = await api.voiceSources();
      setItems(result.voice_sources || []);
      setError(null);
    } catch (e: any) {
      setError(e.message || String(e));
    }
  };

  useEffect(() => {
    void load();
  }, []);

  return (
    <div>
      <PageHeader
        title="Voice Sources"
        subtitle="Map microphones, tablets, panels, and satellites to room context"
        actions={<button className="btn-ghost" onClick={() => void load()}>Refresh</button>}
      />

      {error && <div className="mb-4 rounded border border-rose-500/40 bg-rose-500/10 p-3 text-rose-200">{error}</div>}

      <div className="mb-4 grid grid-cols-1 gap-4 md:grid-cols-3">
        <Stat label="Configured sources" value={items.length} />
        <Stat label="Context behavior" value="source -> room" />
        <Stat label="Generic command" value="room scoped" />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {items.map((source) => (
          <div key={source.id} className="card">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="text-lg font-semibold text-slate-100">{source.name}</span>
              <span className="badge bg-cyan-500/10 text-cyan-200">{source.room}</span>
            </div>
            <div className="space-y-2 text-sm text-slate-300">
              <Row label="Source device" value={source.source_device_id || "not set"} />
              <Row label="Source entity" value={source.source_entity_id || "not set"} />
              <Row label="Aliases" value={(source.aliases || []).join(", ") || "none"} />
            </div>
          </div>
        ))}
      </div>

      {items.length === 0 && (
        <div className="card text-slate-500">
          No voice sources configured yet. Add `voice_sources` to devices.yaml so source_device_id or source_entity_id can infer a room.
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: any }) {
  return (
    <div className="card">
      <div className="mb-1 text-xs uppercase text-slate-500">{label}</div>
      <div className="text-xl font-semibold text-slate-100">{value}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: any }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-950/30 px-3 py-2">
      <span className="text-slate-500">{label}:</span> <span className="font-mono">{value}</span>
    </div>
  );
}
