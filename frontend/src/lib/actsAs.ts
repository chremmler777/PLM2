/**
 * Admin "act as department" switch.
 *
 * An admin can ask the backend to treat them as an engineer in one department:
 * every request then carries `X-Acts-As-Department`, and the server derives all
 * gates, my-actions and permissions from it. The choice lives in sessionStorage
 * so it is per-tab — an admin can keep one tab as themselves and drive another
 * through a department's eyes without the two interfering.
 */
export const ACTS_AS_KEY = 'plm2.actsAsDepartmentId'
export const ACTS_AS_HEADER = 'X-Acts-As-Department'

export function getActsAsDepartmentId(): number | null {
  try {
    const raw = sessionStorage.getItem(ACTS_AS_KEY)
    if (!raw) return null
    const id = Number(raw)
    return Number.isFinite(id) && id > 0 ? id : null
  } catch {
    // Private-mode / disabled storage: acting-as is simply unavailable.
    return null
  }
}

export function setActsAsDepartmentId(id: number | null): void {
  try {
    if (id == null) sessionStorage.removeItem(ACTS_AS_KEY)
    else sessionStorage.setItem(ACTS_AS_KEY, String(id))
  } catch {
    /* ignore — see above */
  }
}
