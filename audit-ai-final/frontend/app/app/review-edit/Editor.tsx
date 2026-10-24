"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { FindingBadge, SeverityBadge, verdictOf } from "@/components/additions/Badges";
import { EmptyState, ErrorState, LoadingState, NeedsBackend } from "@/components/additions/States";
import { findingChip, isRule, isStub, isStubReview, isWholeDraft, suggestionFor } from "@/components/app/reviewLabels";
import { Panel, Panels, StageHead } from "@/components/app/Stage";
import { Thinking } from "@/components/app/Thinking";
import { Button } from "@/components/primitives/Button";
import { history, itemIdOf, rerun, saveNewVersion, type NewVersionOut } from "@/lib/additions/content";
import { wordDiff, changed } from "@/lib/additions/diff";
import { errorText } from "@/lib/additions/http";
import { brokenBy, missingIn } from "@/lib/additions/locks";
import { textOf, useReviewData, useReviewParam } from "@/lib/additions/review";
import { api, backendMessage } from "@/lib/api/client";
import type { FindingOut, ReviewOut } from "@/lib/api/types";
import { segment } from "@/lib/text/codepoints";

/** Must-keep phrases of the version being edited, as the server has them. "error": they couldn't be
 * read, so none are shown (never a local-only guess). */
type Locks = { state: "loading" } | { state: "ok"; phrases: string[] } | { state: "error"; message: string };
const WITHHELD = "A suggestion was hidden because it would remove a protected phrase. Check again to get one that keeps it.";

const ORDER: Record<string, number> = { contradicted: 0, conflicting_sources: 1, unverified: 2, not_applicable: 3, supported: 4 };

export function Editor() {
  const id = useReviewParam();
  const { value, reload } = useReviewData(id);
  if (value.state === "none")
    return (
      <>
        <StageHead title="Correct" />
        <EmptyState title="No review chosen">
          Open a review first, then come here with <code className="add-mono">?id=</code> or from its page.
        </EmptyState>
      </>
    );
  if (value.state === "loading")
    return (
      <>
        <StageHead title="Correct" />
        <LoadingState label="Loading the review…" />
      </>
    );
  if (value.state === "error")
    return (
      <>
        <StageHead title="Correct" />
        <ErrorState error={value.error} onRetry={reload} />
      </>
    );
  return <EditorView key={value.review.id} review={value.review} />;
}

