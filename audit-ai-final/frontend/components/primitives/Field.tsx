import type { InputHTMLAttributes, TextareaHTMLAttributes } from "react";

type FieldProps = { label: string; id: string } & InputHTMLAttributes<HTMLInputElement>;
type TextareaProps = { label: string; id: string } & TextareaHTMLAttributes<HTMLTextAreaElement>;

/** Text input drawn as a pressed well. */
export function Field({ label, id, className, ...rest }: FieldProps) {
  return (
    <div className={className ? `field ${className}` : "field"}>
      <label className="field__label t-caption" htmlFor={id}>
        {label}
      </label>
      <input {...rest} id={id} className="field__input" />
    </div>
  );
}

export function Textarea({ label, id, className, ...rest }: TextareaProps) {
  return (
    <div className={className ? `field ${className}` : "field"}>
      <label className="field__label t-caption" htmlFor={id}>
        {label}
      </label>
      <textarea {...rest} id={id} className="field__input" />
    </div>
  );
}
