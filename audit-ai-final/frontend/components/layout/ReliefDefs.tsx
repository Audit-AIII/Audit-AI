/**
 * Shared SVG filters. `#cut-relief` gives debossed (pressed) letters their inner shadow:
 * the inverted glyph alpha is offset down-right (light from top-left), blurred, tinted --deep
 * and clipped back inside the glyph.
 */
export function ReliefDefs() {
  return (
    <svg className="relief-defs" width="0" height="0" aria-hidden="true" focusable="false">
      <filter id="cut-relief" x="-4%" y="-6%" width="108%" height="112%" colorInterpolationFilters="sRGB">
        <feComponentTransfer in="SourceAlpha" result="outside">
          <feFuncA type="table" tableValues="1 0" />
        </feComponentTransfer>
        <feOffset in="outside" dx="3.5" dy="4.5" result="shifted" />
        <feGaussianBlur in="shifted" stdDeviation="2" result="soft" />
        <feFlood className="relief-defs__shade" result="shade" />
        <feComposite in="shade" in2="soft" operator="in" result="cast" />
        <feComposite in="cast" in2="SourceAlpha" operator="in" result="inner" />
        <feMerge>
          <feMergeNode in="SourceGraphic" />
          <feMergeNode in="inner" />
        </feMerge>
      </filter>
      {/* Hover state: the same cut, pressed deeper (longer offset, softer edge, darker) */}
      <filter id="cut-relief-deep" x="-4%" y="-6%" width="108%" height="112%" colorInterpolationFilters="sRGB">
        <feComponentTransfer in="SourceAlpha" result="outside">
          <feFuncA type="table" tableValues="1 0" />
        </feComponentTransfer>
        <feOffset in="outside" dx="5.5" dy="7" result="shifted" />
        <feGaussianBlur in="shifted" stdDeviation="2.6" result="soft" />
        <feFlood className="relief-defs__shade relief-defs__shade--deep" result="shade" />
        <feComposite in="shade" in2="soft" operator="in" result="cast" />
        <feComposite in="cast" in2="SourceAlpha" operator="in" result="inner" />
        <feMerge>
          <feMergeNode in="SourceGraphic" />
          <feMergeNode in="inner" />
        </feMerge>
      </filter>
      {/* Beach shells (Shore.tsx): top-left lit face, plus a filter that casts a soft
          bottom-right shadow and sprinkles sand grains over the shell. */}
      <linearGradient id="shell-face" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" className="shell-face__hi" />
        <stop offset=".55" className="shell-face__mid" />
        <stop offset="1" className="shell-face__lo" />
      </linearGradient>
      {/* Matte top-left light laid over coloured pieces, and the pearl's soft lustre */}
      <linearGradient id="shell-sheen-grad" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" className="shell-sheen__hi" />
        <stop offset=".5" className="shell-sheen__mid" />
        <stop offset="1" className="shell-sheen__lo" />
      </linearGradient>
      <radialGradient id="shell-pearl" cx=".36" cy=".32" r=".75">
        <stop offset="0" className="shell-pearl__hi" />
        <stop offset=".45" className="shell-pearl__mid" />
        <stop offset="1" className="shell-pearl__lo" />
      </radialGradient>
      <filter id="shell-shadow" x="-30%" y="-30%" width="170%" height="170%" colorInterpolationFilters="sRGB">
        <feGaussianBlur in="SourceAlpha" stdDeviation="1.8" result="blur" />
        <feOffset in="blur" dx="2" dy="3" result="drop" />
        <feFlood className="shell-sand__shade" result="shadeColour" />
        <feComposite in="shadeColour" in2="drop" operator="in" result="shadow" />
        <feMerge>
          <feMergeNode in="shadow" />
          <feMergeNode in="SourceGraphic" />
        </feMerge>
      </filter>
      <clipPath id="shell-cockle-clip">
        <path d="M50 84 C22 84 12 58 18 38 C24 18 40 12 50 12 C60 12 76 18 82 38 C88 58 78 84 50 84 Z" />
      </clipPath>
      <filter id="shell-sand" x="-20%" y="-20%" width="150%" height="150%" colorInterpolationFilters="sRGB">
        <feGaussianBlur in="SourceAlpha" stdDeviation="2.2" result="blur" />
        <feOffset in="blur" dx="2.5" dy="3.5" result="drop" />
        <feFlood className="shell-sand__shade" result="shadeColour" />
        <feComposite in="shadeColour" in2="drop" operator="in" result="shadow" />
        <feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="2" seed="7" result="noise" />
        <feColorMatrix in="noise" values="0 0 0 0 .28  0 0 0 0 .19  0 0 0 0 .11  15 0 0 0 -10.4" result="darkGrains" />
        <feTurbulence type="fractalNoise" baseFrequency=".7" seed="23" result="noise2" />
        <feColorMatrix in="noise2" values="0 0 0 0 .97  0 0 0 0 .91  0 0 0 0 .82  16 0 0 0 -11.4" result="lightGrains" />
        <feMerge result="grains">
          <feMergeNode in="darkGrains" />
          <feMergeNode in="lightGrains" />
        </feMerge>
        <feComposite in="grains" in2="SourceAlpha" operator="in" result="sandOnShell" />
        <feMerge>
          <feMergeNode in="shadow" />
          <feMergeNode in="SourceGraphic" />
          <feMergeNode in="sandOnShell" />
        </feMerge>
      </filter>
    </svg>
  );
}
