"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api/client";
import type { BrandOut } from "@/lib/api/types";

/**
 * The brand the workspace works on. The user never sees or types a brand id: the brands come
 * from GET /api/brands, and the last one picked in this browser is remembered (localStorage),
 * used only if it is still in the list, else the oldest brand.
 */
const KEY = "audit-ai.active-brand";

function saved(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}
function save(id: string) {
  try {
    window.localStorage.setItem(KEY, id);
  } catch {
    /* storage blocked: the pick lasts for this page only */
  }
}

export type ActiveBrand =
  | { state: "loading" }
  | { state: "ready"; brand: BrandOut; brands: BrandOut[] }
  | { state: "none" }
  | { state: "error"; message: string };

async function load(preferred: string | null): Promise<ActiveBrand> {
  try {
    const brands = await api.brands();
    if (!brands.length) return { state: "none" };
    const brand = brands.find((b) => b.id === preferred) ?? brands[0];
    save(brand.id);
    return { state: "ready", brand, brands };
  } catch (err) {
    return {
      state: "error",
      message: err instanceof ApiError ? err.userMessage : "Something went wrong loading your brand. Please try again.",
    };
  }
}

export function useActiveBrand() {
  const [value, setValue] = useState<ActiveBrand>({ state: "loading" });
  const [tick, setTick] = useState(0);
  const [preferred, setPreferred] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    load(preferred ?? saved()).then((next) => live && setValue(next));
    return () => {
      live = false;
    };
  }, [tick, preferred]);

  /** Reload the list (e.g. after an upload changes approved_source_count). */
  const refresh = useCallback(() => setTick((t) => t + 1), []);
  /** Switch brand; remembered for next time. */
  const choose = useCallback((id: string) => {
    save(id);
    setPreferred(id);
  }, []);

  return { ...value, refresh, choose } as ActiveBrand & { refresh: () => void; choose: (id: string) => void };
}

/** Makes `id` the active brand next time the workspace loads (e.g. the brand created at sign-up). */
export const rememberBrand = (id: string) => save(id);
