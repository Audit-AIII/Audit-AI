"use client";

import { useState, type InputHTMLAttributes } from "react";

type PasswordFieldProps = { label: string; id: string } & Omit<InputHTMLAttributes<HTMLInputElement>, "type">;

/**
 * Password input (pressed well, like Field) with an eye button that shows or hides what was typed.
 * The button is a real <button type="button"> (never submits), named by aria-label and announced
 * as pressed / not pressed. Hidden again by default on every page load.
 */
export function PasswordField({ label, id, className, ...rest }: PasswordFieldProps) {
  const [shown, setShown] = useState(false);
  return (
    <div className={className ? `field ${className}` : "field"}>
      <label className="field__label t-caption" htmlFor={id}>
        {label}
      </label>
      <div className="field__password">
        <input {...rest} id={id} type={shown ? "text" : "password"} className="field__input" />
        <button
          type="button"
          className="field__eye"
          aria-label={shown ? "Hide password" : "Show password"}
          aria-pressed={shown}
          aria-controls={id}
          onClick={() => setShown((s) => !s)}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" />
            <circle cx="12" cy="12" r="3" />
            {shown && <path d="M4 4l16 16" />}
          </svg>
        </button>
      </div>
    </div>
  );
}
