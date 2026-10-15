import type { NextStepItem } from '../types/change'

/** HARD #4/#9: is this side's sign-off owed (missing, or given on an older
 * offer than the latest sent)? The backend's next_step says so. */
export const signoffOwed = (change: { next_step?: { items: NextStepItem[] } | null }, side: 'pm' | 'quality'): boolean =>
  !!change.next_step?.items.some((i) => i.key === `${side}_signoff`
    || (i.key === 'release_signoffs' && !!i.sides?.includes(side)))
