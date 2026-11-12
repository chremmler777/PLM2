/** The project team as a flat list of people who can be named responsible. */
import type { TeamRow } from '../../api/lop'

export interface TeamPerson { id: number; name: string; department: string }

/** Everyone named on the project team (responsible or backup), once each. */
export function teamPeople(team: TeamRow[] | undefined): TeamPerson[] {
  const seen = new Map<number, TeamPerson>()
  for (const row of team ?? []) {
    for (const p of [row.responsible, row.backup]) {
      if (p && !seen.has(p.id)) seen.set(p.id, { id: p.id, name: p.name, department: row.department_name })
    }
  }
  return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name))
}
