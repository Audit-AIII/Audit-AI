/** Number tiles and horizontal bars for Insights / Scorecard. Values are always printed as text too. */
export function Metric({ label, value, target, absent }: { label: string; value: string; target?: string; absent?: boolean }) {
  return (
    <div className="add-metric">
      <span className="add-metric__label">{label}</span>
      <span className={absent ? "add-metric__value add-metric__value--absent" : "add-metric__value"}>
        {absent && <span aria-hidden="true">◌ </span>}
        {value}
      </span>
      {target && <span className="add-metric__target">{target}</span>}
    </div>
  );
}

export function Bars({ items, format }: { items: { label: string; value: number; max: number }[]; format: (v: number) => string }) {
  return (
    <ul className="add-bars">
      {items.map((i) => (
        <li key={i.label}>
          <span>{i.label}</span>
          <span className="add-bars__track" aria-hidden="true">
            <span className="add-bars__fill" style={{ width: `${i.max ? Math.min(100, (i.value / i.max) * 100) : 0}%` }} />
          </span>
          <b>{format(i.value)}</b>
        </li>
      ))}
    </ul>
  );
}

export const pct = (v: number | null) => (v === null ? "–" : `${Math.round(v * 100)}%`);
export const duration = (mins: number | null) =>
  mins === null ? "–" : mins > 0 && mins < 1 ? "under 1 min" : mins < 60 ? `${Math.round(mins)} min` : mins < 2880 ? `${Math.round(mins / 60)} h` : `${Math.round(mins / 1440)} days`;
