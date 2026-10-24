"use client";

import { useEffect, useRef, useState } from "react";

const KIND: Record<string, string> = { pdf: "PDF", docx: "Word", txt: "Text" };
const extOf = (name: string) => name.split(".").pop()?.toLowerCase() ?? "";

/**
 * The chosen file, before it is uploaded: a small paper page with a preview and a bin button.
 * - .txt: its first lines, read in the browser;
 * - .pdf: the browser's own render of the first page (blob URL, revoked on unmount);
 * - .docx: browsers can't read Word files, so a labelled sheet (the server reads the text).
 * Nothing leaves the browser until "Upload". The bin only clears the choice.
 */
export function FilePreview({ file, onRemove, disabled = false }: { file: File; onRemove: () => void; disabled?: boolean }) {
  const ext = extOf(file.name);
  const [text, setText] = useState<string | null>(null);
  const frame = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    if (ext !== "txt") return;
    let live = true;
    file
      .slice(0, 1600)
      .text()
      .then((t) => live && setText(t));
    return () => {
      live = false;
    };
  }, [file, ext]);

  // The PDF's blob URL goes straight onto the frame (created and revoked by the same effect).
  useEffect(() => {
    if (ext !== "pdf" || !frame.current) return;
    const u = URL.createObjectURL(file);
    frame.current.src = `${u}#toolbar=0&navpanes=0&scrollbar=0&view=FitH`;
    return () => URL.revokeObjectURL(u);
  }, [file, ext]);

  const size = file.size < 1024 * 1024 ? `${Math.max(1, Math.round(file.size / 1024))} KB` : `${(file.size / 1024 / 1024).toFixed(1)} MB`;
  return (
    <div className="fpreview">
      <div className="fpreview__page" aria-hidden="true">
        {ext === "pdf" ? (
          <>
            {/* lined sheet underneath: what shows if this browser can't draw PDFs inline */}
            <span className="fpreview__sheet">
              <span className="fpreview__lines" />
            </span>
            <iframe ref={frame} className="fpreview__pdf" title="" tabIndex={-1} />
          </>
        ) : ext === "txt" && text !== null ? (
          <p className="fpreview__text">{text}</p>
        ) : (
          <span className="fpreview__sheet">
            <span className="fpreview__lines" />
          </span>
        )}
        <span className="fpreview__badge">{KIND[ext] ?? ext.toUpperCase()}</span>
      </div>
      <div className="fpreview__info">
        <p className="fpreview__name">{file.name}</p>
        <p className="fpreview__meta">
          {KIND[ext] ?? ext.toUpperCase()} file · {size}
        </p>
        <p className="fpreview__note">{ext === "docx" ? "Word files are read on the server after upload." : "Preview of the start of the file. Nothing is sent until you upload."}</p>
      </div>
      <button type="button" className="bin" onClick={onRemove} disabled={disabled} aria-label={`Remove ${file.name}`} title="Remove this file">
        <BinIcon />
      </button>
    </div>
  );
}

export function BinIcon() {
  return (
    <svg className="bin__icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path className="bin__lid" d="M4 6.5h16M9.5 6.5V4.8c0-.7.5-1.3 1.2-1.3h2.6c.7 0 1.2.6 1.2 1.3v1.7" />
      <path d="M6.2 6.5l.9 12.6c.1 1 .9 1.9 2 1.9h5.8c1.1 0 1.9-.9 2-1.9l.9-12.6M10 10.5v6.5M14 10.5v6.5" />
    </svg>
  );
}
