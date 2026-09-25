/**
 * Hours (and trials) that were entered but have no rate in the cost sheet.
 * They are not counted, so every total that skips them is too low. Said per
 * department, in one sentence, and never priced with an invented rate.
 */
import type { Summation } from '../types/change'

type UnpricedLine = NonNullable<Summation['unpriced_lines']>[number]

export interface UnpricedDepartment {
  department_id: number
  name: string
  hours: number
  trials: number
  message: string
}

const qty = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 2 })

/** "No cost sheet rate for Project Manager: 13 h unpriced". */
export function unpricedMessage(name: string, hours: number, trials = 0, booked = false): string {
  const parts = [
    ...(hours > 0 ? [`${qty(hours)} h`] : []),
    ...(trials > 0 ? [`${qty(trials)} trial${trials === 1 ? '' : 's'}`] : []),
  ]
  const what = parts.length ? parts.join(' and ') : 'hours'
  return `No cost sheet rate for ${name}: ${what}${booked ? ' booked,' : ''} unpriced`
}

/** The costing's unpriced lines, one entry per department. */
export function unpricedByDepartment(
  lines: UnpricedLine[] | null | undefined,
  departmentName: (id: number) => string,
): UnpricedDepartment[] {
  const by = new Map<number, { hours: number; trials: number }>()
  for (const l of lines ?? []) {
    const cur = by.get(l.department_id) ?? { hours: 0, trials: 0 }
    const q = Number.isFinite(l.quantity) ? l.quantity : 0
    if (l.unit === 'trial') cur.trials += q
    else cur.hours += q
    by.set(l.department_id, cur)
  }
  return [...by.entries()].map(([id, v]) => {
    const name = departmentName(id)
    return { department_id: id, name, hours: v.hours, trials: v.trials,
      message: unpricedMessage(name, v.hours, v.trials) }
  })
}
