import type { CSSProperties, ReactNode } from "react";

/**
 * Beach decor for the sand-coloured sections: shells half-buried in the canvas.
 * Pure decoration (aria-hidden, no pointer events). Each shell is lit from the top-left
 * (#shell-face gradient), sprinkled with sand and sinks into the board towards the
 * bottom-right (CSS mask). Shared gradient + filter live in ReliefDefs.
 * Coloured pieces (pebbles, sea glass, conch lip, pearls) use a matte palette mixed from the
 * sand (base.css, "Shore"); `tide` is a wide wet-sand wash line with foam.
 */

type Kind =
  | "scallop" | "spiral" | "dollar" | "star" | "auger" | "cockle" | "pebble"
  | "conch" | "pearls" | "glass" | "tide";
export type Tone = "sand" | "terracotta" | "sage" | "ochre" | "slate" | "sea" | "rose" | "charcoal";
export type ShellSpot = { kind: Kind; x: string; y: string; size: number; rotate?: number; tone?: Tone };

// Kinds that stay clean (no sand sprinkled on them): polished or wet pieces.
const SMOOTH = new Set<Kind>(["pearls", "glass", "tide"]);

const r1 = (n: number) => Math.round(n * 10) / 10;
const polar = (cx: number, cy: number, r: number, deg: number) => {
  const a = (deg * Math.PI) / 180;
  return [r1(cx + r * Math.cos(a)), r1(cy + r * Math.sin(a))] as const;
};

// Scallop: fan of ribs from a hinge, scalloped top edge, two small ears.
// Fan spans 214°–326° at r=52 from the hinge so the whole shell (bumps included) stays
// inside the 100×100 box (x ≈ 7–93, top ≈ 30).
const SCALLOP = (() => {
  const ribs = 9, from = 214, span = 112;
  const pts = Array.from({ length: ribs + 1 }, (_, i) => polar(50, 86, 52, from + (span / ribs) * i));
  let d = `M50 86 L${pts[0][0]} ${pts[0][1]}`;
  for (let i = 1; i < pts.length; i++) {
    const mid = polar(50, 86, 60, from + (span / ribs) * (i - 0.5));
    d += ` Q${mid[0]} ${mid[1]} ${pts[i][0]} ${pts[i][1]}`;
  }
  d += " Z";
  const lines = pts.slice(1, -1).map((p) => `M50 86 L${p[0]} ${p[1]}`).join(" ");
  return { d, lines };
})();

// Spiral (moon snail seen from above): a filled whorl with a log-spiral seam.
const SPIRAL = (() => {
  let d = "";
  for (let t = 0; t <= 4.2 * Math.PI; t += 0.18) {
    const r = 3 + 36 * (t / (4.2 * Math.PI)) ** 1.15;
    const [x, y] = [r1(50 + r * Math.cos(t)), r1(50 + r * Math.sin(t))];
    d += d ? ` L${x} ${y}` : `M${x} ${y}`;
  }
  return d;
})();

// Starfish: five rounded arms.
const STAR = (() => {
  let d = "";
  for (let i = 0; i < 5; i++) {
    const tip = polar(50, 52, 44, -90 + i * 72);
    const inner = polar(50, 52, 15, -54 + i * 72);
    const prevInner = polar(50, 52, 15, -126 + i * 72);
    const c1 = polar(50, 52, 30, -96 + i * 72);
    const c2 = polar(50, 52, 30, -84 + i * 72);
    d += `${i ? " L" : "M"}${prevInner[0]} ${prevInner[1]} Q${c1[0]} ${c1[1]} ${tip[0]} ${tip[1]} Q${c2[0]} ${c2[1]} ${inner[0]} ${inner[1]}`;
  }
  const dots = Array.from({ length: 5 }, (_, i) => [0.45, 0.7].map((f) => polar(50, 52, 44 * f, -90 + i * 72))).flat();
  return { d: d + " Z", dots };
})();

// Sand dollar: disc with a five-petal flower.
const PETALS = Array.from({ length: 5 }, (_, i) => -90 + i * 72);

// Cockle: rounded clam with radial ribs.
const COCKLE = "M50 84 C22 84 12 58 18 38 C24 18 40 12 50 12 C60 12 76 18 82 38 C88 58 78 84 50 84 Z";
const COCKLE_RIBS = Array.from({ length: 8 }, (_, i) => polar(50, 84, 80, 218 + i * 15.4));

// Conch: stacked spire at the top-left, flared lip and soft-coloured opening to the right.
const CONCH =
  "M30 8 C34 12 36 14 40 16 C44 18 46 22 52 24 C60 26 66 28 74 32 C84 38 92 46 90 58 C88 70 80 78 70 84 C64 88 60 92 58 96 C54 92 50 90 44 84 C36 76 30 66 28 54 C26 42 24 30 26 20 C27 14 28 10 30 8 Z";
