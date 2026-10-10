/** Cavity layout: "4", or "2+2" for a family tool. Kept as written, never summed. */
export const CAVITY_LAYOUT = /^[1-9]\d{0,2}(\+[1-9]\d{0,2})*$/;

/** "2 + 2" -> "2+2"; null when the text is no layout. */
export function normalizeCavityLayout(raw: string): string | null {
  const text = raw.replace(/\s+/g, '');
  return CAVITY_LAYOUT.test(text) ? text : null;
}

/**
 * Cavity layout from the "n cavities" notes on a tool's produces relations, one
 * number per produced article joined with "+" (2 and 2 -> "2+2"); null when no
 * note names any.
 */
export function cavitiesFromNotes(notes: (string | null | undefined)[]): string | null {
  const counts: string[] = [];
  for (const n of notes) {
    const m = /(\d+)\s*cavit/i.exec(n ?? '');
    if (m) counts.push(String(parseInt(m[1], 10)));
  }
  return counts.length ? counts.join('+') : null;
}
