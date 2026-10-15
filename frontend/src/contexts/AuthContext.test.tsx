import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'

const me = vi.hoisted(() => ({ current: {} as Record<string, unknown> }))
vi.mock('../api/client', () => ({
  default: { get: vi.fn(() => Promise.resolve({ data: me.current })) },
}))

import { AuthProvider, useAuth } from './AuthContext'

function Probe() {
  const { role, canWrite, isAdmin, loading } = useAuth()
  if (loading) return null
  return <div data-testid="probe">{`${role}|${canWrite}|${isAdmin}`}</div>
}

async function probe(data: Record<string, unknown>) {
  me.current = data
  render(<AuthProvider><Probe /></AuthProvider>)
  return (await screen.findByTestId('probe')).textContent
}

describe('AuthContext roles', () => {
  afterEach(cleanup)

  it('maps a department member (local engineer) to a writer, not an admin', async () => {
    expect(await probe({ user_id: 1, plm2_roles: ['plm2_Viewer'], role: 'engineer' }))
      .toBe('engineer|true|false')
  })

  it('keeps a viewer without a department read-only', async () => {
    expect(await probe({ user_id: 2, plm2_roles: ['plm2_Viewer'], role: 'viewer' }))
      .toBe('viewer|false|false')
  })

  it('never lets a local role buy admin: only the plm2_Admin hub role does', async () => {
    expect(await probe({ user_id: 3, plm2_roles: ['plm2_Viewer'], role: 'admin' }))
      .toBe('viewer|false|false')
    cleanup()
    expect(await probe({ user_id: 4, plm2_roles: ['plm2_Admin'], role: 'admin' }))
      .toBe('admin|true|true')
  })
})