const CONCH_LIP = "M56 40 C70 38 84 46 84 58 C84 70 74 78 64 82 C60 70 58 56 56 40 Z";

// Tide: a foam line over darker wet sand, drawn on a wide 400×100 box.
const TIDE_FOAM = "M0 46 C30 38 52 52 84 44 C116 36 136 50 170 42 C204 34 226 50 262 42 C296 35 320 49 352 41 C372 37 388 42 400 40";
const TIDE_WET = `${TIDE_FOAM} L400 100 L0 100 Z`;
const TIDE_FOAM_2 = "M10 62 C44 56 70 66 104 60 C140 54 162 66 198 59 C232 53 258 64 292 58 C324 53 350 61 390 56";
const BUBBLES = [[36, 40], [92, 48], [120, 39], [188, 45], [236, 40], [281, 46], [330, 39], [366, 44], [64, 58], [150, 62], [310, 60]];

function Shape({ kind, tone = "sand" }: { kind: Kind; tone?: Tone }): ReactNode {
  const t = `tone--${tone}`;
  switch (kind) {
    case "scallop":
      return (
        <>
          <path className="shell__ear" d="M38 82 L50 92 L62 82 L59 75 L41 75 Z" />
          <path className="shell__body" d={SCALLOP.d} />
          <path className="shell__line" d={SCALLOP.lines} />
        </>
      );
    case "spiral":
      return (
        <>
          <circle className="shell__body" cx="50" cy="50" r="42" />
          <path className="shell__line shell__line--strong" d={SPIRAL} />
          <circle className="shell__hole" cx="50" cy="50" r="4" />
        </>
      );
    case "dollar":
      return (
        <>
          <circle className="shell__body" cx="50" cy="50" r="42" />
          {PETALS.map((a) => (
            <ellipse key={a} className="shell__line" cx="50" cy="31" rx="5.5" ry="15" transform={`rotate(${a + 90} 50 50)`} />
          ))}
          <circle className="shell__hole" cx="50" cy="50" r="2.6" />
        </>
      );
    case "star":
      return (
        <>
          <path className="shell__body" d={STAR.d} />
          {STAR.dots.map(([x, y], i) => (
            <circle key={i} className="shell__dot" cx={x} cy={y} r="2.2" />
          ))}
        </>
      );
    case "auger":
      return (
        <>
          <path className="shell__body" d="M50 6 C56 30 70 62 66 84 Q50 98 34 84 C30 62 44 30 50 6 Z" />
          <path className="shell__line" d="M47 20 L55 24 M44 34 L59 40 M40 50 L63 58 M37 66 L65 74 M36 80 L62 88" />
        </>
      );
    case "cockle":
      return (
        <>
          <path className="shell__body" d={COCKLE} />
          {/* ribs run past the rim and are clipped to it (#shell-cockle-clip in ReliefDefs) */}
          <path className="shell__line" clipPath="url(#shell-cockle-clip)" d={COCKLE_RIBS.map(([x, y]) => `M50 84 L${x} ${y}`).join(" ")} />
          <path className="shell__ear" d="M42 82 L50 90 L58 82 Z" />
        </>
      );
    case "pebble":
      if (tone === "sand") return <ellipse className="shell__body shell__body--pebble" cx="50" cy="54" rx="40" ry="28" />;
      return (
        <>
          <ellipse className={`shell__tone ${t}`} cx="50" cy="54" rx="40" ry="28" />
          <ellipse className="shell__sheen" cx="50" cy="54" rx="40" ry="28" />
        </>
      );
    case "conch":
      return (
        <>
          <path className="shell__body" d={CONCH} />
          <path className="shell__line" d="M27 18 Q34 21 41 17 M26 29 Q38 33 51 25 M27 41 Q44 44 63 31" />
          {[[43, 19], [52, 25], [62, 29], [72, 33]].map(([x, y]) => (
            <circle key={x} className="shell__knob" cx={x} cy={y} r="3" />
          ))}
          {/* the flared opening, in a soft colour */}
          <path className={`shell__tone ${tone === "sand" ? "tone--rose" : t}`} d={CONCH_LIP} />
          <path className="shell__sheen" d={CONCH_LIP} />
        </>
      );
    case "pearls":
      return (
        <>
          {[[34, 58, 22], [66, 42, 17], [68, 76, 13]].map(([x, y, r]) => (
            <circle key={x + y} className="shell__pearl" cx={x} cy={y} r={r} />
          ))}
        </>
      );
    case "glass":
      return (
        <>
          <path className={`shell__tone shell__tone--glass ${t}`} d="M22 40 C26 24 46 18 62 22 C78 26 84 42 78 58 C72 74 52 80 36 74 C22 68 18 54 22 40 Z" />
          <path className="shell__sheen" d="M22 40 C26 24 46 18 62 22 C78 26 84 42 78 58 C72 74 52 80 36 74 C22 68 18 54 22 40 Z" />
        </>
      );
    case "tide":
      return (
        <>
          <path className="tide__wet" d={TIDE_WET} />
          <path className="tide__foam" d={TIDE_FOAM} />
          <path className="tide__foam tide__foam--faint" d={TIDE_FOAM_2} />
          {BUBBLES.map(([x, y], i) => (
            <circle key={i} className="tide__bubble" cx={x} cy={y} r={i % 3 ? 1.6 : 2.4} />
          ))}
        </>
      );
  }
}

