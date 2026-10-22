import type { AnchorHTMLAttributes, ReactNode } from "react";

type Props = { href: string; children: ReactNode; className?: string } & Omit<
  AnchorHTMLAttributes<HTMLAnchorElement>,
  "href" | "children" | "className"
>;

/** Dashed-underline text link; the underline tightens on hover (250ms). Hit area padded to 44px. */
export function TextLink({ href, children, className, ...rest }: Props) {
  return (
    <a {...rest} href={href} className={className ? `link link--tap ${className}` : "link link--tap"}>
      {children}
    </a>
  );
}
