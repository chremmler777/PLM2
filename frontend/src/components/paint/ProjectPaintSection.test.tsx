import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ProjectPaintSection from './ProjectPaintSection'

const clientMocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks }))

const paint = (id: number, over: Record<string, unknown> = {}) => ({
  id, name: `Paint ${id}`, paint_type: 'basecoat',
  colour_code: `RAL ${9000 + id}`, colour_name: 'Grey', colour_hex: '#888888',
  supplier_id: null, supplier_text: null, spec_reference: null, notes: null,
  is_active: true, ...over,
})

const layer = (order: number, p: ReturnType<typeof paint>) => ({
  layer_order: order, area: null, notes: null, paint: p,
})

function mockOverview(data: unknown[]) {
  clientMocks.get.mockImplementation((url: string) => {
    if (url === '/v1/parts/project/2/paint-overview') return Promise.resolve({ data })
    return Promise.resolve({ data: [] })
  })
}

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ProjectPaintSection projectId={2} />
    </QueryClientProvider>
  )
}

async function expand() {
  fireEvent.click(await screen.findByTestId('project-paint-toggle'))
}

describe('ProjectPaintSection', () => {
  beforeEach(() => clientMocks.get.mockReset())
  afterEach(cleanup)

  it('shows an empty state when nothing is painted', async () => {
    mockOverview([])
    renderSection()
    await expand()
    expect(await screen.findByText('No painted articles yet')).toBeTruthy()
  })

  it('is collapsed until the header is clicked', async () => {
    mockOverview([
      { part_id: 5, part_number: '1994-100', name: 'Top', process: null, layers: [layer(1, paint(1))] },
    ])
    renderSection()
    expect(await screen.findByTestId('project-paint-toggle')).toBeTruthy()
    expect(screen.queryByTestId('paint-group-1')).toBeNull()
    await expand()
    expect(await screen.findByTestId('paint-group-1')).toBeTruthy()
  })

  it('heads each group with the paint swatch, name, type label and colour code', async () => {
    mockOverview([
      { part_id: 5, part_number: '1994-100', name: 'Top', process: 'wet', layers: [layer(1, paint(1))] },
    ])
    renderSection()
    await expand()

    const group = await screen.findByTestId('paint-group-1')
    expect(within(group).getByText('Paint 1')).toBeTruthy()
    expect(within(group).getByText('Basecoat')).toBeTruthy()
    expect(within(group).getByText('RAL 9001')).toBeTruthy()
    expect(within(group).getByRole('img', { name: 'RAL 9001' })).toBeTruthy()
  })

  it('tags a group whose paint is inactive', async () => {
    mockOverview([
      {
        part_id: 5, part_number: '1994-100', name: 'Top', process: null,
        layers: [layer(1, paint(1, { is_active: false })), layer(2, paint(2))],
      },
    ])
    renderSection()
    await expand()

    const inactiveGroup = await screen.findByTestId('paint-group-1')
    expect(within(inactiveGroup).getByText('inactive')).toBeTruthy()
    const activeGroup = screen.getByTestId('paint-group-2')
    expect(within(activeGroup).queryByText('inactive')).toBeNull()
  })

  it('lists a part under each of its paints with its layer position', async () => {
    mockOverview([
      {
        part_id: 5, part_number: '1994-100', name: 'Top', process: null,
        layers: [layer(1, paint(1)), layer(2, paint(2))],
      },
      { part_id: 6, part_number: '1994-200', name: 'Bracket', process: null, layers: [layer(1, paint(2))] },
    ])
    renderSection()
    await expand()

    const first = await screen.findByTestId('paint-group-1')
    expect(within(first).getByText('1994-100')).toBeTruthy()
    expect(within(first).getByText(/Layer 1/)).toBeTruthy()
    expect(within(first).queryByText('1994-200')).toBeNull()

    const second = screen.getByTestId('paint-group-2')
    expect(within(second).getByText('1994-100')).toBeTruthy()
    expect(within(second).getByText(/Layer 2/)).toBeTruthy()
    expect(within(second).getByText('1994-200')).toBeTruthy()
  })

  it('counts the painted articles in the header', async () => {
    mockOverview([
      { part_id: 5, part_number: '1994-100', name: 'Top', process: null, layers: [layer(1, paint(1)), layer(2, paint(2))] },
      { part_id: 6, part_number: '1994-200', name: 'Bracket', process: null, layers: [layer(1, paint(2))] },
    ])
    renderSection()
    await waitFor(() =>
      expect(screen.getByTestId('project-paint-toggle').textContent).toContain('🎨 Paint (2)')
    )
  })
})
