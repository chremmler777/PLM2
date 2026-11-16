import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import LopPanel from './LopPanel'
import { lopLine, lopProject, pdbResponse, pdbTopic } from './lop.fixtures'
import type { LopEquipment, LopProjectResponse, PdbResponse } from '../../types/lop'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ userId: 5, actingAsUser: null }) }))

const team = [{ department_id: 1, department_name: 'Project Manager', responsible: { id: 5, name: 'Paula PM' }, backup: null }]
const TOOL: LopEquipment = { id: 100, part_number: '3345', name: 'UBV Mitte', kind: 'tool', tool_number: '3345' }
const GAUGE: LopEquipment = { id: 101, part_number: '3345-40', name: 'Gauge UBV Mitte', kind: 'gauge', tool_number: '3345' }
const EOAT: LopEquipment = { id: 102, part_number: '3346-10', name: 'EOAT', kind: 'eoat', tool_number: '3346' }
let project: LopProjectResponse
let pdb: PdbResponse
let equipment: LopEquipment[]

function mount() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <LopPanel projectId={2} />
    </QueryClientProvider>)
}
const link = (scope: HTMLElement, id: number) =>
  fireEvent.change(within(scope).getByLabelText('Link equipment'), { target: { value: String(id) } })

describe('LOP equipment', () => {
  beforeEach(() => {
    project = lopProject()
    pdb = pdbResponse({ topics: [] })
    equipment = [TOOL, GAUGE, EOAT]
    window.localStorage.clear()
    for (const m of Object.values(clientMocks)) m.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/lop/projects/2') return Promise.resolve({ data: project })
      if (url === '/v1/lop/projects/2/pdb') return Promise.resolve({ data: pdb })
      if (url === '/v1/projects/2/team') return Promise.resolve({ data: team })
      if (url === '/v1/lop/projects/2/equipment') return Promise.resolve({ data: equipment })
      return Promise.resolve({ data: [] })
    })
    clientMocks.patch.mockResolvedValue({ data: lopLine() })
    clientMocks.post.mockResolvedValue({ data: lopLine({ id: 9 }) })
  })
  afterEach(cleanup)

  it('a new task is linked to a gauge without a hint, and to a tool with the PDB hint', async () => {
    mount()
    fireEvent.click(await screen.findByRole('button', { name: '+ Task' }))
    const form = await screen.findByTestId('lop-new-task')
    fireEvent.change(within(form).getByLabelText('Task'), { target: { value: 'Gauge R&R' } })
    await within(form).findByRole('option', { name: /3345-40/ })
    link(form, 101)
    expect(within(form).queryByTestId('lop-tool-hint')).toBeNull()
    link(form, 100)
    const hint = within(form).getByTestId('lop-tool-hint')
    expect(hint.textContent).toMatch(/belong in PDB/)
    expect(within(hint).getByRole('link', { name: /Open 3345 in PDB/ }).getAttribute('href')).toBe('/pdb/tools/3345')
    fireEvent.click(within(form).getByRole('button', { name: 'Remove Tool 3345' }))
    expect(within(form).queryByTestId('lop-tool-hint')).toBeNull()
    fireEvent.click(within(form).getByRole('button', { name: 'Add task' }))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/lop/projects/2/lines',
      { title: 'Gauge R&R', equipment_ids: [101] }))
  })

  it('shows the linked equipment on the row and the PM changes it in the editor', async () => {
    project = lopProject({ lines: [lopLine({ equipment: [GAUGE] })] })
    mount()
    const row = await screen.findByTestId('lop-row-1')
    expect(within(row).getByTestId('lop-row-equipment').textContent).toBe('Gauge 3345-40')
    fireEvent.click(within(row).getByRole('button', { name: /edit line/i }))
    const editor = await screen.findByTestId('lop-editor-1')
    await within(editor).findByRole('option', { name: /3346-10/ })
    link(editor, 102)
    fireEvent.click(within(editor).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/lop/lines/1', { equipment_ids: [101, 102] }))
  })

  it('the Equipment filter finds a tool\'s PDB topics and the tasks linked to its gauge', async () => {
    project = lopProject({ lines: [
      lopLine({ id: 1, text: 'Gauge task', title: 'Gauge task', equipment: [GAUGE] }),
      lopLine({ id: 2, text: 'EOAT task', title: 'EOAT task', equipment: [EOAT] }),
      lopLine({ id: 3, text: 'No equipment', title: 'No equipment' }),
    ] })
    pdb = pdbResponse({ topics: [pdbTopic({ tool_number: '3345' })] })
    mount()
    await screen.findByTestId('lop-row-1')
    const filter = screen.getByLabelText('Article or equipment')
    expect(within(filter).getAllByRole('option').map((o) => o.textContent)).toEqual(
      ['Article / equipment: all', '3345', '3345-40', '3346', '3346-10'])
    fireEvent.change(filter, { target: { value: '3345' } })
    expect(screen.getByTestId('lop-row-1')).toBeTruthy()
    expect(screen.queryByTestId('lop-row-2')).toBeNull()
    expect(screen.queryByTestId('lop-row-3')).toBeNull()
    expect(within(screen.getByTestId('lop-pdb-group')).getByText(/PDB topics \(1\)/)).toBeTruthy()
    fireEvent.change(filter, { target: { value: '3346-10' } })
    expect(screen.getByTestId('lop-row-2')).toBeTruthy()
    expect(screen.queryByTestId('lop-row-1')).toBeNull()
  })

  it('says so when PLM has no equipment for the project', async () => {
    equipment = []
    mount()
    fireEvent.click(await screen.findByRole('button', { name: '+ Task' }))
    const form = await screen.findByTestId('lop-new-task')
    expect(await within(form).findByText(/No articles, tools, gauges or equipment in PLM/)).toBeTruthy()
  })

  it('links an article and shows it by its customer number', async () => {
    equipment = [{ id: 200, part_number: '21-3345-0001', name: 'UBV Mitte part', kind: 'article', tool_number: null,
      customer_part_number: '51.12.7.123.456' }, TOOL]
    mount()
    fireEvent.click(await screen.findByRole('button', { name: '+ Task' }))
    const form = await screen.findByTestId('lop-new-task')
    fireEvent.change(within(form).getByLabelText('Task'), { target: { value: 'Sink mark' } })
    await within(form).findByRole('option', { name: /51\.12\.7\.123\.456 · 21-3345-0001/ })
    link(form, 200)
    expect(within(form).getByRole('button', { name: 'Remove Article 51.12.7.123.456' })).toBeTruthy()
    expect(within(form).queryByTestId('lop-tool-hint')).toBeNull()
    fireEvent.click(within(form).getByRole('button', { name: 'Add task' }))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/lop/projects/2/lines',
      { title: 'Sink mark', equipment_ids: [200] }))
  })
})
