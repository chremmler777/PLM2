/**
 * A person's mail address for a mailto link. Some accounts carry only the
 * bare username (jubei.hughes): those get the company domain. Idempotent: an
 * address that already has an "@" is returned as it is (trimmed), so it is
 * safe once the backend sends full addresses too (esc P3-7).
 */
export const MAIL_DEFAULT_DOMAIN = 'us.ktx.group'

export function mailAddress(email: string | null | undefined): string | null {
  const e = (email ?? '').trim()
  if (!e) return null
  return e.includes('@') ? e : `${e}@${MAIL_DEFAULT_DOMAIN}`
}
