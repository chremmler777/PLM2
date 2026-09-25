/**
 * One date and money format for the change screens: dd.mm.yyyy, dd.mm.yyyy
 * hh:mm and "12.345,50 EUR" (de-DE grouping, 2 decimals, currency code).
 * Missing values render as "-".
 */

const pad = (x: number) => String(x).padStart(2, '0')

/** dd.mm.yyyy from an ISO date or datetime. A plain date is never shifted by the time zone. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '-'
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
    const [y, m, d] = iso.split('-')
    return `${d}.${m}.${y}`
  }
  const dt = new Date(iso)
  if (Number.isNaN(dt.getTime())) return iso
  return `${pad(dt.getDate())}.${pad(dt.getMonth() + 1)}.${dt.getFullYear()}`
}

/** dd.mm.yyyy hh:mm in local time. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '-'
  const dt = new Date(iso)
  if (Number.isNaN(dt.getTime())) return iso
  return `${formatDate(iso)} ${pad(dt.getHours())}:${pad(dt.getMinutes())}`
}

const moneyFmt = new Intl.NumberFormat('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** "12.345,50 EUR". */
export function formatMoney(amount: number | null | undefined, currency: string | null | undefined = 'EUR'): string {
  if (amount === null || amount === undefined || Number.isNaN(amount)) return '-'
  return `${moneyFmt.format(amount)} ${currency || 'EUR'}`
}
