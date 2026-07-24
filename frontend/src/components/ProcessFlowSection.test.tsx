import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ProcessFlowSection from './ProcessFlowSection'

const flow = {
  tool: { id: 1, part_number: '3455', name: 'Rear Cladding Peak' },
  upstream: [{ id: 4, part_number: '3457', name: 'PDC Brackets', note: '2 brackets' }],
  downstream: [],
  stations: [
    { id: 8, part_number: '3455-10', name: 'EOAT', op_code: '10',
      kind: 'eoat', serves: ['3455'] },
    { id: 9, part_number: '3454-30', name: 'Punch & weld station', op_code: '30',
      kind: 'secondary_station', serves: ['3454', '3455', '3457'] },
    { id: 10, part_number: '3454-40', name: 'Rear Cladding gauge', op_code: '40',
      kind: 'gauge', serves: ['3454', '3455'] },
  ],
}

const get = vi.fn(() => Promise.resolve({ data: flow }))
vi.mock('../api/client', () => ({ default: { get: (...a: unknown[]) => get(...(a as [])) } }))

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })}>{ui}</QueryClientProvider>
)

describe('ProcessFlowSection', () => {
  afterEach(cleanup)

  it('renders the mold first, then stations in op-code order', async () => {
    render(wrap(<ProcessFlowSection partId={1} />))
    await waitFor(() => expect(screen.getByText('3454-30')).toBeDefined())
    const nodes = screen.getAllByTestId('flow-node').map((n) => n.textContent ?? '')
    // node 0 is the upstream feed; the route itself starts after it
    const route = nodes.slice(1)
    expect(route[0]).toContain('3455')
    expect(route[0]).toContain('Mold')
    expect(route[1]).toContain('3455-10')
    expect(route[2]).toContain('3454-30')
    expect(route[3]).toContain('3454-40')
  })

  it('marks a station shared with other tools', async () => {
    render(wrap(<ProcessFlowSection partId={1} />))
    await waitFor(() => expect(screen.getByText('3454-30')).toBeDefined())
    expect(screen.getByText(/shared: 3454, 3455, 3457/)).toBeDefined()
  })

  it('does not mark a station that serves only this tool', async () => {
    render(wrap(<ProcessFlowSection partId={1} />))
    await waitFor(() => expect(screen.getByText('3455-10')).toBeDefined())
    const eoat = screen.getByText('3455-10').closest('[data-testid="flow-node"]')
    expect(eoat?.textContent).not.toContain('shared')
  })

  it('shows an upstream tool with its note', async () => {
    render(wrap(<ProcessFlowSection partId={1} />))
    await waitFor(() => expect(screen.getByText('3457')).toBeDefined())
    expect(screen.getByText(/Feeds in/)).toBeDefined()
    expect(screen.getByText('2 brackets')).toBeDefined()
  })

  it('navigates to a station when clicked', async () => {
    const onSelectPart = vi.fn()
    render(wrap(<ProcessFlowSection partId={1} onSelectPart={onSelectPart} />))
    await waitFor(() => expect(screen.getByText('3454-30')).toBeDefined())
    fireEvent.click(screen.getByText('3454-30'))
    expect(onSelectPart).toHaveBeenCalledWith(9)
  })

  it('says so when the tool has no equipment', async () => {
    get.mockResolvedValueOnce({
      data: { tool: flow.tool, upstream: [], downstream: [], stations: [] },
    })
    render(wrap(<ProcessFlowSection partId={99} />))
    await waitFor(() => expect(screen.getByText(/No equipment recorded/)).toBeDefined())
  })
})
