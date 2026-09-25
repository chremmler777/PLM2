/**
 * People sit in several departments at once — a Manufacturing Engineer who is
 * also in Development, say. Development is the master role: where the UI has to
 * pick one of a user's departments for them, it picks Development if they are in
 * it, and otherwise picks nothing. Guessing between equal peers would file work
 * under the wrong department silently, so the user is asked instead.
 */
export const MASTER_DEPARTMENT = 'Development'

/**
 * Tooling owns the part's weight: during costing they are the ones who can say
 * what it will come out at, so the weight estimate stands in their block and
 * nobody else's.
 */
export const TOOL_ENGINEER_DEPARTMENT = 'Tool Engineer'

export function preferredDepartmentId<T extends { id: number; name: string }>(
  membershipIds: number[],
  departments: T[],
): number | undefined {
  return departments.find(
    (d) => d.name === MASTER_DEPARTMENT && membershipIds.includes(d.id))?.id
}

/**
 * A department as a picker option reads it: a retired one (is_active false)
 * carries "(retired)" so an existing value on an old record still shows
 * what it is without inviting new work onto it.
 */
export function departmentLabel(d: { name: string; is_active?: boolean | null }): string {
  return d.is_active === false ? `${d.name} (retired)` : d.name
}

/**
 * The departments a picker offers: the active ones, plus any retired one a
 * record already holds (keepIds), so the current value stays selectable and
 * named instead of silently blanking the select.
 */
export function pickableDepartments<T extends { id: number; is_active?: boolean | null }>(
  all: T[],
  keepIds: (number | null | undefined)[] = [],
): T[] {
  const keep = new Set(keepIds.filter((x): x is number => x != null))
  return all.filter((d) => d.is_active !== false || keep.has(d.id))
}
