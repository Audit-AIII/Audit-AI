"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Fragment, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Button } from "@/components/primitives/Button";
import { FindingComments } from "@/components/additions/FindingComments";
import { FindingDismiss } from "@/components/additions/FindingDismiss";
import { ApiActionError } from "@/components/additions/ApiActionError";
import { ReviewSummary } from "@/components/additions/ReviewSummary";
import { EmptyState, ErrorState, PartialState } from "@/components/additions/States";
import { Panel, Panels, StageHead } from "@/components/app/Stage";
import { Thinking } from "@/components/app/Thinking";
import {
  checkName,
  findingChip,
  isChecking,
  isPartialReview,
  isRule,
  isStub,
  isStubReview,
  isWholeDraft,
  relationLook,
  reviewHeadline,
  reviewReasonText,
  ruleCategoryLabel,
  ruleTypeLabel,
  severity,
  stubReason,
  suggestionFor,
  validationLook,
} from "@/components/app/reviewLabels";
import { ApiError, api } from "@/lib/api/client";
import type { FindingOut, ReviewOut, RuleCheck } from "@/lib/api/types";
import { rerun } from "@/lib/additions/content";
import { applyComment, applyDecision, commentCountText, DISMISSED, isDismissed } from "@/lib/additions/findingState";
import { isAllowed, isSolo } from "@/lib/additions/governance";
import { hiddenToneText, isTone, isUncertainTone, withToneRule } from "@/lib/additions/tone";
import { segment, spanLocated } from "@/lib/text/codepoints";
import { getReviewText, setLastReviewId } from "@/lib/workspace";

type Load = { state: "loading" } | { state: "ok"; review: ReviewOut } | { state: "error"; error: unknown };

/** How often to look again while a check is still running. */
const CHECKING_POLL_MS = 3000;

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
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let live = true;
    api
      .review(id)
      .then((review) => {
        if (!live) return;
        setLastReviewId(review.id); // Decide / Record pick this up from the stage bar
        setLoad({ state: "ok", review: withToneRule(review) });
      })
      .catch((error) => {
        if (live) setLoad({ state: "error", error });
      });
    return () => {
      live = false;
    };
  }, [id, tick]);

  // Keeps looking while the check runs, so the page never sits on a stale "still checking".
  const checking = load.state === "ok" && isChecking(load.review);
  useEffect(() => {
    if (!checking) return;
    const timer = window.setTimeout(() => setTick((t) => t + 1), CHECKING_POLL_MS);
    return () => window.clearTimeout(timer);
  }, [checking, tick]);

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
    const missing = load.error instanceof ApiError && load.error.status === 404;
    return (
      <>
        <StageHead title="Review" status="Couldn’t load" />
        <div className="app-empty card">
          <ErrorState
            error={load.error}
            message={missing ? "We couldn’t find this review. It may belong to another workspace, or the link is wrong." : undefined}
            onRetry={
              missing
                ? undefined
                : () => {
                    setLoad({ state: "loading" });
                    setTick((t) => t + 1);
                  }
            }
          />
          <Button href="/app/draft">Check a draft →</Button>
        </div>
      </>
    );
  }
  if (isChecking(load.review)) {
    return (
      <>
        <StageHead title="Review" status="Checking…" />
        <div className="app-empty card">
          <Thinking label="Checking your draft" detail="Reading each claim and looking for it in your approved documents." />
        </div>
      </>
    );
  }
  // Only ever called with a backend response (dismiss / restore / comment), never optimistically.
  const onReview = (update: (r: ReviewOut) => ReviewOut) => setLoad((l) => (l.state === "ok" ? { ...l, review: update(l.review) } : l));
  return <ReviewView review={load.review} savedText={text} selected={selected} onSelect={setSelected} onReview={onReview} />;
}

