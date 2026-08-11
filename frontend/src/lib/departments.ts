/**
 * People sit in several departments at once — a Manufacturing Engineer who is
 * also in Development, say. Development is the master role: where the UI has to
 * pick one of a user's departments for them, it picks Development if they are in
 * it, and otherwise picks nothing. Guessing between equal peers would file work
 * under the wrong department silently, so the user is asked instead.
 */
export const MASTER_DEPARTMENT = 'Development'

export function preferredDepartmentId<T extends { id: number; name: string }>(
  membershipIds: number[],
  departments: T[],
): number | undefined {
  return departments.find(
    (d) => d.name === MASTER_DEPARTMENT && membershipIds.includes(d.id))?.id
}
