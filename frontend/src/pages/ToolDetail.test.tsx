import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ToolDetail, { producedArticles, type ToolPart } from './ToolDetail'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ isAdmin: true }) }))
const stub = vi.hoisted(() => (label: string) => ({ default: () => <div>{label}</div> }))
vi.mock('../components/changes/StartChangeModal', () => stub('start-change'))
vi.mock('../components/changes/StartChangeButton', () => stub('start-change-button'))

const tool: ToolPart = {
  id: 7, part_number: '199403', name: 'ISOFIX Cover', part_type: 'purchased', project_id: 2,
  item_category: 'tool', lifecycle_phase: 'nominated',
  tool_cavities: null, toolmaker_id: null, tool_tonnage_class: null, tool_cycle_time_s: null,
}
const relations = [
  { id: 1, relation_type: 'produces', direction: 'outgoing', label: 'produces', other_part_id: 9,
    other_part_number: '20-1994-003-0', other_part_name: '206.887.233 Isofix cover', other_item_category: 'article',
    other_active_revision_name: 'E1', other_active_customer_index: '003', notes: '2 cavities' },
  { id: 2, relation_type: 'serves', direction: 'incoming', label: 'served by', other_part_id: 30,
    other_part_number: '199403-41', other_part_name: 'Assembly station', other_item_category: 'assembly_equipment',
    other_active_revision_name: null, other_active_customer_index: null, notes: null },
]

function renderTool(onOpenPart = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><ToolDetail part={tool} onOpenPart={onOpenPart} onBack={() => {}} /></QueryClientProvider>)
  return onOpenPart
}

describe('ToolDetail', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/7/relations') return Promise.resolve({ data: relations })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('shows the tool number and name without customer or tier 1 numbers', async () => {
    renderTool()
    expect(await screen.findByText('199403')).toBeTruthy()
    expect(screen.getByText('ISOFIX Cover')).toBeTruthy()
    expect(screen.queryByTestId('edit-customer-part-number')).toBeNull()
    expect(screen.queryByTestId('edit-tier1-part-number')).toBeNull()
  })

  it('lists the produced articles as chips with their active revision and opens them', async () => {
    const onOpen = renderTool()
    const chips = await screen.findByTestId('produced-articles')
    expect(chips.textContent).toContain('206.887.233 Isofix cover · E1 · 003')
    expect(chips.textContent).not.toContain('Assembly station')
    fireEvent.click(screen.getByText(/206.887.233 Isofix cover/))
    expect(onOpen).toHaveBeenCalledWith(9)
  })

  it('says so when the tool produces nothing yet', async () => {
    clientMocks.get.mockImplementation(() => Promise.resolve({ data: [] }))
    renderTool()
    expect((await screen.findByTestId('produced-articles')).textContent).toContain('No produced article linked yet')
  })
})

describe('producedArticles', () => {
  it('keeps outgoing produces links only, in part number order', () => {
    const out = producedArticles([relations[1], relations[0]] as never)
    expect(out).toEqual([{ part_id: 9, part_number: '20-1994-003-0', name: '206.887.233 Isofix cover',
      revision_name: 'E1', customer_index: '003', notes: '2 cavities' }])
  })
})
