import type { ReactNode } from "react";

export default function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card w-full min-w-0 max-w-full ${className}`}>
      {children}
    </section>
  );
}
