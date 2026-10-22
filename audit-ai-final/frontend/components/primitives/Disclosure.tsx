import type { ReactNode } from "react";

/** Native details/summary row with a raised plus that presses in when open. */
export function Disclosure({ question, children }: { question: string; children: ReactNode }) {
  return (
    <details className="disclosure">
      <span className="disclosure__crease" aria-hidden="true" />
      <summary className="disclosure__summary">
        <span className="disclosure__question t-title relief-raised-canvas">{question}</span>
        <span className="disclosure__mark" aria-hidden="true" />
      </summary>
      <div className="disclosure__answer t-body">{children}</div>
    </details>
  );
}