function ReviewView({
  review,
  savedText,
  selected,
  onSelect,
  onReview,
}: {
  review: ReviewOut;
  savedText: string | null;
  selected: string | null;
  onSelect: (id: string) => void;
  onReview: (update: (r: ReviewOut) => ReviewOut) => void;
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
  const personal = isSolo(review);
  const canRerun = isAllowed(review.allowed_actions, "rerun");
  const detailRef = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const [rechecking, setRechecking] = useState(false);
  const [recheckError, setRecheckError] = useState<unknown>(null);

  // A new check is a new review, so this opens it; on failure the page and its message stay.
  const recheck = async () => {
    setRechecking(true);
    setRecheckError(null);
    try {
      const r = await rerun(review.id, crypto.randomUUID());
      router.push(`/app/review?id=${r.id}`);
    } catch (err) {
      setRecheckError(err);
      setRechecking(false);
    }
  };

  // Moves the other side into view after a pick. On phones the panels stack, so a pick in the list
  // stays put rather than jumping up to the draft.
  const reveal = (selector: string) =>
    requestAnimationFrame(() => {
      const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      document.querySelector(selector)?.scrollIntoView({ block: "nearest", behavior: still ? "auto" : "smooth" });
    });
  const pickFromList = (id: string) => {
    onSelect(id);
    if (window.matchMedia("(min-width: 768px)").matches) reveal(".heat__mark.is-current");
  };
  const pickFromDraft = (id: string) => {
    onSelect(id);
    reveal(".problem.is-selected");
  };
  // Arrow keys walk the list, Enter opens the details, Esc (there) comes back to the row.
  const onRowKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    if (e.key === "Enter") {
      e.preventDefault();
      pickFromList(findings[i].finding_id);
      detailRef.current?.focus();
      return;
    }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const next = findings[i + (e.key === "ArrowDown" ? 1 : -1)];
    if (!next) return;
    e.preventDefault();
    pickFromList(next.finding_id);
    requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-finding="${next.finding_id}"]`)?.focus());
  };
  const onDetailKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Escape" || /^(TEXTAREA|INPUT)$/.test((e.target as HTMLElement).tagName)) return;
    document.querySelector<HTMLElement>(".problem.is-selected")?.focus();
  };

  if (review.status === "failed" && findings.length === 0) {
    return (
      <>
        <StageHead title="Review" status={reviewHeadline(review, stub)} />
        <div className="app-empty card">
          {rechecking ? (
            <Thinking label="Checking your draft again" />
          ) : (
            <ErrorState title="We couldn’t check this draft" message={review.error_summary ?? "The server didn’t say why."} onRetry={canRerun ? recheck : undefined}>
              {/no approved source/i.test(review.error_summary ?? "") && (
                <Link className="link" href="/app/sources">
                  Check the brand’s documents
                </Link>
              )}
            </ErrorState>
          )}
          <ApiActionError error={recheckError} />
        </div>
      </>
    );
  }

  return (
    <>
      <StageHead title="Review" status={reviewHeadline(review, stub)} />

      {stub && (
        <div className="app-alert app-alert--placeholder" role="note">
          <b>Placeholder, not a real check.</b> The server has no AI service set up, so no claims were checked. What you see below
          is a fixed test result that proves the connection works.
        </div>
      )}
      {review.rules_status === "not_applied" && (
        <div className="app-alert app-alert--bad" role="alert">
          <b>Your brand rules didn’t run on this draft.</b> So this draft is not shown as passing your brand rules.{" "}
          {review.status !== "failed" && review.error_summary ? review.error_summary : ""}
        </div>
      )}
      {isPartialReview(review) && (
        <div className="add-partial-wrap">
          {rechecking ? (
            <Thinking label="Checking your draft again" />
          ) : (
            <PartialState
              title="This check didn’t finish"
              missing={
                <>
                  {review.rules_status === "incomplete"
                    ? "Some brand rule checks didn’t finish, so this draft is not shown as passing your brand rules. "
                    : "Some claims couldn’t be checked. "}
                  {review.error_summary ?? ""}
                </>
              }
              shown={findings.length ? "The results below are real, but there may be more to find." : "Nothing else came back from this check."}
              onRetry={canRerun ? recheck : undefined}
            />
          )}
          <ApiActionError error={recheckError} />
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

      {!stub && findings.length > 0 && <ReviewSummary findings={findings} counts={review.summary_counts} current={current?.finding_id} onSelect={pickFromDraft} />}

      <Panels>
        <Panel n="01" label="Your draft" title="Problems marked">
          {fullText !== null ? (
            <HeatText
              text={fullText}
              // "Whole draft" rule findings anchor on line 1 but are about what is missing: not highlighted.
              // Nor is a finding whose span doesn't hold its words: that would mark the wrong text.
              findings={findings.filter((f) => !isWholeDraft(f) && !isUncertainTone(f) && spanLocated(fullText, f.span, f.original_text))}
              current={current?.finding_id}
              onSelect={pickFromDraft}
            />
          ) : (
            <p className="app-alert" role="note">
              The full draft isn’t stored on the server, and this browser doesn’t have a copy. Each problem below still shows the
              sentence it’s about.
            </p>
          )}
          {!stub && fullText !== null && (
            <p className="legend t-caption">
              <span className="legend__ok">✓ Matches</span> <span className="legend__warn">? Not proven yet</span>{" "}
              <span className="legend__bad">≠ Doesn’t match</span> <span className="legend__rule">§ Brand rule</span>
            </p>
          )}
          {findings.some(isWholeDraft) && (
            <ul className="whole-draft" aria-label="About the whole draft">
              {findings.filter(isWholeDraft).map((f) => (
                <li key={f.finding_id}>
                  <button type="button" className="whole-draft__item" onClick={() => pickFromDraft(f.finding_id)}>
                    <span aria-hidden="true">§</span> Whole draft: {f.explanation ?? ruleTypeLabel(f.rule_type)}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel n="02" label="Problems found" title={findings.length ? `${findings.length} to look at` : "Nothing found"}>
          {findings.length === 0 ? (
            <EmptyState title="No problems were flagged">
              <NothingFlagged review={review} />
            </EmptyState>
          ) : (
            <ul className="rows" aria-label="Problems">
              {findings.map((f, i) => {
                const v = findingChip(f);
                const sev = severity(f.severity);
                const on = f.finding_id === current?.finding_id;
                return (
                  <li key={f.finding_id}>
                    <button
                      type="button"
                      className={`rows__item problem${on ? " is-selected" : ""}${isStub(f) ? " problem--stub" : ""}`}
                      aria-pressed={on}
                      data-finding={f.finding_id}
                      onClick={() => pickFromList(f.finding_id)}
                      onKeyDown={(e) => onRowKey(e, i)}
                    >
                      <span>
                        <span className="t-caption">{isStub(f) ? "Placeholder" : checkName(f)}</span>
                        <span className="rows__title">{isWholeDraft(f) ? "About the whole draft" : `“${clip(f.original_text)}”`}</span>
                        <span className="rows__meta">
                          {isStub(f) ? (
                            <span className="chip chip--placeholder">◌ Not checked</span>
                          ) : (
                            <span className={`chip chip--${v.tone}`}>
                              {v.glyph} {v.label}
                            </span>
                          )}{" "}
                          {isDismissed(f) && (
                            <span className="chip add-dismissed">
                              <span aria-hidden="true">{DISMISSED.glyph}</span> {DISMISSED.label}
                            </span>
                          )}{" "}
                          {!isStub(f) && (
                            <span className="sev" aria-label={`${sev.word} severity`}>
                              {sev.marks} {sev.word}
                            </span>
                          )}
                          {(f.comment_count ?? 0) > 0 && <span className="add-count t-caption"> · {commentCountText(f.comment_count ?? 0)}</span>}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          {!!review.hidden_tone_count && <p className="t-caption add-team-help">{hiddenToneText(review.hidden_tone_count)}</p>}
        </Panel>

        <Panel n="03" label="Why it was flagged" title={current ? (isStub(current) ? "Placeholder" : findingChip(current).label) : "Nothing flagged"}>
          <div ref={detailRef} className="add-detail" tabIndex={-1} onKeyDown={onDetailKey}>
            {current ? <FindingDetail f={current} text={fullText} personal={personal} /> : <p className="t-body panel__note">There’s nothing to explain on this draft.</p>}
            {current && !isStub(current) && (
              <>
                {isAllowed(review.allowed_actions, "dismiss_finding") && (
                  <FindingDismiss key={current.finding_id} f={current} onDecided={(d) => onReview((r) => applyDecision(r, d))} />
                )}
                <FindingComments
                  key={`c-${current.finding_id}`}
                  findingId={current.finding_id}
                  onAdded={(c) => onReview((r) => applyComment(r, c))}
                  canAdd={isAllowed(review.allowed_actions, "comment")}
                  personal={personal}
                />
              </>
            )}
          </div>
          <EngineNote review={review} stub={stub} />
          {isAllowed(review.allowed_actions, "create_version") && <a className="link" href={`/app/review-edit?id=${review.id}`}>Fix the wording →</a>}
          <a className="link" href={`/app/coverage?id=${review.id}`}>See evidence coverage →</a>
          <Button href={`/app/decide?id=${review.id}`}>Choose what to do →</Button>
        </Panel>
      </Panels>
      <RuleChecks review={review} />
    </>
  );
}

const CHECK_STATUS: Record<string, { glyph: string; label: string; tone: string }> = {
  passed: { glyph: "✓", label: "Passed", tone: "supported" },
  violated: { glyph: "§", label: "Found", tone: "rule" },
  // Nothing to inspect (no links, headings, images...): never call it passed.
  not_checkable: { glyph: "–", label: "Not checked", tone: "neutral" },
  error: { glyph: "!", label: "Couldn’t run", tone: "contradicted" },
};

/** Every brand-rule check that ran on this review, grouped by category. */
function RuleChecks({ review }: { review: ReviewOut }) {
  const checks = review.rule_checks;
  if (review.rules_status == null && !checks) return null; // review from before brand rules existed
  const groups = new Map<string, RuleCheck[]>();
  for (const c of checks ?? []) groups.set(c.category, [...(groups.get(c.category) ?? []), c]);
  return (
    <section className="rule-checks card" aria-labelledby="rule-checks-title">
      <h2 id="rule-checks-title" className="panel__title">
        Brand rule checks
      </h2>
      {!checks || checks.length === 0 ? (
        <p className="t-body panel__note">
          {review.rules_status === "not_applied" ? "No rule checks ran on this draft (see the note above)." : "No rule checks are recorded for this draft."}
        </p>
      ) : (
        [...groups.entries()].map(([cat, list]) => (
          <div key={cat} className="rule-checks__group">
            <h3 className="t-caption">{ruleCategoryLabel(cat)}</h3>
            <ul className="rows">
              {list.map((c) => {
                const s = CHECK_STATUS[c.status] ?? { glyph: "?", label: c.status.replace(/_/g, " "), tone: "neutral" };
                return (
                  <li key={c.rule_id} className="rows__item">
                    <div>
                      <p className="rows__title">{ruleTypeLabel(c.rule_type)}</p>
                      {c.reason && <p className="rows__meta">{c.reason}</p>}
                    </div>
                    <span className={`chip chip--${s.tone}`}>
                      {s.glyph} {c.status === "violated" ? `Found ${c.findings}` : s.label}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        ))
      )}
    </section>
  );
}

/** What was checked on a draft with no findings, so an empty result never looks like a blank one. */
function NothingFlagged({ review }: { review: ReviewOut }) {
  const passed = (review.rule_checks ?? []).filter((c) => c.status === "passed").map((c) => ruleTypeLabel(c.rule_type));
  return (
    <>
      <p className="add-state__body">We looked for claims to check against your approved documents and found nothing to flag.</p>
      {passed.length > 0 && <p className="add-state__body">Brand rules passed: {passed.join(", ")}.</p>}
    </>
  );
}

/** Verdict, severity and (only if the API sends it) validation, each with a glyph and a word. */
function FindingMeta({ f }: { f: FindingOut }) {
  const v = findingChip(f);
  const sev = severity(f.severity);
  const check = f.validation_status ? validationLook(f.validation_status) : null;
  return (
    <p className="rows__meta">
      <span className={`chip chip--${v.tone}`}>
        {v.glyph} {v.label}
      </span>{" "}
      <span className="sev" aria-label={`${sev.word} severity`}>
        {sev.marks} {sev.word}
      </span>{" "}
      {check && (
        <span className="chip chip--neutral">
          {check.glyph} {check.label}
        </span>
      )}
    </p>
  );
}

/** The span doesn't hold the finding's words: say so rather than highlight the wrong text. */
function SpanNote({ f, text }: { f: FindingOut; text: string | null }) {
  if (text === null || isWholeDraft(f) || spanLocated(text, f.span, f.original_text)) return null;
  return (
    <p className="app-alert" role="note">
      <b>Span could not be located.</b> This finding isn’t marked in your draft because its position doesn’t match the text. It’s about: “{clip(f.original_text)}”
    </p>
  );
}

/** One evidence quote in the die-cut window, with the document, its version and how it relates. */
function Evidence({ e, showRelation }: { e: FindingOut["evidence"][number]; showRelation: boolean }) {
  const relation = relationLook(e.relation);
  return (
    <div className="evidence">
      <p className="t-caption evidence__src">
        {e.source_title ?? "Your approved document"}
        {e.source_version_number != null ? ` · version ${e.source_version_number}` : ""}
      </p>
      {showRelation && (
        <p className="t-caption">
          <span aria-hidden="true">{relation.glyph}</span> {relation.label}
        </p>
      )}
      <p className="evidence__quote">“{e.quote}”</p>
    </div>
  );
}

function FindingDetail({ f, text, personal }: { f: FindingOut; text: string | null; personal: boolean }) {
  if (isStub(f)) {
    return (
      <div className="evidence evidence--placeholder" aria-live="polite">
        <p className="t-caption">From the server</p>
        <p className="evidence__quote">{stubReason(f) || "No AI service is set up for this server."}</p>
      </div>
    );
  }
  if (isTone(f)) {
    const uncertain = isUncertainTone(f);
    return (
      <div className="finding-detail" aria-live="polite">
        <FindingMeta f={f} />
        {uncertain && (
          <p className="app-alert" role="note">
            <b>Uncertain.</b> The server couldn’t confirm this against the guideline, so it isn’t marked in your draft.
          </p>
        )}
        {!uncertain && <SpanNote f={f} text={text} />}
        <div className={uncertain ? "evidence evidence--placeholder" : "evidence"}>
          <p className="t-caption evidence__src">
            {f.guideline_source_title ?? "Your brand guideline"}
            {f.guideline_source_version != null ? ` · version ${f.guideline_source_version}` : ""}
          </p>
          <p className="evidence__quote">“{f.guideline_quote}”</p>
        </div>
        {f.explanation && (
          <p className="t-body panel__note">
            <b>Why it doesn’t fit:</b> {f.explanation}
          </p>
        )}
        {f.alternative_wording && (
          <p className="t-body panel__note">
            <b>Suggested wording (nothing is changed for you):</b> “{f.alternative_wording}”
          </p>
        )}
      </div>
    );
  }
  if (isRule(f)) {
    return (
      <div className="finding-detail" aria-live="polite">
        <p className="t-caption">
          {checkName(f)}
          {isWholeDraft(f) ? " · about the whole draft" : ""}
        </p>
        <FindingMeta f={f} />
        <SpanNote f={f} text={text} />
        {f.explanation && (
          <p className="t-body panel__note">
            <b>The problem:</b> {f.explanation}
          </p>
        )}
        {f.evidence.map((e) => (
          <Evidence key={e.id} e={e} showRelation={false} />
        ))}
        <Suggestion f={f} />
        <p className="t-caption">This is a brand rule, not a fact check. {personal ? "You decide on it." : "A person decides on it."}</p>
      </div>
    );
  }
  // The note above already says no document covers an unverified claim.
  const reasons = (f.review_reasons ?? []).filter((r) => !(r === "not_enough_evidence" && f.verification_status === "unverified"));
  return (
    <div className="finding-detail" aria-live="polite">
      <FindingMeta f={f} />
      <SpanNote f={f} text={text} />
      {/* An unverified claim has no proof either way, so no quote is shown as if it were one. */}
      {f.evidence.length > 0 && f.verification_status !== "unverified" ? (
        f.evidence.map((e) => <Evidence key={e.id} e={e} showRelation />)
      ) : (
        <p className="app-alert" role="note">
          None of your approved documents cover this. That means it isn’t proven yet, not that it’s wrong.
        </p>
      )}
      {f.explanation && (
        <p className="t-body panel__note">
          <b>{f.verification_status === "supported" ? "Why it matches:" : "The problem:"}</b> {f.explanation}
        </p>
      )}
      <Suggestion f={f} />
      {f.requires_human_review && <p className="t-caption">{personal ? "You need to decide on this one." : "A person needs to decide on this one."}</p>}
      {reasons.length > 0 && (
        <ul className="add-reasons" aria-label="Why a person needs to decide">
          {reasons.map((r) => (
            <li key={r}>{reviewReasonText(r)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The suggestion for a finding with its label (never applied for you). */
function Suggestion({ f }: { f: FindingOut }) {
  const sg = suggestionFor(f);
  if (!sg && f.withheld_by_intent_lock)
    return (
      <p className="t-body panel__note">
        <span aria-hidden="true">🔒</span> A suggestion was hidden because it would remove a protected phrase. Check again (in “Fix the wording”)
        to get one that keeps it.
      </p>
    );
  if (!sg) return null;
  return (
    <p className="t-body panel__note">
      <b>{sg.label}:</b> “{sg.text}”
    </p>
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
  current,
  onSelect,
}: {
  text: string;
  findings: FindingOut[];
  current?: string;
  onSelect: (id: string) => void;
}) {
  const parts = useMemo(() => segment(text, findings.map((f) => ({ span: f.span, item: f }))), [text, findings]);
  return (
    <p className="heat">
      {parts.map((p, i) => {
        if (!p.marks.length) return <span key={i}>{p.text}</span>;
        // Several findings over one run: show the most serious verdict, select the first.
        // The placeholder finding spans the whole draft, so any real finding on the same words wins.
        const rank = (f: FindingOut) => (isStub(f) ? 9 : (ORDER[f.verification_status] ?? 2));
        const top = [...p.marks].sort((a, b) => rank(a) - rank(b))[0];
        const tone = isStub(top) ? "placeholder" : isRule(top) || isTone(top) ? "rule" : ({ supported: "ok", contradicted: "bad" }[top.verification_status as string] ?? "warn");
        const on = p.marks.some((m) => m.finding_id === current);
        const dismissed = !isStub(top) && isDismissed(top);
        // <mark> (not <button>) so the highlight wraps inline with the sentence; still a keyboard stop.
        return (
          <Fragment key={i}>
            <mark
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
              aria-label={`${p.text}: ${isStub(top) ? "placeholder" : findingChip(top).label}${dismissed ? ", dismissed by you" : ""}`}
            >
              {p.text}
            </mark>
            {dismissed && (
              <span className="add-heat-dismissed" aria-hidden="true">
                {DISMISSED.glyph} {DISMISSED.label}
              </span>
            )}
          </Fragment>
        );
      })}
    </p>
  );
}

const clip = (s: string, n = 90) => ([...s].length > n ? `${[...s].slice(0, n).join("")}…` : s);
