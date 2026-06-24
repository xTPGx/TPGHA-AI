import type { ReactNode } from "react";

export default function DeveloperDetails({
  title = "Developer details",
  data,
  children,
}: {
  title?: string;
  data?: unknown;
  children?: ReactNode;
}) {
  if (!children && (data === undefined || data === null)) return null;
  return (
    <details className="developer-details group rounded-xl border border-slate-800 bg-slate-950/40">
      <summary className="cursor-pointer list-none px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-400 transition hover:text-sky-200">
        {title}
      </summary>
      <div className="border-t border-slate-800 p-3">
        {children || (
          <pre className="max-w-full overflow-x-auto rounded-lg bg-black/40 p-3 text-xs leading-relaxed text-slate-300">
            {JSON.stringify(data, null, 2)}
          </pre>
        )}
      </div>
    </details>
  );
}
