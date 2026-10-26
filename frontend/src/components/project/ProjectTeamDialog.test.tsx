import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import ProjectTeamDialog from './ProjectTeamDialog'
import ProjectHeaderBar from './ProjectHeaderBar'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), patch: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../MilestoneStrip', () => ({ default: () => <div>milestones</div> }))

const TEAM = [
  { department_id: 9, department_name: 'Development',
    responsible: { id: 11, name: 'Dana' }, backup: { id: 12, name: 'Ben' },
    members: [
      { id: 13, name: 'Carl', email: 'carl@ktx.test', role: 'backup' },
      { id: 12, name: 'Ben', email: 'ben@ktx.test', role: 'backup', named_backup: true },
      { id: 11, name: 'Dana', email: 'dana@ktx.test', role: 'main' }] },
  { department_id: 5, department_name: 'Sales', responsible: null, backup: null, members: [] },
]

const mockGet = (canManage: boolean) => clientMocks.get.mockImplementation(async (url: string) =>
  url.includes('/permissions') ? { data: { can_start_change: true, can_manage_team: canManage } }
    : url.endsWith('/team') ? { data: TEAM } : { data: [] })

const wrap = (ui: React.ReactElement) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter>{ui}</MemoryRouter>
  </QueryClientProvider>)

describe('ProjectTeamDialog', () => {
  beforeEach(() => { mockGet(true); clientMocks.put.mockResolvedValue({ data: [] }) })
  afterEach(() => { cleanup(); vi.clearAllMocks() })

  it('per department: lead and backup, and every member with name, mailto email and a badge', async () => {
    wrap(<ProjectTeamDialog projectId={2} open onClose={vi.fn()} />)
    const dev = await screen.findByTestId('team-row-9')
    expect(within(dev).getByTestId('team-responsible-9').textContent).toContain('Dana')
    expect(within(dev).getByTestId('team-backup-9').textContent).toContain('Ben')
    const members = within(dev).getAllByTestId(/^team-member-9-/)
    // lead first, then the backup, then the rest
    expect(members.map((m) => m.dataset.testid)).toEqual(['team-member-9-11', 'team-member-9-12', 'team-member-9-13'])
    expect(screen.getByTestId('team-badge-9-11').dataset.kind).toBe('lead')
    expect(screen.getByTestId('team-badge-9-12').dataset.kind).toBe('backup')
    expect(screen.getByTestId('team-badge-9-13').dataset.kind).toBe('member')
    expect(within(members[2]).getByText('carl@ktx.test').getAttribute('href')).toBe('mailto:carl@ktx.test')
    expect(within(screen.getByTestId('team-row-5')).getByText('No members in this department')).toBeTruthy()
  })

  it('the lead stays changeable with the same rules (the backup is not offered as their own backup)', async () => {
    wrap(<ProjectTeamDialog projectId={2} open onClose={vi.fn()} />)
    fireEvent.click(await screen.findByTestId('team-backup-edit-9'))
    const sel = screen.getByTestId('team-backup-select-9') as HTMLSelectElement
    expect([...sel.options].map((o) => o.text)).not.toContain('Dana')
    fireEvent.change(sel, { target: { value: '13' } })
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith(
      '/v1/projects/2/team', { department_id: 9, user_id: 13, slot: 'backup' }))
  })

  it('no change buttons for someone who may not manage the team', async () => {
    mockGet(false)
    wrap(<ProjectTeamDialog projectId={2} open onClose={vi.fn()} />)
    await screen.findByTestId('team-row-9')
    expect(screen.queryByTestId('team-edit-9')).toBeNull()
  })

  it('opens from the header Team button and from the ⋯ menu', async () => {
    const project = { id: 2, name: 'Seat Trim', code: '1994', status: 'active', customer_naming: 'vw' as const }
    wrap(<ProjectHeaderBar project={project} onStartChange={vi.fn()} onAddPart={vi.fn()} />)
    expect(screen.queryByTestId('project-team-dialog')).toBeNull()
    fireEvent.click(screen.getByTestId('project-team-button'))
    expect(await screen.findByTestId('project-team-dialog')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByTestId('project-team-dialog')).toBeNull()
    fireEvent.click(screen.getByLabelText('Project actions'))
    expect(screen.queryByTestId('project-team-card')).toBeNull()   // no cramped card in the menu
    fireEvent.click(screen.getByTestId('menu-project-team'))
    expect(await screen.findByTestId('project-team-dialog')).toBeTruthy()
  })
})
