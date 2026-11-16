import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ItemsPane, { type ItemsPaneProps } from './ItemsPane'
import type { Part } from './projectTypes'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
const toastMocks = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }))
vi.mock('sonner', () => ({ toast: toastMocks }))
vi.mock('../parts/AssemblyTreeList', () => ({ default: () => <div>assemblies</div> }))

const parts: Part[] = [
  { id: 1, part_number: '199401', name: '1994 TOOL Handle', part_type: 'purchased', item_category: 'tool', active_revision_id: null, parent_part_id: null },
  { id: 2, part_number: '20-1994-001-0', name: 'Handle LH', part_type: 'internal_mfg', item_category: 'article', active_revision_id: null, parent_part_id: null },
]

function mount(over: Partial<ItemsPaneProps> = {}) {
  const props: ItemsPaneProps = {
    projectId: 2, projectCode: '1994', parts, partsLoading: false, structure: { articles: [] },
    paintByPartId: new Map(), paintedIds: new Set(), paintedCount: 0, selectedPartId: null,
    onSelect: vi.fn(), onOpenPart: vi.fn(), onPickRevision: vi.fn(), onContextMenu: vi.fn(), ...over,
  }
  render(<QueryClientProvider client={new QueryClient()}><ItemsPane {...props} /></QueryClientProvider>)
  return props
}

