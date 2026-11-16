import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import LopPanel from './LopPanel'
import { lopLine, lopProject, pdbResponse } from './lop.fixtures'
import type { LopProjectResponse } from '../../types/lop'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ userId: 5, actingAsUser: null }) }))

const team = [
  { department_id: 1, department_name: 'Project Manager', responsible: { id: 5, name: 'Paula PM' }, backup: null },
  { department_id: 10, department_name: 'Logistics', responsible: { id: 7, name: 'Lena Logistics' }, backup: null },
  { department_id: 11, department_name: 'APQP', responsible: { id: 8, name: 'George APQP' }, backup: null },
]
let project: LopProjectResponse

function mount() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <LopPanel projectId={2} />
    </QueryClientProvider>)
}
const openEditor = async (id: number) => {
  fireEvent.click(within(await screen.findByTestId(`lop-row-${id}`)).getByRole('button', { name: /edit line/i }))
  return screen.findByTestId(`lop-editor-${id}`)
}
const add = (scope: HTMLElement, id: number) =>
  fireEvent.change(within(scope).getByLabelText('Add an additional owner'), { target: { value: String(id) } })

describe('LOP additional owners', () => {
  beforeEach(() => {
    project = lopProject()
    for (const m of Object.values(clientMocks)) m.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/lop/projects/2') return Promise.resolve({ data: project })
      if (url === '/v1/lop/projects/2/pdb') return Promise.resolve({ data: pdbResponse({ topics: [] }) })
      if (url === '/v1/projects/2/team') return Promise.resolve({ data: team })
      return Promise.resolve({ data: [] })
    })
    clientMocks.patch.mockResolvedValue({ data: lopLine() })
    clientMocks.post.mockResolvedValue({ data: lopLine({ id: 9 }) })
  })
  afterEach(cleanup)

  it('a new task goes out with its main owner and the additional owners picked', async () => {
    mount()
    fireEvent.click(await screen.findByRole('button', { name: '+ Task' }))
    const form = await screen.findByTestId('lop-new-task')
    fireEvent.change(within(form).getByLabelText('Task'), { target: { value: 'Warm measurement' } })
    fireEvent.change(within(form).getByLabelText('Responsible'), { target: { value: '8' } })
    add(form, 7)
    // the main owner is not offered as an additional owner
    expect(within(within(form).getByLabelText('Add an additional owner')).queryByText(/George APQP/)).toBeNull()
    add(form, 5)
    fireEvent.click(within(form).getByRole('button', { name: 'Remove Paula PM as additional owner' }))
    fireEvent.click(within(form).getByRole('button', { name: 'Add task' }))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/lop/projects/2/lines',
      { title: 'Warm measurement', responsible_id: 8, additional_owner_ids: [7] }))
  })

  it('shows the additional owners under the responsible in the list', async () => {
    project = lopProject({ lines: [lopLine({ additional_owners: [{ id: 8, name: 'George APQP' }, { id: 5, name: 'Paula PM' }] })] })
    mount()
    const row = await screen.findByTestId('lop-row-1')
    expect(within(row).getByTestId('lop-row-owners').textContent).toBe('+ George APQP, Paula PM')
  })

  it('the PM adds and removes additional owners in the editor', async () => {
    project = lopProject({ lines: [lopLine({ additional_owners: [{ id: 8, name: 'George APQP' }] })] })
    mount()
    const editor = await openEditor(1)
    add(editor, 5)
    fireEvent.click(within(editor).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/lop/lines/1', { additional_owner_ids: [8, 5] }))
    clientMocks.patch.mockClear()
    fireEvent.click(within(editor).getByRole('button', { name: 'Remove George APQP as additional owner' }))
    fireEvent.click(within(editor).getByRole('button', { name: 'Remove Paula PM as additional owner' }))
    fireEvent.click(within(editor).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/lop/lines/1', { additional_owner_ids: [] }))
  })

  it('making an additional owner the responsible takes them off the additional list', async () => {
    project = lopProject({ lines: [lopLine({ additional_owners: [{ id: 8, name: 'George APQP' }] })] })
    mount()
    const editor = await openEditor(1)
    fireEvent.change(within(editor).getByLabelText('Responsible'), { target: { value: '8' } })
    fireEvent.click(within(editor).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/lop/lines/1',
      { responsible_id: 8, additional_owner_ids: [] }))
  })
})
