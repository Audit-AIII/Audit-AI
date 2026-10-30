"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiActionError } from "@/components/additions/ApiActionError";
import { WorkflowBadge } from "@/components/additions/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/additions/States";
import { auditLook, routingText, statusChange } from "@/lib/additions/governance";
import { ApiError } from "@/lib/api/client";
import type { AuditEventOut } from "@/lib/api/types";
import "@/styles/additions.css";

type Page = { items: AuditEventOut[]; next_cursor: string | null };
type Load = { state: "loading" } | { state: "ok"; items: AuditEventOut[]; next: string | null } | { state: "error"; error: unknown };

/** Events whose note is the server's routing text. */
const ROUTING_ACTIONS = new Set(["routing_decision", "review_requested"]);

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

/**
 * An audit trail, newest first, from the server's append-only log. Raw details are never printed;
 * only a before and after status when the event has one. `fetchPage` must be stable (useCallback).
 */
export function AuditTimeline({
  fetchPage,
  emptyTitle,
  emptyBody,
  forbidden,
  solo = false,
}: {
  fetchPage: (cursor: string | null) => Promise<Page>;
  emptyTitle: string;
  emptyBody?: string;
  /** Replaces the 403 wording where a page has a specific reason. */
  forbidden?: string;
  /** Alone in the workspace: a routing note's "a reviewer must check" isn't true for them. */
  solo?: boolean;
}) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [tick, setTick] = useState(0);
  const [more, setMore] = useState(false);
  const [moreError, setMoreError] = useState<unknown>(null);

  useEffect(() => {
    let live = true;
    fetchPage(null)
      .then((p) => live && setLoad({ state: "ok", items: p.items, next: p.next_cursor }))
      .catch((error) => live && setLoad({ state: "error", error }));
    return () => {
      live = false;
    };
  }, [fetchPage, tick]);

  const loadMore = useCallback(async () => {
    if (load.state !== "ok" || !load.next) return;
    setMore(true);
    setMoreError(null);
    try {
      const p = await fetchPage(load.next);
      setLoad({ state: "ok", items: [...load.items, ...p.items], next: p.next_cursor });
    } catch (err) {
      setMoreError(err);
    } finally {
      setMore(false);
    }
  }, [fetchPage, load]);

  if (load.state === "loading") return <LoadingState label="Loading the history…" />;
  if (load.state === "error") {
    const denied = load.error instanceof ApiError && load.error.status === 403;
    return (
      <ErrorState
        error={load.error}
        message={denied ? forbidden : undefined}
        onRetry={() => {
          setLoad({ state: "loading" });
          setTick((t) => t + 1);
        }}
      />
    );
  }
  if (load.items.length === 0) return <EmptyState title={emptyTitle}>{emptyBody}</EmptyState>;
  return (
    <>
      <ol className="timeline" aria-label="History, newest first">
        {load.items.map((e) => {
          const look = auditLook(e.action);
          const change = statusChange(e.details);
          return (
            <li key={e.id} className="timeline__item">
              <time className="timeline__at t-caption" dateTime={e.created_at} title={e.created_at}>
                {when(e.created_at)}
              </time>
              <div>
                <p className="rows__title">
                  <span aria-hidden="true">{look.glyph}</span> {look.label}
                </p>
                <p className="rows__meta">
                  {e.actor?.display_name ?? "System"}
                  {e.version_number != null ? ` · version ${e.version_number}` : ""}
                </p>
                {change && (
                  <p className="rows__meta add-audit-change">
                    <WorkflowBadge status={change.before} /> <span aria-label="changed to">→</span> <WorkflowBadge status={change.after} />
                  </p>
                )}
                {e.note && <p className="t-body panel__note add-prewrap">{ROUTING_ACTIONS.has(e.action) ? routingText(e.note, solo) : e.note}</p>}
              </div>
            </li>
          );
        })}
      </ol>
      <ApiActionError error={moreError} />
      {load.next && (
        <button type="button" className="add-btn-small add-audit-more" onClick={loadMore} disabled={more} aria-busy={more}>
          {more ? "Loading…" : "Load more"}
        </button>
      )}
    </>
  );
}
