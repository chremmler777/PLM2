/**
 * Hours (and trials) that were entered but have no rate in the cost sheet.
 * They are not counted, so every total that skips them is too low. Said per
 * department, in one sentence, and never priced with an invented rate.
 */
import type { Summation } from '../types/change'
import { formatNumber } from './format'

type UnpricedLine = NonNullable<Summation['unpriced_lines']>[number]

export interface UnpricedDepartment {
  department_id: number
  /** A machine_time / sampling group: what is missing ("machine rate for
   * class 200-450 t at USA Toccoa"), not the department's rate. */
  subject: string | null
  name: string
  hours: number
  trials: number
  message: string
}

const qty = (n: number) => formatNumber(n)

/** "No cost sheet rate for Project Manager: 13 h unpriced". */
export function unpricedMessage(name: string, hours: number, trials = 0, booked = false): string {
  return `No cost sheet rate for ${name}: ${amounts(hours, trials)}${booked ? ' booked,' : ''} unpriced`
}

/** "No machine rate for class 200-450 t at USA Toccoa: 12 h unpriced". */
export function unpricedSubjectMessage(subject: string, hours: number, trials = 0): string {
  return `No ${subject}: ${amounts(hours, trials)} unpriced`
}

/** "12 h and 2 trials"; "hours" when nothing is counted. */
function amounts(hours: number, trials: number): string {
  const parts = [
    ...(hours > 0 ? [`${qty(hours)} h`] : []),
    ...(trials > 0 ? [`${qty(trials)} trial${trials === 1 ? '' : 's'}`] : []),
  ]
  return parts.length ? parts.join(' and ') : 'hours'
}

/** The costing's unpriced lines, one entry per department. */
export function unpricedByDepartment(
  lines: UnpricedLine[] | null | undefined,
  departmentName: (id: number) => string,
): UnpricedDepartment[] {
  // a labour line groups by its department; a machine_time / sampling line
  // by what is missing (its class's rate at the plant)
  const by = new Map<string, { id: number; subject: string | null; hours: number; trials: number }>()
  for (const l of lines ?? []) {
    const subject = l.subject ?? null
    const key = subject ? `s:${subject}` : `d:${l.department_id}`
    const cur = by.get(key) ?? { id: l.department_id, subject, hours: 0, trials: 0 }
    const q = Number.isFinite(l.quantity) ? l.quantity : 0
    if (l.unit === 'trial') cur.trials += q
    else cur.hours += q
    by.set(key, cur)
  }
  return [...by.values()].map((v) => {
    const name = departmentName(v.id)
    return { department_id: v.id, subject: v.subject, name, hours: v.hours, trials: v.trials,
      message: v.subject ? unpricedSubjectMessage(v.subject, v.hours, v.trials)
        : unpricedMessage(name, v.hours, v.trials) }
  })
}
