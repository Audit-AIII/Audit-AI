"use client";

import { useCallback, useEffect, useState } from "react";
import type { BrandOut } from "@/lib/api/types";
import { errorText, isMissingRoute, request } from "./http";

/**
 * Brands for the additive pages. GET /api/brands is the real source. If a backend doesn't have it
 * (404/405), fall back to the brand the existing workspace last used: lib/brand.ts stores its id
 * under "audit-ai.active-brand" (read here, never written), and say so in a one-line notice.
 */
const ACTIVE_KEY = "audit-ai.active-brand"; // owned by lib/brand.ts
const PICK_KEY = "audit-ai.additions.brand"; // this page's own pick, so lib/brand.ts is never touched

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}
function write(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage blocked */
  }
}

export type BrandChoice = { id: string; name: string; approvedCount: number | null };
export type BrandsState =
  | { state: "loading" }
  | { state: "ready"; brand: BrandChoice; brands: BrandChoice[]; fallback: boolean }
  | { state: "none" }
  | { state: "error"; message: string };

const fromApi = (b: BrandOut): BrandChoice => ({ id: b.id, name: b.name, approvedCount: b.approved_source_count });

async function load(preferred: string | null): Promise<BrandsState> {
  try {
    const brands = (await request<BrandOut[]>("/api/brands")).map(fromApi);
    if (!brands.length) return { state: "none" };
    const pick = brands.find((b) => b.id === preferred) ?? brands.find((b) => b.id === read(ACTIVE_KEY)) ?? brands[0];
    return { state: "ready", brand: pick, brands, fallback: false };
  } catch (err) {
    if (isMissingRoute(err)) {
      const id = read(ACTIVE_KEY);
      if (!id) return { state: "error", message: "Your brand list isn’t available yet. Open Sources once, then come back." };
      const only = { id, name: "Your brand", approvedCount: null };
      return { state: "ready", brand: only, brands: [only], fallback: true };
    }
    return { state: "error", message: errorText(err) };
  }
}

export function useBrands() {
  const [value, setValue] = useState<BrandsState>({ state: "loading" });
  const [tick, setTick] = useState(0);
  const [preferred, setPreferred] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    load(preferred ?? read(PICK_KEY)).then((v) => live && setValue(v));
    return () => {
      live = false;
    };
  }, [tick, preferred]);
  const refresh = useCallback(() => setTick((t) => t + 1), []);
  const choose = useCallback((id: string) => {
    write(PICK_KEY, id);
    setPreferred(id);
  }, []);
  return { value, refresh, choose };
}
