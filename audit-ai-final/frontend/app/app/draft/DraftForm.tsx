"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/primitives/Button";
import { Dropzone, Option, Panel, Panels } from "@/components/app/Stage";
import { canSubmit, roleName } from "@/components/app/roles";
import { ACCEPTED_FILE_TYPES, ApiError, MAX_UPLOAD_BYTES, api } from "@/lib/api/client";
import { useActiveBrand } from "@/lib/brand";
import { useSession } from "@/lib/session";
import { rememberReviewText } from "@/lib/workspace";

const MAX = 100_000; // backend limit, in characters (code points)

// Optional label only: the review request has no field for it (brand_id, title, text), so it is
// never sent. Kept so the writer can note it; wire it up once the backend accepts a content type.
const PLACES = ["Website", "Social media", "Email", "Product page", "Other"];

/** New review: pasted text -> POST /api/reviews, or a file -> POST /api/reviews/upload. */
export function DraftForm() {
  const router = useRouter();
  const role = useSession()?.role ?? "";
  const allowed = canSubmit(role);
  const active = useActiveBrand();
  const brand = active.state === "ready" ? active.brand : null;

  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // One key per draft: a double click or a retry after a dropped connection replays the same
  // review instead of running (and paying for) a second one. Reset when the draft changes.
  const idemKey = useRef<string>("");

  useEffect(() => {
    idemKey.current = "";
  }, [text, title, file, brand?.id]);

  const length = [...text].length;

  const pick = (f: File) => {
    if (f.size > MAX_UPLOAD_BYTES) return setError(`That file is ${(f.size / 1024 / 1024).toFixed(1)} MB. The limit is 10 MB.`);
    if (!/\.(pdf|docx|txt)$/i.test(f.name)) return setError("Only PDF, Word (.docx) or text (.txt) files can be read.");
    setError(null);
    setFile(f);
  };

  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (busy) return;
    if (!brand) return setError("Your brand hasn’t loaded yet. Please wait a moment or reload the page.");
    if (!file && !text.trim()) return setError("Paste the text you want checked, or upload a file.");
    if (!file && length > MAX) return setError(`The text is too long (${length.toLocaleString()} of ${MAX.toLocaleString()} characters).`);
    idemKey.current ||= crypto.randomUUID();
    setBusy(true);
    setError(null);
    try {
      const t = title.trim() || undefined;
      const review = file
        ? await api.createReviewFromFile(brand.id, file, idemKey.current, t)
        : await api.createReview({ brand_id: brand.id, text, ...(t ? { title: t } : {}) }, idemKey.current);
      // Fallback for backends that don't return ReviewOut.text yet.
      if (!review.text && !file) rememberReviewText(review.id, text);
      router.push(`/app/review?id=${review.id}`);
    } catch (err) {
      setBusy(false);
      if (err instanceof ApiError && err.status === 422 && file) {
        setError(
          `We couldn’t read that file${/limit|exceeds/i.test(err.message) ? ` (${err.message})` : ""}. Use a PDF with selectable text, a Word (.docx) or a text (.txt) file, or paste the text instead.`,
        );
      } else if (err instanceof ApiError && err.status === 404) {
        setError("Your brand wasn’t found. Reload the page and try again.");
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
              placeholder={file ? "A file is chosen below. Remove it to paste text instead." : "Paste or type your text here"}
              disabled={!!file}
            />
          </label>
          {!file && (
            <p className={`draft__count t-caption${length > MAX ? " is-over" : ""}`}>
              {length.toLocaleString()} / {MAX.toLocaleString()} characters
            </p>
          )}
          <Dropzone
            small
            title="Upload a file instead"
            hint="PDF, Word (.docx) or text · up to 10 MB"
            accept={ACCEPTED_FILE_TYPES}
            onFile={pick}
            fileName={file ? file.name : null}
            disabled={busy}
          />
          {file && (
            <button type="button" className="draft__remove" onClick={() => setFile(null)}>
              Remove the file and paste text instead
            </button>
          )}
        </Panel>

        <Panel n="02" label="Details" title="Name it">
          <label className="field">
            <span className="field__label">Title (optional)</span>
            <input className="field__input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Earbuds launch page" />
          </label>
          <div className="brand-pill">
            <span className="t-caption">Checked against</span>
            <span className="brand-pill__id">
              {active.state === "loading"
                ? "Loading…"
                : brand
                  ? `${brand.name} · ${brand.approved_source_count} approved document${brand.approved_source_count === 1 ? "" : "s"}`
                  : "No brand"}
            </span>
            <Link className="link link--tap" href="/app/sources">
              Manage documents
            </Link>
          </div>
          {brand && brand.approved_source_count === 0 && (
            <p className="app-alert" role="status">
              {brand.name} has no approved documents yet, so a check would come back as “couldn’t check”.{" "}
              <Link className="link" href="/app/sources">
                Upload one first
              </Link>
            </p>
          )}
          {active.state === "error" && (
            <p className="app-alert app-alert--bad" role="alert">
              {active.message}
            </p>
          )}
          <p className="t-body panel__note">Your text is checked against the approved documents saved for this brand.</p>
          <fieldset className="options" style={{ border: 0, margin: 0, padding: 0 }}>
            <legend className="field__label" style={{ marginBottom: 10 }}>
              Where will this be posted? (optional)
            </legend>
            {PLACES.map((p) => (
              <Option key={p} type="radio" name="place" label={p} />
            ))}
            <p className="t-caption panel__hint">For your own reference: this isn’t used by the check yet.</p>
          </fieldset>
        </Panel>

        <Panel n="03" label="Check it" title="Run the check">
          <p className="t-body panel__note">
            This can take up to a minute. Each problem we find shows the reason and the document it came from. Nothing is
            changed for you.
          </p>
          {!allowed && (
            <p className="app-alert" role="note">
              Your role ({roleName(role)}) can’t send drafts for checking. A submitter or admin needs to do this. You can still
              review and decide on drafts others send.
            </p>
          )}
          {error && (
            <p className="app-alert app-alert--bad" role="alert">
              {error}
            </p>
          )}
          <Button type="submit" disabled={busy || !allowed || !brand} aria-busy={busy}>
            {busy ? "Checking…" : "Check my draft →"}
          </Button>
        </Panel>
      </Panels>
    </form>
  );
}
