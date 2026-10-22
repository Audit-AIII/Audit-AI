import type { HTMLAttributes, ReactNode } from "react";

type Props = { children: ReactNode; as?: "div" | "article" | "li" } & HTMLAttributes<HTMLElement>;

/** Raised board: grain + the single raised shadow recipe. */
export function Card({ children, as: Tag = "div", className, ...rest }: Props) {
  return (
    <Tag {...rest} className={className ? `card ${className}` : "card"}>
      {children}
    </Tag>
  );
}
