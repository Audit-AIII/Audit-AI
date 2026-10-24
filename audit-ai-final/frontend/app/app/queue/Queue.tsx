"use client";

import { useEffect, useMemo, useState } from "react";
import { EmptyState, ErrorState, LoadingState } from "@/components/additions/States";
import { canReview, roleName } from "@/components/app/roles";
import { Panel, Panels, StageHead } from "@/components/app/Stage";
import { useBrands } from "@/lib/additions/brands";
import { loadQueue, type QueueLoad, type QueueRow } from "@/lib/additions/queue";
import { useSession } from "@/lib/session";

type Load = { state: "loading" } | { state: "ok"; data: QueueLoad } | { state: "error"; error: unknown };

const RISK_LOOK: Record<QueueRow["risk"], { glyph: string; label: string; tone: string }> = {
  high: { glyph: "●●●", label: "High", tone: "bad" },
  medium: { glyph: "●●○", label: "Medium", tone: "warn" },
  low: { glyph: "●○○", label: "Low", tone: "ok" },
  none: { glyph: "○○○", label: "None found", tone: "none" },
};
const STATUS_LABEL: Record<string, string> = {
  needs_human_review: "Waiting for a reviewer",
  completed: "Checked, nothing flagged",
  approved: "Approved",
  changes_requested: "Sent back",
  rejected: "Rejected",
  failed: "Check didn’t run",
  source_changed: "Source changed, re-check",
};

function age(iso: string) {
  if (!iso) return "–";
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 60) return `${mins} min`;
  const h = Math.round(mins / 60);
  return h < 48 ? `${h} h` : `${Math.round(h / 24)} days`;
}

export function Queue() {
  const role = useSession()?.role ?? "";
  const { value: brands } = useBrands();
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    loadQueue()
      .then((data) => live && setLoad({ state: "ok", data }))
      .catch((error) => live && setLoad({ state: "error", error }));
    return () => {
      live = false;
    };
  }, [tick]);

  const brandName = useMemo(() => {
    const map = new Map(brands.state === "ready" ? brands.brands.map((b) => [b.id, b.name] as const) : []);
    return (id: string | null) => (id ? (map.get(id) ?? "Another brand") : "–");
  }, [brands]);

  const rows = load.state === "ok" ? load.data.rows : [];
  const waiting = rows.filter((r) => r.status === "needs_human_review" || r.status === "completed");
  const done = rows.filter((r) => !waiting.includes(r));

  return (
    <>
      <StageHead title="Queue" status={load.state === "ok" ? `${waiting.length} waiting` : undefined} />
      {!canReview(role) && (
        <p className="app-alert" role="note">
          ⊘ Your role ({roleName(role)}) can see the queue but can’t decide on drafts. A reviewer or approver does that.
        </p>
      )}

      <Panels cols="wide">
        <Panel n="01" label="Waiting for review" title="Waiting for review">
          {load.state === "loading" && <LoadingState label="Loading reviews…" />}
          {load.state === "error" && <ErrorState error={load.error} onRetry={() => setTick((t) => t + 1)} />}
          {load.state === "ok" && rows.length === 0 && <EmptyState title="Nothing here yet">Reviews appear here after a draft is checked.</EmptyState>}
          {load.state === "ok" && rows.length > 0 && waiting.length === 0 && <EmptyState title="Nothing waiting">Every review has been decided.</EmptyState>}
          {waiting.length > 0 && <QueueTable rows={waiting} brandName={brandName} />}
          {done.length > 0 && (
            <details className="add-details">
              <summary>Already decided or not decidable ({done.length})</summary>
              <QueueTable rows={done} brandName={brandName} />
            </details>
          )}
        </Panel>

      </Panels>
    </>
  );
}

function QueueTable({ rows, brandName }: { rows: QueueRow[]; brandName: (id: string | null) => string }) {
  return (
    <div className="add-table__wrap">
      <table className="add-table">
        <thead>
          <tr>
            <th scope="col">Draft</th>
            <th scope="col">Brand</th>
            <th scope="col">Risk</th>
            <th scope="col">Needs</th>
            <th scope="col">Age</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const risk = RISK_LOOK[r.risk];
            return (
              <tr key={r.id}>
                <td>
                  <a className="link" href={`/app/decide?id=${r.id}`}>
                    {r.title}
                  </a>
                  {r.placeholder && <div className="add-note add-muted">◌ Placeholder check (no AI ran)</div>}
                </td>
                <td>{brandName(r.brandId)}</td>
                <td>
                  <span className={`add-badge add-badge--${risk.tone}`}>
                    <span aria-hidden="true">{risk.glyph}</span> {risk.label}
                  </span>
                </td>
                <td>{r.requiredRole ? roleName(r.requiredRole) : "–"}</td>
                <td>{age(r.createdAt)}</td>
                <td>{STATUS_LABEL[r.status] ?? r.status.replace(/_/g, " ")}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