function EditorView({ review }: { review: ReviewOut }) {
  const router = useRouter();
  const original = textOf(review);
  const stub = isStubReview(review);
  const itemId = itemIdOf(review);
  const findings = useMemo(
    () => review.findings.filter((f) => !isStub(f)).sort((a, b) => (ORDER[a.verification_status] ?? 2) - (ORDER[b.verification_status] ?? 2)),
    [review.findings],
  );

  const [draft, setDraft] = useState(original ?? "");
  const [current, setCurrent] = useState<string | null>(findings[0]?.finding_id ?? null);
  const [lockState, setLockState] = useState<Locks>(() =>
    Array.isArray(review.locked_phrases) ? { state: "ok", phrases: review.locked_phrases } : { state: "loading" },
  );
  const [lockBusy, setLockBusy] = useState(false);
  const [lockError, setLockError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<NewVersionOut | null>(null);
  const [rechecking, setRechecking] = useState(false);
  const [newer, setNewer] = useState<number | null>(null);
  const area = useRef<HTMLTextAreaElement>(null);

  // After "Save as new version" the editor works on that version: its locks (inherited) come from the response.
  const versionId = saved?.content_version_id ?? review.content_version_id;
  const locks = lockState.state === "ok" ? lockState.phrases : [];

  // Older backends don't put locked_phrases on the review: read them from the locks route instead.
  const needsFetch = lockState.state === "loading";
  useEffect(() => {
    if (!needsFetch) return;
    let live = true;
    api
      .getLocks(versionId)
      .then((r) => live && setLockState({ state: "ok", phrases: r.locked_phrases }))
      .catch((err) => live && setLockState({ state: "error", message: backendMessage(err) }));
    return () => {
      live = false;
    };
  }, [needsFetch, versionId]);

  /** PUT the full new list; the screen shows only what the server saved. On error the old list stays. */
  const writeLocks = async (next: string[], done: string) => {
    if (lockBusy) return false;
    setLockBusy(true);
    setLockError(null);
    try {
      const r = await api.putLocks(versionId, next);
      setLockState({ state: "ok", phrases: r.locked_phrases });
      setNotice({ ok: true, text: done });
      return true;
    } catch (err) {
      setLockError(backendMessage(err));
      return false;
    } finally {
      setLockBusy(false);
    }
  };

  // Is there a version newer than the one this review checked? Then its approval doesn't apply here.
  useEffect(() => {
    if (!itemId) return;
    let live = true;
    history(itemId)
      .then((h) => {
        const cur = h.versions.find((v) => v.is_current);
        if (live && cur && review.version_number != null && cur.version_number > review.version_number) setNewer(cur.version_number);
      })
      .catch(() => {
        /* history is only for the notice; the editor works without it */
      });
    return () => {
      live = false;
    };
  }, [itemId, review.version_number]);

  const selected = findings.find((f) => f.finding_id === current) ?? null;
  const diff = useMemo(() => (original === null ? [] : wordDiff(original, draft)), [original, draft]);
  const lost = missingIn(original ?? "", draft, locks);

  const markSelection = () => {
    const el = area.current;
    if (!el) return;
    const phrase = el.value.slice(el.selectionStart, el.selectionEnd).trim();
    if (!phrase) return setNotice({ ok: false, text: "Select the words to keep in the text box first (a price, a date, a product name)." });
    if (locks.includes(phrase)) return;
    void writeLocks([...locks, phrase], `“${phrase}” is marked must-keep and saved to your account.`);
  };
  const unlock = (phrase: string) => void writeLocks(locks.filter((x) => x !== phrase), `“${phrase}” is no longer protected.`);

  const apply = (f: FindingOut) => {
    const sg = suggestionFor(f);
    if (!sg) return;
    const broken = brokenBy(f.original_text, sg.text, locks);
    if (broken.length) return setNotice({ ok: false, text: `Not applied: it would change must-keep text (${broken.map((b) => `“${b}”`).join(", ")}). Edit by hand if you really mean to.` });
    if (!draft.includes(f.original_text)) return setNotice({ ok: false, text: "That sentence has already changed in your draft, so the suggestion can’t be placed. Edit it by hand." });
    setDraft(draft.replace(f.original_text, sg.text));
    setNotice({ ok: true, text: "Suggestion placed in your draft. Nothing is saved until you save a new version." });
  };

  const save = async () => {
    if (!itemId || saving) return;
    if (lost.length && !window.confirm(`Your draft no longer contains must-keep text: ${lost.join(", ")}. Save anyway?`)) return;
    setSaving(true);
    setNotice(null);
    try {
      const r = await saveNewVersion(itemId, draft);
      setSaved(r);
      // The new version inherits the locks on the server: show what its review says it has.
      setLockState(Array.isArray(r.review.locked_phrases) ? { state: "ok", phrases: r.review.locked_phrases } : { state: "loading" });
      setNotice({ ok: true, text: `Saved as version ${r.version_number} and checked again. The earlier version’s review or approval does not apply to it.` });
    } catch (err) {
      setNotice({ ok: false, text: errorText(err) });
    } finally {
      setSaving(false);
    }
  };

  const recheck = async () => {
    const target = saved?.review.id ?? review.id;
    setRechecking(true);
    setNotice(null);
    try {
      const r = await rerun(target, crypto.randomUUID());
      setNotice({ ok: true, text: `Checked again: ${r.status.replace(/_/g, " ")}.` });
      if (saved) setSaved({ ...saved, review: r });
      else router.push(`/app/review-edit?id=${r.id}`);
    } catch (err) {
      setNotice({ ok: false, text: errorText(err) });
    } finally {
      setRechecking(false);
    }
  };

  if (original === null)
    return (
      <>
        <StageHead title="Correct" status={review.title ?? undefined} />
        <EmptyState title="The draft text isn’t available">
          This server didn’t send the review’s text, and this browser has no copy. <NeedsBackend>ReviewOut.text</NeedsBackend>
        </EmptyState>
      </>
    );

  return (
    <>
      <StageHead title="Correct" status={[review.title, review.version_number != null ? `Version ${review.version_number}` : null].filter(Boolean).join(" · ") || undefined} />

      {newer !== null && (
        <div className="app-alert" role="status">
          <b>A newer version exists (version {newer}).</b> This page edits version {review.version_number}; any review or approval of it does
          not apply to version {newer}.
        </div>
      )}
      {stub && (
        <div className="app-alert app-alert--placeholder" role="note">
          <b>Placeholder review.</b> No AI service checked this text, so there are no real findings or suggestions. You can still edit and save a
          new version.
        </div>
      )}
      {review.status === "failed" && (
        <div className="app-alert app-alert--bad" role="alert">
          <b>The check didn’t run.</b> {review.error_summary ?? "No reason given."} This is not an approval. Use “Check again”.
        </div>
      )}
      {(saving || rechecking) && (
        <Thinking
          label={saving ? "Saving your new version and checking it" : "Checking the draft again"}
          detail="Each claim is looked up in your approved documents. Nothing is changed for you."
        />
      )}
      {notice && (
        <p className={`app-alert ${notice.ok ? "app-alert--ok" : "app-alert--bad"}`} role={notice.ok ? "status" : "alert"}>
          {notice.text}
        </p>
      )}

      <Panels cols="2">
        <Panel n="01" label="Your draft" title="Edit the text">
          <div className="add-editor">
            <p className="t-caption add-muted">Flagged in the checked version (click to see why)</p>
            <MarkedText text={original} findings={findings.filter((f) => !isWholeDraft(f))} locks={locks} current={current} onPick={setCurrent} />
            <label className="add-field-row">
              <span className="field__label">Your new version</span>
              <textarea ref={area} className="add-editor__text" value={draft} onChange={(e) => setDraft(e.target.value)} disabled={saving} />
            </label>
            <div className="add-row">
              <button type="button" className="add-btn-small" onClick={markSelection} disabled={lockBusy || lockState.state !== "ok"} aria-busy={lockBusy}>
                {lockBusy ? "Saving…" : "🔒 Mark must-keep text"}
              </button>
              <span className="add-note add-muted">Select words in the box above first.</span>
              <span className="add-note add-muted">Saved to your account. Suggested wording that would remove a protected phrase is never offered.</span>
            </div>
            {lockState.state === "loading" && <LoadingState label="Loading must-keep text…" />}
            {lockState.state === "error" && (
              <p className="app-alert app-alert--bad" role="alert">
                Couldn’t load the must-keep text: {lockState.message}
              </p>
            )}
            {lockError && (
              <p className="app-alert app-alert--bad" role="alert">
                Not saved: {lockError}
              </p>
            )}
            {locks.length > 0 && (
              <ul className="add-locks" aria-label="Must-keep text">
                {locks.map((l) => (
                  <li key={l} className="add-lock">
                    <span aria-hidden="true">🔒</span> {l}
                    {lost.includes(l) && <b> (missing)</b>}
                    <button type="button" aria-label={`Unlock ${l}`} onClick={() => unlock(l)} disabled={lockBusy}>
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {changed(diff) && (
              <>
                <p className="t-caption add-muted">Changes from version {review.version_number ?? "checked"}</p>
                <p className="add-diff" aria-label="Changes">
                  {diff.map((p, i) => (p.kind === "same" ? <span key={i}>{p.text}</span> : p.kind === "del" ? <del key={i}>{p.text}</del> : <ins key={i}>{p.text}</ins>))}
                </p>
              </>
            )}
          </div>
        </Panel>

        <Panel n="02" label="Findings" title={findings.length ? `${findings.length} to look at` : "No findings"}>
          {findings.length === 0 && (
            <EmptyState title={stub ? "Nothing was checked" : "No findings"}>{stub ? "A placeholder review has no findings." : "Every claim matched your documents."}</EmptyState>
          )}
          <ul className="rows" aria-label="Findings">
            {findings.map((f) => (
              <li key={f.finding_id}>
                <button type="button" className={`add-finding${f.finding_id === current ? " is-current" : ""}`} aria-pressed={f.finding_id === current} onClick={() => setCurrent(f.finding_id)}>
                  <span className="add-row">
                    <FindingBadge f={f} />
                    <SeverityBadge severity={f.severity} />
                  </span>
                  <span className="add-finding__text">{isWholeDraft(f) ? "About the whole draft" : `“${f.original_text}”`}</span>
                </button>
              </li>
            ))}
          </ul>
          {selected && (
            <FindingDetail f={selected} locks={locks} canApply onApply={() => apply(selected)} onRecheck={recheck} rechecking={rechecking} />
          )}
        </Panel>
      </Panels>

      <div className="add-footer">
        {!itemId ? (
          <NeedsBackend>
            this server doesn’t return <code className="add-mono">content_item_id</code> on reviews, so a new version can’t be saved from here.
          </NeedsBackend>
        ) : (
          <>
            <Button type="button" onClick={save} disabled={saving || !changed(diff) || !draft.trim()} aria-busy={saving}>
              {saving ? "Saving…" : "Save as new version"}
            </Button>
            {saved && (
              <a className="link" href={`/app/review?id=${saved.review.id}`}>
                Open version {saved.version_number}’s review →
              </a>
            )}
          </>
        )}
        <button type="button" className="add-btn-small" onClick={recheck} disabled={rechecking}>
          {rechecking ? "Checking…" : saved ? `↻ Check version ${saved.version_number} again` : "↻ Check again"}
        </button>
        <span className="add-note add-muted">Saving creates a new version; nothing is changed in the old one.</span>
      </div>
    </>
  );
}

function FindingDetail({
  f,
  locks,
  canApply,
  onApply,
  onRecheck,
  rechecking,
}: {
  f: FindingOut;
  locks: string[];
  canApply: boolean;
  onApply: () => void;
  onRecheck: () => void;
  rechecking: boolean;
}) {
  const sg = suggestionFor(f);
  const broken = sg ? brokenBy(f.original_text, sg.text, locks) : [];
  return (
    <div className="add-stack" aria-live="polite">
      {f.evidence.length ? (
        f.evidence.map((e) => (
          <div key={e.id} className="add-window">
            <p className="add-window__src">
              {e.relation === "supports" ? "Approved source agrees" : e.relation === "contradicts" ? "Approved source says otherwise" : "Related approved text"}
            </p>
            <p className="add-window__quote">“{e.quote}”</p>
          </div>
        ))
      ) : isRule(f) ? (
        <p className="add-note">§ A brand rule, not a fact check.</p>
      ) : (
        <p className="app-alert" role="note">
          ? No approved document covers this. It isn’t proven yet, which is not the same as wrong.
        </p>
      )}
      {f.explanation && (
        <p className="add-note">
          <b>Why:</b> {f.explanation}
        </p>
      )}
      {sg ? (
        <div className="add-suggest">
          <p className="t-caption add-muted">{sg.label} (not applied)</p>
          <p>“{sg.text}”</p>
          {broken.length > 0 && <p className="add-note">🔒 Blocked: would change {broken.map((b) => `“${b}”`).join(", ")}.</p>}
          <button type="button" className="add-btn-small" onClick={onApply} disabled={!canApply || broken.length > 0}>
            Apply suggestion to my draft
          </button>
        </div>
      ) : f.withheld_by_intent_lock ? (
        <div className="add-suggest">
          <p className="add-note">🔒 {WITHHELD}</p>
          <button type="button" className="add-btn-small" onClick={onRecheck} disabled={rechecking}>
            {rechecking ? "Checking…" : "↻ Check again"}
          </button>
        </div>
      ) : (
        <p className="add-note add-muted">No suggested wording for this one. {findingChip(f).label}.</p>
      )}
    </div>
  );
}

/** Checked text with finding spans (code points, converted) and must-keep phrases marked. */
function MarkedText({ text, findings, locks, current, onPick }: { text: string; findings: FindingOut[]; locks: string[]; current: string | null; onPick: (id: string) => void }) {
  const parts = useMemo(() => {
    const items: { span: { start: number; end: number }; item: { kind: "f"; f: FindingOut } | { kind: "lock" } }[] = findings.map((f) => ({ span: f.span, item: { kind: "f", f } }));
    for (const l of locks) {
      let from = 0;
      for (;;) {
        const at = text.indexOf(l, from);
        if (at < 0) break;
        const start = Array.from(text.slice(0, at)).length;
        items.push({ span: { start, end: start + Array.from(l).length }, item: { kind: "lock" } });
        from = at + l.length;
      }
    }
    return segment(text, items);
  }, [text, findings, locks]);
  return (
    <p className="add-marked">
      {parts.map((p, i) => {
        const f = p.marks.find((m) => m.kind === "f") as { kind: "f"; f: FindingOut } | undefined;
        const locked = p.marks.some((m) => m.kind === "lock");
        if (!f && !locked) return <span key={i}>{p.text}</span>;
        if (!f) return (
          <span key={i} className="add-mark add-mark--lock" title="Must-keep">
            {p.text}
          </span>
        );
        const tone = isRule(f.f) ? "rule" : verdictOf(f.f.verification_status).tone;
        return (
          <mark
            key={i}
            role="button"
            tabIndex={0}
            className={`add-mark add-mark--${locked ? "lock" : tone === "none" ? "ok" : tone}${f.f.finding_id === current ? " is-current" : ""}`}
            onClick={() => onPick(f.f.finding_id)}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onPick(f.f.finding_id))}
            aria-label={`${p.text}: ${findingChip(f.f).label}`}
          >
            {p.text}
          </mark>
        );
      })}
    </p>
  );
}
