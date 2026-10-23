"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/primitives/Button";
import { Dropzone, Panel, Panels } from "@/components/app/Stage";
import { canManageSources, roleName } from "@/components/app/roles";
import { ACCEPTED_FILE_TYPES, ApiError, MAX_UPLOAD_BYTES, api } from "@/lib/api/client";
import type { BrandSourceOut } from "@/lib/api/types";
import { useActiveBrand } from "@/lib/brand";
import { useSession } from "@/lib/session";

const STATUS: Record<string, string> = { approved: "Approved", draft: "Waiting for approval", superseded: "Replaced", archived: "Withdrawn" };
const TYPE: Record<string, string> = { txt: "Text file", pdf: "PDF", docx: "Word file" };

type Sources = { state: "loading" } | { state: "ok"; sources: BrandSourceOut[] } | { state: "error"; message: string };

const message = (err: unknown, fallback = "Something went wrong. Please try again.") => (err instanceof ApiError ? err.userMessage : fallback);

/** Loads a brand's documents; resolves to the next screen state (never throws). */
async function fetchSources(brandId: string): Promise<Sources> {
  try {
    return { state: "ok", sources: await api.brandSources(brandId) };
  } catch (err) {
    return { state: "error", message: message(err) };
  }
}

const baseName = (name: string) => name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();

/** Turns a 422 from an upload into a plain sentence (the backend message names the problem). */
export function unreadableFile(err: ApiError) {
  const why = /limit|exceeds/i.test(err.message) ? ` (${err.message})` : "";
  return `We couldn’t read that file${why}. Use a PDF with selectable text, a Word (.docx) or a text (.txt) file.`;
}

