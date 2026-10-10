import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ToolFieldsCard, { type ToolFieldValues } from './ToolFieldsCard'
import { cavitiesFromNotes } from './toolCavities'
import { toast } from 'sonner'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const empty: ToolFieldValues = { tool_cavities: null, toolmaker_id: null, tool_tonnage_class: null, tool_cycle_time_s: null, tool_machine: null, tool_shrink_parallel_pct: null, tool_shrink_normal_pct: null }

function wrap(values: ToolFieldValues = empty, notes: (string | null)[] = [], projectId: number | null = null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><ToolFieldsCard partId={7} values={values} producedNotes={notes} projectId={projectId} /></QueryClientProvider>)
}

describe('ToolFieldsCard', () => {
  beforeEach(() => {
    clientMocks.get.mockReset(); clientMocks.put.mockReset(); vi.mocked(toast.error).mockClear()
    clientMocks.get.mockResolvedValue({ data: [{ id: 3, name: 'Toolshop Sued' }, { id: 4, name: 'Formenbau Nord' }] })
    clientMocks.put.mockResolvedValue({ data: {} })
  })
  afterEach(cleanup)

  it('saves a family layout as written, never summed', async () => {
    wrap(empty)
    fireEvent.click(screen.getByTestId('edit-tool-cavities'))
    fireEvent.change(screen.getByTestId('tool-cavities-input'), { target: { value: '2 + 2' } })
    fireEvent.click(screen.getByTestId('save-tool-cavities'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7', { tool_cavities: '2+2' }))
  })

  it('refuses cavities that are no layout', () => {
    wrap(empty)
    fireEvent.click(screen.getByTestId('edit-tool-cavities'))
    fireEvent.change(screen.getByTestId('tool-cavities-input'), { target: { value: '2x2' } })
    fireEvent.click(screen.getByTestId('save-tool-cavities'))
    expect(clientMocks.put).not.toHaveBeenCalled()
    expect(toast.error).toHaveBeenCalledWith('Cavities must be a number or a layout like 2+2')
  })

  it('saves cavities as text', async () => {
    wrap()
    fireEvent.click(screen.getByTestId('edit-tool-cavities'))
    fireEvent.change(screen.getByTestId('tool-cavities-input'), { target: { value: '4' } })
    fireEvent.click(screen.getByTestId('save-tool-cavities'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7', { tool_cavities: '4' }))
  })

  it('clears a field when emptied and saves cycle time as a decimal', async () => {
    wrap({ ...empty, tool_tonnage_class: 650, tool_cycle_time_s: 32.5 })
    fireEvent.click(screen.getByTestId('edit-tool-tonnage'))
    fireEvent.change(screen.getByTestId('tool-tonnage-input'), { target: { value: '' } })
    fireEvent.click(screen.getByTestId('save-tool-tonnage'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7', { tool_tonnage_class: null }))

    fireEvent.click(screen.getByTestId('edit-tool-cycle'))
    fireEvent.change(screen.getByTestId('tool-cycle-input'), { target: { value: '31.8' } })
    fireEvent.keyDown(screen.getByTestId('tool-cycle-input'), { key: 'Enter' })
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7', { tool_cycle_time_s: 31.8 }))
  })

  it('saves the machine as trimmed text and clears it when emptied', async () => {
    wrap({ ...empty, tool_machine: 'KM 200-1 (KM 200/750 CX)' })
    expect(screen.getByTestId('edit-tool-machine').textContent).toBe('KM 200-1 (KM 200/750 CX)')
    fireEvent.click(screen.getByTestId('edit-tool-machine'))
    fireEvent.change(screen.getByTestId('tool-machine-input'), { target: { value: ' KM 350-1 ' } })
    fireEvent.keyDown(screen.getByTestId('tool-machine-input'), { key: 'Enter' })
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7', { tool_machine: 'KM 350-1' }))
    fireEvent.click(screen.getByTestId('edit-tool-machine'))
    fireEvent.change(screen.getByTestId('tool-machine-input'), { target: { value: '' } })
    fireEvent.click(screen.getByTestId('save-tool-machine'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7', { tool_machine: null }))
  })

  it('picks the toolmaker from the supplier list and saves at once', async () => {
    wrap()
    const select = await screen.findByTestId('toolmaker-select') as HTMLSelectElement
    await screen.findByRole('option', { name: 'Formenbau Nord' })
    fireEvent.change(select, { target: { value: '4' } })
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7', { toolmaker_id: 4 }))
    fireEvent.change(select, { target: { value: '' } })
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7', { toolmaker_id: null }))
  })

  it('falls back to the relation note for cavities and says so', async () => {
    wrap(empty, ['2 cavities', null])
    expect(screen.getByTestId('edit-tool-cavities').textContent).toContain('2')
    expect(screen.getByTestId('cavities-fallback').textContent).toContain('from the produces note')
  })

  it('prefers the stored cavities over the note', () => {
    wrap({ ...empty, tool_cavities: '4' }, ['2 cavities'])
    expect(screen.getByTestId('edit-tool-cavities').textContent).toContain('4')
    expect(screen.queryByTestId('cavities-fallback')).toBeNull()
  })

  it('shows a string toast, not a crash, on a 422 with an array detail', async () => {
    clientMocks.put.mockRejectedValue({
      response: { data: { detail: [{ type: 'greater_than', loc: ['body', 'tool_cavities'], msg: 'Input should be greater than 0' }] } },
    })
    wrap()
    fireEvent.click(screen.getByTestId('edit-tool-cavities'))
    fireEvent.change(screen.getByTestId('tool-cavities-input'), { target: { value: '4' } })
    fireEvent.click(screen.getByTestId('save-tool-cavities'))
    await waitFor(() => expect(toast.error).toHaveBeenCalled())
    const message = (toast.error as ReturnType<typeof vi.fn>).mock.calls[0][0]
    expect(typeof message).toBe('string')
    expect(message).toContain('Input should be greater than 0')
  })

  it('shows field history on every tool field marker when a project id is given', async () => {
    wrap(empty, [], 35)
    for (const key of ['tool.cavities', 'tool.tonnage_class', 'tool.cycle_time_s', 'tool.toolmaker']) {
      fireEvent.click(screen.getByTestId(`note-marker-${key}`))
      expect(await screen.findByTestId('note-history-toggle')).toBeTruthy()
      fireEvent.click(screen.getByTestId(`note-marker-${key}`))
    }
  })

  it('has no field history without a project id', async () => {
    wrap()
    fireEvent.click(screen.getByTestId('note-marker-tool.cavities'))
    await screen.findByTestId('note-popover-tool.cavities')
    expect(screen.queryByTestId('note-history-toggle')).toBeNull()
  })

  it('puts a note marker on every tool field', async () => {
    clientMocks.get.mockImplementation((url: string) => Promise.resolve({ data: url === '/v1/parts/7/field-notes'
      ? [{ id: 1, part_id: 7, field_key: 'tool.cavities', flag_status: 'open', flag_set_by: null, flag_set_by_name: null,
          flag_set_at: null, created_at: null, comment_count: 0, last_comment: null }]
      : [{ id: 3, name: 'Toolshop Sued' }] }))
    wrap()
    await waitFor(() => expect(screen.getByTestId('note-dot-tool.cavities').className).toContain('bg-yellow-400'))
    for (const key of ['tool.tonnage_class', 'tool.cycle_time_s', 'tool.toolmaker']) {
      expect(screen.getByTestId(`note-marker-${key}`)).toBeTruthy()
    }
  })
})

describe('cavitiesFromNotes', () => {
  it('joins the cavity counts per article as a layout, never sums them', () => {
    expect(cavitiesFromNotes(['2 cavities', '2 cavities'])).toBe('2+2')
    expect(cavitiesFromNotes(['2 cavities', '1 cavity', 'RFQ2 bom_item 12', null])).toBe('2+1')
    expect(cavitiesFromNotes(['per RFQ'])).toBeNull()
    expect(cavitiesFromNotes([])).toBeNull()
  })

  it('shows the chosen shrinkage next to cycle time: either combined or parallel and normal', () => {
    wrap({ ...empty, tool_shrink_combined_pct: 0.65 })
    expect(screen.getByTestId('tool-shrink-summary').textContent).toBe('Shrinkage (%)0.65 combined')
    cleanup()
    wrap({ ...empty, tool_shrink_parallel_pct: 0.7, tool_shrink_normal_pct: 1 })
    expect(screen.getByTestId('tool-shrink-summary').textContent).toBe('Shrinkage (%)0.7 parallel · 1 normal')
    cleanup()
    wrap()
    expect(screen.getByTestId('tool-shrink-summary').textContent).toBe('Shrinkage (%)not chosen')
  })

  it('shows the MaterialDB shrinkage as a reference under the chosen value', async () => {
    clientMocks.get.mockImplementation((url: string) => Promise.resolve({ data: url === '/v1/parts/7/shrinkage'
      ? { tool: { parallel_pct: null, normal_pct: null, combined_pct: 0.65 }, decisions: [], materials: [], error: null,
          no_material: false, no_article: false, candidates: [
            { key: 'a', kind: 'datasheet', materialdb_id: 4, material_label: '40-0011 Bayblend T85 XF', parallel_pct: 0.5,
              normal_pct: 0.7, parallel_text: '0.5-0.7', normal_text: '0.5-0.7', method: 'ISO 294-4', condition: null,
              source_label: 'Datasheet', doc_date: null, origin: null },
            { key: 'b', kind: 'ktx_experience', materialdb_id: 4, material_label: '40-0011 Bayblend T85 XF', parallel_pct: 0.65,
              normal_pct: 0.65, parallel_text: '0.65', normal_text: '0.65', method: null, condition: null,
              source_label: 'Tool 3127', doc_date: null, origin: null }] }
      : [] }))
    wrap({ ...empty, tool_shrink_combined_pct: 0.65 })
    expect((await screen.findByTestId('tool-shrink-reference')).textContent).toBe('MaterialDB 0.5-0.7 %')
  })

  it('is view only without tool rights: values shown, no edit, toolmaker locked', async () => {
    cleanup()
    clientMocks.get.mockImplementation((url: string) => Promise.resolve({ data: url === '/v1/auth/me'
      ? { can_edit_tools: false } : [{ id: 3, name: 'Toolshop Sued' }] }))
    wrap({ ...empty, tool_cavities: '4', tool_machine: 'KM 350-1' })
    expect(await screen.findByTestId('tool-view-only')).toBeTruthy()
    expect(screen.queryByTestId('edit-tool-cavities')).toBeNull()
    expect(screen.getByTestId('view-tool-cavities').textContent).toBe('4')
    expect(screen.getByTestId('view-tool-machine').textContent).toBe('KM 350-1')
    expect(screen.getByTestId('toolmaker-select')).toHaveProperty('disabled', true)
  })
})
