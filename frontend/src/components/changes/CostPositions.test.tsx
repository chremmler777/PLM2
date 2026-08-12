import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CostPositions from './CostPositions'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

vi.mock('../../api/changes', () => ({
  changesApi: {
    listCostPositions: vi.fn(),
    createCostPosition: vi.fn().mockResolvedValue({}),
    updateCostPosition: vi.fn().mockResolvedValue({}),
    deleteCostPosition: vi.fn().mockResolvedValue({}),
    addCostingOffer: vi.fn().mockResolvedValue({}),
    updateCostingOffer: vi.fn().mockResolvedValue({}),
    deleteCostingOffer: vi.fn().mockResolvedValue({}),
    setWeightEstimate: vi.fn().mockResolvedValue({}),
    costingTags: vi.fn(),
    uploadAttachment: vi.fn().mockResolvedValue({}),
  },
}))

const TAGS = {
  items: [{ key: 'tool_change' }, { key: 'equipment_change' }, { key: 'other' }],
}

const external = {
  id: 11, department_id: 2, label: 'Anlagenumbau', tag: 'equipment_change',
  kind: 'external', pricing: 'quote', est_cost: null, hours: 6,
  lead_time_days: null, lead_time_unit: null, notes: null, effective_cost: null,
  offers: [
    { id: 91, vendor_name: 'Vendor A', cost: 5000, shipping_cost: 200,
      shipping_included: false, lead_time_days: 30,
      lead_time_unit: 'business_days', favorite: true },
    { id: 92, vendor_name: 'Vendor B', cost: 5400, shipping_cost: null,
      shipping_included: true, lead_time_days: 20,
      lead_time_unit: 'calendar_days', favorite: false },
  ],
}

const effort = {
  id: 10, department_id: 2, label: t('costpos.internalEffortField'), tag: null,
  kind: 'internal_effort', pricing: null, est_cost: null, hours: 12,
  lead_time_days: null, notes: null, effective_cost: 1080, offers: [],
}

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>)

const positions = (props: Record<string, unknown> = {}) =>
  wrap(<CostPositions changeId={7} departmentId={2} editable {...props} />)

