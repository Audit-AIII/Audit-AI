import type { AnchorHTMLAttributes, ReactNode } from "react";

type Props = { href: string; children: ReactNode; className?: string; arrow?: boolean } & Omit<
  AnchorHTMLAttributes<HTMLAnchorElement>,
  "href" | "children" | "className"
>;

/**
 * Dashed-underline text link; the underline tightens on hover (250ms). Hit area padded to 44px.
 * `arrow` adds a trailing arrow that slides right on hover (underline stays on the label).
 */
export function TextLink({ href, children, className, arrow, ...rest }: Props) {
  if (arrow) {
    return (
      <a {...rest} href={href} className={className ? `link-arrow link--tap ${className}` : "link-arrow link--tap"}>
        <span className="link">{children}</span>
        <span className="link-arrow__glyph" aria-hidden="true">
          →
        </span>
      </a>
    );
  }
  return (
    <a {...rest} href={href} className={className ? `link link--tap ${className}` : "link link--tap"}>
      {children}
    </a>
  );
}