describe('ItemsPane', () => {
  afterEach(cleanup)

  it('counts the items, filters by category and reports a row click', () => {
    const props = mount()
    expect(screen.getByText('Items (2)')).toBeTruthy()
    fireEvent.click(screen.getByText('🔧 Tool'))
    expect(screen.getByText('Items (1 of 2)')).toBeTruthy()
    fireEvent.click(screen.getByText('TOOL Handle'))
    expect(props.onSelect).toHaveBeenCalledWith(1)
  })

  it('shows the assembly tree for the assemblies filter', () => {
    mount()
    fireEvent.click(screen.getByText('🧩 Assemblies'))
    expect(screen.getByText('assemblies')).toBeTruthy()
  })

  it('rows show the thumbnail, the labelled numbers and leave missing numbers out', () => {
    mount({ parts: [
      { ...parts[1], tier1_part_number: 'S00H54-110', customer_part_number: '206.887.233', thumbnail_url: '/api/v1/parts/2/thumbnail?v=1' },
      parts[0],
    ] })
    expect(screen.getByTestId('row-numbers-2').textContent).toBe('KTX 20-1994-001-0 · Tier 1 S00H54-110 · OEM 206.887.233')
    expect(screen.getByAltText('Handle LH').getAttribute('src')).toBe('/v1/parts/2/thumbnail?v=1')
    expect(screen.getByTestId('row-numbers-1').textContent).toBe('KTX 199401')
    expect(screen.queryByTestId('row-numbers-1-tier1')).toBeNull()
    expect(screen.queryByTestId('row-numbers-1-oem')).toBeNull()
    expect(screen.getByTestId('row-thumb-1-placeholder')).toBeTruthy()
  })

  it('rows show the active revision with our E level bold', () => {
    mount({ structure: { articles: [{
      part_id: 2, part_number: '20-1994-001-0', customer_part_number: null, name: 'Handle LH', lifecycle_phase: 'nominated',
      active_revision_id: 9, related: [], mirror_of: null, mirrored_by: [],
      revisions: [{ id: 9, revision_name: 'E1', customer_index: '001', status: 'approved', phase: 'review', parent_revision_id: null, is_active: true }],
    }] } })
    const rev = screen.getByTestId('row-rev-2')
    expect(rev.textContent).toBe('E1 · 001')
    expect(within(rev).getByText('E1').className).toContain('font-bold')
    expect(screen.getByTestId('row-phase-2').textContent).toBe('nominated')
  })

  it('search matches the KTX, Tier 1 and OEM numbers', () => {
    mount({ parts: [{ ...parts[1], tier1_part_number: 'S00H54-110', customer_part_number: '206.887.233' }, parts[0]] })
    for (const q of ['20-1994-001', 'S00H54', '206.887']) {
      fireEvent.change(screen.getByLabelText('Search items'), { target: { value: q } })
      expect(screen.getByText('Items (1 of 2)')).toBeTruthy()
    }
  })

  it('the table shows a thumbnail and the KTX number', () => {
    mount({ mode: 'table' })
    expect(screen.getAllByRole('columnheader').map((th) => th.textContent).slice(0, 3)).toEqual(['Image', 'KTX no.', 'Customer no.'])
    const cells = within(screen.getByTestId('table-row-2')).getAllByRole('cell')
    expect(within(cells[0]).getByTestId('table-thumb-2-placeholder')).toBeTruthy()
    expect(cells[1].textContent).toBe('20-1994-001-0')
  })

  describe('mirror connectors', () => {
    const mirrorParts: Part[] = [
      { id: 2, part_number: '20-1994-001-0', name: 'Handle LH', part_type: 'internal_mfg', item_category: 'article', active_revision_id: null, parent_part_id: null },
      { id: 3, part_number: '20-1994-002-0', name: 'Handle RH', part_type: 'internal_mfg', item_category: 'article', active_revision_id: null, parent_part_id: null },
    ]
    const mirrorStructure = { articles: [
      { part_id: 2, part_number: '20-1994-001-0', customer_part_number: null, name: 'Handle LH', lifecycle_phase: 'nominated', active_revision_id: null, revisions: [], related: [], mirror_of: null, mirrored_by: [{ part_id: 3, part_number: '20-1994-002-0', customer_part_number: null, name: 'Handle RH' }] },
      { part_id: 3, part_number: '20-1994-002-0', customer_part_number: null, name: 'Handle RH', lifecycle_phase: 'nominated', active_revision_id: null, revisions: [], related: [], mirror_of: { part_id: 2, part_number: '20-1994-001-0', customer_part_number: null, name: 'Handle LH' }, mirrored_by: [] },
    ] }

    it('draws start and end segments for a visible mirror pair', () => {
      mount({ parts: mirrorParts, structure: mirrorStructure })
      expect(screen.getByTestId('mirror-seg-2-0-start')).toBeTruthy()
      expect(screen.getByTestId('mirror-seg-3-0-end')).toBeTruthy()
      // Both rows get a tick to the thumbnail; only the start row carries the line on past its row.
      expect(screen.getByTestId('mirror-tick-2-0')).toBeTruthy()
      expect(screen.getByTestId('mirror-tick-3-0')).toBeTruthy()
      expect(screen.getByTestId('mirror-tail-2-0')).toBeTruthy()
      expect(screen.queryByTestId('mirror-tail-3-0')).toBeNull()
    })

    it('draws no connectors when the partner is filtered out', () => {
      mount({ parts: mirrorParts, structure: mirrorStructure })
      fireEvent.change(screen.getByLabelText('Search items'), { target: { value: 'RH' } })
      expect(screen.queryByTestId('mirror-seg-3-0-start')).toBeNull()
      expect(screen.queryByTestId('mirror-seg-2-0-start')).toBeNull()
    })

    it('hovering either row of a pair highlights both, and hovering away removes it', () => {
      mount({ parts: mirrorParts, structure: mirrorStructure })
      const row = screen.getByTestId('item-row-2')
      const seg2 = screen.getByTestId('mirror-seg-2-0-start')
      const seg3 = screen.getByTestId('mirror-seg-3-0-end')
      expect(seg2.className).toContain('opacity-70')
      expect(row.className).not.toContain('ring-1')
      fireEvent.mouseOver(row)
      expect(seg2.className).toContain('opacity-100')
      expect(seg3.className).toContain('opacity-100')
      expect(row.className).toContain('ring-1')
      expect(screen.getByTestId('item-row-3').className).toContain('ring-1')
    })
  })

  it('offers the worksheet when the page supports it', () => {
    const onShowWorksheet = vi.fn()
    mount({ onShowWorksheet })
    fireEvent.click(screen.getByTestId('show-worksheet'))
    expect(onShowWorksheet).toHaveBeenCalled()
  })

  describe('drag and drop linking', () => {
    const base = { part_type: 'internal_mfg', active_revision_id: null, parent_part_id: null }
    const linkParts: Part[] = [
      { ...base, id: 1, part_number: '3345', name: 'Tool Cover', item_category: 'tool' },
      { ...base, id: 2, part_number: '1748-0012', name: 'Cover LH', item_category: 'article' },
      { ...base, id: 3, part_number: '3345-40', name: 'Gauge Cover', item_category: 'gauge' },
      { ...base, id: 4, part_number: '3345-20', name: 'Degate station', item_category: 'assembly_equipment' },
      { ...base, id: 5, part_number: '1748-0100', name: 'Cover assy', item_category: 'article', part_type: 'sub_assembly' },
    ]
    const ALL = { can_edit_tools: true, can_edit_gauges: true, can_edit_assembly_equipment: true }
    const withRights = (rights: Record<string, boolean>) =>
      clientMocks.get.mockImplementation((url: string) => Promise.resolve({ data: url === '/v1/auth/me' ? rights : [] }))
    const drag = (fromId: number, toId: number) => {
      const dataTransfer = { effectAllowed: '' }
      fireEvent.dragStart(screen.getByTestId(`item-row-${fromId}`), { dataTransfer })
      const target = screen.getByTestId(`item-row-${toId}`)
      fireEvent.dragOver(target, { dataTransfer })
      const highlighted = target.className.includes('border-green-500')
      fireEvent.drop(target, { dataTransfer })
      return highlighted
    }

    beforeEach(() => {
      clientMocks.get.mockReset(); clientMocks.post.mockReset(); clientMocks.put.mockReset()
      Object.values(toastMocks).forEach((m) => m.mockReset())
      clientMocks.post.mockResolvedValue({ data: {} })
      clientMocks.put.mockResolvedValue({ data: {} })
      withRights(ALL)
    })

    it('an article dropped on a gauge, tool or equipment links them in plain words', async () => {
      mount({ parts: linkParts })
      expect(drag(2, 3)).toBe(true)
      await waitFor(() => expect(toastMocks.success).toHaveBeenCalledWith('Linked: gauge 3345-40 checks 1748-0012'))
      expect(clientMocks.post).toHaveBeenLastCalledWith('/v1/parts/3/relations', { to_part_id: 2, relation_type: 'checks' })
      drag(2, 1)
      await waitFor(() => expect(toastMocks.success).toHaveBeenCalledWith('Linked: tool 3345 produces 1748-0012'))
      expect(clientMocks.post).toHaveBeenLastCalledWith('/v1/parts/1/relations', { to_part_id: 2, relation_type: 'produces' })
      drag(2, 4)
      await waitFor(() => expect(toastMocks.success).toHaveBeenCalledWith('Linked: equipment 3345-20 assembles 1748-0012'))
      expect(clientMocks.post).toHaveBeenLastCalledWith('/v1/parts/4/relations', { to_part_id: 2, relation_type: 'assembles' })
    })

    it('says so and does nothing when the link already exists', () => {
      mount({ parts: linkParts, structure: { articles: [{
        part_id: 2, part_number: '1748-0012', customer_part_number: null, name: 'Cover LH', lifecycle_phase: 'series',
        active_revision_id: null, revisions: [], mirror_of: null, mirrored_by: [],
        related: [{ relation_type: 'checks', direction: 'incoming', label: 'checked by', part_id: 3, part_number: '3345-40', name: 'Gauge Cover', item_category: 'gauge' }],
      }] } })
      drag(2, 3)
      expect(toastMocks.info).toHaveBeenCalledWith('Already linked: gauge 3345-40 checks 1748-0012')
      expect(clientMocks.post).not.toHaveBeenCalled()
    })

    it('only an article links: a gauge dragged onto a tool is not accepted', () => {
      mount({ parts: linkParts })
      expect(drag(3, 1)).toBe(false)
      expect(clientMocks.post).not.toHaveBeenCalled()
    })

    it('a row is no drop target without the right for its category', async () => {
      withRights({ can_edit_tools: false, can_edit_gauges: true, can_edit_assembly_equipment: false })
      mount({ parts: linkParts })
      await waitFor(() => expect(clientMocks.get).toHaveBeenCalledWith('/v1/auth/me'))
      await waitFor(() => expect(drag(2, 1)).toBe(false))
      expect(drag(2, 4)).toBe(false)
      expect(clientMocks.post).not.toHaveBeenCalled()
      expect(drag(2, 3)).toBe(true)
      await waitFor(() => expect(clientMocks.post).toHaveBeenCalledTimes(1))
    })

    it("shows the server's 403 text when it refuses", async () => {
      clientMocks.post.mockRejectedValue({ response: { status: 403, data: { detail: 'Only APQP, the Project Manager or an admin can change gauges; you can view them.' } } })
      mount({ parts: linkParts })
      drag(2, 3)
      await waitFor(() => expect(toastMocks.error).toHaveBeenCalledWith('Only APQP, the Project Manager or an admin can change gauges; you can view them.'))
    })

    it('dropping on a sub-assembly still re-parents', async () => {
      mount({ parts: linkParts })
      expect(drag(2, 5)).toBe(true)
      await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/2', { parent_part_id: 5 }))
      expect(clientMocks.post).not.toHaveBeenCalled()
    })

    it('shows the hint only to people who may link', async () => {
      mount({ parts: linkParts })
      expect(screen.getByTestId('link-hint').textContent).toBe('Drag an article onto a tool, gauge or equipment to link it.')
      cleanup()
      withRights({ can_edit_tools: false, can_edit_gauges: false, can_edit_assembly_equipment: false })
      mount({ parts: linkParts })
      await waitFor(() => expect(screen.queryByTestId('link-hint')).toBeNull())
    })
  })

  it('has an "+ Add" button above the list that opens the create dialog', () => {
    const onAddItem = vi.fn()
    mount({ onAddItem })
    fireEvent.click(screen.getByRole('button', { name: 'Add item (article, tool, gauge, equipment)' }))
    expect(onAddItem).toHaveBeenCalled()
  })

  describe('obsolete items', () => {
    const withObsolete: Part[] = [
      ...parts,
      { id: 7, part_number: '199401-40', name: 'Old gauge', part_type: 'internal_mfg', item_category: 'gauge', active_revision_id: null, parent_part_id: null, obsolete_at: '2026-11-01T10:00:00' },
    ]

    it('are hidden behind "Show obsolete (n)" and greyed with a tag when shown', () => {
      mount({ parts: withObsolete })
      expect(screen.getByText('Items (2)')).toBeTruthy()
      expect(screen.queryByTestId('item-row-7')).toBeNull()
      fireEvent.click(screen.getByLabelText('Show obsolete (1)'))
      expect(screen.getByText('Items (3)')).toBeTruthy()
      expect(screen.getByTestId('item-row-7').className).toContain('opacity-50')
      expect(screen.getByTestId('row-obsolete-7').textContent).toBe('obsolete')
    })

    it('offers no toggle when nothing is obsolete', () => {
      mount()
      expect(screen.queryByTestId('show-obsolete')).toBeNull()
    })

    it('are no drop target for an article', () => {
      mount({ parts: withObsolete })
      fireEvent.click(screen.getByTestId('show-obsolete'))
      const dataTransfer = { effectAllowed: '' }
      fireEvent.dragStart(screen.getByTestId('item-row-2'), { dataTransfer })
      const target = screen.getByTestId('item-row-7')
      fireEvent.dragOver(target, { dataTransfer })
      expect(target.className).not.toContain('border-green-500')
      fireEvent.drop(target, { dataTransfer })
      expect(clientMocks.post).not.toHaveBeenCalled()
    })
  })

  it('reports the dragged row to the page when the page holds the drag state', () => {
    const onDraggingChange = vi.fn()
    mount({ draggingPartId: null, onDraggingChange })
    fireEvent.dragStart(screen.getByTestId('item-row-2'), { dataTransfer: { effectAllowed: '' } })
    expect(onDraggingChange).toHaveBeenCalledWith(2)
    fireEvent.dragEnd(screen.getByTestId('item-row-2'))
    expect(onDraggingChange).toHaveBeenLastCalledWith(null)
  })
})
