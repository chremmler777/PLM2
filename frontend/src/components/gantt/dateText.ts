/** Date text for inputs: dd.mm.yyyy out, dd.mm.yyyy / dd.mm.yy / ISO in. */
import { isIsoDay } from './engine/calendar'

/** "05.10.2026" from an ISO day ('' stays ''). */
export function formatDateInput(iso: string | null | undefined): string {
  if (!iso || !isIsoDay(iso)) return ''
  return `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`
}

/** ISO day from what a user typed: dd.mm.yyyy, dd.mm.yy, d.m.yyyy, yyyy-mm-dd; null when not a date. */
export function parseDateInput(text: string): string | null {
  const s = text.trim()
  if (!s) return null
  if (isIsoDay(s)) return s
  const m = /^(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})$/.exec(s)
  if (!m) return null
  const y = m[3].length === 2 ? 2000 + Number(m[3]) : Number(m[3])
  const iso = `${y}-${m[2].padStart(2, '0')}-${m[1].padStart(2, '0')}`
  return isIsoDay(iso) ? iso : null
}

