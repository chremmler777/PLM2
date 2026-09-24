/** Cavities from the "n cavities" notes on a tool's produces relations, summed; null when no note names any. */
export function cavitiesFromNotes(notes: (string | null | undefined)[]): number | null {
  let total = 0;
  let found = false;
  for (const n of notes) {
    const m = /(\d+)\s*cavit/i.exec(n ?? '');
    if (m) { total += parseInt(m[1], 10); found = true; }
  }
  return found ? total : null;
}
