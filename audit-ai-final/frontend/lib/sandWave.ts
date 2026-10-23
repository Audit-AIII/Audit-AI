/**
 * Sand-wave page transition between the landing side (/, /login) and the workspace (/app/*).
 * Links are picked up automatically (components/layout/SandWave.tsx); code that navigates with
 * the router calls `sandNavigate` instead of `router.push`.
 */
export type Area = "site" | "app";

export const areaOf = (path: string): Area => (path === "/app" || path.startsWith("/app/") ? "app" : "site");

export type SandGo = {
  href: string;
  /** Runs once the sand covers the screen, just before navigating (e.g. sign out). */
  beforeNavigate?: () => void;
};

export const SAND_EVENT = "sandwave:go";

/** True while a sand transition is running (set by SandWave). Lets pages skip their own
 * redirects, e.g. the workspace must not bounce to /login while signing out goes to "/". */
let transitioning = false;
export const isSandTransitioning = () => transitioning;
export const setSandTransitioning = (on: boolean) => {
  transitioning = on;
};

export function sandNavigate(href: string, beforeNavigate?: () => void) {
  window.dispatchEvent(new CustomEvent<SandGo>(SAND_EVENT, { detail: { href, beforeNavigate } }));
}
