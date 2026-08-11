/** "1864 · VW426 Atlas" — number first, the way people say it. */
export function projectLabel(
  number?: string | null, name?: string | null,
): string | null {
  const parts = [number, name].filter(Boolean)
  return parts.length > 0 ? parts.join(' · ') : null
}
