"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/primitives/Button";
import { Panel, Panels } from "@/components/app/Stage";
import { ApiError, api } from "@/lib/api/client";
import { getBrandId, rememberReviewText } from "@/lib/workspace";

const MAX = 100_000; // backend limit, in characters (code points)

/** New review: sends the draft to POST /api/reviews and opens the result on the Review stage. */
export function DraftForm() {
  const router = useRouter();
  // Workspace stages render only on the client (AppShell waits for the session), so reading
  // localStorage in an initialiser is safe here.
  const [brandId] = useState(getBrandId);
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // One key per draft: a double click or a retry after a dropped connection replays the same
  // review instead of running (and paying for) a second one. Reset when the draft changes.
  const idemKey = useRef<string>("");

  useEffect(() => {
    idemKey.current = "";
  }, [text, title, brandId]);

  const length = [...text].length;

  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (busy) return;
    if (!brandId) return setError("Choose your brand on the Sources stage first.");
    if (!text.trim()) return setError("Paste the text you want checked.");
    if (length > MAX) return setError(`The text is too long (${length.toLocaleString()} of ${MAX.toLocaleString()} characters).`);
    idemKey.current ||= crypto.randomUUID();
    setBusy(true);
    setError(null);
    try {
      const review = await api.createReview({ brand_id: brandId, text, ...(title.trim() ? { title: title.trim() } : {}) }, idemKey.current);
      rememberReviewText(review.id, text);
      router.push(`/app/review?id=${review.id}`);
    } catch (err) {
      setBusy(false);
      if (err instanceof ApiError && err.status === 404) {
        setError("That brand wasn’t found in your organisation. Check the brand on the Sources stage.");
      } else {
        setError(err instanceof ApiError ? err.userMessage : "Something went wrong. Please try again.");
      }
    }
  };

  return (
    <form onSubmit={onSubmit}>
      <Panels>
        <Panel n="01" label="Your text" title="Paste your draft">
          <label className="field">
            <span className="field__label">Text to check</span>
            <textarea
              className="field__input draft__text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Paste or type your text here"
              required
            />
          </label>
          <p className={`draft__count t-caption${length > MAX ? " is-over" : ""}`}>
            {length.toLocaleString()} / {MAX.toLocaleString()} characters
          </p>
        </Panel>

        <Panel n="02" label="Details" title="Name it">
          <label className="field">
            <span className="field__label">Title (optional)</span>
            <input className="field__input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Earbuds launch page" />
          </label>
          <div className="brand-pill">
            <span className="t-caption">Checked against</span>
            {brandId ? (
              <span className="brand-pill__id">Brand {brandId.slice(0, 8)}…</span>
            ) : (
              <span className="brand-pill__id">No brand chosen</span>
            )}
            <Link className="link link--tap" href="/app/sources">
              {brandId ? "Change" : "Choose"}
            </Link>
          </div>
          <p className="t-body panel__note">Your text is checked against the approved documents saved for this brand.</p>
        </Panel>

        <Panel n="03" label="Check it" title="Run the check">
          <p className="t-body panel__note">
            This can take up to a minute. Each problem we find shows the reason and the document it came from. Nothing is
            changed for you.
          </p>
          {error && (
            <p className="app-alert app-alert--bad" role="alert">
              {error}
            </p>
          )}
          <Button type="submit" disabled={busy} aria-busy={busy}>
            {busy ? "Checking…" : "Check my draft →"}
          </Button>
        </Panel>
      </Panels>
    </form>
  );
}
