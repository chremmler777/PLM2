import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import LopPanel from './LopPanel'
import { lopLine, lopProject, pdbResponse, pdbTopic } from './lop.fixtures'
import type { LopProjectResponse, PdbResponse } from '../../types/lop'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ userId: 5, actingAsUser: null }) }))

const team = [
  { department_id: 1, department_name: 'Project Manager', responsible: { id: 5, name: 'Paula PM' }, backup: null },
  { department_id: 10, department_name: 'Logistics', responsible: { id: 7, name: 'Lena Logistics' }, backup: null },
]

let project: LopProjectResponse
let pdb: PdbResponse

function mount() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <LopPanel projectId={2} />
    </QueryClientProvider>)
}

const row = async (id: number) => screen.findByTestId(`lop-row-${id}`)
const openEditor = async (id: number) => {
  fireEvent.click(within(await row(id)).getByRole('button', { name: /edit line/i }))
  return screen.findByTestId(`lop-editor-${id}`)
}

describe('LopPanel', () => {
  beforeEach(() => {
    project = lopProject()
    pdb = pdbResponse({ topics: [] })
    for (const m of Object.values(clientMocks)) m.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/lop/projects/2') return Promise.resolve({ data: project })
      if (url === '/v1/lop/projects/2/pdb') return Promise.resolve({ data: pdb })
      if (url === '/v1/projects/2/team') return Promise.resolve({ data: team })
      if (url === '/v1/lop/projects/2/sep-candidates') return Promise.resolve({ data: { gates: [] } })
      return Promise.resolve({ data: [] })
    })
    clientMocks.patch.mockResolvedValue({ data: lopLine() })
    clientMocks.post.mockResolvedValue({ data: {} })
    clientMocks.put.mockResolvedValue({ data: {} })
  })
  afterEach(cleanup)

  it('shows the struck-through first due date on a moved line', async () => {
    project = lopProject({ lines: [lopLine({
      group: 'overdue', moved: true, first_due_date: '2026-10-20', due_date: '2026-11-06', late: true, days_late: 5,
    })] })
    mount()
    const r = await row(1)
    const first = within(r).getByTestId('first-due')
    expect(first.textContent).toBe('Oct 20')
    expect(first.className).toContain('line-through')
    expect(r.textContent).toContain('Nov 6 · 5 d late')
    expect(screen.getByText(/Overdue \(1\)/)).toBeTruthy()
  })

  it('hides + Task, Add from SEP, Send minutes and Confirm for a non-PM', async () => {
    project = lopProject({
      can_manage: false,
      meeting: { id: 3, held_on: '2026-11-10', open: false },
      lines: [lopLine({ group: 'waiting_check', status: 'done_check', can_manage: false, responsible_id: 9 })],
    })
    mount()
    await row(1)
    expect(screen.queryByRole('button', { name: '+ Task' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Add from SEP' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Send minutes' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Start meeting' })).toBeNull()
    expect(screen.queryByRole('button', { name: /^Confirm line/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /to me$/ })).toBeNull()
    expect(screen.getByRole('button', { name: 'Excel' })).toBeTruthy()
  })

  it('lets the responsible set "Done, please check"', async () => {
    project = lopProject({
      can_manage: false,
      lines: [lopLine({ status: 'in_work', responsible_id: 5, can_manage: false, can_report: true })],
    })
    mount()
    fireEvent.click(within(await row(1)).getByRole('button', { name: 'Line 1: done, please check' }))
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/lop/lines/1', { status: 'done_check' }))
  })

  it('asks for a reason when the PM moves a due date', async () => {
    mount()
    const editor = await openEditor(1)
    fireEvent.change(within(editor).getByLabelText('Due date'), { target: { value: '2026-11-20' } })
    const save = within(editor).getByRole('button', { name: 'Save' })
    expect((save as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(within(editor).getByLabelText('Reason for moving the date'), { target: { value: 'Customer drawing late' } })
    expect((save as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(save)
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/lop/lines/1',
      { due_date: '2026-11-20', reason: 'Customer drawing late' }))
  })

  it('sets a next-check date without a reason', async () => {
    mount()
    const editor = await openEditor(1)
    fireEvent.change(within(editor).getByLabelText('Next check'), { target: { value: '2026-11-18' } })
    expect(within(editor).queryByLabelText('Reason for moving the date')).toBeNull()
    fireEvent.click(within(editor).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/lop/lines/1', { next_check_date: '2026-11-18' }))
  })

  it('assign to me fills the PM as responsible in one click', async () => {
    mount()
    fireEvent.click(within(await row(1)).getByRole('button', { name: 'Assign line 1 to me' }))
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/lop/lines/1', { responsible_id: 5 }))
  })

  it('marks default date and default name until the PM confirms them', async () => {
    project = lopProject({ lines: [lopLine({ responsible_is_default: true, due_is_default: true })] })
    mount()
    const r = await row(1)
    expect(within(r).getByTestId('default-name').textContent).toBe('default')
    expect(within(r).getByTestId('default-due').textContent).toBe('default')
    fireEvent.click(within(r).getByRole('button', { name: 'Confirm the responsible of line 1' }))
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/lop/lines/1', { responsible_id: 7 }))
  })

  it('pin dialog needs a date before it can be saved', async () => {
    pdb = pdbResponse({ topics: [pdbTopic()] })
    mount()
    const topicRow = await screen.findByTestId('lop-row-pdb-501')
    expect(topicRow.textContent).toContain('227701')
    expect(topicRow.textContent).toContain('41 d open')
    expect(topicRow.textContent).not.toMatch(/d late/)
    fireEvent.click(within(topicRow).getByRole('button', { name: 'Pin topic 227701 Warpage on clip towers after T1' }))
    const dialog = await screen.findByRole('dialog')
    const save = within(dialog).getByRole('button', { name: 'Pin topic' }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.change(within(dialog).getByLabelText('Due date'), { target: { value: '2026-11-20' } })
    expect(save.disabled).toBe(false)
    fireEvent.click(save)
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/lop/projects/2/pdb/501/pin',
      { due_date: '2026-11-20' }))
  })

  it('a pinned PDB topic shows its tool and cannot be closed here', async () => {
    const pin = pdbTopic({ id: 44, project_id: 2, pinned: true, group: 'other', responsible_id: 7,
      responsible_name: 'Lena Logistics', due_date: '2026-11-20', first_due_date: '2026-11-20' })
    project = lopProject({ lines: [pin] })
    pdb = pdbResponse({ topics: [pin] })
    mount()
    const r = await row(44)
    expect(within(r).getByTestId('pin-marker')).toBeTruthy()
    expect(r.textContent).toContain('227701')
    const editor = await openEditor(44)
    expect(within(editor).queryByRole('button', { name: 'Close line' })).toBeNull()
    expect(editor.textContent).toContain('closed in PDB')
  })

  it('shows a late pinned topic in Overdue when PDB cannot be reached', async () => {
    project = lopProject({ lines: [pdbTopic({
      id: 44, project_id: 2, pinned: true, group: 'overdue', late: true, days_late: 3, responsible_id: 7,
      responsible_name: 'Lena Logistics', due_date: '2026-11-08', first_due_date: '2026-11-08',
      text: 'Snapshot: tool leaks', tool_number: null, pdb_live: false,
    })] })
    pdb = pdbResponse({ available: false, reason: 'PDB answered 502', status: null, topics: [] })
    mount()
    const r = await row(44)
    expect(within(screen.getByTestId('lop-group-overdue')).getByTestId('lop-row-44')).toBe(r)
    expect(r.textContent).toContain('Snapshot: tool leaks')
    expect(r.textContent).toContain('3 d late')
    await waitFor(() => expect(screen.getByTestId('lop-pdb-group').textContent).toContain('PDB cannot be reached'))
  })

  it('merges live PDB text onto a pinned line and does not list it twice', async () => {
    const snap = pdbTopic({ id: 44, project_id: 2, pinned: true, group: 'other', responsible_id: 7,
      responsible_name: 'Lena Logistics', due_date: '2026-11-20', first_due_date: '2026-11-20',
      ref_key: '501', text: 'Old snapshot', tool_number: null, age_days: null, escalated: false,
      escalation_level: null, pdb_live: false })
    project = lopProject({ lines: [snap] })
    pdb = pdbResponse({ topics: [
      { ...snap, text: 'Live issue\nTo do: live todo', tool_number: '227701', age_days: 41, pdb_live: true },
      pdbTopic({ ref_key: '502', text: 'Another topic' }),
    ] })
    mount()
    await screen.findByTestId('lop-row-pdb-502')
    const r = await row(44)
    expect(r.textContent).toContain('Live issue')
    expect(r.textContent).toContain('227701')
    expect(r.textContent).not.toContain('Old snapshot')
    expect(screen.getAllByText(/Live issue/)).toHaveLength(1)
    expect(within(screen.getByTestId('lop-pdb-group')).queryByText(/Live issue/)).toBeNull()
    expect(screen.queryByTestId('lop-row-pdb-501')).toBeNull()
  })

  it('says PDB cannot be reached in the PDB group instead of an empty group', async () => {
    pdb = pdbResponse({ available: false, reason: 'PDB answered 502', status: null, topics: [] })
    mount()
    await waitFor(() => expect(screen.getByTestId('lop-pdb-group').textContent).toContain('PDB cannot be reached'))
    expect(screen.getByTestId('lop-pdb-group').textContent).toContain('PDB answered 502')
    expect(screen.queryByTestId('lop-row-pdb-501')).toBeNull()
  })

  it('shows "+ N more" and refetches all PDB topics on "show all"', async () => {
    pdb = pdbResponse({ topics: [pdbTopic()], hidden: 5 })
    mount()
    expect(await screen.findByText(/\+ 5 more/)).toBeTruthy()
    expect(within(screen.getByTestId('lop-pdb-group')).getByText(/PDB topics \(6\)/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /show all/i }))
    await waitFor(() => expect(clientMocks.get).toHaveBeenCalledWith('/v1/lop/projects/2/pdb', { params: { all: true } }))
  })

  it('runs the meeting: marks, escalate by hand, untouched counter, close', async () => {
    project = lopProject({
      meeting: { id: 3, held_on: '2026-11-11', open: true },
      lines: [
        lopLine({ id: 1, meeting_mark: 'updated', meeting: { id: 3, held_on: '2026-11-11', open: true } }),
        lopLine({ id: 2, meeting_mark: 'none', meeting: { id: 3, held_on: '2026-11-11', open: true } }),
      ],
    })
    const base = clientMocks.get.getMockImplementation()!
    clientMocks.get.mockImplementation((url: string, cfg?: unknown) => url === '/v1/lop/meetings/3'
      ? Promise.resolve({ data: { id: 3, held_on: '2026-11-11', open: true, project_id: 2, closed_at: null, minutes_sent_at: null,
        marks: [{ line_id: 1, mark: 'updated', was_late: false, was_stale: false },
          { line_id: 2, mark: 'none', was_late: false, was_stale: false },
          { line_id: 9, mark: 'none', was_late: false, was_stale: false }] } })
      : base(url, cfg))
    mount()
    expect(within(await row(1)).getByTestId('meeting-mark').textContent).toBe('updated')
    expect(within(await row(2)).getByTestId('meeting-mark').textContent).toBe('not touched')
    // the counter is the server's marks (line 9 is not in this view), not a count of the rows shown
    await waitFor(() => expect(screen.getByTestId('untouched-count').textContent).toContain('2 lines not touched yet'))
    fireEvent.click(within(await row(2)).getByRole('button', { name: 'Escalate line 2' }))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/lop/meetings/3/marks/2', { mark: 'escalated' }))
    fireEvent.click(screen.getByRole('button', { name: 'Close meeting' }))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/lop/meetings/3/close'))
  })

  it('marks a line as discussed during the meeting; moved and escalated lines keep their mark', async () => {
    const meeting = { id: 3, held_on: '2026-11-11', open: true }
    project = lopProject({
      meeting,
      lines: [
        lopLine({ id: 1, meeting_mark: 'none', meeting }),
        lopLine({ id: 2, meeting_mark: 'moved', meeting }),
        lopLine({ id: 4, meeting_mark: 'escalated', meeting }),
      ],
    })
    mount()
    fireEvent.click(within(await row(1)).getByRole('button', { name: 'Mark line 1 as discussed' }))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/lop/meetings/3/marks/1', { mark: 'updated' }))
    expect(within(await row(2)).getByTestId('meeting-mark').textContent).toBe('moved')
    expect(within(await row(2)).queryByRole('button', { name: 'Mark line 2 as discussed' })).toBeNull()
    expect(within(await row(4)).getByTestId('meeting-mark').textContent).toBe('escalated')
    expect(within(await row(4)).queryByRole('button', { name: 'Mark line 4 as discussed' })).toBeNull()
  })

  it('sends minutes only for a closed meeting, after confirmation', async () => {
    project = lopProject({ meeting: { id: 3, held_on: '2026-11-10', open: false } })
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/lop/projects/2') return Promise.resolve({ data: project })
      if (url === '/v1/lop/projects/2/pdb') return Promise.resolve({ data: pdb })
      if (url === '/v1/projects/2/team') return Promise.resolve({ data: team })
      if (url === '/v1/lop/meetings/3') return Promise.resolve({ data: {
        id: 3, held_on: '2026-11-10', open: false, project_id: 2, closed_at: '2026-11-10T15:00:00', minutes_sent_at: null, marks: [] } })
      return Promise.resolve({ data: [] })
    })
    mount()
    const send = await screen.findByRole('button', { name: 'Send minutes' })
    await waitFor(() => expect((send as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(send)
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog.textContent).toContain('Send the minutes to the project team?')
    expect(clientMocks.post).not.toHaveBeenCalled()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Send minutes' }))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/lop/meetings/3/minutes'))
  })

  it('adds SEP items only through the dialog, one item or a whole gate', async () => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/lop/projects/2') return Promise.resolve({ data: project })
      if (url === '/v1/lop/projects/2/pdb') return Promise.resolve({ data: pdb })
      if (url === '/v1/projects/2/team') return Promise.resolve({ data: team })
      if (url === '/v1/lop/projects/2/sep-candidates') return Promise.resolve({ data: { gates: [
        { gate_id: 11, code: 'K0/RG1', status: 'in_progress', target_date: null,
          items: [{ id: 101, item_no: 17, title: 'Gauge concept', department: 'Quality' }] },
      ] } })
      return Promise.resolve({ data: [] })
    })
    mount()
    fireEvent.click(await screen.findByRole('button', { name: 'Add from SEP' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('Gauge concept')).toBeTruthy()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/lop/projects/2/lines/from-sep', { item_id: 101 }))
    fireEvent.click(within(dialog).getByRole('button', { name: /Add all open items of this gate/ }))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/lop/projects/2/lines/from-sep',
      { gate_id: 11, only_open: true }))
  })

  it('shows the server reason inline when a change is refused', async () => {
    clientMocks.patch.mockRejectedValue({ response: { status: 403, data: { detail: 'Only the Project Manager changes a line' } } })
    mount()
    fireEvent.click(within(await row(1)).getByRole('button', { name: 'Assign line 1 to me' }))
    expect(await within(await row(1)).findByText('Only the Project Manager changes a line')).toBeTruthy()
  })

  it('setting a date on a line whose date was cleared asks for a reason', async () => {
    project = lopProject({ lines: [lopLine({ due_date: null, first_due_date: '2026-11-03', moved: true })] })
    mount()
    const editor = await openEditor(1)
    fireEvent.change(within(editor).getByLabelText('Due date'), { target: { value: '2026-11-25' } })
    const save = within(editor).getByRole('button', { name: 'Save' }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.change(within(editor).getByLabelText('Reason for moving the date'), { target: { value: 'New plan from customer' } })
    fireEvent.click(save)
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/lop/lines/1',
      { due_date: '2026-11-25', reason: 'New plan from customer' }))
  })

  it('sets the first due date without a reason', async () => {
    project = lopProject({ lines: [lopLine({ due_date: null, first_due_date: null })] })
    mount()
    const editor = await openEditor(1)
    fireEvent.change(within(editor).getByLabelText('Due date'), { target: { value: '2026-11-25' } })
    expect(within(editor).queryByLabelText('Reason for moving the date')).toBeNull()
    fireEvent.click(within(editor).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/lop/lines/1', { due_date: '2026-11-25' }))
  })

  it('Confirm date on a default due date sends the same date and no reason', async () => {
    project = lopProject({ lines: [lopLine({ due_is_default: true, due_date: '2026-12-04', first_due_date: '2026-12-04' })] })
    mount()
    const editor = await openEditor(1)
    expect(within(editor).getByTestId('default-due-editor').textContent).toBe('default')
    fireEvent.click(within(editor).getByRole('button', { name: 'Confirm date' }))
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/lop/lines/1', { due_date: '2026-12-04' }))
  })

  it('changing a default due date asks for no reason', async () => {
    project = lopProject({ lines: [lopLine({ due_is_default: true, due_date: '2026-12-04', first_due_date: '2026-12-04' })] })
    mount()
    const editor = await openEditor(1)
    fireEvent.change(within(editor).getByLabelText(/^Due date/), { target: { value: '2026-12-20' } })
    expect(within(editor).queryByLabelText('Reason for moving the date')).toBeNull()
    fireEvent.click(within(editor).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/lop/lines/1', { due_date: '2026-12-20' }))
  })

  it('refetches the project lines after a successful write', async () => {
    mount()
    await row(1)
    const projectCalls = () => clientMocks.get.mock.calls.filter(([u]) => u === '/v1/lop/projects/2').length
    const before = projectCalls()
    fireEvent.click(within(await row(1)).getByRole('button', { name: 'Assign line 1 to me' }))
    await waitFor(() => expect(projectCalls()).toBeGreaterThan(before))
  })

  it('a comment refreshes the lines but not the live PDB call', async () => {
    mount()
    const editor = await openEditor(1)
    await waitFor(() => expect(clientMocks.get).toHaveBeenCalledWith('/v1/lop/projects/2/pdb', undefined))
    const calls = (url: string) => clientMocks.get.mock.calls.filter(([u]) => u === url).length
    const pdbBefore = calls('/v1/lop/projects/2/pdb')
    const linesBefore = calls('/v1/lop/projects/2')
    fireEvent.change(within(editor).getByLabelText('Comment'), { target: { value: 'Drawing requested' } })
    fireEvent.click(within(editor).getByRole('button', { name: 'Add comment' }))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/lop/lines/1/comments', { text: 'Drawing requested' }))
    await waitFor(() => expect(calls('/v1/lop/projects/2')).toBeGreaterThan(linesBefore))
    expect(calls('/v1/lop/projects/2/pdb')).toBe(pdbBefore)
  })

  it('says the team could not be loaded next to the responsible picker', async () => {
    const base = clientMocks.get.getMockImplementation()!
    clientMocks.get.mockImplementation((url: string, cfg?: unknown) => url === '/v1/projects/2/team'
      ? Promise.reject({ response: { status: 500, data: { detail: 'Team service down' } } })
      : base(url, cfg))
    mount()
    const editor = await openEditor(1)
    expect(await within(editor).findByText(/The project team could not be loaded: Team service down/)).toBeTruthy()
  })

  it('says why the SEP items could not be loaded', async () => {
    const base = clientMocks.get.getMockImplementation()!
    clientMocks.get.mockImplementation((url: string, cfg?: unknown) => url === '/v1/lop/projects/2/sep-candidates'
      ? Promise.reject({ response: { status: 409, data: { detail: 'SEP is not active on this project' } } })
      : base(url, cfg))
    mount()
    fireEvent.click(await screen.findByRole('button', { name: 'Add from SEP' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText(/SEP is not active on this project/)).toBeTruthy()
  })

  it('shows "Minutes sent" with the date once the minutes went out', async () => {
    project = lopProject({ meeting: { id: 3, held_on: '2026-11-10', open: false } })
    const base = clientMocks.get.getMockImplementation()!
    clientMocks.get.mockImplementation((url: string, cfg?: unknown) => url === '/v1/lop/meetings/3'
      ? Promise.resolve({ data: { id: 3, held_on: '2026-11-10', open: false, project_id: 2, closed_at: '2026-11-10T15:00:00',
        minutes_sent_at: '2026-11-10T15:05:00', marks: [] } })
      : base(url, cfg))
    mount()
    expect(await screen.findByText('Minutes sent Nov 10')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Send minutes' })).toBeNull()
  })

  it('says "No unpinned PDB topics" when every open topic is pinned', async () => {
    const pin = pdbTopic({ id: 44, project_id: 2, pinned: true, group: 'other' })
    project = lopProject({ lines: [pin] })
    pdb = pdbResponse({ topics: [pin] })
    mount()
    await row(44)
    await waitFor(() => expect(screen.getByTestId('lop-pdb-group').textContent).toContain('No unpinned PDB topics'))
  })
})