describe('CostPositions', () => {
  beforeEach(() => {
    vi.mocked(changesApi.listCostPositions).mockResolvedValue([effort, external] as never)
    vi.mocked(changesApi.costingTags).mockResolvedValue(TAGS as never)
    vi.mocked(changesApi.createCostPosition).mockClear()
    vi.mocked(changesApi.updateCostPosition).mockClear()
    vi.mocked(changesApi.addCostingOffer).mockClear()
    vi.mocked(changesApi.updateCostingOffer).mockClear()
    vi.mocked(changesApi.setWeightEstimate).mockClear()
  })
  afterEach(cleanup)

  it('stands the two effort answers in front of the department', async () => {
    positions()
    // No hunting through an add-form: both fields are simply there, and the one
    // already answered shows its number.
    await waitFor(() => expect(
      (screen.getByTestId('costpos-effort-internal_effort-2') as HTMLInputElement).value,
    ).toBe('12'))
    expect(screen.getByTestId('costpos-effort-support_effort-2')).toBeTruthy()
    expect(screen.getByTestId(`costpos-effort-2`).textContent)
      .toContain(t('costpos.internalEffortField'))
    expect(screen.getByTestId(`costpos-effort-2`).textContent)
      .toContain(t('costpos.supportEffortField'))
    // The position behind a bound field is not repeated in the list below.
    expect(screen.queryByTestId('costpos-row-10')).toBeNull()
  })

  it('creates the position behind an unanswered effort field on first save', async () => {
    positions()
    await screen.findByTestId('costpos-row-11')
    const support = screen.getByTestId('costpos-effort-support_effort-2')
    fireEvent.change(support, { target: { value: '16' } })
    fireEvent.blur(support)
    await waitFor(() => expect(changesApi.createCostPosition).toHaveBeenCalledWith(7, {
      department_id: 2, label: t('costpos.supportEffortField'),
      kind: 'support_effort', hours: 16,
    }))
    expect(changesApi.updateCostPosition).not.toHaveBeenCalled()
  })

  it('edits that same position on every save after the first', async () => {
    positions()
    // Once the answered position has arrived, the field is bound to it.
    await waitFor(() => expect(
      (screen.getByTestId('costpos-effort-internal_effort-2') as HTMLInputElement).value,
    ).toBe('12'))
    const internal = screen.getByTestId('costpos-effort-internal_effort-2')
    fireEvent.change(internal, { target: { value: '14' } })
    fireEvent.click(screen.getByTestId('costpos-effort-save-internal_effort-2'))
    await waitFor(() => expect(changesApi.updateCostPosition)
      .toHaveBeenCalledWith(7, 10, { hours: 14 }))
    expect(changesApi.createCostPosition).not.toHaveBeenCalled()
  })

  it('adds an external position — the only kind left to add', async () => {
    positions()
    await screen.findByTestId('costpos-new-2')
    // The kind picker is gone; what remains is what an external position needs.
    expect(screen.queryByTestId('costpos-new-kind-2')).toBeNull()
    expect(screen.getByTestId('costpos-new-hours-2').getAttribute('aria-label'))
      .toBe(t('costpos.ownTime'))
    fireEvent.change(screen.getByTestId('costpos-new-label-2'), { target: { value: 'Anlagenumbau' } })
    // The tag list is the backend's vocabulary, spelled out in both languages.
    await waitFor(() => expect(
      screen.getByTestId('costpos-new-tag-2').textContent,
    ).toContain(t('costtag.tool_change')))
    fireEvent.change(screen.getByTestId('costpos-new-tag-2'), { target: { value: 'tool_change' } })
    fireEvent.change(screen.getByTestId('costpos-new-est-2'), { target: { value: '1200' } })
    fireEvent.change(screen.getByTestId('costpos-new-hours-2'), { target: { value: '6' } })
    // The lead time is meaningless without saying which days are counted.
    fireEvent.change(screen.getByTestId('costpos-new-lead-2'), { target: { value: '10' } })
    fireEvent.change(screen.getByTestId('costpos-new-unit-2'), { target: { value: 'business_days' } })
    fireEvent.click(screen.getByTestId('costpos-add-2'))
    await waitFor(() => expect(changesApi.createCostPosition).toHaveBeenCalledWith(7,
      expect.objectContaining({
        department_id: 2, label: 'Anlagenumbau', tag: 'tool_change',
        kind: 'external', pricing: 'estimate', est_cost: 1200, hours: 6,
        lead_time_days: 10, lead_time_unit: 'business_days',
      })))
  })

  it('swaps the estimate for a vendor table when the price is quoted', async () => {
    positions()
    await screen.findByTestId('costpos-new-2')
    expect(screen.getByTestId('costpos-new-est-2')).toBeTruthy()
    fireEvent.change(screen.getByTestId('costpos-new-pricing-2'), { target: { value: 'quote' } })
    expect(screen.queryByTestId('costpos-new-est-2')).toBeNull()
    // Own time survives the switch — somebody still runs the vendor.
    expect(screen.getByTestId('costpos-new-hours-2')).toBeTruthy()
  })

  it('takes a free-text tag when the list does not have the word', async () => {
    positions()
    await screen.findByTestId('costpos-new-2')
    fireEvent.change(screen.getByTestId('costpos-new-label-2'), { target: { value: 'Sonderfall' } })
    fireEvent.change(screen.getByTestId('costpos-new-tag-2'), { target: { value: '__free' } })
    fireEvent.change(screen.getByTestId('costpos-new-tag-free-2'), { target: { value: 'Kalibrierung' } })
    fireEvent.click(screen.getByTestId('costpos-add-2'))
    await waitFor(() => expect(changesApi.createCostPosition).toHaveBeenCalledWith(7,
      expect.objectContaining({ tag: 'Kalibrierung', kind: 'external' })))
  })

  it('draws a quoted position as one row per vendor, shipping included or separate', async () => {
    positions()
    await screen.findByTestId('costpos-offers-11')
    expect(screen.getByTestId('offer-row-91')).toBeTruthy()
    expect(screen.getByTestId('offer-row-92')).toBeTruthy()
    // Writers edit the row in place; shipping is an amount unless the vendor
    // rolled it into the price.
    expect((screen.getByTestId('offer-vendor-91') as HTMLInputElement).value).toBe('Vendor A')
    expect((screen.getByTestId('offer-shipping-included-91') as HTMLInputElement).checked).toBe(false)
    expect(screen.getByTestId('offer-shipping-cost-91')).toBeTruthy()
    expect((screen.getByTestId('offer-shipping-included-92') as HTMLInputElement).checked).toBe(true)
    expect(screen.queryByTestId('offer-shipping-cost-92')).toBeNull()
    // The position shows what it is worth — the favourite offer's price and
    // its lead time, in the unit that offer was quoted in.
    expect(screen.getByTestId('costpos-cost-11').textContent).toContain('5200.00')
    expect(screen.getByTestId('costpos-lead-11').textContent)
      .toBe(`30 ${t('costpos.unitShort.business_days')}`)
  })

  it('reads the position’s price and lead time off whichever offer is starred', async () => {
    // Vendor B wins the vote: cheaper freight, shorter lead, different unit.
    vi.mocked(changesApi.listCostPositions).mockResolvedValue([{
      ...external,
      offers: external.offers.map((o) => ({ ...o, favorite: o.id === 92 })),
    }] as never)
    positions()
    await screen.findByTestId('costpos-row-11')
    // 5400 with freight included — nothing on top.
    expect(screen.getByTestId('costpos-cost-11').textContent).toContain('5400.00')
    expect(screen.getByTestId('costpos-lead-11').textContent)
      .toBe(`20 ${t('costpos.unitShort.calendar_days')}`)
    expect(screen.queryByTestId('costpos-needs-favorite-11')).toBeNull()
  })

  it('nags for a vote while a quoted position has none', async () => {
    vi.mocked(changesApi.listCostPositions).mockResolvedValue([{
      ...external,
      offers: external.offers.map((o) => ({ ...o, favorite: false })),
    }] as never)
    positions()
    await screen.findByTestId('costpos-row-11')
    expect(screen.getByTestId('costpos-needs-favorite-11').textContent)
      .toContain(t('costpos.pickFavorite'))
    // No vote, no price and no date — the job is not finished.
    expect(screen.getByTestId('costpos-cost-11').textContent).toBe('— + 6 h')
    expect(screen.queryByTestId('costpos-lead-11')).toBeNull()
  })

  it('adds the next vendor to a quoted position', async () => {
    positions()
    await screen.findByTestId('offer-new-11')
    fireEvent.change(screen.getByTestId('offer-new-vendor-11'), { target: { value: 'Vendor C' } })
    fireEvent.change(screen.getByTestId('offer-new-cost-11'), { target: { value: '4800' } })
    fireEvent.click(screen.getByTestId('offer-new-shipping-included-11'))
    fireEvent.change(screen.getByTestId('offer-new-lead-11'), { target: { value: '15' } })
    fireEvent.change(screen.getByTestId('offer-new-unit-11'), { target: { value: 'business_days' } })
    fireEvent.click(screen.getByTestId('offer-add-11'))
    await waitFor(() => expect(changesApi.addCostingOffer).toHaveBeenCalledWith(7, 11,
      expect.objectContaining({
        vendor_name: 'Vendor C', cost: 4800, shipping_included: true, shipping_cost: null,
        lead_time_days: 15, lead_time_unit: 'business_days',
      })))
  })

  it('keeps exactly one favourite when the department votes', async () => {
    positions()
    // The server clears the siblings; the list it hands back afterwards agrees
    // with what the click already showed.
    vi.mocked(changesApi.updateCostingOffer).mockImplementation((async () => {
      vi.mocked(changesApi.listCostPositions).mockResolvedValue([effort, {
        ...external,
        offers: external.offers.map((o) => ({ ...o, favorite: o.id === 92 })),
      }] as never)
      return {}
    }) as never)
    await screen.findByTestId('offer-fav-91')
    expect(screen.getByTestId('offer-fav-91').textContent).toBe('★')
    expect(screen.getByTestId('offer-fav-92').textContent).toBe('☆')
    fireEvent.click(screen.getByTestId('offer-fav-92'))
    await waitFor(() => expect(changesApi.updateCostingOffer)
      .toHaveBeenCalledWith(7, 92, { favorite: true }))
    // The star moves the moment it is clicked — the sibling goes dark with it.
    await waitFor(() => expect(screen.getByTestId('offer-fav-92').textContent).toBe('★'))
    expect(screen.getByTestId('offer-fav-91').textContent).toBe('☆')
  })

  it('gives a reader the figures and no input at all', async () => {
    positions({ editable: false })
    await screen.findByTestId('costpos-row-11')
    expect(screen.getByTestId('costpos-readonly-2').textContent).toBe(t('costpos.readOnly'))
    expect(screen.queryByTestId('costpos-new-2')).toBeNull()
    expect(screen.queryByTestId('offer-new-11')).toBeNull()
    expect(screen.queryByTestId('costpos-delete-11')).toBeNull()
    // The vote is still visible — Sales needs to know which vendor was chosen.
    expect(screen.getByTestId('offer-fav-91').textContent).toBe('★')
    expect(screen.getByTestId('offer-vendor-91').textContent).toBe('Vendor A')
    expect(screen.getByTestId('offer-shipping-92').textContent)
      .toContain(t('costpos.shippingIncluded'))
    expect(screen.getByTestId('offer-lead-91').textContent)
      .toBe(`30 ${t('costpos.unitShort.business_days')}`)
    // The effort answers read as plain text for someone who may not write them.
    expect(screen.getByTestId('costpos-effort-value-internal_effort-2').textContent).toBe('12')
    expect(screen.getByTestId('costpos-effort-value-support_effort-2').textContent).toBe('—')
    expect(screen.queryByTestId('costpos-effort-internal_effort-2')).toBeNull()
    // Tags read as words, in the labelled vocabulary.
    expect(screen.getByTestId('costpos-tag-11').textContent).toBe(t('costtag.equipment_change'))
    expect(screen.getByTestId('costpos-kind-11').textContent)
      .toContain(t('costpos.kind.external'))
  })
})

