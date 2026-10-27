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
  { department_id: 6, department_name: 'Project Manager', responsible: { id: 3, name: 'Petra PM' }, backup: null,
    members: [{ id: 3, name: 'Petra PM', email: 'petra@ktx.test' }] },
  { department_id: 9, department_name: 'Development',
    responsible: { id: 11, name: 'Dana' }, backup: { id: 12, name: 'Ben' },
    members: [
      { id: 11, name: 'Dana', email: 'dana@ktx.test' },
      { id: 12, name: 'Ben', email: 'ben@ktx.test' },
      { id: 13, name: 'Carl', email: 'carl@ktx.test' }] },
  { department_id: 5, department_name: 'Sales', responsible: null, backup: null,
    backup_missing: { id: 40, name: 'Roman' },
    members: [{ id: 7, name: 'Sam Sales', email: 'sam@ktx.test' }] },
  { department_id: 8, department_name: 'Tooling', responsible: null, backup: null, members: [] },
]

const mockGet = (canManage: boolean) => clientMocks.get.mockImplementation(async (url: string) =>
  url.includes('/permissions') ? { data: { can_start_change: true, can_manage_team: canManage } }
    : url.endsWith('/team') ? { data: TEAM } : { data: [] })

const wrap = (ui: React.ReactElement) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter>{ui}</MemoryRouter>
  </QueryClientProvider>)

const dt = (id: number) => {
  const data: Record<string, string> = {}
  return { setData: (k: string, v: string) => { data[k] = v }, getData: (k: string) => data[k] ?? String(id),
    effectAllowed: '', dropEffect: '' }
}

/** Drag the person out of a slot onto another target (a slot or the row's people list). */
function dragFromSlot(dept: number, slot: 'responsible' | 'backup', userId: number, target: HTMLElement) {
  const transfer = dt(userId)
  fireEvent.dragStart(screen.getByTestId(`team-slot-person-${slot}-${dept}`), { dataTransfer: transfer })
  fireEvent.dragOver(target, { dataTransfer: transfer })
  fireEvent.drop(target, { dataTransfer: transfer })
}

/** Drag a member card of one department onto a slot. */
function drag(fromDept: number, userId: number, slot: 'responsible' | 'backup', toDept: number) {
  const card = screen.getByTestId(`team-member-${fromDept}-${userId}`).closest('li')!
  const transfer = dt(userId)
  fireEvent.dragStart(card, { dataTransfer: transfer })
  const zone = screen.getByTestId(`team-slot-${slot}-${toDept}`)
  fireEvent.dragOver(zone, { dataTransfer: transfer })
  fireEvent.drop(zone, { dataTransfer: transfer })
}

