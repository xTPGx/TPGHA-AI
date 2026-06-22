import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

export default function Rooms() {
  const [cfg, setCfg] = useState<any>(null);
  const [test, setTest] = useState("driveway");
  const [result, setResult] = useState<any>(null);

  useEffect(() => {
    api.config().then(setCfg);
  }, []);

  const runResolve = async () => {
    setResult(await api.resolve("room", test));
  };

  const rooms = cfg?.devices?.rooms ?? [];

  return (
    <div>
      <PageHeader
        title="Rooms"
        subtitle="Room aliases and their assigned speaker / camera / display / lock. Edit in config/devices.yaml, then Reload."
      />

      <div className="card mb-6">
        <div className="mb-2 text-sm font-medium text-slate-300">Resolve a room</div>
        <div className="flex gap-2">
          <input className="input max-w-xs" value={test} onChange={(e) => setTest(e.target.value)} />
          <button className="btn" onClick={runResolve}>
            Resolve
          </button>
        </div>
        {result && (
          <pre className="mt-3 overflow-auto rounded-lg bg-slate-950/70 p-3 text-xs text-slate-300">
            {JSON.stringify(result, null, 2)}
          </pre>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {rooms.map((r: any) => (
          <div key={r.id} className="card">
            <div className="flex items-center justify-between">
              <div className="text-lg font-semibold">{r.name}</div>
              <span className="badge bg-slate-700 text-slate-300">{r.id}</span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {(r.aliases ?? []).map((a: string) => (
                <span key={a} className="badge bg-brand-dark/20 text-brand">
                  {a}
                </span>
              ))}
            </div>
            <dl className="mt-3 space-y-1 text-sm">
              <Row label="Speaker" value={r.speaker} />
              <Row label="Camera" value={r.camera} />
              <Row label="Display" value={r.display} />
              <Row label="Lock" value={r.lock} />
              <Row label="Lights" value={(r.lights ?? []).join(", ")} />
              <Row label="Climate" value={r.climate} />
            </dl>
          </div>
        ))}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-mono text-xs text-slate-300">{value}</dd>
    </div>
  );
}
