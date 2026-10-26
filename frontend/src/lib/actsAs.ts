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
    else {
      sessionStorage.setItem(ACTS_AS_KEY, String(id))
      sessionStorage.removeItem('plm2.actsAsUserId')
    }
  } catch {
    /* ignore — see above */
  }
}

/**
 * Act as a PERSON (Christoph 2026-10-26): the admin sees PLM exactly as that
 * person (their departments, manager role, My Tasks, team slots; never
 * admin), every request carrying `X-Acts-As-User`; writes are audited as
 * the admin acting as them. Per tab, like the department switch; the two
 * exclude each other.
 */
export const ACTS_AS_USER_KEY = 'plm2.actsAsUserId'
export const ACTS_AS_USER_HEADER = 'X-Acts-As-User'

export function getActsAsUserId(): number | null {
  try {
    const raw = sessionStorage.getItem(ACTS_AS_USER_KEY)
    if (!raw) return null
    const id = Number(raw)
    return Number.isFinite(id) && id > 0 ? id : null
  } catch {
    return null
  }
}

export function setActsAsUserId(id: number | null): void {
  try {
    if (id == null) sessionStorage.removeItem(ACTS_AS_USER_KEY)
    else {
      sessionStorage.setItem(ACTS_AS_USER_KEY, String(id))
      sessionStorage.removeItem(ACTS_AS_KEY)
    }
  } catch {
    /* ignore */
  }
}