// The weight the part will come out at is Tooling's answer, and only theirs —
// an estimate on purpose, written straight onto the change.
describe('CostPositions — part weight', () => {
  beforeEach(() => {
    vi.mocked(changesApi.listCostPositions).mockResolvedValue([] as never)
    vi.mocked(changesApi.costingTags).mockResolvedValue(TAGS as never)
    vi.mocked(changesApi.setWeightEstimate).mockClear()
  })
  afterEach(cleanup)

  it('asks Tooling for the weight and nobody else', async () => {
    wrap(<CostPositions changeId={7} departmentId={2} editable
      departmentName="Tool Engineer" partWeightG={412} />)
    await waitFor(() => expect(
      (screen.getByTestId('costpos-weight-2') as HTMLInputElement).value,
    ).toBe('412'))
    // The label carries the caveat: it is a guess until somebody validates it.
    expect(screen.getByTestId('costpos-effort-2').textContent)
      .toContain(t('costpos.partWeightField'))
  })

  it('leaves the field out of another department’s block', async () => {
    wrap(<CostPositions changeId={7} departmentId={3} editable
      departmentName="Quality" partWeightG={412} />)
    await screen.findByTestId('costpos-effort-3')
    expect(screen.queryByTestId('costpos-weight-3')).toBeNull()
    expect(screen.queryByTestId('costpos-weight-value-3')).toBeNull()
  })

  it('saves the estimate when the field is left', async () => {
    wrap(<CostPositions changeId={7} departmentId={2} editable
      departmentName="Tool Engineer" partWeightG={null} />)
    const field = await screen.findByTestId('costpos-weight-2')
    fireEvent.change(field, { target: { value: '412' } })
    fireEvent.blur(field)
    await waitFor(() => expect(changesApi.setWeightEstimate).toHaveBeenCalledWith(7, 412))
  })

  it('gives a reader the number and no input', async () => {
    wrap(<CostPositions changeId={7} departmentId={2} editable={false}
      departmentName="Tool Engineer" partWeightG={412} />)
    await screen.findByTestId('costpos-weight-value-2')
    expect(screen.getByTestId('costpos-weight-value-2').textContent).toBe('412')
    expect(screen.queryByTestId('costpos-weight-2')).toBeNull()
  })
})

