import type { ReactNode } from "react";
import "@/styles/additions.css";

/** Wraps each additive route (via its own layout.tsx) so styles/additions.css loads only there. */
export function AdditionsFrame({ children }: { children: ReactNode }) {
  return <div className="add-root">{children}</div>;
}
