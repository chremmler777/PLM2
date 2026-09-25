import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ImpactTree from './ImpactTree'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

vi.mock('../../api/changes', () => ({
  changesApi: {
    getImpactTree: vi.fn(),
    suggestImpact: vi.fn(),
    applyImpactSelection: vi.fn(),
    confirmImpact: vi.fn(),
    get: vi.fn(),
    assessmentObjects: vi.fn(),
    impactObjects: vi.fn(),
    makeLead: vi.fn(),
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

// A mixed set: an article root, a tool and a gauge, so the top level has to be
// grouped rather than listed flat.
const mixedTree = {
  tree: [
    { part_id: 1, part_number: '20-3454-001-0', customer_part_number: '3CR.807.425',
      name: 'RR Cladding', part_type: 'internal_mfg', item_category: 'article',
      is_impacted: true, is_lead: true, resulting_revision_id: null, children: [] },
    { part_id: 2, part_number: '3454', customer_part_number: null,
      name: 'Rear Cladding', part_type: 'purchased', item_category: 'tool',
      is_impacted: false, is_lead: false, resulting_revision_id: null, children: [] },
    { part_id: 3, part_number: '3454-40', customer_part_number: null,
      name: 'Rear Cladding Gauge', part_type: 'purchased', item_category: 'gauge',
      is_impacted: false, is_lead: false, resulting_revision_id: null, children: [] },
  ],
  impacted_part_ids: [1],
  lead_part_id: 1,
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
    vi.mocked(changesApi.get).mockResolvedValue({
      id: 7, impacted_items: [{ id: 20, part_id: 2, is_lead: true }, { id: 30, part_id: 3 }],
    } as never)
    vi.mocked(changesApi.assessmentObjects).mockResolvedValue({ departments: [] })
    vi.mocked(changesApi.makeLead).mockResolvedValue({})
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

  it('apply sends the selection', async () => {
    wrap(<ImpactTree changeId={7} status="captured" />)
    await screen.findByText('Child')
    fireEvent.click(screen.getByRole('checkbox', { name: /Sibling/ }))
    fireEvent.click(screen.getAllByRole('button', { name: /Apply selection/ })[0])
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

  it('says the review asks the serving departments when locking an engineering review', async () => {
    wrap(<ImpactTree changeId={7} status="scoping" origin="engineering_review" />)
    await screen.findByText('Child')
    fireEvent.click(screen.getByRole('button', { name: /Confirm impact \(Development\)/ }))
    const text = screen.getByTestId('confirm-consequence').textContent
    expect(text).toContain('The review asks the departments serving these parts')
    expect(text).not.toContain('assessment is routed')
  })

  it('labels the resulting revision by its name, a pending customer index as pending', async () => {
    const child = tree.tree[0].children
    vi.mocked(changesApi.getImpactTree).mockResolvedValue({
      ...tree,
      tree: [{ ...tree.tree[0], children: [
        { ...child[0], resulting_revision_id: 2128, resulting_revision_label: 'E2 · 005', resulting_revision_pending: true },
        { ...child[1], is_impacted: true, resulting_revision_id: 2129, resulting_revision_label: 'E1.1', resulting_revision_pending: false },
      ] }],
    })
    wrap(<ImpactTree changeId={7} status="scoping" />)
    expect((await screen.findByTestId('impact-resulting-2')).textContent).toBe('E2 · 005 pending')
    expect(screen.getByTestId('impact-resulting-3').textContent).toBe('E1.1')
    expect(screen.queryByText(/ECN #/)).toBeNull()
  })

  it('shows an enabled Confirm impact button to Development, and calls the API', async () => {
    wrap(<ImpactTree changeId={7} status="captured" />)
    await screen.findByText('Child')
    const btn = screen.getByRole('button', { name: /Confirm impact \(Development\)/ })
    expect((btn as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(btn)
    // Asked once more: confirming locks the set the assessment is routed on.
    expect(changesApi.confirmImpact).not.toHaveBeenCalled()
    expect(screen.getByTestId('confirm-consequence').textContent).toContain('Development has to confirm again')
    fireEvent.click(screen.getByTestId('confirm-go'))
    await waitFor(() => expect(changesApi.confirmImpact).toHaveBeenCalledWith(7))
  })

  it('greys the confirm button for a non-Development viewer and says why', async () => {
    vi.mocked(changesApi.confirmImpact).mockClear()
    wrap(<ImpactTree changeId={7} status="captured" canConfirm={false} />)
    await screen.findByText('Child')
    const btn = screen.getByRole('button', { name: /Confirm impact \(Development\)/ })
    // Visible but inert — the rule is stated, not hidden behind a 403.
    expect((btn as HTMLButtonElement).disabled).toBe(true)
    expect(btn.getAttribute('title')).toBe(t('impact.developmentOnly'))
    fireEvent.click(btn)
    expect(changesApi.confirmImpact).not.toHaveBeenCalled()
  })

  it('shows a confirmed badge with who/when instead of the button once confirmed', async () => {
    wrap(<ImpactTree changeId={7} status="captured"
      impactConfirmedByName="RD Member" impactConfirmedAt="2026-07-01T12:00:00" />)
    await screen.findByText('Child')
    expect(screen.queryByRole('button', { name: /Confirm impact \(Development\)/ })).toBeNull()
    expect(screen.getByText(/RD Member/)).toBeDefined()
  })

  it('shows our number, the customer number and the name, in that order', async () => {
    vi.mocked(changesApi.getImpactTree).mockResolvedValue(mixedTree)
    wrap(<ImpactTree changeId={7} status="captured" />)
    await screen.findByText('20-3454-001-0')
    expect(screen.getByText('3CR.807.425')).toBeDefined()
    expect(screen.getByText('RR Cladding')).toBeDefined()
    // The tool has no customer number; the column holds its place rather than
    // collapsing and knocking the names out of alignment.
    expect(screen.getAllByText('-').length).toBeGreaterThanOrEqual(2)
  })

  it('groups the top level by controlled-item class, articles first', async () => {
    vi.mocked(changesApi.getImpactTree).mockResolvedValue(mixedTree)
    wrap(<ImpactTree changeId={7} status="captured" />)
    await screen.findByText('20-3454-001-0')
    const headings = ['Articles', 'Tools & molds', 'Gauges'].map((h) => screen.getByText(h))
    expect(headings).toHaveLength(3)
    // Articles lead, gauges trail — order comes from ITEM_GROUP_ORDER.
    const order = headings.map((el) => el.compareDocumentPosition(headings[0]))
    expect(order[1] & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()
  })

  it('lets the lead be unpicked while scoping, and pins it from assessment on', async () => {
    vi.mocked(changesApi.getImpactTree).mockResolvedValue(tree)
    const { unmount } = wrap(<ImpactTree changeId={7} status="scoping" />)
    await screen.findByText('Child')
    // 'Child' is the lead. Naming it wrong is an ordinary scoping mistake.
    expect((screen.getByRole('checkbox', { name: /Child/ }) as HTMLInputElement).disabled)
      .toBe(false)
    unmount()

    vi.mocked(changesApi.getImpactTree).mockResolvedValue(tree)
    wrap(<ImpactTree changeId={7} status="in_assessment" />)
    await screen.findByText('Child')
    // Departments are routed against it by now — frozen.
    expect((screen.getByRole('checkbox', { name: /Child/ }) as HTMLInputElement).disabled)
      .toBe(true)
  })
})

describe('ImpactTree, spec §16', () => {
  beforeEach(() => {
    vi.mocked(changesApi.getImpactTree).mockResolvedValue(tree)
    vi.mocked(changesApi.suggestImpact).mockResolvedValue({ suggested_part_ids: [] })
    vi.mocked(changesApi.applyImpactSelection).mockReset().mockResolvedValue({ impacted_part_ids: [2, 3] })
    vi.mocked(changesApi.get).mockResolvedValue({
      id: 7, impacted_items: [{ id: 20, part_id: 2, is_lead: true }, { id: 30, part_id: 3 }],
    } as never)
    vi.mocked(changesApi.assessmentObjects).mockResolvedValue({ departments: [] })
    // An older backend: no impact-objects endpoint, the assessment objects serve.
    vi.mocked(changesApi.impactObjects).mockReset().mockRejectedValue({ response: { status: 404 } })
    vi.mocked(changesApi.makeLead).mockReset().mockResolvedValue({})
  })
  afterEach(cleanup)

  it('shows which tools and gauges serve a part', async () => {
    vi.mocked(changesApi.assessmentObjects).mockResolvedValue({ departments: [
      { department_id: 4, name: 'Tool Engineer', objects: [
        { type: 'tool', id: 90, number: 'T-3454', name: 'Mold', via_part_id: 2 },
      ] },
      { department_id: 5, name: 'Quality', objects: [
        { type: 'gauge', id: 91, number: 'G-77', name: 'Gauge', via_part_id: 2 },
        // The same tool seen by a second department is listed once.
        { type: 'tool', id: 90, number: 'T-3454', name: 'Mold', via_part_id: 2 },
      ] },
    ] })
    wrap(<ImpactTree changeId={7} status="scoping" />)
    const line = await screen.findByTestId('impact-served-2')
    expect(line.textContent).toContain('T-3454')
    expect(line.textContent).toContain('G-77')
    expect(line.textContent!.match(/T-3454/g)).toHaveLength(1)
  })

  it('during scoping reads served-by from impact-objects for the selected parts', async () => {
    vi.mocked(changesApi.impactObjects).mockResolvedValue({ parts: [
      { part_id: 2, served_by: [
        { type: 'tool', id: 95, number: 'T-9000', name: 'Mold', via_part_id: 2, category: 'tool' },
      ] },
    ] })
    wrap(<ImpactTree changeId={7} status="scoping" />)
    const line = await screen.findByTestId('impact-served-2')
    expect(line.textContent).toContain('T-9000')
    expect(changesApi.impactObjects).toHaveBeenCalledWith(7, [2])
    // Ticking another part asks again for the new selection.
    fireEvent.click(screen.getByRole('checkbox', { name: /Sibling/ }))
    await waitFor(() => expect(changesApi.impactObjects).toHaveBeenCalledWith(7, [2, 3]))
  })

  it('does not ask impact-objects once the change is routed', async () => {
    wrap(<ImpactTree changeId={7} status="in_assessment" />)
    await screen.findByText('Child')
    expect(changesApi.impactObjects).not.toHaveBeenCalled()
  })

  it('marks a pending selection, names it, and discards it', async () => {
    wrap(<ImpactTree changeId={7} status="scoping" />)
    await screen.findByText('Child')
    expect(screen.queryByTestId('impact-pending-bar')).toBeNull()
    fireEvent.click(screen.getByRole('checkbox', { name: /Sibling/ }))
    const bar = screen.getByTestId('impact-pending-bar')
    expect(bar.textContent).toContain('+CHD-2')
    expect(screen.getByTestId('impact-row-3').getAttribute('data-pending')).toBe('add')
    fireEvent.click(screen.getByTestId('impact-discard'))
    expect(screen.queryByTestId('impact-pending-bar')).toBeNull()
    expect((screen.getByRole('checkbox', { name: /Sibling/ }) as HTMLInputElement).checked).toBe(false)
  })

  it('shows suggestions as their own chip that adds the part', async () => {
    vi.mocked(changesApi.suggestImpact).mockResolvedValue({ suggested_part_ids: [1] })
    wrap(<ImpactTree changeId={7} status="scoping" />)
    const chip = await screen.findByTestId('impact-suggested-1')
    fireEvent.click(chip)
    expect((screen.getByRole('checkbox', { name: /Assembly/ }) as HTMLInputElement).checked).toBe(true)
  })

  it('warns before an apply clears Development\'s confirmation', async () => {
    wrap(<ImpactTree changeId={7} status="scoping"
      impactConfirmedByName="RD Member" impactConfirmedAt="2026-09-20T08:00:00" />)
    await screen.findByText('Child')
    fireEvent.click(screen.getByRole('checkbox', { name: /Sibling/ }))
    fireEvent.click(screen.getByTestId('impact-apply-bar'))
    const dlg = screen.getByTestId('impact-lock-confirm')
    expect(dlg.textContent).toContain('RD Member')
    expect(changesApi.applyImpactSelection).not.toHaveBeenCalled()
    fireEvent.click(screen.getByTestId('impact-lock-go'))
    await waitFor(() => expect(changesApi.applyImpactSelection).toHaveBeenCalledWith(7, [2, 3]))
  })

  it('asks a reason once the offer went out and sends it', async () => {
    wrap(<ImpactTree changeId={7} status="quoted" quoted />)
    await screen.findByText('Child')
    fireEvent.click(screen.getByRole('checkbox', { name: /Sibling/ }))
    fireEvent.click(screen.getByTestId('impact-apply-bar'))
    expect(screen.getByText(t('impact.afterQuoteWarning'), { exact: false })).toBeTruthy()
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Customer added the RH part' } })
    fireEvent.click(screen.getAllByRole('button', { name: t('impact.apply') }).slice(-1)[0])
    await waitFor(() => expect(changesApi.applyImpactSelection)
      .toHaveBeenCalledWith(7, [2, 3], 'Customer added the RH part'))
  })

  it('states that the offer no longer covers the scope', async () => {
    wrap(<ImpactTree changeId={7} status="quoted" quoted scopeChangedAfterQuote />)
    expect((await screen.findByTestId('impact-scope-changed')).textContent)
      .toBe(t('impact.scopeChangedAfterQuote'))
  })

  it('is read only for someone who may not edit the set', async () => {
    wrap(<ImpactTree changeId={7} status="scoping" canEdit={false} />)
    await screen.findByText('Child')
    expect(screen.queryByRole('button', { name: /Apply selection/ })).toBeNull()
    expect(screen.getByTestId('impact-readonly').textContent).toBe(t('impact.editRights'))
    expect((screen.getByRole('checkbox', { name: /Sibling/ }) as HTMLInputElement).disabled).toBe(true)
    expect(screen.queryByTestId('impact-make-lead-3')).toBeNull()
  })

  it('makes another impacted item the lead and says the title follows', async () => {
    vi.mocked(changesApi.getImpactTree).mockResolvedValue({ ...tree, impacted_part_ids: [2, 3] })
    wrap(<ImpactTree changeId={7} status="scoping" titleAuto />)
    expect((await screen.findByTestId('impact-title-auto')).textContent).toBe(t('impact.titleFollowsLead'))
    fireEvent.click(await screen.findByTestId('impact-make-lead-3'))
    await waitFor(() => expect(changesApi.makeLead).toHaveBeenCalledWith(7, 30))
    // The lead itself offers no "Make lead".
    expect(screen.queryByTestId('impact-make-lead-2')).toBeNull()
  })

  it('offers no "Make lead" once the lead is pinned', async () => {
    vi.mocked(changesApi.getImpactTree).mockResolvedValue({ ...tree, impacted_part_ids: [2, 3] })
    wrap(<ImpactTree changeId={7} status="in_assessment" />)
    await screen.findByText('Child')
    expect(screen.queryByTestId('impact-make-lead-3')).toBeNull()
  })
})
