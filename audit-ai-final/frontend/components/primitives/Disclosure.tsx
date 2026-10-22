import type { ReactNode } from "react";

/** Native details/summary row with a raised plus that presses in when open. */
export function Disclosure({ question, children, id }: { question: string; children: ReactNode; id?: string }) {
  return (
    <details className="disclosure" id={id}>
      <summary className="disclosure__summary">
        <span className="disclosure__question t-title relief-raised-canvas">{question}</span>
        <span className="disclosure__mark" aria-hidden="true" />
      </summary>
      <div className="disclosure__answer t-body">{children}</div>
    </details>
  );
}
