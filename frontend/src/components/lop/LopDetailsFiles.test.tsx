import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import LopPanel from './LopPanel'
import { lopLine, lopProject, pdbResponse } from './lop.fixtures'
import type { LopFile, LopProjectResponse } from '../../types/lop'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '/api' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ userId: 5, actingAsUser: null }) }))

const team = [
  { department_id: 1, department_name: 'Project Manager', responsible: { id: 5, name: 'Paula PM' }, backup: null },
  { department_id: 10, department_name: 'Logistics', responsible: { id: 7, name: 'Lena Logistics' }, backup: null },
]
const file = (over: Partial<LopFile> = {}): LopFile => ({
  id: 11, line_id: 1, filename: 'plan.xlsx', content_type: 'application/vnd.ms-excel', size_bytes: 2048,
  uploaded_by: 5, uploaded_by_name: 'Paula PM', uploaded_at: '2026-11-16T09:00:00', can_delete: true, ...over,
})

let project: LopProjectResponse
let files: LopFile[]

function mount() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <LopPanel projectId={2} />
    </QueryClientProvider>)
}
const openEditor = async (id: number) => {
  fireEvent.click(within(await screen.findByTestId(`lop-row-${id}`)).getByRole('button', { name: /(edit|open) line/i }))
  return screen.findByTestId(`lop-editor-${id}`)
}
const openNewTask = async () => {
  fireEvent.click(await screen.findByRole('button', { name: '+ Task' }))
  return screen.findByTestId('lop-new-task')
}
const drop = (el: HTMLElement, dropped: File[]) => fireEvent.drop(el, { dataTransfer: { files: dropped } })

