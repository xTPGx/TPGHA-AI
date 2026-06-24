import type { ReactNode } from "react";

export default function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-4 flex min-w-0 flex-col gap-3 sm:mb-6 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <h1 className="break-words text-2xl font-bold tracking-tight text-white sm:text-3xl">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm leading-relaxed text-slate-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap gap-2 sm:justify-end">{actions}</div>}
    </div>
  );
}