// Sales decides which offer is bought; the department reads the outcome of
// its own vote here, and cannot touch it.
describe('CostPositions — vendor decision', () => {
  beforeEach(() => {
    vi.mocked(changesApi.listCostPositions).mockResolvedValue([external] as never)
    vi.mocked(changesApi.costingTags).mockResolvedValue(TAGS as never)
  })
  afterEach(cleanup)

  // The engineer voted; Sales decided. The block says what happened to the vote
  // without offering to change it — the decision is not theirs to make here.
  it('shows Sales’ decision against the department’s recommendation, read-only', async () => {
    vi.mocked(changesApi.listCostPositions).mockResolvedValue([{
      ...external,
      offers: [
        { ...external.offers[0], favorite: true, chosen: false },
        { ...external.offers[1], favorite: false, chosen: true,
          chosen_reason: 'Liefertermin', chosen_by_name: 'Sara Sales',
          chosen_at: '2026-08-01T10:00:00Z' },
      ],
    }] as never)
    positions()
    const line = await screen.findByTestId('costpos-chosen-11')
    expect(line.textContent).toContain(t('vendor.salesChose'))
    expect(line.textContent).toContain('Vendor B')
    expect(line.textContent).toContain(t('vendor.againstRecommendation'))
    expect(line.textContent).toContain('Liefertermin')
    // Nothing to press: no choose control leaks into the department's block.
    expect(screen.queryByTestId('vendor-choose-92')).toBeNull()
    // The department's own figures still read off its favourite.
    expect(screen.getByTestId('costpos-cost-11').textContent).toContain('5200.00')
  })

  it('says nothing about a decision nobody has made', async () => {
    positions()
    await screen.findByTestId('costpos-row-11')
    expect(screen.queryByTestId('costpos-chosen-11')).toBeNull()
  })

  it('marks agreement without the divergence wording', async () => {
    vi.mocked(changesApi.listCostPositions).mockResolvedValue([{
      ...external,
      offers: [
        { ...external.offers[0], favorite: true, chosen: true,
          chosen_by_name: 'Sara Sales', chosen_at: '2026-08-01T10:00:00Z' },
        { ...external.offers[1], favorite: false, chosen: false },
      ],
    }] as never)
    positions()
    const line = await screen.findByTestId('costpos-chosen-11')
    expect(line.textContent).toContain('Vendor A')
    expect(line.textContent).not.toContain(t('vendor.againstRecommendation'))
  })
})
