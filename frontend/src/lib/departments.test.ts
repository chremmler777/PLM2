import { describe, it, expect } from 'vitest'
import { departmentLabel, pickableDepartments, preferredDepartmentId } from './departments'

const depts = [
  { id: 2, name: 'Quality' },
  { id: 5, name: 'Manufacturing Engineer' },
  { id: 6, name: 'Development' },
]

describe('preferredDepartmentId', () => {
  it('prefers Development when the user is in it', () => {
    expect(preferredDepartmentId([5, 6], depts)).toBe(6)
    // Order of the memberships must not decide it.
    expect(preferredDepartmentId([6, 5], depts)).toBe(6)
  })

  it('picks nothing when Development is not one of them', () => {
    // Between equal peers the user chooses — a guess would file the work wrong.
    expect(preferredDepartmentId([5, 2], depts)).toBeUndefined()
    expect(preferredDepartmentId([5], depts)).toBeUndefined()
  })

  it('has nothing to pick for a user in no listed department', () => {
    expect(preferredDepartmentId([], depts)).toBeUndefined()
    expect(preferredDepartmentId([99], depts)).toBeUndefined()
  })
})

describe('retired departments in pickers', () => {
  const all = [
    { id: 1, name: 'Quality', is_active: true },
    { id: 2, name: 'Old Lab', is_active: false },
    { id: 3, name: 'Old Shop', is_active: false },
  ]
  it('offers active ones plus a retired one the record already holds', () => {
    expect(pickableDepartments(all).map((d) => d.id)).toEqual([1])
    expect(pickableDepartments(all, [2, null]).map((d) => d.id)).toEqual([1, 2])
  })
  it('marks a retired one "(retired)"', () => {
    expect(departmentLabel(all[0])).toBe('Quality')
    expect(departmentLabel(all[1])).toBe('Old Lab (retired)')
  })
})
