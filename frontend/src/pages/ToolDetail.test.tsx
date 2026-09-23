import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ToolDetail, { type ToolPart } from './ToolDetail'
import { producedArticles } from '../components/tools/toolRelations'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ isAdmin: true }) }))
const stub = vi.hoisted(() => (label: string) => ({ default: () => <div>{label}</div> }))
vi.mock('../components/changes/StartChangeModal', () => stub('start-change'))
vi.mock('../components/changes/StartChangeButton', () => stub('start-change-button'))
vi.mock('../components/dfm/DfmArchive', () => ({
  default: (p: { onOpenPdf: (d: unknown) => void }) => (
    <button data-testid="dfm-archive" onClick={() => p.onOpenPdf({
      fileId: 41, filename: 'ISOFIX_DFM_rev2.pdf', kind: 'pdf', revisionName: 'Gate position ISOFIX',
      sourceLabel: 'Answer #8 · KTX to Toolmaker', inlineUrl: '/x',
    })} />
  ),
}))

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

function renderTool(onOpenPart = vi.fn(), part: ToolPart = tool) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><ToolDetail part={part} onOpenPart={onOpenPart} onBack={() => {}} /></QueryClientProvider>)
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

  it('shows the tool picture left of the title, or the placeholder without one', async () => {
    renderTool(vi.fn(), { ...tool, thumbnail_url: '/api/v1/parts/7/thumbnail?v=2' })
    expect((await screen.findByAltText('ISOFIX Cover')).getAttribute('src')).toBe('/v1/parts/7/thumbnail?v=2')
    expect(screen.getByTestId('tool-thumbnail').className).toContain('w-24')
    cleanup()
    renderTool()
    expect(await screen.findByTestId('tool-thumbnail-placeholder')).toBeTruthy()
  })

  it('shows the produced article revision with our E level bold', async () => {
    renderTool()
    const chips = await screen.findByTestId('produced-articles')
    expect((await within(chips).findByText('E1')).className).toContain('font-bold')
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

  it('shows the tool fields card', async () => {
    renderTool()
    expect(await screen.findByTestId('edit-tool-cavities')).toBeTruthy()
    expect(screen.getByTestId('toolmaker-select')).toBeTruthy()
  })

  it('mounts the DFM archive and no revision file list', async () => {
    renderTool()
    expect(await screen.findByTestId('dfm-archive')).toBeTruthy()
    expect(screen.queryByText(/Files ·/)).toBeNull()
  })

  it('scrolls an opened DFM pdf into view and shows a title bar naming the message, with a close button', async () => {
    const scrollSpy = vi.fn()
    Element.prototype.scrollIntoView = scrollSpy
    renderTool()
    fireEvent.click(await screen.findByTestId('dfm-archive'))
    expect(scrollSpy).toHaveBeenCalledWith(expect.objectContaining({ behavior: 'smooth', block: 'start' }))
    expect((await screen.findByTestId('doc-header')).textContent).toContain('ISOFIX_DFM_rev2.pdf · Answer #8 · KTX to Toolmaker')
    fireEvent.click(screen.getByTestId('doc-close'))
    expect(screen.queryByTestId('doc-header')).toBeNull()
  })
})

describe('producedArticles', () => {
  it('keeps outgoing produces links only, in part number order', () => {
    const out = producedArticles([relations[1], relations[0]] as never)
    expect(out).toEqual([{ part_id: 9, part_number: '20-1994-003-0', name: '206.887.233 Isofix cover',
      revision_name: 'E1', customer_index: '003', notes: '2 cavities' }])
  })
})
