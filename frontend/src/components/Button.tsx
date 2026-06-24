import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "ghost" | "danger" | "warning";

export default function Button({
  children,
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  variant?: Variant;
}) {
  const variants: Record<Variant, string> = {
    primary: "border-sky-400/30 bg-sky-500 text-white hover:bg-sky-400",
    ghost: "border-slate-600/70 bg-slate-900/40 text-slate-100 hover:border-sky-400/50 hover:bg-slate-800",
    danger: "border-rose-400/40 bg-rose-600 text-white hover:bg-rose-500",
    warning: "border-amber-400/40 bg-amber-600 text-white hover:bg-amber-500",
  };
  return (
    <button
      className={`min-h-11 rounded-xl border px-4 py-2 text-sm font-semibold transition focus:outline-none focus:ring-2 focus:ring-sky-300/70 disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