/** Sources stage: upload the brand's documents and see which are approved for checks. */
export function BrandSources() {
  const role = useSession()?.role ?? "";
  const manager = canManageSources(role);
  const active = useActiveBrand();
  const brandId = active.state === "ready" ? active.brand.id : null;

  const [sources, setSources] = useState<Sources>({ state: "loading" });
  const [tick, setTick] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [confidential, setConfidential] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [approving, setApproving] = useState<string | null>(null);

  useEffect(() => {
    if (!brandId) return;
    let live = true;
    fetchSources(brandId).then((next) => live && setSources(next));
    return () => {
      live = false;
    };
  }, [brandId, tick]);

  const reloadAll = () => {
    setTick((t) => t + 1);
    active.refresh();
  };

  const pick = (f: File) => {
    setNotice(null);
    if (f.size > MAX_UPLOAD_BYTES) {
      setFile(null);
      return setError(`That file is ${(f.size / 1024 / 1024).toFixed(1)} MB. The limit is 10 MB.`);
    }
    if (!/\.(pdf|docx|txt)$/i.test(f.name)) {
      setFile(null);
      return setError("Only PDF, Word (.docx) or text (.txt) files can be read.");
    }
    setError(null);
    setFile(f);
    setTitle(baseName(f.name));
  };

  const onUpload = async (e: FormEvent) => {
    e.preventDefault();
    if (!brandId || !file || busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      let source = await api.uploadBrandSource(brandId, file, { title: title.trim() || baseName(file.name), approve: manager, confidential });
      // A backend that ignores `approve` saves a draft: approve it explicitly so it is usable.
      if (manager && source.status === "draft") source = await api.approveBrandSource(brandId, source.id);
      setNotice(
        source.status === "approved"
          ? `“${source.title}” is saved and approved. New drafts are checked against it.`
          : `“${source.title}” is saved. It is used for checks once a manager approves it.`,
      );
      setFile(null);
      setTitle("");
      setConfidential(false);
      reloadAll();
    } catch (err) {
      setError(err instanceof ApiError && err.status === 422 ? unreadableFile(err) : message(err));
    } finally {
      setBusy(false);
    }
  };

  const approve = async (sourceId: string) => {
    if (!brandId) return;
    setApproving(sourceId);
    setError(null);
    try {
      await api.approveBrandSource(brandId, sourceId);
      reloadAll();
    } catch (err) {
      setError(message(err));
    } finally {
      setApproving(null);
    }
  };

  if (active.state === "loading")
    return (
      <p className="t-body" role="status">
        Loading your brand…
      </p>
    );
  if (active.state === "error")
    return (
      <div className="app-empty card">
        <p className="app-alert app-alert--bad" role="alert">
          {active.message}
        </p>
        <Button type="button" onClick={active.refresh}>
          Try again
        </Button>
      </div>
    );
  if (active.state === "none")
    return (
      <div className="app-empty card">
        <p className="t-body">Your organisation has no brand yet. Ask your admin to set one up.</p>
      </div>
    );

  const list = sources.state === "ok" ? sources.sources : [];
  const approved = list.filter((s) => s.status === "approved").length;

  return (
    <Panels>
      <Panel n="01" label="Add a document" title="Upload your brand document">
        <p className="t-body panel__note">
          Upload one document that describes your brand or product: facts, prices, features, the words you use. Every draft is
          checked against it.
        </p>
        {active.brands.length > 1 && (
          <label className="field">
            <span className="field__label">Brand</span>
            <select className="field__input" value={active.brand.id} onChange={(e) => active.choose(e.target.value)}>
              {active.brands.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </label>
        )}
        {manager ? (
          <form className="upload-form" onSubmit={onUpload}>
            <Dropzone
              title="Drag your document here"
              hint="PDF, Word (.docx) or text file · up to 10 MB"
              accept={ACCEPTED_FILE_TYPES}
              onFile={pick}
              fileName={file ? `${file.name} · ${Math.max(1, Math.round(file.size / 1024))} KB` : null}
              disabled={busy}
            />
            {file && (
              <label className="field">
                <span className="field__label">Document name</span>
                <input className="field__input" value={title} maxLength={300} onChange={(e) => setTitle(e.target.value)} />
              </label>
            )}
            <label className="option">
              <input type="checkbox" className="tick tick--checkbox" checked={confidential} onChange={(e) => setConfidential(e.target.checked)} />
              <span className="option__text">
                <span className="option__label">Keep this document private</span>
                <span className="option__help">Marked confidential: checked only with a local AI, never sent to an outside service.</span>
              </span>
            </label>
            {error && (
              <p className="app-alert app-alert--bad" role="alert">
                {error}
              </p>
            )}
            {notice && (
              <p className="app-alert app-alert--ok" role="status">
                {notice}
              </p>
            )}
            <Button type="submit" disabled={!file || busy} aria-busy={busy}>
              {busy ? "Uploading…" : "Upload"}
            </Button>
          </form>
        ) : (
          <p className="app-alert" role="note">
            Your role ({roleName(role)}) can’t upload documents. An admin or source manager adds them.
          </p>
        )}
      </Panel>

      <Panel n="02" label="Your documents" title={active.brand.name}>
        {sources.state === "loading" && (
          <p className="t-body panel__note" role="status">
            Loading documents…
          </p>
        )}
        {sources.state === "error" && (
          <p className="app-alert app-alert--bad" role="alert">
            {sources.message}
          </p>
        )}
        {sources.state === "ok" && list.length === 0 && <p className="t-body panel__note">No documents yet. Upload one to start checking drafts.</p>}
        {list.length > 0 && (
          <ul className="rows">
            {list.map((d) => (
              <li key={d.id} className="rows__item">
                <div>
                  <p className="rows__title">{d.title}</p>
                  <p className="rows__meta">
                    {[d.source_type ? (TYPE[d.source_type] ?? d.source_type) : null, d.latest_version ? `Version ${d.latest_version}` : null]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                  <p className="rows__meta">
                    <span className={`chip chip--${d.status === "approved" ? "supported" : d.status === "draft" ? "unverified" : "neutral"}`}>
                      {d.status === "approved" ? "✓" : d.status === "draft" ? "…" : "–"} {STATUS[d.status] ?? d.status}
                    </span>
                  </p>
                </div>
                <div className="rows__side">
                  <span className={`tag${d.sensitivity === "confidential" ? " tag--private" : ""}`}>
                    {d.sensitivity === "confidential" ? "Private" : "Team only"}
                  </span>
                  {manager && d.status === "draft" && (
                    <button type="button" className="decision decision--small" onClick={() => approve(d.id)} disabled={approving === d.id}>
                      {approving === d.id ? "Approving…" : "Approve"}
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel n="03" label="Ready?" title="Before you check">
        <dl className="spec">
          <div className="spec__row">
            <dt>Approved documents</dt>
            <dd className="approved-count">{sources.state === "ok" ? approved : "–"}</dd>
          </div>
          <div className="spec__row">
            <dt>Used for checks</dt>
            <dd>Only approved ones. Drafts and withdrawn documents are ignored.</dd>
          </div>
        </dl>
        {sources.state === "ok" && approved === 0 && (
          <p className="app-alert" role="status">
            No approved documents yet. Upload one first, or a check will come back as “couldn’t check”.
          </p>
        )}
        <Button href="/app/draft">Next: check a draft →</Button>
      </Panel>
    </Panels>
  );
}
