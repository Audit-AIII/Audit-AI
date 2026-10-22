import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from "react";

type Common = { children: ReactNode; className?: string };
type AsLink = Common & { href: string } & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "className" | "children">;
type AsButton = Common & { href?: undefined } & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className" | "children">;

const cx = (extra?: string) => (extra ? `btn ${extra}` : "btn");

/** Raised button. Hover/active presses it in (translate 1px,2px + well overlay). */
export function Button(props: AsLink | AsButton) {
  if (props.href !== undefined) {
    const { children, className, ...rest } = props;
    return (
      <a {...rest} className={cx(className)}>
        <span className="btn__label">{children}</span>
      </a>
    );
  }
  const { children, className, type = "button", ...rest } = props;
  return (
    <button {...rest} type={type} className={cx(className)}>
      <span className="btn__label">{children}</span>
    </button>
  );
}
