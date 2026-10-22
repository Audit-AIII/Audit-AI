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
    </svg>
  );
}
