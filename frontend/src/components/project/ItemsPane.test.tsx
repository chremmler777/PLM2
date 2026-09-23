import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
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
})
