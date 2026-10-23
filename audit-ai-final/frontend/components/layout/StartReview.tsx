"use client";

import type { ReactNode } from "react";
import { Button } from "@/components/primitives/Button";
import { useSession } from "@/lib/session";

/** Where a new review starts. Signed in: straight to the Draft stage. Signed out: sign in first,
 * then come back here (the login page honours ?next=). */
export const START_REVIEW = "/app/draft";
export const loginThen = (next: string) => `/login?next=${encodeURIComponent(next)}`;

export function StartReviewButton({ children = "Start a review" }: { children?: ReactNode }) {
  const session = useSession();
  return <Button href={session ? START_REVIEW : loginThen(START_REVIEW)}>{children}</Button>;
}
