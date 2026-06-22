export default function StatusDot({ ok, label }: { ok: boolean | null | undefined; label: string }) {
  const color =
    ok === null || ok === undefined
      ? "bg-slate-500"
      : ok
      ? "bg-emerald-400"
      : "bg-rose-500";
  return (
    <span className="inline-flex items-center gap-2 text-sm">
      <span className={`h-2.5 w-2.5 rounded-full ${color}`} />
      {label}
    </span>
  );
}
