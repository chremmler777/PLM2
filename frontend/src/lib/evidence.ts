/**
 * Evidence words, the one rule of the backend (cm_rules.reference_refusal):
 * a reference names something (a number, a date or a few words, at least 5
 * characters); "ok", "tbd", "n/a" and the like say nothing. Every form that
 * asks for a reference uses this, so no button is enabled the backend
 * refuses (R24).
 */
export const EMPTY_EVIDENCE = new Set(['ok', 'okay', 'tbd', 'na', 'n/a', 'done', 'checked', 'yes', '-', '--'])

export function refOk(v: string | null | undefined): boolean {
  const s = (v ?? '').trim()
  if (s.length < 5 || EMPTY_EVIDENCE.has(s.toLowerCase())) return false
  const words = s.match(/[A-Za-z0-9ÄÖÜäöüß]+/g) ?? []
  const empty = words.every((w) => EMPTY_EVIDENCE.has(w.toLowerCase()) || w.length <= 2)
  const named = /\d/.test(s) || words.length >= 2
  return !empty && named
}
