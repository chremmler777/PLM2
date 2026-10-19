import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ProjectTeamCard } from './ProjectTeamCard'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)

const TEAM = [
  { department_id: 6, department_name: 'Project Manager',
    responsible: { id: 3, name: 'Petra PM' }, backup: null,
    members: [{ id: 3, name: 'Petra PM', role: 'main' }, { id: 4, name: 'Paul Two', role: 'backup' }] },
  { department_id: 5, department_name: 'Sales', responsible: null, backup: null,
    members: [{ id: 7, name: 'Sam Sales', role: 'main' }, { id: 8, name: 'Sue Sales', role: 'main' }] },
  { department_id: 9, department_name: 'Development',
    responsible: { id: 11, name: 'Dana' }, backup: { id: 12, name: 'Ben' },
    members: [{ id: 11, name: 'Dana', role: 'main' }, { id: 12, name: 'Ben', role: 'backup', named_backup: true },
      { id: 13, name: 'Carl', role: 'backup' }] },
]

const mockGet = (canManage: boolean) => clientMocks.get.mockImplementation(async (url: string) =>
  url.includes('/permissions')
    ? { data: { can_start_change: true, can_manage_team: canManage } }
    : { data: TEAM })

describe('ProjectTeamCard', () => {
  beforeEach(() => {
    mockGet(true)
    clientMocks.put.mockResolvedValue({ data: [] })
  })
  afterEach(() => { cleanup(); vi.clearAllMocks() })

  it('lists roles with their responsible, unassigned shown for an unset role', async () => {
    wrap(<ProjectTeamCard projectId={2} />)
    await screen.findByText('Petra PM')
    expect(screen.getAllByText('Unassigned').length).toBeGreaterThan(0)
  })

  it('sets a responsible from that department\'s own members', async () => {
    wrap(<ProjectTeamCard projectId={2} />)
    await screen.findByTestId('team-edit-5')
    fireEvent.click(screen.getByTestId('team-edit-5'))
    const sel = screen.getByTestId('team-select-5') as HTMLSelectElement
    expect([...sel.options].map((o) => o.text)).toEqual(['Unassigned', 'Sam Sales', 'Sue Sales'])
    fireEvent.change(sel, { target: { value: '7' } })
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith(
      '/v1/projects/2/team', { department_id: 5, user_id: 7, slot: 'responsible' }))
  })

  it('clears a responsible', async () => {
    wrap(<ProjectTeamCard projectId={2} />)
    await screen.findByTestId('team-edit-6')
    fireEvent.click(screen.getByTestId('team-edit-6'))
    const sel = screen.getByTestId('team-select-6') as HTMLSelectElement
    fireEvent.change(sel, { target: { value: '' } })
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith(
      '/v1/projects/2/team', { department_id: 6, user_id: null, slot: 'responsible' }))
  })

  it('D2b: shows the named backup and sets one, never the responsible', async () => {
    wrap(<ProjectTeamCard projectId={2} />)
    expect((await screen.findByTestId('team-backup-9')).textContent).toContain('Ben')
    fireEvent.click(screen.getByTestId('team-backup-edit-9'))
    const sel = screen.getByTestId('team-backup-select-9') as HTMLSelectElement
    // the responsible is not offered as their own backup
    expect([...sel.options].map((o) => o.text)).toEqual(['Unassigned', 'Ben', 'Carl'])
    fireEvent.change(sel, { target: { value: '13' } })
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith(
      '/v1/projects/2/team', { department_id: 9, user_id: 13, slot: 'backup' }))
  })

  it('D2: the Project Manager row says the lead PM leads every change', async () => {
    wrap(<ProjectTeamCard projectId={2} />)
    expect((await screen.findByTestId('team-lead-pm-hint')).textContent).toContain('lead PM')
  })

  it('R24: someone who may not set the team sees no change buttons', async () => {
    mockGet(false)
    wrap(<ProjectTeamCard projectId={2} />)
    await screen.findByText('Petra PM')
    await waitFor(() => expect(clientMocks.get).toHaveBeenCalledWith('/v1/changes/permissions'))
    expect(screen.queryByTestId('team-edit-6')).toBeNull()
    expect(screen.queryByTestId('team-backup-edit-9')).toBeNull()
    expect(screen.getByTestId('team-backup-9').textContent).toContain('Ben')
  })
})
