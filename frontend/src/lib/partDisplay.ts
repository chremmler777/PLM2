/** How part numbers sort and how part names read in project lists. */

// Part numbers carry a numeric position after the project or tool prefix:
// 1994-1, 1994-10 (project items) or 10-3450 (tooling, tool number second).
// Project-coded tools (199401, 199402) have no hyphen and sort by the whole number.
// Sort by that number so -10 lands after -9, then a bare tool before its
// articles, then plain text.
function positionNumber(partNumber: string): number {
  const segs = partNumber.split('-');
  const n = parseInt(segs.length > 1 ? segs[1] : segs[0], 10);
  return Number.isNaN(n) ? Number.MAX_SAFE_INTEGER : n;
}

export function comparePartNumbers(a: string, b: string): number {
  const na = positionNumber(a);
  const nb = positionNumber(b);
  if (na !== nb) return na - nb;
  const ha = a.includes('-') ? 1 : 0;
  const hb = b.includes('-') ? 1 : 0;
  if (ha !== hb) return ha - hb;
  return a.localeCompare(b, undefined, { numeric: true });
}

/** "1994 TOOL Handle" → "TOOL Handle": the row already shows the number, so
 *  a name that repeats the project code only adds noise. */
export function stripProjectCode(name: string, code: string | undefined | null): string {
  if (!code) return name;
  const escaped = code.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const stripped = name.replace(new RegExp(`^${escaped}(?=[\\s\\-_:·•])[\\s\\-_:·•]+`, 'i'), '');
  return stripped.length ? stripped : name;
}
