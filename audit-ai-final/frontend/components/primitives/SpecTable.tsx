import type { ReactNode } from "react";

export type SpecRow = { label: string; value: ReactNode };

/** Dotted label/value rows (e.g. CHECK / SOURCE / RESULT). */
export function SpecTable({ rows, className }: { rows: SpecRow[]; className?: string }) {
  return (
    <dl className={className ? `spec ${className}` : "spec"}>
      {rows.map((row) => (
        <div className="spec__row" key={row.label}>
          <dt>{row.label}</dt>
          <dd>{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}
