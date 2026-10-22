import type { HTMLAttributes, ReactNode } from "react";

type Relief = "pressed" | "raised" | "raised-canvas" | "flat";
type Props = {
  as?: "h1" | "h2" | "h3" | "p";
  relief?: Relief;
  size?: "heading" | "title";
  children: ReactNode;
} & HTMLAttributes<HTMLHeadingElement>;

/**
 * Display heading. Written in sentence case, rendered uppercase.
 * pressed = debossed into the board (ink-2 + inner shadow); raised = lifted letters (canvas on dark).
 */
export function Heading({ as: Tag = "h2", relief = "pressed", size = "heading", className, children, ...rest }: Props) {
  const cls = [size === "heading" ? "t-heading" : "t-title", relief !== "flat" && `relief-${relief}`, className]
    .filter(Boolean)
    .join(" ");
  return (
    <Tag {...rest} className={cls}>
      {children}
    </Tag>
  );
}
