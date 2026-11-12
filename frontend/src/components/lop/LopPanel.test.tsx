import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import LopPanel from './LopPanel'
import { lopLine, lopProject, pdbResponse, pdbTopic } from './lopFixtures'
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
    expect(screen.queryByRole('button', { name: 'Confirm' })).toBeNull()
    expect(screen.queryByRole('button', { name: /assign to me/i })).toBeNull()
    expect(screen.getByRole('button', { name: 'Excel' })).toBeTruthy()
  })

  it('lets the responsible set "Done, please check"', async () => {
    project = lopProject({
      can_manage: false,
      lines: [lopLine({ status: 'in_work', responsible_id: 5, can_manage: false, can_report: true })],
    })
    mount()
    fireEvent.click(within(await row(1)).getByRole('button', { name: 'Done, please check' }))
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
    fireEvent.click(within(await row(1)).getByRole('button', { name: 'Assign to me' }))
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/lop/lines/1', { responsible_id: 5 }))
  })

  it('marks default date and default name until the PM confirms them', async () => {
    project = lopProject({ lines: [lopLine({ responsible_is_default: true, due_is_default: true })] })
    mount()
    const r = await row(1)
    expect(within(r).getByTestId('default-name').textContent).toBe('default')
    expect(within(r).getByTestId('default-due').textContent).toBe('default')
    fireEvent.click(within(r).getByRole('button', { name: 'Confirm name' }))
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/lop/lines/1', { responsible_id: 7 }))
  })

  it('pin dialog needs a date before it can be saved', async () => {
    pdb = pdbResponse({ topics: [pdbTopic()] })
    mount()
    const topicRow = await screen.findByTestId('lop-row-pdb-501')
    expect(topicRow.textContent).toContain('227701')
    expect(topicRow.textContent).toContain('41 d open')
    expect(topicRow.textContent).not.toMatch(/d late/)
    fireEvent.click(within(topicRow).getByRole('button', { name: 'Pin' }))
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
    pdb = pdbResponse({ topics: [pdbTopic({ id: 44, project_id: 2, pinned: true, group: 'other', responsible_id: 7,
      responsible_name: 'Lena Logistics', due_date: '2026-11-20', first_due_date: '2026-11-20' })] })
    mount()
    const r = await row(44)
    expect(within(r).getByTestId('pin-marker')).toBeTruthy()
    expect(r.textContent).toContain('227701')
    const editor = await openEditor(44)
    expect(within(editor).queryByRole('button', { name: 'Close line' })).toBeNull()
    expect(editor.textContent).toContain('closed in PDB')
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
    mount()
    expect(within(await row(1)).getByTestId('meeting-mark').textContent).toBe('updated')
    expect(within(await row(2)).getByTestId('meeting-mark').textContent).toBe('not touched')
    expect(screen.getByTestId('untouched-count').textContent).toContain('1 line not touched yet')
    fireEvent.click(within(await row(2)).getByRole('button', { name: 'Escalate' }))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/lop/meetings/3/marks/2', { mark: 'escalated' }))
    fireEvent.click(screen.getByRole('button', { name: 'Close meeting' }))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/lop/meetings/3/close'))
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
    fireEvent.click(within(await row(1)).getByRole('button', { name: 'Assign to me' }))
    expect(await within(await row(1)).findByText('Only the Project Manager changes a line')).toBeTruthy()
  })
})