describe('LOP details and files', () => {
  beforeEach(() => {
    project = lopProject()
    files = []
    for (const m of Object.values(clientMocks)) m.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/lop/projects/2') return Promise.resolve({ data: project })
      if (url === '/v1/lop/projects/2/pdb') return Promise.resolve({ data: pdbResponse({ topics: [] }) })
      if (url === '/v1/projects/2/team') return Promise.resolve({ data: team })
      if (url === '/v1/lop/lines/1/files') return Promise.resolve({ data: files })
      return Promise.resolve({ data: [] })
    })
    clientMocks.patch.mockResolvedValue({ data: lopLine() })
    clientMocks.post.mockResolvedValue({ data: lopLine({ id: 9 }) })
    clientMocks.delete.mockResolvedValue({ data: null })
  })
  afterEach(cleanup)

  it('sends title and details of a new task', async () => {
    mount()
    const form = await openNewTask()
    fireEvent.change(within(form).getByLabelText('Task'), { target: { value: 'Warm measurement' } })
    fireEvent.change(within(form).getByLabelText(/details/i), { target: { value: 'Goal: predict\n1. Method' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Add task' }))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/lop/projects/2/lines',
      { title: 'Warm measurement', details: 'Goal: predict\n1. Method' }))
  })

  it('says why a task line over 500 characters cannot be added, before sending', async () => {
    mount()
    const form = await openNewTask()
    fireEvent.change(within(form).getByLabelText('Task'), { target: { value: 'x'.repeat(520) } })
    expect(within(form).getByRole('alert').textContent).toMatch(/520 of 500 characters.*Details/)
    expect((within(form).getByRole('button', { name: 'Add task' }) as HTMLButtonElement).disabled).toBe(true)
    expect(clientMocks.post).not.toHaveBeenCalled()
  })

  it('attaches the files dropped onto the new-task form to the new task', async () => {
    mount()
    const form = await openNewTask()
    fireEvent.change(within(form).getByLabelText('Task'), { target: { value: 'With a drawing' } })
    const drawing = new File(['pdf'], 'drawing.pdf', { type: 'application/pdf' })
    drop(within(form).getByTestId('lop-new-task-drop'), [drawing])
    expect(within(form).getByLabelText('Files to attach').textContent).toContain('drawing.pdf')
    fireEvent.click(within(form).getByRole('button', { name: 'Add task' }))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledTimes(2))
    const [url, body] = clientMocks.post.mock.calls[1]
    expect(url).toBe('/v1/lop/lines/9/files')
    expect((body as FormData).getAll('files')).toEqual([drawing])
  })

  it('keeps the form open and says so when the task was added but the files were not', async () => {
    clientMocks.post.mockImplementation((url: string) => url.endsWith('/files')
      ? Promise.reject({ response: { status: 413, data: { detail: 'File big.zip is too large (max 100 MB)' } } })
      : Promise.resolve({ data: lopLine({ id: 9 }) }))
    mount()
    const form = await openNewTask()
    fireEvent.change(within(form).getByLabelText('Task'), { target: { value: 'Big one' } })
    drop(within(form).getByTestId('lop-new-task-drop'), [new File(['x'], 'big.zip')])
    fireEvent.click(within(form).getByRole('button', { name: 'Add task' }))
    const alert = await within(form).findByRole('alert')
    expect(alert.textContent).toMatch(/task was added.*big\.zip is too large/)
    expect((within(form).getByRole('button', { name: 'Add task' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('shows details and the file count on the row', async () => {
    project = lopProject({ lines: [lopLine({ details: 'Goal: predict the final size', file_count: 2 })] })
    mount()
    const row = await screen.findByTestId('lop-row-1')
    expect(within(row).getByTestId('lop-row-details').textContent).toBe('Goal: predict the final size')
    expect(within(row).getByTestId('lop-row-files').textContent).toBe('2')
  })

  it('lets the PM change the details in the editor', async () => {
    project = lopProject({ lines: [lopLine({ details: 'old' })] })
    mount()
    const editor = await openEditor(1)
    fireEvent.change(within(editor).getByLabelText('Details'), { target: { value: 'new text' } })
    fireEvent.click(within(editor).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/lop/lines/1', { details: 'new text' }))
  })

  it('lists files as download links, uploads a drop and removes after asking once', async () => {
    files = [file()]
    mount()
    const editor = await openEditor(1)
    const link = await within(editor).findByRole('link', { name: 'plan.xlsx' })
    expect(link.getAttribute('href')).toBe('/api/v1/lop/lines/1/files/11/download')
    const photo = new File(['png'], 'photo.png', { type: 'image/png' })
    drop(within(editor).getByTestId('lop-files-drop-1'), [photo])
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalled())
    expect(clientMocks.post.mock.calls[0][0]).toBe('/v1/lop/lines/1/files')
    fireEvent.click(within(editor).getByRole('button', { name: 'Remove plan.xlsx' }))
    expect(clientMocks.delete).not.toHaveBeenCalled()
    fireEvent.click(within(editor).getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(clientMocks.delete).toHaveBeenCalledWith('/v1/lop/lines/1/files/11'))
  })

  it('a team member who is not the PM reads the details, can attach, cannot remove others\' files', async () => {
    files = [file({ can_delete: false })]
    project = lopProject({ can_manage: false, lines: [lopLine({ can_manage: false, details: 'Read me', responsible_id: 7 })] })
    mount()
    const editor = await openEditor(1)
    expect(within(editor).getByTestId('lop-details-1').textContent).toContain('Read me')
    await within(editor).findByRole('link', { name: 'plan.xlsx' })
    expect(within(editor).queryByLabelText('Details')).toBeNull()
    expect(within(editor).getByTestId('lop-files-drop-1')).toBeTruthy()
    expect(within(editor).queryByRole('button', { name: /remove/i })).toBeNull()
  })

  it('a drop without a file says what to do', async () => {
    mount()
    const editor = await openEditor(1)
    drop(within(editor).getByTestId('lop-files-drop-1'), [])
    expect((await within(editor).findByRole('alert')).textContent).toMatch(/Save it to disk first/)
    expect(clientMocks.post).not.toHaveBeenCalled()
  })
})
