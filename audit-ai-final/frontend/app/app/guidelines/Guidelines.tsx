"use client";

import { useEffect, useState, type FormEvent } from "react";
import { BrandBar } from "@/components/additions/BrandBar";
import { SourceStatusBadge } from "@/components/additions/Badges";
import { ConfirmDialog } from "@/components/additions/ConfirmDialog";
import { EmptyState, ErrorState, LoadingState } from "@/components/additions/States";
import { UploadDropzone, checkFile } from "@/components/additions/UploadDropzone";
import { canManageSources, roleName } from "@/components/app/roles";
import { Panel, Panels, StageHead } from "@/components/app/Stage";
import { Button } from "@/components/primitives/Button";
import { useBrands } from "@/lib/additions/brands";
import { errorText } from "@/lib/additions/http";
import { approveSource, listSources, uploadSource, uploadSourceVersion, withdrawSource, type FlippedDependent } from "@/lib/additions/sources";
import { ApiError } from "@/lib/api/client";
import type { BrandSourceOut } from "@/lib/api/types";
import { useSession } from "@/lib/session";

const TYPE: Record<string, string> = { pdf: "PDF", docx: "Word file", txt: "Text file" };
const baseName = (n: string) => n.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();

type Docs = { state: "loading" } | { state: "ok"; docs: BrandSourceOut[] } | { state: "error"; error: unknown };

async function fetchDocs(brandId: string): Promise<Docs> {
  try {
    return { state: "ok", docs: await listSources(brandId) };
  } catch (error) {
    return { state: "error", error };
  }
}

/** A 422 from an upload, in plain words. The backend names the cause (type, size, no text). */
function uploadError(err: unknown) {
  if (err instanceof ApiError && err.status === 422) {
    const m = err.message.toLowerCase();
    if (m.includes("limit") || m.includes("exceeds")) return `That file is too big (${err.message}).`;
    if (m.includes("type") || m.includes("extension") || m.includes("unsupported")) return "That kind of file can’t be read. Use a PDF, a Word (.docx) or a text (.txt) file.";
    return "We couldn’t find any text in that file. Scanned or image-only PDFs can’t be read. Use a PDF with selectable text, a .docx or a .txt.";
  }
  return errorText(err);
}

