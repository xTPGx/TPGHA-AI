import type { ReactNode } from "react";

export default function Badge({
  children,
  tone = "slate",
  className = "",
}: {
  children: ReactNode;
  tone?: "brand" | "good" | "warn" | "danger" | "slate";
  className?: string;
}) {
  const tones = {
    brand: "border-cyan-400/35 bg-cyan-400/10 text-cyan-100",
    good: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
    warn: "border-amber-400/30 bg-amber-400/10 text-amber-200",
    danger: "border-rose-400/30 bg-rose-400/10 text-rose-200",
    slate: "border-slate-500/30 bg-slate-700/30 text-slate-300",
  };
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium ${tones[tone]} ${className}`}>
      {children}
    </span>
  );
}
