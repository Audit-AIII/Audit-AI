"use client";

import { useSyncExternalStore } from "react";

/**
 * Demo session (no backend yet): the signed-in user's email and name live in this browser's
 * localStorage. Replace with real auth when the API exists; components only use useSession().
 */
export type Session = { email: string; name?: string };

const KEY = "audit-ai.session";
const EVENT = "audit-ai:session";

let cachedRaw: string | null = null;
let cached: Session | null = null;

function read(): Session | null {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    try {
      cached = raw ? (JSON.parse(raw) as Session) : null;
    } catch {
      cached = null;
    }
  }
  return cached;
}

function subscribe(cb: () => void) {
  window.addEventListener(EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(EVENT, cb);
    window.removeEventListener("storage", cb);
  };
}

export function signIn(session: Session) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(session));
  } catch {
    /* storage blocked: session lasts for this page only */
  }
  window.dispatchEvent(new Event(EVENT));
}

export function signOut() {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new Event(EVENT));
}

/** Reads the stored session directly (for effects that run before the hook has re-rendered). */
export function getSession(): Session | null {
  return read();
}

/** Current session, or null when signed out (always null during server render). */
export function useSession(): Session | null {
  return useSyncExternalStore(subscribe, read, () => null);
}
