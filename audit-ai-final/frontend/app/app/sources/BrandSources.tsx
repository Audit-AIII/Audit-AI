"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/primitives/Button";
import { Panel, Panels } from "@/components/app/Stage";
import { ApiError, api } from "@/lib/api/client";
import type { BrandSourceOut } from "@/lib/api/types";
import { getBrandId, setBrandId } from "@/lib/workspace";

const STATUS: Record<string, string> = { approved: "Approved", draft: "Draft", superseded: "Replaced", archived: "Withdrawn" };
const TYPE: Record<string, string> = { txt: "Text file", pdf: "PDF", docx: "Word file" };

type Load = { state: "idle" } | { state: "loading" } | { state: "ok"; sources: BrandSourceOut[] } | { state: "error"; message: string };

/** Loads a brand's sources; resolves to the next screen state (never throws). */
async function fetchSources(id: string): Promise<Load> {
  try {
    return { state: "ok", sources: await api.brandSources(id) };
  } catch (err) {
    const message =
      err instanceof ApiError && (err.status === 404 || err.status === 422)
        ? "No brand with that ID in your organisation. Check the ID and try again."
        : err instanceof ApiError
          ? err.userMessage
          : "Something went wrong. Please try again.";
    return { state: "error", message };
  }
}

/** Sources stage: pick the brand (no "list my brands" route yet) and show GET /api/brands/{id}/sources. */
export function BrandSources() {
  // Client-only render (AppShell waits for the session), so localStorage is safe to read here.
  const [draftId, setDraftId] = useState(getBrandId);
  const [brandId, setActive] = useState(getBrandId);
  const [load, setLoad] = useState<Load>(() => (getBrandId() ? { state: "loading" } : { state: "idle" }));

  useEffect(() => {
    const saved = getBrandId();
    if (!saved) return;
    let live = true;
    fetchSources(saved).then((next) => live && setLoad(next));
    return () => {
      live = false;
    };
  }, []);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const id = draftId.trim();
    setBrandId(id);
    setActive(id);
    if (id) {
      setLoad({ state: "loading" });
      void fetchSources(id).then(setLoad);
    }
    else setLoad({ state: "idle" });
  };

  const approved = load.state === "ok" ? load.sources.filter((s) => s.status === "approved").length : 0;

  return (
    <Panels>
      <Panel n="01" label="Your brand" title="Choose your brand">
        <p className="t-body panel__note">Paste your brand ID once. Every draft you check is compared with this brand’s approved documents.</p>
        <form className="brand-form" onSubmit={onSubmit}>
          <label className="field">
            <span className="field__label">Brand ID</span>
            <input
              className="field__input"
              value={draftId}
              onChange={(e) => setDraftId(e.target.value)}
              placeholder="e.g. 3f2a…"
              spellCheck={false}
              autoComplete="off"
            />
          </label>
          <Button type="submit">{brandId && draftId.trim() === brandId ? "Reload documents" : "Use this brand"}</Button>
        </form>
        <p className="t-caption panel__hint">Demo: the backend’s seed script prints this as BRAND_ID.</p>
      </Panel>

      <Panel n="02" label="Your documents" title="Saved documents">
        {load.state === "idle" && <p className="t-body panel__note">Choose a brand to see its documents.</p>}
        {load.state === "loading" && (
          <p className="t-body panel__note" role="status">
            Loading documents…
          </p>
        )}
        {load.state === "error" && (
          <p className="app-alert app-alert--bad" role="alert">
            {load.message}
          </p>
        )}
        {load.state === "ok" && load.sources.length === 0 && (
          <p className="app-alert" role="status">
            This brand has no documents yet. Drafts can’t be checked until at least one is approved.
          </p>
        )}
        {load.state === "ok" && load.sources.length > 0 && (
          <ul className="rows">
            {load.sources.map((d) => (
              <li key={d.id} className="rows__item">
                <div>
                  <p className="rows__title">{d.title}</p>
                  <p className="rows__meta">
                    {[d.latest_version ? `Version ${d.latest_version}` : null, d.source_type ? (TYPE[d.source_type] ?? d.source_type) : null, STATUS[d.status] ?? d.status]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                </div>
                <span className={`tag${d.sensitivity === "confidential" ? " tag--private" : ""}`}>
                  {d.sensitivity === "confidential" ? "Private" : "Team only"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel n="03" label="Ready?" title="Before you check">
        <dl className="spec">
          <div className="spec__row">
            <dt>Approved documents</dt>
            <dd>{load.state === "ok" ? approved : "–"}</dd>
          </div>
          <div className="spec__row">
            <dt>Used for checks</dt>
            <dd>Only approved ones. Drafts and withdrawn documents are ignored.</dd>
          </div>
        </dl>
        {load.state === "ok" && approved === 0 && (
          <p className="app-alert" role="status">
            No approved documents yet, so a check would come back as “couldn’t check”.
          </p>
        )}
        <Button href="/app/draft">Next: check a draft →</Button>
      </Panel>
    </Panels>
  );
}
