"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/primitives/Button";
import { Panel, Panels, StageHead } from "@/components/app/Stage";
import { checkName, isStub, isStubReview, reviewHeadline, severity, stubReason, verdict } from "@/components/app/reviewLabels";
import { ApiError, api } from "@/lib/api/client";
import type { FindingOut, ReviewOut } from "@/lib/api/types";
import { segment } from "@/lib/text/codepoints";
import { getReviewText, setLastReviewId } from "@/lib/workspace";

type Load = { state: "loading" } | { state: "ok"; review: ReviewOut } | { state: "error"; message: string; requestId: string | null };

const ORDER: Record<string, number> = { contradicted: 0, conflicting_sources: 1, unverified: 2, not_applicable: 3, supported: 4 };

/** Review stage: GET /api/reviews/{id} (id from ?id=, so a refresh reloads the same review). */
export function ReviewResult() {
  const id = useSearchParams().get("id");
  // Keyed so opening another review starts again from "loading".
  return id ? <ReviewLoader key={id} id={id} /> : <NoReview />;
}

function NoReview() {
  return (
    <>
      <StageHead title="Review" status="No review yet" />
      <div className="app-empty card">
        <p className="t-body">Send a draft first. Its problems will show up here.</p>
        <Button href="/app/draft">Check a draft →</Button>
      </div>
    </>
  );
}

function ReviewLoader({ id }: { id: string }) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  // Client-only render (AppShell waits for the session), so localStorage is safe to read here.
  const [text] = useState(() => getReviewText(id));
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .review(id)
      .then((review) => {
        if (!live) return;
        setLastReviewId(review.id); // Decide / Record pick this up from the stage bar
        setLoad({ state: "ok", review });
      })
      .catch((err) => {
        if (!live) return;
        const message =
          err instanceof ApiError && err.status === 404
            ? "We couldn’t find this review. It may belong to another organisation, or the link is wrong."
            : err instanceof ApiError
              ? err.userMessage
              : "Something went wrong. Please try again.";
        setLoad({ state: "error", message, requestId: err instanceof ApiError ? err.requestId : null });
      });
    return () => {
      live = false;
    };
  }, [id]);

  if (load.state === "loading") {
    return (
      <>
        <StageHead title="Review" status="Loading…" />
        <p className="t-body" role="status">
          Loading the review…
        </p>
      </>
    );
  }
  if (load.state === "error") {
    return (
      <>
        <StageHead title="Review" status="Couldn’t load" />
        <div className="app-empty card">
          <p className="app-alert app-alert--bad" role="alert">
            {load.message}
          </p>
          {load.requestId && (
            <p className="t-caption">
              Reference: <code className="request-id">{load.requestId}</code>
            </p>
          )}
          <Button href="/app/draft">Check a draft →</Button>
        </div>
      </>
    );
  }
  return <ReviewView review={load.review} savedText={text} selected={selected} onSelect={setSelected} />;
}

