import { describe, it, expect } from 'vitest'
import { preferredDepartmentId } from './departments'

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
