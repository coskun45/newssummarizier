const HEX_RE = /^#([0-9a-f]{6})$/i;

/** Appends an alpha channel to a clean 6-digit hex color (e.g. "#2563eb" + "1a" -> "#2563eb1a"). */
export function withAlpha(hex: string | null | undefined, alphaHex: string): string | null {
  if (!hex || !HEX_RE.test(hex)) return null;
  return `${hex}${alphaHex}`;
}
