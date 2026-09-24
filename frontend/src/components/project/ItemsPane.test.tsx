import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ItemsPane, { type ItemsPaneProps } from './ItemsPane'
import type { Part } from './projectTypes'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
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
})
