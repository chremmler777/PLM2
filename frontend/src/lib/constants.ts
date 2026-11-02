/**
 * Shared constants for the PLM application
 */

/** RASIC color mapping used in flowchart and workflow progress views */
/** The two letters the change flow shows (Christoph 2026-10-28: RASIC
 *  reduced to Responsible / Informed; old A reads R, S/C read I). Audit
 *  P3-11: My Tasks chips and the workflow rows still showed A, S, C. The
 *  workflow designer keeps the full set. */
export const shownLetter = (l: string): 'R' | 'I' => (l === 'R' || l === 'A' ? 'R' : 'I')
export const shownLetters = (ls: string[]): ('R' | 'I')[] =>
  [...new Set(ls.map(shownLetter))].sort((a, b) => (a === b ? 0 : a === 'R' ? -1 : 1))

export const rasicColors: Record<string, { bg: string; text: string }> = {
  R: { bg: 'bg-blue-900', text: 'text-blue-200' },
  A: { bg: 'bg-green-900', text: 'text-green-200' },
  S: { bg: 'bg-yellow-900', text: 'text-yellow-200' },
  I: { bg: 'bg-purple-900', text: 'text-purple-200' },
  C: { bg: 'bg-red-900', text: 'text-red-200' },
};

/** Status badge colors for workflow instances */
export const instanceStatusColors: Record<string, string> = {
  active: 'bg-blue-600 text-white',
  completed: 'bg-green-600 text-white',
  rejected: 'bg-red-600 text-white',
  canceled: 'bg-slate-600 text-white',
};