export function Guidelines() {
  const role = useSession()?.role ?? "";
  const manager = canManageSources(role);
  const { value: brands, refresh: refreshBrands, choose } = useBrands();
  const brandId = brands.state === "ready" ? brands.brand.id : null;

  const [docs, setDocs] = useState<Docs>({ state: "loading" });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!brandId) return;
    let live = true;
    fetchDocs(brandId).then((d) => live && setDocs(d));
    return () => {
      live = false;
    };
  }, [brandId, tick]);
  const reload = () => {
    setTick((t) => t + 1);
    refreshBrands();
  };

  // Upload form
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [confidential, setConfidential] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // Row actions
  const [rowBusy, setRowBusy] = useState<string | null>(null);
  const [versionFor, setVersionFor] = useState<BrandSourceOut | null>(null);
  const [versionFile, setVersionFile] = useState<File | null>(null);
  const [withdrawFor, setWithdrawFor] = useState<BrandSourceOut | null>(null);
  const [withdrawReason, setWithdrawReason] = useState("");
  const [withdrawKind, setWithdrawKind] = useState<"archived" | "superseded">("archived");
  const [flipped, setFlipped] = useState<{ title: string; items: FlippedDependent[] } | null>(null);

  const pick = (f: File) => {
    const problem = checkFile(f);
    setMsg(problem ? { ok: false, text: problem } : null);
    setFile(problem ? null : f);
    if (!problem) setTitle(baseName(f.name));
  };

  const onUpload = async (e: FormEvent) => {
    e.preventDefault();
    if (!brandId || !file || busy) return;
    setBusy(true);
    setMsg(null);
    try {
      let s = await uploadSource(brandId, file, { title: title.trim() || baseName(file.name), confidential, approve: manager });
      if (manager && s.status === "draft") s = await approveSource(brandId, s.id); // backends that ignore `approve`
      setMsg({ ok: true, text: s.status === "approved" ? `“${s.title}” is uploaded and approved. New checks use it.` : `“${s.title}” is uploaded as a draft. It isn’t used for checks until approved.` });
      setFile(null);
      setTitle("");
      setConfidential(false);
      reload();
    } catch (err) {
      setMsg({ ok: false, text: uploadError(err) });
    } finally {
      setBusy(false);
    }
  };

  const approve = async (d: BrandSourceOut) => {
    if (!brandId) return;
    setRowBusy(d.id);
    setMsg(null);
    try {
      await approveSource(brandId, d.id);
      setMsg({ ok: true, text: `“${d.title}” is approved. New checks use it.` });
      reload();
    } catch (err) {
      setMsg({ ok: false, text: errorText(err) });
    } finally {
      setRowBusy(null);
    }
  };

  const newVersion = async () => {
    if (!brandId || !versionFor || !versionFile) return;
    setRowBusy(versionFor.id);
    try {
      const r = await uploadSourceVersion(brandId, versionFor.id, versionFile);
      setMsg({ ok: true, text: `“${versionFor.title}” now has version ${r.version_number}. Its approval status didn’t change.` });
      if (r.flipped.length) setFlipped({ title: versionFor.title, items: r.flipped });
      setVersionFor(null);
      setVersionFile(null);
      reload();
    } catch (err) {
      setMsg({ ok: false, text: uploadError(err) });
    } finally {
      setRowBusy(null);
    }
  };

  const withdraw = async () => {
    if (!brandId || !withdrawFor || !withdrawReason.trim()) return;
    setRowBusy(withdrawFor.id);
    try {
      const r = await withdrawSource(brandId, withdrawFor.id, { status: withdrawKind, reason: withdrawReason.trim() });
      setMsg({ ok: true, text: `“${withdrawFor.title}” is withdrawn and no longer used for checks.` });
      setFlipped({ title: withdrawFor.title, items: r.flipped });
      setWithdrawFor(null);
      setWithdrawReason("");
      reload();
    } catch (err) {
      setMsg({ ok: false, text: errorText(err) });
    } finally {
      setRowBusy(null);
    }
  };

  if (brands.state === "loading")
    return (
      <>
        <StageHead title="Guidelines" />
        <LoadingState label="Loading your brand…" />
      </>
    );
  if (brands.state === "error")
    return (
      <>
        <StageHead title="Guidelines" />
        <ErrorState message={brands.message} onRetry={refreshBrands} />
      </>
    );
  if (brands.state === "none")
    return (
      <>
        <StageHead title="Guidelines" />
        <EmptyState title="No brand yet">Your organisation has no brand. Ask your admin to create one.</EmptyState>
      </>
    );

  const list = docs.state === "ok" ? docs.docs : [];
  const approved = list.filter((d) => d.status === "approved").length;

  return (
    <>
      <StageHead title="Guidelines" status={docs.state === "ok" ? `${approved} approved` : undefined} />
      <BrandBar brand={brands.brand} brands={brands.brands} fallback={brands.fallback} onChoose={choose} />

      {msg && (
        <p className={`app-alert ${msg.ok ? "app-alert--ok" : "app-alert--bad"}`} role={msg.ok ? "status" : "alert"}>
          {msg.text}
        </p>
      )}
      {flipped && (
        <div className="app-alert" role="status">
          <b>{flipped.items.length ? `${flipped.items.length} approved item${flipped.items.length === 1 ? "" : "s"} went back to review` : "No approved items relied on it"}</b>{" "}
          after the change to “{flipped.title}”.
          {flipped.items.length > 0 && (
            <ul className="add-flipped">
              {flipped.items.map((f) => (
                <li key={f.review_id}>
                  <a className="link" href={`/app/review?id=${f.review_id}`}>
                    Open the review
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <Panels>
        <Panel n="01" label="Add a document" title="Upload a guideline">
          <p className="add-note">
            Brand guides, product facts, approved claims. <b>Only approved documents are used for checks.</b> Drafts and withdrawn
            documents are ignored.
          </p>
          {manager ? (
            <form className="add-stack" onSubmit={onUpload}>
              <UploadDropzone file={file} onFile={pick} busy={busy} />
              {file && (
                <label className="field">
                  <span className="field__label">Document name</span>
                  <input className="field__input" value={title} maxLength={300} onChange={(e) => setTitle(e.target.value)} />
                </label>
              )}
              <label className="option">
                <input type="checkbox" className="tick tick--checkbox" checked={confidential} onChange={(e) => setConfidential(e.target.checked)} />
                <span className="option__text">
                  <span className="option__label">Private</span>
                  <span className="option__help">Checked only with a local AI, never sent to an outside service.</span>
                </span>
              </label>
              <Button type="submit" disabled={!file || busy} aria-busy={busy}>
                {busy ? "Uploading…" : "Upload and approve"}
              </Button>
            </form>
          ) : (
            <p className="app-alert" role="note">
              ⊘ Your role ({roleName(role)}) can’t add or change documents. An admin or source manager does this.
            </p>
          )}
        </Panel>

        <Panel n="02" label="Documents" title={brands.brand.name}>
          {docs.state === "loading" && <LoadingState label="Loading documents…" />}
          {docs.state === "error" && <ErrorState error={docs.error} onRetry={reload} />}
          {docs.state === "ok" && list.length === 0 && (
            <EmptyState title="No documents yet">Upload a brand guide or product fact sheet to start checking drafts.</EmptyState>
          )}
          {list.length > 0 && (
            <ul className="rows" aria-label="Documents">
              {list.map((d) => {
                const off = d.status !== "approved" && d.status !== "draft";
                return (
                  <li key={d.id} className={`add-doc${off ? " add-doc--off" : ""}`}>
                    <div className="add-doc__top">
                      <div>
                        <p className="add-doc__title">{d.title}</p>
                        <p className="add-doc__meta">
                          {[d.source_type ? (TYPE[d.source_type] ?? d.source_type) : null, d.latest_version ? `Version ${d.latest_version}` : null, `Added ${new Date(d.created_at).toLocaleDateString()}`]
                            .filter(Boolean)
                            .join(" · ")}
                        </p>
                      </div>
                      <div className="add-row">
                        <SourceStatusBadge status={d.status} />
                        <span className={`tag${d.sensitivity === "confidential" ? " tag--private" : ""}`}>{d.sensitivity === "confidential" ? "Private" : "Team only"}</span>
                      </div>
                    </div>
                    {d.status === "draft" && <p className="add-note add-muted">Not used for checks until approved.</p>}
                    {manager && !off && (
                      <div className="add-doc__actions">
                        {d.status === "draft" && (
                          <button type="button" className="add-btn-small" onClick={() => approve(d)} disabled={rowBusy === d.id}>
                            ✓ Approve
                          </button>
                        )}
                        <button type="button" className="add-btn-small" onClick={() => (setVersionFor(d), setVersionFile(null))} disabled={rowBusy === d.id}>
                          ↑ Upload new version
                        </button>
                        {d.status === "approved" && (
                          <button type="button" className="add-btn-small" onClick={() => setWithdrawFor(d)} disabled={rowBusy === d.id}>
                            – Withdraw
                          </button>
                        )}
                      </div>
                    )}
                    <details className="add-details">
                      <summary>Details</summary>
                      <code className="add-mono">Document {d.id}</code>
                    </details>
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>

        <Panel n="03" label="How it works" title="What gets used">
          <dl className="spec">
            <div className="spec__row">
              <dt>Used for checks</dt>
              <dd>{docs.state === "ok" ? `${approved} approved document${approved === 1 ? "" : "s"}` : "–"}</dd>
            </div>
            <div className="spec__row">
              <dt>Draft</dt>
              <dd>Uploaded but not approved. Not used.</dd>
            </div>
            <div className="spec__row">
              <dt>New version</dt>
              <dd>Keeps its approval. Items that cited text which changed go back to review.</dd>
            </div>
            <div className="spec__row">
              <dt>Withdraw</dt>
              <dd>Stops using it. Items approved with it go back to review.</dd>
            </div>
          </dl>
        </Panel>
      </Panels>

      <ConfirmDialog
        open={!!versionFor}
        title="Upload a new version"
        confirmLabel="Upload version"
        busy={rowBusy === versionFor?.id}
        confirmDisabled={!versionFile}
        onConfirm={newVersion}
        onCancel={() => (setVersionFor(null), setVersionFile(null))}
      >
        <p>
          New version of <b>{versionFor?.title}</b>. Approved items whose cited text changes will go back to review.
        </p>
        <UploadDropzone
          file={versionFile}
          onFile={(f) => {
            const problem = checkFile(f);
            if (problem) setMsg({ ok: false, text: problem });
            setVersionFile(problem ? null : f);
          }}
          label="Drop the new version here"
        />
      </ConfirmDialog>

      <ConfirmDialog
        open={!!withdrawFor}
        title="Withdraw this document?"
        confirmLabel="Withdraw"
        busy={rowBusy === withdrawFor?.id}
        confirmDisabled={!withdrawReason.trim()}
        onConfirm={withdraw}
        onCancel={() => (setWithdrawFor(null), setWithdrawReason(""))}
      >
        <p>
          <b>{withdrawFor?.title}</b> will stop being used for checks. <b>Approved items that relied on this will be sent back to review.</b>
        </p>
        <label className="add-field-row">
          <span className="field__label">Why</span>
          <select className="add-select" value={withdrawKind} onChange={(e) => setWithdrawKind(e.target.value as "archived" | "superseded")}>
            <option value="archived">No longer valid</option>
            <option value="superseded">Replaced by another document</option>
          </select>
        </label>
        <label className="add-field-row">
          <span className="field__label">Reason (required)</span>
          <textarea className="field__input" value={withdrawReason} maxLength={2000} onChange={(e) => setWithdrawReason(e.target.value)} placeholder="e.g. Battery spec changed in March" />
        </label>
      </ConfirmDialog>
    </>
  );
}