function ReviewView({
  review,
  savedText,
  selected,
  onSelect,
}: {
  review: ReviewOut;
  savedText: string | null;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const stub = isStubReview(review);
  const findings = useMemo(
    () => [...review.findings].sort((a, b) => (ORDER[a.verification_status] ?? 2) - (ORDER[b.verification_status] ?? 2)),
    [review.findings],
  );
  // The text the spans point into: from the API first; older backends don't send it, so fall
  // back to this browser's copy, then the stub finding (its original_text is the whole text).
  const fullText = review.text ?? savedText ?? review.findings.find(isStub)?.original_text ?? null;
  const current = findings.find((f) => f.finding_id === selected) ?? findings[0] ?? null;

  return (
    <>
      <StageHead title="Review" status={reviewHeadline(review, stub)} />

      {stub && (
        <div className="app-alert app-alert--placeholder" role="note">
          <b>Placeholder, not a real check.</b> The server has no AI service set up, so no claims were checked. What you see below
          is a fixed test result that proves the connection works.
        </div>
      )}
      {review.status === "failed" && (
        <div className="app-alert app-alert--bad" role="alert">
          <b>We couldn’t check this draft.</b> {review.error_summary ?? "The server didn’t say why."}{" "}
          {/no approved source/i.test(review.error_summary ?? "") && (
            <Link className="link" href="/app/sources">
              Check the brand’s documents
            </Link>
          )}
        </div>
      )}

      <Panels>
        <Panel n="01" label="Your draft" title="Problems marked">
          {fullText !== null ? (
            <HeatText text={fullText} findings={findings} stub={stub} current={current?.finding_id} onSelect={onSelect} />
          ) : (
            <p className="app-alert" role="note">
              The full draft isn’t stored on the server, and this browser doesn’t have a copy. Each problem below still shows the
              sentence it’s about.
            </p>
          )}
          {!stub && fullText !== null && (
            <p className="legend t-caption">
              <span className="legend__ok">✓ Matches</span> <span className="legend__warn">? Not proven yet</span>{" "}
              <span className="legend__bad">≠ Doesn’t match</span>
            </p>
          )}
        </Panel>

        <Panel n="02" label="Problems found" title={findings.length ? `${findings.length} to look at` : "Nothing found"}>
          {findings.length === 0 ? (
            <p className="t-body panel__note">{review.status === "failed" ? "No results, see the note above." : "No problems found in this draft."}</p>
          ) : (
            <ul className="rows" aria-label="Problems">
              {findings.map((f) => {
                const v = verdict(f.verification_status);
                const sev = severity(f.severity);
                const on = f.finding_id === current?.finding_id;
                return (
                  <li key={f.finding_id}>
                    <button
                      type="button"
                      className={`rows__item problem${on ? " is-selected" : ""}${isStub(f) ? " problem--stub" : ""}`}
                      aria-pressed={on}
                      onClick={() => onSelect(f.finding_id)}
                    >
                      <span>
                        <span className="t-caption">{isStub(f) ? "Placeholder" : checkName(f)}</span>
                        <span className="rows__title">“{clip(f.original_text)}”</span>
                        <span className="rows__meta">
                          {isStub(f) ? (
                            <span className="chip chip--placeholder">◌ Not checked</span>
                          ) : (
                            <span className={`chip chip--${v.tone}`}>
                              {v.glyph} {v.label}
                            </span>
                          )}{" "}
                          {!isStub(f) && (
                            <span className="sev" aria-label={`${sev.word} severity`}>
                              {sev.marks} {sev.word}
                            </span>
                          )}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>

        <Panel n="03" label="Why it was flagged" title={current ? (isStub(current) ? "Placeholder" : verdict(current.verification_status).label) : "–"}>
          {current ? <FindingDetail f={current} /> : <p className="t-body panel__note">Pick a problem to see why.</p>}
          <EngineNote review={review} stub={stub} />
          <Button href={`/app/decide?id=${review.id}`}>Choose what to do →</Button>
        </Panel>
      </Panels>
    </>
  );
}

function FindingDetail({ f }: { f: FindingOut }) {
  if (isStub(f)) {
    return (
      <div className="evidence evidence--placeholder" aria-live="polite">
        <p className="t-caption">From the server</p>
        <p className="evidence__quote">{stubReason(f) || "No AI service is set up for this server."}</p>
      </div>
    );
  }
  return (
    <div className="finding-detail" aria-live="polite">
      {f.evidence.length > 0 ? (
        f.evidence.map((e) => (
          <div className="evidence" key={e.id}>
            <p className="t-caption evidence__src">
              {e.relation === "supports" ? "Your document says (agrees)" : e.relation === "contradicts" ? "Your document says (disagrees)" : "Related text in your documents"}
            </p>
            <p className="evidence__quote">“{e.quote}”</p>
          </div>
        ))
      ) : (
        <p className="app-alert" role="note">
          None of your approved documents cover this. That means it isn’t proven yet, not that it’s wrong.
        </p>
      )}
      {f.explanation && (
        <p className="t-body panel__note">
          <b>The problem:</b> {f.explanation}
        </p>
      )}
      {f.suggested_correction && (
        <p className="t-body panel__note">
          <b>We suggest:</b> “{f.suggested_correction}”
        </p>
      )}
      {f.requires_human_review && <p className="t-caption">A person needs to decide on this one.</p>}
    </div>
  );
}

function EngineNote({ review, stub }: { review: ReviewOut; stub: boolean }) {
  const e = review.engine;
  return (
    <p className="t-caption engine-note">
      {stub ? "Checked by: nobody (placeholder)" : e?.model_id ? `Checked by ${e.provider ?? "AI"} · ${e.model_id}` : "Checked by the rules engine"}
      {review.served_from_cache ? " · reused an earlier identical check" : ""}
    </p>
  );
}

/** Draft text with each finding's span marked. Spans are code points, converted in segment(). */
function HeatText({
  text,
  findings,
  stub,
  current,
  onSelect,
}: {
  text: string;
  findings: FindingOut[];
  stub: boolean;
  current?: string;
  onSelect: (id: string) => void;
}) {
  const parts = useMemo(() => segment(text, findings.map((f) => ({ span: f.span, item: f }))), [text, findings]);
  return (
    <p className="heat">
      {parts.map((p, i) => {
        if (!p.marks.length) return <span key={i}>{p.text}</span>;
        // Several findings over one run: show the most serious verdict, select the first.
        const top = [...p.marks].sort((a, b) => (ORDER[a.verification_status] ?? 2) - (ORDER[b.verification_status] ?? 2))[0];
        const tone = stub ? "placeholder" : { supported: "ok", contradicted: "bad" }[top.verification_status as string] ?? "warn";
        const on = p.marks.some((m) => m.finding_id === current);
        return (
          // <mark> (not <button>) so the highlight wraps inline with the sentence; still a keyboard stop.
          <mark
            key={i}
            role="button"
            tabIndex={0}
            className={`heat__mark heat__${tone}${on ? " is-current" : ""}`}
            onClick={() => onSelect(top.finding_id)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect(top.finding_id);
              }
            }}
            aria-label={`${p.text}: ${stub ? "placeholder" : verdict(top.verification_status).label}`}
          >
            {p.text}
          </mark>
        );
      })}
    </p>
  );
}

const clip = (s: string, n = 90) => ([...s].length > n ? `${[...s].slice(0, n).join("")}…` : s);
