"use client";

import { useMemo, useState } from "react";
import { SeverityBadge, StatusBadge } from "@/components/additions/Badges";
import { EmptyState, ErrorState, LoadingState, NeedsBackend } from "@/components/additions/States";
import { isStub, isStubReview } from "@/components/app/reviewLabels";
import { Panel, Panels, StageHead } from "@/components/app/Stage";
import { coverage, type Sentence, type SentenceStatus } from "@/lib/additions/coverage";
import { textOf, useReviewData, useReviewParam } from "@/lib/additions/review";
import type { ReviewOut } from "@/lib/api/types";

const LOOK: Record<SentenceStatus, { tone: string; glyph: string; label: string }> = {
  supported: { tone: "ok", glyph: "✓", label: "Supported" },
  unverified: { tone: "warn", glyph: "?", label: "Not proven yet" },
  contradicted: { tone: "bad", glyph: "≠", label: "Contradicted" },
  none: { tone: "none", glyph: "–", label: "No claim" },
};

export function Coverage() {
  const id = useReviewParam();
  const { value, reload } = useReviewData(id);
  if (value.state === "none")
    return (
      <>
        <StageHead title="Coverage" />
        <EmptyState title="No review chosen">Open a review first, then come here with its link.</EmptyState>
      </>
    );
  if (value.state === "loading")
    return (
      <>
        <StageHead title="Coverage" />
        <LoadingState label="Loading the review…" />
      </>
    );
  if (value.state === "error")
    return (
      <>
        <StageHead title="Coverage" />
        <ErrorState error={value.error} onRetry={reload} />
      </>
    );
  return <CoverageView key={value.review.id} review={value.review} />;
}

function CoverageView({ review }: { review: ReviewOut }) {
  const text = textOf(review);
  const stub = isStubReview(review);
  const real = useMemo(() => review.findings.filter((f) => !isStub(f)), [review.findings]);
  const cov = useMemo(() => (text === null || stub ? null : coverage(text, real)), [text, stub, real]);
  const [pick, setPick] = useState<number | null>(null);
  const firstFlagged = cov?.sentences.findIndex((s) => s.status !== "none") ?? -1;
  const current = cov ? (cov.sentences[pick ?? (firstFlagged >= 0 ? firstFlagged : 0)] ?? null) : null;
  const total = cov?.sentences.length ?? 0;

  return (
    <>
      <StageHead title="Coverage" status={review.title ?? undefined} />

      {review.status === "failed" && (
        <div className="app-alert app-alert--bad" role="alert">
          <b>The check didn’t run</b>, so there is no coverage to show. {review.error_summary ?? ""} This is not an approval.
        </div>
      )}
      {stub && (
        <div className="app-alert app-alert--placeholder" role="note">
          <b>Placeholder review.</b> No AI service checked this text, so there is no evidence coverage. Nothing below is a result.
        </div>
      )}
      {text === null && (
        <EmptyState title="The draft text isn’t available">
          <NeedsBackend>ReviewOut.text (this server didn’t send the review’s text and this browser has no copy).</NeedsBackend>
        </EmptyState>
      )}

      {cov && (
        <div className="add-coverage" aria-label="Evidence coverage">
          <div className="add-row">
            <span className="t-caption">Evidence coverage</span>
            <span className="add-coverage__pct">{cov.percent === null ? "–" : `${cov.percent}%`}</span>
            <span className="add-note add-muted">
              {cov.percent === null
                ? "No checkable claims were found in this text."
                : `${cov.counts.supported} of ${cov.counts.supported + cov.counts.unverified + cov.counts.contradicted} sentences with a claim are backed by an approved document.`}
            </span>
          </div>
          {total > 0 && (
            <span className="add-coverage__bar" aria-hidden="true">
              {(["supported", "unverified", "contradicted", "none"] as SentenceStatus[]).map((s) =>
                cov.counts[s] ? <span key={s} className={`add-coverage__${LOOK[s].tone}`} style={{ flex: cov.counts[s] }} /> : null,
              )}
            </span>
          )}
          <ul className="add-coverage__legend">
            {(["supported", "unverified", "contradicted", "none"] as SentenceStatus[]).map((s) => (
              <li key={s}>
                <span aria-hidden="true">{LOOK[s].glyph}</span> {LOOK[s].label}: <b>{cov.counts[s]}</b>
              </li>
            ))}
          </ul>
        </div>
      )}

      {cov && (
        <Panels cols="2">
          <Panel n="01" label="Your text" title="Sentence by sentence">
            {total === 0 ? (
              <EmptyState title="Nothing to show">The text is empty.</EmptyState>
            ) : (
              <ol className="add-sentences">
                {cov.sentences.map((s, i) => (
                  <li key={i}>
                    <button
                      type="button"
                      className={`add-sentence add-sentence--${LOOK[s.status].tone}${current === s ? " is-current" : ""}`}
                      aria-pressed={current === s}
                      onClick={() => setPick(i)}
                    >
                      <span>{s.text.trim()}</span>
                      <span className="add-badge add-badge--none" aria-label={LOOK[s.status].label}>
                        <span aria-hidden="true">{LOOK[s.status].glyph}</span> {LOOK[s.status].label}
                      </span>
                    </button>
                  </li>
                ))}
              </ol>
            )}
          </Panel>

          <Panel n="02" label="Why" title={current ? LOOK[current.status].label : "–"}>
            {current ? <SentenceDetail s={current} /> : <p className="add-note">Pick a sentence.</p>}
          </Panel>
        </Panels>
      )}
    </>
  );
}

function SentenceDetail({ s }: { s: Sentence }) {
  if (s.status === "none")
    return <p className="add-note">No claim in this sentence was checked, so it doesn’t count toward coverage either way.</p>;
  return (
    <div className="add-stack" aria-live="polite">
      {s.findings.map((f) => (
        <div key={f.finding_id} className="add-stack">
          <div className="add-row">
            <StatusBadge status={f.verification_status} />
            <SeverityBadge severity={f.severity} />
          </div>
          <p className="add-note">
            <b>Claim:</b> “{f.original_text}”
          </p>
          {f.evidence.length ? (
            f.evidence.map((e) => (
              <div key={e.id} className="add-window">
                <p className="add-window__src">
                  {e.relation === "supports" ? "Approved source agrees" : e.relation === "contradicts" ? "Approved source says otherwise" : "Related approved text"}
                </p>
                <p className="add-window__quote">“{e.quote}”</p>
              </div>
            ))
          ) : (
            <p className="app-alert" role="note">
              ? No approved document covers this claim. Not proven yet is not the same as wrong.
            </p>
          )}
          {f.explanation && (
            <p className="add-note">
              <b>Why:</b> {f.explanation}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