export function Shore({ shells }: { shells: ShellSpot[] }) {
  return (
    <div className="shore" aria-hidden="true">
      {[...shells].sort((a, b) => Number(b.kind === "tide") - Number(a.kind === "tide")).map((s, i) => {
        const wide = s.kind === "tide";
        return (
          <svg
            key={i}
            className={`shell shell--${s.kind}`}
            viewBox={wide ? "0 0 400 100" : "0 0 100 100"}
            preserveAspectRatio="none"
            focusable="false"
            style={{ "--x": s.x, "--y": s.y, "--size": `${s.size}px` } as CSSProperties}
          >
            {/* Rotate inside the filter so the cast shadow always falls bottom-right */}
            <g filter={wide ? undefined : SMOOTH.has(s.kind) ? "url(#shell-shadow)" : "url(#shell-sand)"}>
              <g transform={wide ? undefined : `rotate(${s.rotate ?? 0} 50 50)`}>
                <Shape kind={s.kind} tone={s.tone} />
              </g>
            </g>
          </svg>
        );
      })}
    </div>
  );
}

/**
 * Sand drift banked against the bottom edge of a card, with a small find lying in it.
 * Drawn on a 400×70 box; the card's bottom edge sits at y≈44 (see .checks__drift).
 */
const DRIFT_CREST = "M0 54 C34 48 64 32 116 35 C168 38 192 27 242 29 C292 31 322 43 362 41 C382 40 393 46 400 50";
const DRIFT_FINDS: { kind: Kind; tone?: Tone; x: number; y: number; size: number; rotate: number }[][] = [
  [{ kind: "scallop", x: 17, y: 3, size: 62, rotate: -18 }, { kind: "pebble", tone: "sage", x: 326, y: 25, size: 31, rotate: 10 }],
  [{ kind: "pebble", tone: "terracotta", x: 55, y: 20, size: 34, rotate: -8 }, { kind: "spiral", x: 311, y: 8, size: 48, rotate: 30 }],
  [{ kind: "glass", tone: "sea", x: 38, y: 15, size: 42, rotate: 25 }, { kind: "cockle", x: 304, y: 2, size: 56, rotate: 14 }],
  [{ kind: "pearls", x: 45, y: 12, size: 48, rotate: 0 }, { kind: "pebble", tone: "slate", x: 330, y: 25, size: 31, rotate: -20 }],
  [{ kind: "conch", x: 21, y: -5, size: 64, rotate: -30 }, { kind: "pebble", tone: "rose", x: 336, y: 28, size: 25, rotate: 0 }],
  [{ kind: "pebble", tone: "ochre", x: 66, y: 23, size: 31, rotate: 15 }, { kind: "dollar", x: 310, y: 5, size: 53, rotate: -10 }],
];

export function SandDrift({ variant, className }: { variant: number; className?: string }) {
  const finds = DRIFT_FINDS[variant % DRIFT_FINDS.length];
  return (
    <svg className={`drift${className ? ` ${className}` : ""}`} viewBox="0 0 400 70" aria-hidden="true" focusable="false">
      <g filter="url(#shell-sand)">
        <path className="drift__sand" d={`${DRIFT_CREST} L400 70 L0 70 Z`} />
      </g>
      <path className="drift__crest" d={DRIFT_CREST} />
      {finds.map((f, i) => (
        <g key={i} transform={`translate(${f.x} ${f.y}) scale(${f.size / 100})`}>
          <g filter={SMOOTH.has(f.kind) ? "url(#shell-shadow)" : "url(#shell-sand)"}>
            <g transform={`rotate(${f.rotate} 50 50)`}>
              <Shape kind={f.kind} tone={f.tone} />
            </g>
          </g>
        </g>
      ))}
    </svg>
  );
}

/** One small beach find (shell, pebble, pearls…) as its own decorative SVG, for placing by hand. */
export function BeachFind({
  kind,
  tone,
  size,
  rotate = 0,
  className,
}: {
  kind: Exclude<Kind, "tide">;
  tone?: Tone;
  size: number;
  rotate?: number;
  className?: string;
}) {
  return (
    <svg
      className={`find${className ? ` ${className}` : ""}`}
      viewBox="0 0 100 100"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
    >
      <g filter={SMOOTH.has(kind) ? "url(#shell-shadow)" : "url(#shell-sand)"}>
        <g transform={`rotate(${rotate} 50 50)`}>
          <Shape kind={kind} tone={tone} />
        </g>
      </g>
    </svg>
  );
}
