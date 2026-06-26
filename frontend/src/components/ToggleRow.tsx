export default function ToggleRow({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="tpg-panel-flat flex min-h-11 cursor-pointer items-center justify-between gap-3 px-3 py-2 transition hover:border-sky-400/40">
      <span className="min-w-0">
        <span className="block text-sm font-medium text-slate-100">{label}</span>
        {description && <span className="block text-xs text-slate-500">{description}</span>}
      </span>
      <span className={`relative h-6 w-11 shrink-0 rounded-full border transition ${checked ? "border-sky-300 bg-sky-500" : "border-slate-600 bg-slate-800"}`}>
        <input
          className="sr-only"
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span className={`absolute top-1 h-4 w-4 rounded-full bg-white transition ${checked ? "left-6" : "left-1"}`} />
      </span>
    </label>
  );
}