describe('ProjectTeamDialog', () => {
  beforeEach(() => { mockGet(true); clientMocks.put.mockResolvedValue({ data: TEAM }) })
  afterEach(() => { cleanup(); vi.clearAllMocks() })

  it('shows the project responsible (PM) on top, people with name, mailto and a badge', async () => {
    wrap(<ProjectTeamDialog projectId={2} open onClose={vi.fn()} />)
    expect((await screen.findByTestId('team-project-responsible')).textContent).toContain('Project responsible (PM)')
    expect(screen.getByTestId('team-project-responsible').textContent).toContain('Petra PM')
    expect(screen.getByTestId('team-badge-9-11').dataset.kind).toBe('lead')
    // esc P3-7: the project responsible reads "Responsible", not "Lead" (the change lead).
    expect(screen.getByTestId('team-badge-9-11').textContent).toBe('Responsible')
    expect(screen.getByTestId('team-badge-9-12').dataset.kind).toBe('backup')
    expect(screen.getByTestId('team-badge-9-13').dataset.kind).toBe('member')
    expect(within(screen.getByTestId('team-member-9-13')).getByText('carl@ktx.test').getAttribute('href'))
      .toBe('mailto:carl@ktx.test')
  })

  it('red where the team is not defined: an empty Responsible of a staffed department only', async () => {
    wrap(<ProjectTeamDialog projectId={2} open onClose={vi.fn()} />)
    await screen.findByTestId('team-row-5')
    expect(screen.getByTestId('team-slot-responsible-5').dataset.missing).toBe('true')
    expect(screen.getByTestId('team-slot-backup-5').dataset.missing).toBeUndefined()   // backup empty: not red
    expect(screen.getByTestId('team-slot-responsible-8').dataset.missing).toBeUndefined() // no members
    expect(screen.getByTestId('team-slot-responsible-9').dataset.missing).toBeUndefined()
    // a slot pointing to someone who left says so
    expect(screen.getByTestId('team-missing-backup-5').textContent).toContain('Roman')
  })

  it('drag and drop edits a draft; nothing is stored until Save, then one batch', async () => {
    wrap(<ProjectTeamDialog projectId={2} open onClose={vi.fn()} />)
    await screen.findByTestId('team-row-9')
    drag(9, 13, 'backup', 9)
    expect(screen.getByTestId('team-slot-backup-9').textContent).toContain('Carl')
    expect(screen.getByTestId('team-badge-9-13').dataset.kind).toBe('backup')
    expect(clientMocks.put).not.toHaveBeenCalled()
    expect(screen.getByTestId('team-unsaved')).toBeTruthy()
    fireEvent.click(screen.getByTestId('team-save'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/projects/2/team/batch', {
      slots: [{ department_id: 9, responsible_id: 11, backup_id: 13 }] }))
  })

  it('head blue, manager yellow (as on the Departments page); the manager is no pick unless placed or alone', async () => {
    const team = [{ department_id: 21, department_name: 'Process Engineer', responsible: null, backup: null,
      head_id: 31, manager: { id: 30, name: 'Chris D', email: 'cd@ktx.test' },
      members: [{ id: 30, name: 'Chris D', email: 'cd@ktx.test' }, { id: 31, name: 'Holmes', email: 'h@ktx.test' },
        { id: 32, name: 'Nathan', email: 'n@ktx.test' }] },
      { department_id: 28, department_name: 'Development', responsible: null, backup: null,
        manager: { id: 30, name: 'Chris D' }, members: [{ id: 30, name: 'Chris D', email: 'cd@ktx.test' }] }]
    clientMocks.get.mockImplementation(async (url: string) =>
      url.includes('/permissions') ? { data: { can_start_change: true, can_manage_team: true } }
        : url.endsWith('/team') ? { data: team } : { data: [] })
    wrap(<ProjectTeamDialog projectId={2} open onClose={vi.fn()} />)
    const mgr = await screen.findByTestId('team-manager-21')
    expect(mgr.textContent).toContain('Chris D')
    expect(mgr.className).toContain('yellow')
    expect(screen.getByTestId('team-head-21-31').className).toContain('indigo')
    expect(screen.queryByTestId('team-member-21-30')).toBeNull()
    expect(screen.getByTestId('team-member-21-31')).toBeTruthy()
    // the only member of a department stays a pick even as its manager
    expect(screen.getByTestId('team-member-28-30')).toBeTruthy()
  })

  it('the dialog title names the project', async () => {
    wrap(<ProjectTeamDialog projectId={2} projectLabel="1994 Brose Seat Trim" open onClose={vi.fn()} />)
    expect(await screen.findByText('Project team: 1994 Brose Seat Trim')).toBeTruthy()
  })

  it('people already placed as Responsible or Backup are greyed out in the list and not draggable from it', async () => {
    wrap(<ProjectTeamDialog projectId={2} open onClose={vi.fn()} />)
    await screen.findByTestId('team-row-9')
    const li = (id: number) => screen.getByTestId(`team-member-9-${id}`).closest('li')!
    expect(li(11).dataset.placed).toBe('true')
    expect(li(11).className).toContain('opacity-40')
    expect(li(11).getAttribute('draggable')).toBe('false')
    expect(li(12).dataset.placed).toBe('true')
    expect(li(13).dataset.placed).toBeUndefined()
    expect(li(13).getAttribute('draggable')).toBe('true')
  })

  it('dragging a person out of a slot back onto the people list clears that slot (draft only)', async () => {
    wrap(<ProjectTeamDialog projectId={2} open onClose={vi.fn()} />)
    await screen.findByTestId('team-row-9')
    dragFromSlot(9, 'backup', 12, screen.getByTestId('team-people-9'))
    expect(screen.getByTestId('team-slot-backup-9').textContent).toContain('Unassigned')
    expect(screen.getByTestId('team-member-9-12').closest('li')!.dataset.placed).toBeUndefined()
    expect(clientMocks.put).not.toHaveBeenCalled()
    fireEvent.click(screen.getByTestId('team-save'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/projects/2/team/batch', {
      slots: [{ department_id: 9, responsible_id: 11, backup_id: null }] }))
  })

  it('a drop of a non-member is refused and says why', async () => {
    wrap(<ProjectTeamDialog projectId={2} open onClose={vi.fn()} />)
    await screen.findByTestId('team-row-5')
    drag(9, 13, 'responsible', 5)
    expect(screen.getByTestId('team-drop-error-responsible-5').textContent).toBe('Carl is not a member of Sales')
    expect((screen.getByTestId('team-pick-responsible-5') as HTMLSelectElement).value).toBe('')
    expect(screen.queryByTestId('team-unsaved')).toBeNull()
  })

  it('the backup dropped on Responsible swaps the two; the select is the keyboard fallback', async () => {
    wrap(<ProjectTeamDialog projectId={2} open onClose={vi.fn()} />)
    await screen.findByTestId('team-row-9')
    dragFromSlot(9, 'backup', 12, screen.getByTestId('team-slot-responsible-9'))
    expect(screen.getByTestId('team-slot-responsible-9').textContent).toContain('Ben')
    expect(screen.getByTestId('team-slot-backup-9').textContent).toContain('Dana')
    fireEvent.change(screen.getByTestId('team-pick-responsible-5'), { target: { value: '7' } })
    fireEvent.click(screen.getByTestId('team-save'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/projects/2/team/batch', {
      slots: [{ department_id: 9, responsible_id: 12, backup_id: 11 },
        { department_id: 5, responsible_id: 7, backup_id: null }] }))
  })

  it('Discard drops the draft; closing with unsaved changes asks first', async () => {
    const onClose = vi.fn()
    wrap(<ProjectTeamDialog projectId={2} open onClose={onClose} />)
    await screen.findByTestId('team-row-9')
    fireEvent.click(screen.getByTestId('team-clear-backup-9'))
    fireEvent.click(screen.getByTestId('team-discard'))
    expect(screen.getByTestId('team-slot-backup-9').textContent).toContain('Ben')
    fireEvent.click(screen.getByTestId('team-clear-backup-9'))
    fireEvent.click(screen.getAllByRole('button', { name: 'Close' })[0])
    expect(onClose).not.toHaveBeenCalled()
    const ask = await screen.findByTestId('team-discard-confirm')
    fireEvent.click(within(ask).getByRole('button', { name: 'Discard' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('read-only for someone who may not manage the team: no drag, no pickers, no Save', async () => {
    mockGet(false)
    wrap(<ProjectTeamDialog projectId={2} open onClose={vi.fn()} />)
    await screen.findByTestId('team-row-9')
    expect(screen.queryByTestId('team-pick-responsible-9')).toBeNull()
    expect(screen.queryByTestId('team-save')).toBeNull()
    expect(screen.getByTestId('team-member-9-11').closest('li')!.getAttribute('draggable')).toBe('false')
  })

  it('the header Team button carries a red count of open slots and opens the dialog; the ⋯ menu links it', async () => {
    const project = { id: 2, name: 'Seat Trim', code: '1994', status: 'active', customer_naming: 'vw' as const }
    wrap(<ProjectHeaderBar project={project} onStartChange={vi.fn()} onAddPart={vi.fn()} />)
    expect((await screen.findByTestId('project-team-gaps')).textContent).toBe('1')
    fireEvent.click(screen.getByTestId('project-team-button'))
    expect(await screen.findByTestId('project-team-dialog')).toBeTruthy()
    fireEvent.click(screen.getAllByRole('button', { name: 'Close' })[0])
    expect(screen.queryByTestId('project-team-dialog')).toBeNull()
    fireEvent.click(screen.getByLabelText('Project actions'))
    expect(screen.queryByTestId('project-team-card')).toBeNull()
    fireEvent.click(screen.getByTestId('menu-project-team'))
    expect(await screen.findByTestId('project-team-dialog')).toBeTruthy()
  })
})
