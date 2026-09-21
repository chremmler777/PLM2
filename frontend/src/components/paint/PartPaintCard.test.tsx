import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import PartPaintCard from './PartPaintCard'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const paint = (id: number, over: Record<string, unknown> = {}) => ({
  id, organization_id: 1, name: `Paint ${id}`, paint_type: 'primer',
  colour_code: `RAL ${9000 + id}`, colour_name: 'Grey', colour_hex: '#888888',
  supplier_id: null, supplier_text: null, spec_reference: null, notes: null,
  is_active: true, created_at: '2026-01-01', updated_at: '2026-01-01', ...over,
})

const setup = (over: Record<string, unknown> = {}) => ({
  paint_required: false, process: null, notes: null, layers: [], ...over,
})

function mockGet(partSetup: ReturnType<typeof setup>, paints: ReturnType<typeof paint>[] = []) {
  clientMocks.get.mockImplementation((url: string) => {
    if (url === '/v1/paints') return Promise.resolve({ data: paints })
    if (url === '/v1/parts/1/paint') return Promise.resolve({ data: partSetup })
    return Promise.resolve({ data: [] })
  })
}

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <PartPaintCard partId={1} />
    </QueryClientProvider>
  )
}

describe('PartPaintCard', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.put.mockReset()
  })
  afterEach(cleanup)

  it('loads the existing setup', async () => {
    mockGet(setup({
      paint_required: true,
      process: 'Spray coat',
      notes: 'careful',
      layers: [{ layer_order: 1, area: 'A-side', notes: null, paint: paint(1, { name: 'RAL 9005 Primer' }) }],
    }))
    renderCard()
    await screen.findByTestId('paint-process-input')
    expect((screen.getByTestId('paint-process-input') as HTMLInputElement).value).toBe('Spray coat')
    expect(screen.getByTestId('paint-layer-0').textContent).toContain('RAL 9005 Primer')
  })

  it('reveals process/layers when paint required is toggled on', async () => {
    mockGet(setup())
    renderCard()
    const toggle = await screen.findByTestId('paint-required-toggle')
    expect(screen.queryByTestId('paint-process-input')).toBeNull()
    fireEvent.click(toggle)
    expect(screen.getByTestId('paint-process-input')).toBeTruthy()
  })

  it('adds a layer from the picker', async () => {
    mockGet(setup({ paint_required: true }), [paint(1), paint(2)])
    renderCard()
    await screen.findByTestId('paint-required-toggle')
    await waitFor(() => expect(screen.getByTestId('paint-picker').querySelectorAll('option').length).toBe(3))
    fireEvent.change(screen.getByTestId('paint-picker'), { target: { value: '2' } })
    fireEvent.click(screen.getByTestId('add-layer-button'))
    expect(screen.getByTestId('paint-layer-0').textContent).toContain('Paint 2')
  })

  it('reorders layers with move up/down', async () => {
    mockGet(setup({
      paint_required: true,
      layers: [
        { layer_order: 1, area: null, notes: null, paint: paint(1) },
        { layer_order: 2, area: null, notes: null, paint: paint(2) },
      ],
    }))
    renderCard()
    await screen.findByTestId('paint-layer-0')
    expect(screen.getByTestId('paint-layer-0').textContent).toContain('Paint 1')
    fireEvent.click(screen.getByTestId('move-down-0'))
    expect(screen.getByTestId('paint-layer-0').textContent).toContain('Paint 2')
    expect(screen.getByTestId('paint-layer-1').textContent).toContain('Paint 1')
    fireEvent.click(screen.getByTestId('move-up-1'))
    expect(screen.getByTestId('paint-layer-0').textContent).toContain('Paint 1')
  })

  it('removes a layer', async () => {
    mockGet(setup({
      paint_required: true,
      layers: [
        { layer_order: 1, area: null, notes: null, paint: paint(1) },
        { layer_order: 2, area: null, notes: null, paint: paint(2) },
      ],
    }))
    renderCard()
    await screen.findByTestId('paint-layer-1')
    fireEvent.click(screen.getByTestId('remove-layer-0'))
    expect(screen.getByTestId('paint-layer-0').textContent).toContain('Paint 2')
    expect(screen.queryByTestId('paint-layer-1')).toBeNull()
  })

  it('saves the whole setup in the shown order', async () => {
    clientMocks.put.mockResolvedValue({ data: setup() })
    mockGet(setup({
      paint_required: true,
      process: 'Spray',
      notes: 'note1',
      layers: [
        { layer_order: 1, area: 'top', notes: null, paint: paint(1) },
        { layer_order: 2, area: 'bottom', notes: null, paint: paint(2) },
      ],
    }))
    renderCard()
    await screen.findByTestId('paint-layer-1')
    fireEvent.click(screen.getByTestId('move-down-0'))
    fireEvent.click(screen.getByTestId('save-paint'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalled())
    expect(clientMocks.put.mock.calls[0][0]).toBe('/v1/parts/1/paint')
    expect(clientMocks.put.mock.calls[0][1]).toEqual({
      paint_required: true,
      process: 'Spray',
      notes: 'note1',
      layers: [
        { paint_id: 2, area: 'bottom', notes: null },
        { paint_id: 1, area: 'top', notes: null },
      ],
    })
  })

  it('empties the payload when paint required is unchecked, but keeps the draft on screen', async () => {
    clientMocks.put.mockResolvedValue({ data: setup() })
    mockGet(setup({
      paint_required: true,
      process: 'Spray',
      notes: 'note1',
      layers: [
        { layer_order: 1, area: 'top', notes: null, paint: paint(1) },
        { layer_order: 2, area: 'bottom', notes: null, paint: paint(2) },
      ],
    }))
    renderCard()
    await screen.findByTestId('paint-layer-1')
    fireEvent.click(screen.getByTestId('paint-required-toggle'))
    fireEvent.click(screen.getByTestId('save-paint'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalled())
    expect(clientMocks.put.mock.calls[0][1]).toEqual({
      paint_required: false,
      process: null,
      notes: null,
      layers: [],
    })

    fireEvent.click(screen.getByTestId('paint-required-toggle'))
    expect(screen.getByTestId('paint-layer-0').textContent).toContain('Paint 1')
    expect(screen.getByTestId('paint-layer-1').textContent).toContain('Paint 2')
    expect((screen.getByTestId('paint-process-input') as HTMLInputElement).value).toBe('Spray')
  })

  it('shows "paint spec missing" when required with no layers', async () => {
    mockGet(setup({ paint_required: true, layers: [] }))
    renderCard()
    await waitFor(() => expect(screen.getByText('paint spec missing')).toBeTruthy())
  })

  it('shows "inactive" for a layer whose paint is inactive', async () => {
    mockGet(setup({
      paint_required: true,
      layers: [{ layer_order: 1, area: null, notes: null, paint: paint(1, { is_active: false }) }],
    }))
    renderCard()
    await screen.findByTestId('paint-layer-0')
    expect(screen.getByTestId('paint-layer-0').textContent).toContain('inactive')
  })
})
