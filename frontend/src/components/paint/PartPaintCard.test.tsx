import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { toast } from 'sonner'
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

// Setups keyed by part id, for the tests that navigate from one part to another.
function mockGetByPart(setups: Record<number, ReturnType<typeof setup>>, paints: ReturnType<typeof paint>[] = []) {
  clientMocks.get.mockImplementation((url: string) => {
    if (url === '/v1/paints') return Promise.resolve({ data: paints })
    const m = /^\/v1\/parts\/(\d+)\/paint$/.exec(url)
    if (m && setups[Number(m[1])]) return Promise.resolve({ data: setups[Number(m[1])] })
    return Promise.resolve({ data: [] })
  })
}

function renderCard(partId = 1) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const utils = render(
    <QueryClientProvider client={qc}>
      <PartPaintCard partId={partId} />
    </QueryClientProvider>
  )
  return {
    ...utils,
    rerenderWith: (nextPartId: number) =>
      utils.rerender(
        <QueryClientProvider client={qc}>
          <PartPaintCard partId={nextPartId} />
        </QueryClientProvider>
      ),
  }
}

describe('PartPaintCard', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.put.mockReset()
    vi.mocked(toast.error).mockReset()
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

  it('drops the draft when partId changes and saves against the new part', async () => {
    clientMocks.put.mockResolvedValue({ data: setup() })
    mockGetByPart({
      5: setup({
        paint_required: true,
        process: 'Spray',
        notes: 'note1',
        layers: [
          { layer_order: 1, area: 'top', notes: null, paint: paint(1) },
          { layer_order: 2, area: 'bottom', notes: null, paint: paint(2) },
        ],
      }),
      6: setup({ paint_required: true, process: null, notes: null, layers: [] }),
    })

    const { rerenderWith } = renderCard(5)
    await screen.findByTestId('paint-layer-1')

    rerenderWith(6)

    // the old part's layers must be gone, not carried over
    await waitFor(() => expect(screen.queryByTestId('paint-layer-0')).toBeNull())
    expect(screen.queryByTestId('paint-layer-1')).toBeNull()
    await waitFor(() => expect(screen.getByTestId('save-paint')).toBeTruthy())
    expect((screen.getByTestId('paint-process-input') as HTMLInputElement).value).toBe('')

    fireEvent.click(screen.getByTestId('save-paint'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalled())
    expect(clientMocks.put.mock.calls[0][0]).toBe('/v1/parts/6/paint')
    expect(clientMocks.put.mock.calls[0][1]).toEqual({
      paint_required: true,
      process: null,
      notes: null,
      layers: [],
    })
  })

  // FastAPI sends `detail` as an ARRAY for 422s; passing that to toast.error()
  // used to hand React an object to render and take the whole app down.
  it('toasts a string when the save fails with an array-detail 422', async () => {
    clientMocks.put.mockRejectedValue({
      response: {
        status: 422,
        data: { detail: [{ type: 'string_too_long', loc: ['body', 'layers', 0, 'area'], msg: 'String should have at most 255 characters' }] },
      },
    })
    mockGet(setup({
      paint_required: true,
      layers: [{ layer_order: 1, area: 'top', notes: null, paint: paint(1) }],
    }))
    renderCard()
    await screen.findByTestId('paint-layer-0')

    fireEvent.click(screen.getByTestId('save-paint'))
    await waitFor(() => expect(toast.error).toHaveBeenCalled())
    const calls = vi.mocked(toast.error).mock.calls
    const arg = calls[calls.length - 1][0]
    expect(typeof arg).toBe('string')
    expect(arg).toContain('at most 255 characters')
    // still rendered: nothing threw
    expect(screen.getByTestId('paint-layer-0')).toBeTruthy()
  })

  it('caps the layer area input at 255 characters', async () => {
    mockGet(setup({
      paint_required: true,
      layers: [{ layer_order: 1, area: null, notes: null, paint: paint(1) }],
    }))
    renderCard()
    const area = (await screen.findByTestId('paint-layer-area-0')) as HTMLInputElement
    expect(area.maxLength).toBe(255)
  })
})
