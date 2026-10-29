"use client";

import { useEffect } from "react";

const TOKENS = ["grain", "grain-dark", "grain-ink", "grain-scatter"];
/** The first of these ends largest-contentful-paint recording, so the swap can't count as a new LCP. */
const INPUT = ["wheel", "scroll", "touchstart", "pointerdown", "keydown"] as const;

/**
 * Paper grain, rasterised once. The --grain* tokens (design/tokens.css) are SVG feTurbulence
 * stacks; Chromium keeps an SVG background as a vector recording and re-runs every turbulence
 * filter each time a tile is rastered, which was ~90% of the raster work while scrolling the
 * landing page (PERF_BASELINE.md). Here each token's own SVG is drawn once, at this screen's pixel
 * density, into a bitmap, and the token is pointed at that bitmap. Same browser, same SVG, same
 * size, so the grain looks the same (qa/perf-shots.mjs). Nothing is downloaded.
 *
 * Baked and swapped in while idle, except on the sections already on screen: they keep the SVG
 * until the first scroll or input. The swap is invisible, but a background repainted on screen
 * would be reported as a late LCP, and swapping everything at the first scroll restyled the whole
 * landing page in one 57 ms task (4x CPU throttle). Pinning only the on-screen sections keeps that
 * last step small. If anything fails the SVG token stays.
 */
export function GrainBake() {
  useEffect(() => {
    if (typeof createImageBitmap !== "function" || !CSS.supports("background-image", 'image-set(url("g.png") 1x)')) return;
    const root = document.documentElement;
    const styles = getComputedStyle(root);
    // The stylesheet's SVGs, read before this component sets anything.
    const sources = TOKENS.map((name) => {
      const value = styles.getPropertyValue(`--${name}`).trim();
      const svg = /^url\("(data:image\/svg\+xml,[^"]+)"\)$/.exec(value)?.[1];
      return { name, value, svg, size: svg ? Number(/width='(\d+)'/.exec(svg)?.[1]) : 0 };
    });
    let urls: string[] = [];
    let baked: [string, string][] | null = null;
    let interacted = false;
    let cancelled = false;
    let pinned: HTMLElement[] = [];
    // Safari has no requestIdleCallback.
    const hasIdle = typeof window.requestIdleCallback === "function";
    const later = (fn: () => void, timeout: number) =>
      hasIdle ? window.requestIdleCallback(fn, { timeout }) : window.setTimeout(fn, Math.min(timeout, 300));

    /** Top-level sections on screen now; very tall wrappers (e.g. <main>) are opened up. */
    const onScreen = (parent: Element): HTMLElement[] =>
      Array.from(parent.children).flatMap((el) => {
        if (!(el instanceof HTMLElement)) return [];
        const r = el.getBoundingClientRect();
        if (r.bottom <= 0 || r.top >= window.innerHeight || r.height === 0) return [];
        return r.height > window.innerHeight * 1.5 && el.childElementCount ? onScreen(el) : [el];
      });

    const unpin = () => {
      pinned.forEach((el) => sources.forEach(({ name }) => el.style.removeProperty(`--${name}`)));
      pinned = [];
    };

    const apply = () => {
      if (!baked || cancelled) return;
      if (!interacted && !pinned.length) {
        pinned = onScreen(document.body);
        pinned.forEach((el) => sources.forEach(({ name, value }) => el.style.setProperty(`--${name}`, value)));
      }
      for (const [name, value] of baked) root.style.setProperty(`--${name}`, value);
    };

    const bake = async () => {
      const dpr = window.devicePixelRatio || 1;
      const next: [string, string][] = [];
      const made: string[] = [];
      for (const { name, svg, size } of sources) {
        if (!svg || !size) continue;
        try {
          const img = new Image();
          img.src = svg;
          await img.decode();
          const px = Math.round(size * dpr);
          // createImageBitmap rasterises off the main thread (drawImage blocked it for 150+ ms on a
          // throttled phone profile).
          const bitmap = await createImageBitmap(img, { resizeWidth: px, resizeHeight: px });
          const canvas = document.createElement("canvas");
          canvas.width = canvas.height = px;
          canvas.getContext("bitmaprenderer")?.transferFromImageBitmap(bitmap);
          const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve));
          if (cancelled) return;
          if (!blob) continue;
          const url = URL.createObjectURL(blob);
          made.push(url);
          // image-set at the screen's density keeps the tile at its CSS size (e.g. 360px).
          next.push([name, `image-set(url("${url}") ${dpr}x)`]);
        } catch {
          // Keep this token's SVG.
        }
      }
      const old = urls;
      urls = made;
      baked = next;
      apply();
      old.forEach((u) => URL.revokeObjectURL(u));
    };

    const onInput = () => {
      interacted = true;
      INPUT.forEach((t) => window.removeEventListener(t, onInput));
      // Not inside the input's own task: on a phone that stacked with the first scroll's work into a
      // 50+ ms task. The next idle moment restyles just the pinned sections.
      later(unpin, 1000);
    };
    INPUT.forEach((t) => window.addEventListener(t, onInput, { passive: true }));

    const start = () => void bake();
    const idle = later(start, 2000);
    // Zoom or a move to another screen changes the pixel density: bake again so the grain stays sharp.
    const density = window.matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`);
    density.addEventListener("change", start, { once: true });

    return () => {
      cancelled = true;
      if (hasIdle) window.cancelIdleCallback(idle);
      else window.clearTimeout(idle);
      density.removeEventListener("change", start);
      INPUT.forEach((t) => window.removeEventListener(t, onInput));
      unpin();
      TOKENS.forEach((n) => root.style.removeProperty(`--${n}`));
      urls.forEach((u) => URL.revokeObjectURL(u));
    };
  }, []);

  return null;
}
