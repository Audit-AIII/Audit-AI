"use client";

import { useState, type ReactNode } from "react";

/** Stage page header: big pressed title + a dashed status pill. */
export function StageHead({ title, status, children }: { title: string; status?: string; children?: ReactNode }) {
  return (
    <div className="stage-head">
      <h1 className="stage-head__title relief-pressed grain-text" data-text={title}>
        {title}
      </h1>
      {status && <span className="stage-head__status t-caption">{status}</span>}
      {children && <div className="stage-head__actions">{children}</div>}
    </div>
  );
}

/** Numbered panel: a raised card with a "01 · LABEL" tab and an optional title. */
export function Panel({
  n,
  label,
  title,
  children,
  className,
}: {
  n: string;
  label: string;
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel card${className ? ` ${className}` : ""}`} aria-label={label}>
      <header className="panel__head">
        <span className="panel__tab">
          <span className="panel__n">{n}</span>
          <span className="t-caption">{label}</span>
        </span>
        {title && <h2 className="panel__title">{title}</h2>}
      </header>
      <div className="panel__body">{children}</div>
    </section>
  );
}

/**
 * File drop: a pressed, dashed well with a real (visually hidden) file input behind it.
 * Click / keyboard opens the picker; files can also be dragged onto it. `onFile` receives the
 * first file; the input is reset afterwards so picking the same file again still fires.
 */
export function Dropzone({
  title,
  hint,
  small = false,
  onFile,
  accept,
  fileName,
  disabled = false,
}: {
  title: string;
  hint: string;
  small?: boolean;
  onFile?: (file: File) => void;
  accept?: string;
  /** Name of the file already chosen, shown in place of the hint. */
  fileName?: string | null;
  disabled?: boolean;
}) {
  const [over, setOver] = useState(false);
  const take = (files: FileList | null | undefined) => {
    const file = files?.[0];
    if (file && onFile && !disabled) onFile(file);
  };
  return (
    <label
      className={`dropzone${small ? " dropzone--small" : ""}${over ? " is-over" : ""}${fileName ? " has-file" : ""}${disabled ? " is-disabled" : ""}`}
      onDragOver={(e) => {
        if (disabled) return;
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
      <input
        type="file"
        className="sr-only"
        accept={accept}
        disabled={disabled}
        onChange={(e) => {
          take(e.currentTarget.files);
          e.currentTarget.value = "";
        }}
      />
      <svg className="dropzone__icon" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 16V4M7 9l5-5 5 5M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4" />
      </svg>
      <span className="dropzone__title">{fileName ? "File chosen" : title}</span>
      <span className="dropzone__hint" aria-live="polite">
        {fileName ?? hint}
      </span>
      <span className="dropzone__btn">{fileName ? "Choose another" : "Choose a file"}</span>
    </label>
  );
}

/** Checkbox or radio drawn in the paper style: a raised tile that presses in when chosen. */
export function Option({
  type = "checkbox",
  name,
  label,
  help,
  defaultChecked,
}: {
  type?: "checkbox" | "radio";
  name?: string;
  label: string;
  help?: string;
  defaultChecked?: boolean;
}) {
  return (
    <label className="option">
      <input type={type} name={name} className={`tick tick--${type}`} defaultChecked={defaultChecked} />
      <span className="option__text">
        <span className="option__label">{label}</span>
        {help && <span className="option__help">{help}</span>}
      </span>
    </label>
  );
}

export function Panels({ children, cols = "3" }: { children: ReactNode; cols?: "2" | "3" | "wide" }) {
  return <div className={`panels panels--${cols}`}>{children}</div>;
}
