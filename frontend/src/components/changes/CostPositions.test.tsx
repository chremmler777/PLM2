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
    costingTags: vi.fn(),
    uploadAttachment: vi.fn().mockResolvedValue({}),
  },
}))

const TAGS = {
  items: [{ key: 'tool_change' }, { key: 'equipment_change' }, { key: 'other' }],
}

const external = {
  id: 11, department_id: 2, label: 'Anlagenumbau', tag: 'equipment_change',
  kind: 'external', pricing: 'quote', est_cost: null, hours: null,
  lead_time_days: 30, notes: null, effective_cost: 5200,
  offers: [
    { id: 91, vendor_name: 'Vendor A', cost: 5000, shipping_cost: 200,
      shipping_included: false, lead_time_days: 30, favorite: true },
    { id: 92, vendor_name: 'Vendor B', cost: 5400, shipping_cost: null,
      shipping_included: true, lead_time_days: 20, favorite: false },
  ],
}

const effort = {
  id: 10, department_id: 2, label: 'Moldflow-Lauf', tag: 'moldflow',
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
    vi.mocked(changesApi.addCostingOffer).mockClear()
    vi.mocked(changesApi.updateCostingOffer).mockClear()
  })
  afterEach(cleanup)

  it('adds an internal-effort position with its tag and hours', async () => {
    positions()
    await screen.findByTestId('costpos-new-2')
    fireEvent.change(screen.getByTestId('costpos-new-label-2'), { target: { value: 'Moldflow' } })
    // The tag list is the backend's vocabulary, spelled out in both languages.
    await waitFor(() => expect(
      screen.getByTestId('costpos-new-tag-2').textContent,
    ).toContain(t('costtag.tool_change')))
    fireEvent.change(screen.getByTestId('costpos-new-tag-2'), { target: { value: 'tool_change' } })
    fireEvent.change(screen.getByTestId('costpos-new-hours-2'), { target: { value: '8' } })
    fireEvent.click(screen.getByTestId('costpos-add-2'))
    await waitFor(() => expect(changesApi.createCostPosition).toHaveBeenCalledWith(7,
      expect.objectContaining({
        department_id: 2, label: 'Moldflow', tag: 'tool_change',
        kind: 'internal_effort', hours: 8, pricing: null,
      })))
  })

  it('asks for hours per effort kind and for a price basis when external', async () => {
    positions()
    const kind = await screen.findByTestId('costpos-new-kind-2')
    // Effort kinds want hours, no pricing toggle.
    expect(screen.getByTestId('costpos-new-hours-2')).toBeTruthy()
    expect(screen.queryByTestId('costpos-new-pricing-2')).toBeNull()

    fireEvent.change(kind, { target: { value: 'support_effort' } })
    expect(screen.getByTestId('costpos-new-hours-2')).toBeTruthy()

    // External asks estimate-or-quote; an estimate wants a number, a quote
    // wants vendors instead.
    fireEvent.change(kind, { target: { value: 'external' } })
    expect(screen.queryByTestId('costpos-new-hours-2')).toBeNull()
    expect(screen.getByTestId('costpos-new-est-2')).toBeTruthy()
    fireEvent.change(screen.getByTestId('costpos-new-pricing-2'), { target: { value: 'quote' } })
    expect(screen.queryByTestId('costpos-new-est-2')).toBeNull()
  })

  it('takes a free-text tag when the list does not have the word', async () => {
    positions()
    await screen.findByTestId('costpos-new-2')
    fireEvent.change(screen.getByTestId('costpos-new-label-2'), { target: { value: 'Sonderfall' } })
    fireEvent.change(screen.getByTestId('costpos-new-tag-2'), { target: { value: '__free' } })
    fireEvent.change(screen.getByTestId('costpos-new-tag-free-2'), { target: { value: 'Kalibrierung' } })
    fireEvent.click(screen.getByTestId('costpos-add-2'))
    await waitFor(() => expect(changesApi.createCostPosition).toHaveBeenCalledWith(7,
      expect.objectContaining({ tag: 'Kalibrierung' })))
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
    // The position shows what it is worth — the favourite offer's price.
    expect(screen.getByTestId('costpos-cost-11').textContent).toBe('5200.00')
  })

  it('adds the next vendor to a quoted position', async () => {
    positions()
    await screen.findByTestId('offer-new-11')
    fireEvent.change(screen.getByTestId('offer-new-vendor-11'), { target: { value: 'Vendor C' } })
    fireEvent.change(screen.getByTestId('offer-new-cost-11'), { target: { value: '4800' } })
    fireEvent.click(screen.getByTestId('offer-new-shipping-included-11'))
    fireEvent.click(screen.getByTestId('offer-add-11'))
    await waitFor(() => expect(changesApi.addCostingOffer).toHaveBeenCalledWith(7, 11,
      expect.objectContaining({
        vendor_name: 'Vendor C', cost: 4800, shipping_included: true, shipping_cost: null,
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
    // Tags read as words, in the labelled vocabulary.
    expect(screen.getByTestId('costpos-tag-10').textContent).toBe(t('costtag.moldflow'))
    expect(screen.getByTestId('costpos-kind-10').textContent)
      .toContain(t('costpos.kind.internal_effort'))
  })
})
