import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ImpactTree from './ImpactTree'
import { changesApi } from '../../api/changes'

vi.mock('../../api/changes', () => ({
  changesApi: {
    getImpactTree: vi.fn(),
    suggestImpact: vi.fn(),
    applyImpactSelection: vi.fn(),
    confirmImpact: vi.fn(),
  },
}))

const tree = {
  tree: [
    {
      part_id: 1, part_number: 'ASM-1', name: 'Assembly', part_type: 'sub_assembly',
      item_category: 'article', is_impacted: false, is_lead: false,
      resulting_revision_id: null,
      children: [
        { part_id: 2, part_number: 'CHD-1', name: 'Child', part_type: 'internal_mfg',
          item_category: 'article', is_impacted: true, is_lead: true,
          resulting_revision_id: null, children: [] },
        { part_id: 3, part_number: 'CHD-2', name: 'Sibling', part_type: 'internal_mfg',
          item_category: 'article', is_impacted: false, is_lead: false,
          resulting_revision_id: null, children: [] },
      ],
    },
  ],
  impacted_part_ids: [2],
  lead_part_id: 2,
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const result = render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
  return { ...result, qc }
}

describe('ImpactTree', () => {
  beforeEach(() => {
    vi.mocked(changesApi.getImpactTree).mockResolvedValue(tree)
    vi.mocked(changesApi.suggestImpact).mockResolvedValue({ suggested_part_ids: [1] })
    vi.mocked(changesApi.applyImpactSelection).mockResolvedValue({ impacted_part_ids: [2, 3] })
    vi.mocked(changesApi.confirmImpact).mockResolvedValue({} as never)
  })
  afterEach(cleanup)

  it('renders nodes and marks suggested parents when selection changes', async () => {
    wrap(<ImpactTree changeId={7} status="captured" />)
    expect(await screen.findByText('Child')).toBeDefined()
    fireEvent.click(screen.getByRole('checkbox', { name: /Sibling/ }))
    await waitFor(() =>
      expect(changesApi.suggestImpact).toHaveBeenCalledWith(7, [2, 3]))
    expect(await screen.findByText(/Suggested/)).toBeDefined()
  })

  it('lead checkbox is disabled and apply sends the selection', async () => {
    wrap(<ImpactTree changeId={7} status="captured" />)
    await screen.findByText('Child')
    const lead = screen.getByRole('checkbox', { name: /Child/ }) as HTMLInputElement
    expect(lead.disabled).toBe(true)
    fireEvent.click(screen.getByRole('checkbox', { name: /Sibling/ }))
    fireEvent.click(screen.getByRole('button', { name: /Apply selection/ }))
    await waitFor(() =>
      expect(changesApi.applyImpactSelection).toHaveBeenCalledWith(7, [2, 3]))
  })

  it('locks editing once implementation started', async () => {
    wrap(<ImpactTree changeId={7} status="in_implementation" />)
    await screen.findByText('Child')
    expect(screen.queryByRole('button', { name: /Apply selection/ })).toBeNull()
    expect(screen.getByText(/Selection locked/)).toBeDefined()
  })

  it('preserves unsaved edits across a background refetch', async () => {
    const { qc } = wrap(<ImpactTree changeId={7} status="captured" />)
    await screen.findByText('Child')

    // Unsaved edit: check the sibling node.
    fireEvent.click(screen.getByRole('checkbox', { name: /Sibling/ }))
    const sibling = screen.getByRole('checkbox', { name: /Sibling/ }) as HTMLInputElement
    expect(sibling.checked).toBe(true)

    // Simulate a background refetch (e.g. window focus) that resolves fresh
    // server data — the underlying impacted_part_ids are unchanged, but the
    // payload is a new object reference (e.g. an unrelated field changed
    // server-side). This must not clobber the user's in-progress edit.
    const refetched = {
      ...tree,
      tree: [{ ...tree.tree[0], name: 'Assembly Updated' }],
    }
    vi.mocked(changesApi.getImpactTree).mockResolvedValueOnce(refetched)
    await qc.refetchQueries({ queryKey: ['change', 7, 'impact-tree'] })
    await screen.findByText('Assembly Updated')

    expect(sibling.checked).toBe(true)
  })

  it('shows a Confirm impact (R&D) button when unconfirmed, and calls the API', async () => {
    wrap(<ImpactTree changeId={7} status="captured" />)
    await screen.findByText('Child')
    const btn = screen.getByRole('button', { name: /Confirm impact \(R&D\)/ })
    fireEvent.click(btn)
    await waitFor(() => expect(changesApi.confirmImpact).toHaveBeenCalledWith(7))
  })

  it('shows a confirmed badge with who/when instead of the button once confirmed', async () => {
    wrap(<ImpactTree changeId={7} status="captured"
      impactConfirmedByName="RD Member" impactConfirmedAt="2026-07-01T12:00:00" />)
    await screen.findByText('Child')
    expect(screen.queryByRole('button', { name: /Confirm impact \(R&D\)/ })).toBeNull()
    expect(screen.getByText(/RD Member/)).toBeDefined()
  })
})
