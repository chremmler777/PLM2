import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ToolFieldsCard, { type ToolFieldValues } from './ToolFieldsCard'
import { cavitiesFromNotes } from './toolCavities'
import { toast } from 'sonner'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const empty: ToolFieldValues = { tool_cavities: null, toolmaker_id: null, tool_tonnage_class: null, tool_cycle_time_s: null }

function wrap(values: ToolFieldValues = empty, notes: (string | null)[] = []) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><ToolFieldsCard partId={7} values={values} producedNotes={notes} /></QueryClientProvider>)
}

describe('ToolFieldsCard', () => {
  beforeEach(() => {
    clientMocks.get.mockReset(); clientMocks.put.mockReset()
    clientMocks.get.mockResolvedValue({ data: [{ id: 3, name: 'Toolshop Sued' }, { id: 4, name: 'Formenbau Nord' }] })
    clientMocks.put.mockResolvedValue({ data: {} })
  })
  afterEach(cleanup)

  it('saves cavities as an integer', async () => {
    wrap()
    fireEvent.click(screen.getByTestId('edit-tool-cavities'))
    fireEvent.change(screen.getByTestId('tool-cavities-input'), { target: { value: '4' } })
    fireEvent.click(screen.getByTestId('save-tool-cavities'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7', { tool_cavities: 4 }))
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
    wrap({ ...empty, tool_cavities: 4 }, ['2 cavities'])
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
  it('sums the cavity counts it finds and ignores the rest', () => {
    expect(cavitiesFromNotes(['2 cavities', '1 cavity', 'RFQ2 bom_item 12', null])).toBe(3)
    expect(cavitiesFromNotes(['per RFQ'])).toBeNull()
    expect(cavitiesFromNotes([])).toBeNull()
  })
})
