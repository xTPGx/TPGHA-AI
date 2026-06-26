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
    primary: "btn",
    ghost: "btn-ghost",
    danger: "border-rose-400/45 bg-rose-600 text-white hover:bg-rose-500",
    warning: "border-amber-400/45 bg-amber-600 text-white hover:bg-amber-500",
  };
  return (
    <button
      className={`rounded-lg border px-4 py-2 text-sm font-semibold transition focus:outline-none focus:ring-2 focus:ring-cyan-300/60 disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
