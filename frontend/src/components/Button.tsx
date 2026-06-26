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
    primary: "border-cyan-300/50 bg-cyan-500 text-white hover:bg-cyan-400 shadow-[0_12px_30px_rgba(25,211,230,0.22)]",
    ghost: "border-cyan-300/20 bg-[#081225]/75 text-slate-100 hover:border-cyan-300/45 hover:bg-cyan-300/10",
    danger: "border-rose-400/40 bg-rose-600 text-white hover:bg-rose-500",
    warning: "border-amber-400/40 bg-amber-600 text-white hover:bg-amber-500",
  };
  return (
    <button
      className={`min-h-11 rounded-lg border px-4 py-2 text-sm font-semibold transition focus:outline-none focus:ring-2 focus:ring-cyan-300/60 disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
