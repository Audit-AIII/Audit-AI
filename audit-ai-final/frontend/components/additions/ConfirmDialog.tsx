"use client";

import { useEffect, useRef, type ReactNode } from "react";

/**
 * Native <dialog> (focus trapped and Escape to close by the browser), drawn as a raised card.
 * `children` can hold extra fields (e.g. a reason box); `confirmDisabled` gates the action.
 */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  busy = false,
  confirmDisabled = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  busy?: boolean;
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} className="add-dialog" aria-labelledby="add-dialog-title" onCancel={(e) => (e.preventDefault(), onCancel())}>
      <h2 id="add-dialog-title" className="add-dialog__title">
        {title}
      </h2>
      <div className="add-dialog__body">{children}</div>
      <div className="add-dialog__actions">
        <button type="button" className="decision" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button type="button" className="add-btn-danger" onClick={onConfirm} disabled={busy || confirmDisabled} aria-busy={busy}>
          {busy ? "Working…" : confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
