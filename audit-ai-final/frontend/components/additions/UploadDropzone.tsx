"use client";

import { useId, useState } from "react";

export const ACCEPT = ".pdf,.docx,.txt";
export const MAX_BYTES = 10 * 1024 * 1024; // backend max_source_upload_bytes default

/** Plain-word check before sending; returns an error sentence or null. */
export function checkFile(f: File): string | null {
  if (!/\.(pdf|docx|txt)$/i.test(f.name)) return `“${f.name}” isn’t a supported file. Use a PDF, a Word (.docx) or a text (.txt) file.`;
  if (f.size > MAX_BYTES) return `“${f.name}” is ${(f.size / 1024 / 1024).toFixed(1)} MB. The limit is 10 MB.`;
  if (f.size === 0) return `“${f.name}” is empty.`;
  return null;
}

/**
 * New drop zone for the additive pages (the existing Dropzone is left as it is). A real button
 * opens the picker (keyboard: Tab + Enter), files can be dropped anywhere on it, and an upload in
 * progress shows an indeterminate bar (fetch has no upload progress events).
 */
export function UploadDropzone({
  onFile,
  file,
  busy = false,
  disabled = false,
  label = "Drop a file here",
}: {
  onFile: (f: File) => void;
  file: File | null;
  busy?: boolean;
  disabled?: boolean;
  label?: string;
}) {
  const id = useId();
  const [over, setOver] = useState(false);
  const off = disabled || busy;
  const take = (list: FileList | null | undefined) => {
    const f = list?.[0];
    if (f && !off) onFile(f);
  };
  return (
    <div
      className={`add-drop${over ? " is-over" : ""}${off ? " is-off" : ""}`}
      onDragOver={(e) => {
        if (off) return;
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        take(e.dataTransfer?.files);
      }}
    >
      <svg className="add-drop__icon" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 16V4M7 9l5-5 5 5M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4" />
      </svg>
      <p className="add-drop__title">{file ? file.name : label}</p>
      <p className="add-drop__hint" aria-live="polite">
        {file ? `${Math.max(1, Math.round(file.size / 1024))} KB · ready to upload` : "PDF, Word (.docx) or text (.txt) · up to 10 MB"}
      </p>
      <input
        id={id}
        type="file"
        className="add-sr"
        accept={ACCEPT}
        disabled={off}
        onChange={(e) => {
          take(e.currentTarget.files);
          e.currentTarget.value = "";
        }}
      />
      <label htmlFor={id} className="add-drop__btn" aria-disabled={off}>
        {file ? "Choose another file" : "Choose a file"}
      </label>
      {busy && (
        <span className="add-progress" role="progressbar" aria-label="Uploading">
          <span className="add-progress__bar" />
        </span>
      )}
    </div>
  );
}
