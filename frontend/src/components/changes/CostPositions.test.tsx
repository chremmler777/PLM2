import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, within, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CostPositions from './CostPositions'
import { changesApi } from '../../api/changes'
import { costSheetMachinesApi } from '../../api/costSheetMachines'
import { t } from '../../i18n/cmLabels'
import { formatHours } from '../../lib/format'

vi.mock('../../api/changes', () => ({
  changesApi: {
    listCostPositions: vi.fn(),
    createCostPosition: vi.fn().mockResolvedValue({}),
    createCostCategory: vi.fn().mockResolvedValue({ id: 5, department_id: 2, key: 'd2_laser', label: 'Laser', entry_type: 'money' }),
    deleteCostCategory: vi.fn().mockResolvedValue({ id: 5 }),
    updateCostPosition: vi.fn().mockResolvedValue({}),
    deleteCostPosition: vi.fn().mockResolvedValue({}),
    addCostingOffer: vi.fn().mockResolvedValue({}),
    updateCostingOffer: vi.fn().mockResolvedValue({}),
    deleteCostingOffer: vi.fn().mockResolvedValue({}),
    setWeightEstimate: vi.fn().mockResolvedValue({}),
    costingTags: vi.fn(),
    listSuppliers: vi.fn().mockResolvedValue([{ id: 1, name: 'Hasco', is_active: true }]),
    createSupplier: vi.fn().mockResolvedValue({ id: 2, name: 'Meusburger' }),
    uploadAttachment: vi.fn().mockResolvedValue({}),
    costingContext: vi.fn().mockResolvedValue({
      plant_id: 1, plant_name: 'Toccoa', currency: 'USD', rate_source: 'cost_sheet',
      current_version: { id: 9, version: 2, valid_from: '2026-07-01' }, latest_version: 2,
      stale: null,
      machine_classes: [{ id: 3, name: '200-450 t', tonnage_min: 200, tonnage_max: 450 },
        { id: 4, name: '>450 t', tonnage_min: 450, tonnage_max: null }],
      machine_class_id: null, default_machine_class_id: 3, effective_machine_class_id: 3,
      tonnage: 350, positions_by_department: { '2': ['Engineer', 'Technician'] },
    }),
  },
}))

vi.mock('../../api/costSheetMachines', () => ({
  costSheetMachinesApi: { list: vi.fn().mockResolvedValue({ machines: [] }) },
}))

const TAGS = {
  items: [
    { key: 'tool_change', entry_type: 'money', extra: true },
    { key: 'equipment_change', entry_type: 'money', extra: true },
    { key: 'sampling', entry_type: 'time', extra: true },
    { key: 'trial_support', label_en: 'Trial support', entry_type: 'time', extra: true },
    { key: 'other', entry_type: 'money', extra: false },
  ],
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

  it('saves a standing row once when blur and the Save click arrive together (final walk P2-1)', async () => {
    // The create is still in flight (and the position not yet listed) when the
    // click lands: a second create would be a duplicate standing row.
    let resolve!: (v: unknown) => void
    vi.mocked(changesApi.createCostPosition).mockImplementationOnce(
      () => new Promise((r) => { resolve = r }) as never)
    positions()
    await screen.findByTestId('costpos-row-11')
    const support = screen.getByTestId('costpos-effort-support_effort-2')
    fireEvent.change(support, { target: { value: '16' } })
    fireEvent.blur(support)
    fireEvent.click(screen.getByTestId('costpos-effort-save-support_effort-2'))
    fireEvent.keyDown(support, { key: 'Enter' })
    await waitFor(() => expect(changesApi.createCostPosition).toHaveBeenCalled())
    resolve({ id: 77 })
    await waitFor(() => expect(changesApi.createCostPosition).toHaveBeenCalledTimes(1))
    // Even after the create answered, the row holds until the new position
    // arrives: no second create from a late click.
    fireEvent.click(screen.getByTestId('costpos-effort-save-support_effort-2'))
    fireEvent.blur(support)
    await new Promise((r) => setTimeout(r, 20))
    expect(changesApi.createCostPosition).toHaveBeenCalledTimes(1)
  })

  it('an hours change made while an hours save is in flight is sent when it settles (review M2)', async () => {
    let resolve!: (v: unknown) => void
    vi.mocked(changesApi.updateCostPosition).mockImplementationOnce(
      () => new Promise((r) => { resolve = r }) as never)
    positions()
    await waitFor(() => expect(
      (screen.getByTestId('costpos-effort-internal_effort-2') as HTMLInputElement).value,
    ).toBe('12'))
    const internal = screen.getByTestId('costpos-effort-internal_effort-2')
    fireEvent.change(internal, { target: { value: '14' } })
    fireEvent.click(screen.getByTestId('costpos-effort-save-internal_effort-2'))
    await waitFor(() => expect(changesApi.updateCostPosition).toHaveBeenCalledTimes(1))
    fireEvent.change(internal, { target: { value: '15' } })
    fireEvent.blur(internal)
    // Held while the first save is out, not dropped.
    expect(changesApi.updateCostPosition).toHaveBeenCalledTimes(1)
    resolve({})
    await waitFor(() => expect(changesApi.updateCostPosition)
      .toHaveBeenLastCalledWith(7, 10, { hours: 15 }))
    expect(changesApi.updateCostPosition).toHaveBeenCalledTimes(2)
  })

  it('after a create, a queued change goes out as an edit of the new position (review)', async () => {
    let resolveCreate!: (v: unknown) => void
    vi.mocked(changesApi.createCostPosition).mockImplementationOnce(
      () => new Promise((r) => { resolveCreate = r }) as never)
    positions()
    await screen.findByTestId('costpos-row-11')
    const support = screen.getByTestId('costpos-effort-support_effort-2')
    fireEvent.change(support, { target: { value: '16' } })
    fireEvent.blur(support)
    await waitFor(() => expect(changesApi.createCostPosition).toHaveBeenCalledTimes(1))
    // Changed while the create is out: queued, not dropped, not a second create.
    fireEvent.change(support, { target: { value: '18' } })
    fireEvent.blur(support)
    const listed = vi.mocked(changesApi.listCostPositions).mock.calls.length
    resolveCreate({ id: 77 })
    await waitFor(() => expect(changesApi.updateCostPosition)
      .toHaveBeenLastCalledWith(7, 77, { hours: 18 }))
    expect(changesApi.createCostPosition).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(vi.mocked(changesApi.listCostPositions).mock.calls.length).toBeGreaterThan(listed))
  })

  it('a failed queued edit still reloads the row', async () => {
    let resolveCreate!: (v: unknown) => void
    vi.mocked(changesApi.createCostPosition).mockImplementationOnce(
      () => new Promise((r) => { resolveCreate = r }) as never)
    vi.mocked(changesApi.updateCostPosition).mockRejectedValueOnce(new Error('no'))
    positions()
    await screen.findByTestId('costpos-row-11')
    const support = screen.getByTestId('costpos-effort-support_effort-2')
    fireEvent.change(support, { target: { value: '16' } })
    fireEvent.blur(support)
    await waitFor(() => expect(changesApi.createCostPosition).toHaveBeenCalledTimes(1))
    fireEvent.change(support, { target: { value: '18' } })
    fireEvent.blur(support)
    const listed = vi.mocked(changesApi.listCostPositions).mock.calls.length
    resolveCreate({ id: 77 })
    await waitFor(() => expect(changesApi.updateCostPosition).toHaveBeenCalledWith(7, 77, { hours: 18 }))
    await waitFor(() => expect(vi.mocked(changesApi.listCostPositions).mock.calls.length).toBeGreaterThan(listed))
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
    fireEvent.click(screen.getByTestId('costpos-new-pricing-2-quote'))
    expect(screen.queryByTestId('costpos-new-est-2')).toBeNull()
    // Own time survives the switch — somebody still runs the vendor.
    expect(screen.getByTestId('costpos-new-hours-2')).toBeTruthy()
  })

  it('makes a time category an own-time line: hours only, no money', async () => {
    positions()
    await screen.findByTestId('costpos-new-2')
    await waitFor(() => expect(screen.getByTestId('costpos-new-tag-2').textContent)
      .toContain('Trial support (hours)'))
    // The own-time "Sampling" category is not offered next to the cost sheet's
    // "Sampling (trials x price)": one word, one meaning.
    const values = [...(screen.getByTestId('costpos-new-tag-2') as HTMLSelectElement).options].map((o) => o.value)
    expect(values).not.toContain('sampling')
    expect(values).toContain('__sampling')
    fireEvent.change(screen.getByTestId('costpos-new-tag-2'), { target: { value: 'trial_support' } })
    // No pricing and no money field for hours; the amount is the hours.
    expect(screen.queryByTestId('costpos-new-pricing-2')).toBeNull()
    expect(screen.queryByTestId('costpos-new-est-2')).toBeNull()
    expect(screen.getByTestId('costpos-new-hours-2').getAttribute('aria-label')).toBe(t('costpos.hours'))
    fireEvent.change(screen.getByTestId('costpos-new-label-2'), { target: { value: '2 trial runs' } })
    fireEvent.change(screen.getByTestId('costpos-new-hours-2'), { target: { value: '8' } })
    fireEvent.keyDown(screen.getByTestId('costpos-new-hours-2'), { key: 'Enter' })
    await waitFor(() => expect(changesApi.createCostPosition).toHaveBeenCalledWith(7,
      expect.objectContaining({
        tag: 'trial_support', kind: 'own_time', pricing: 'estimate', hours: 8, est_cost: null,
        label: '2 trial runs',
      })))
  })

  it('lets the department add its own category, typed, and remove it again', async () => {
    positions()
    await screen.findByTestId('costpos-new-2')
    const select = screen.getByTestId('costpos-new-tag-2') as HTMLSelectElement
    await waitFor(() => expect([...select.options].map((o) => o.value)).toContain('__add_category'))
    fireEvent.change(select, { target: { value: '__add_category' } })
    fireEvent.change(screen.getByTestId('costpos-new-category-2'), { target: { value: 'Laser texturing' } })
    fireEvent.change(screen.getByTestId('costpos-new-category-type-2'), { target: { value: 'money' } })
    // Once created, the reference serves it back with its id: selected, removable.
    vi.mocked(changesApi.costingTags).mockResolvedValue({ items: [
      ...TAGS.items,
      { key: 'd2_laser', label_en: 'Laser texturing', entry_type: 'money', extra: true, custom_id: 5 },
    ] } as never)
    fireEvent.click(screen.getByTestId('costpos-new-category-save-2'))
    await waitFor(() => expect(changesApi.createCostCategory).toHaveBeenCalledWith(2, 'Laser texturing', 'money'))
    await waitFor(() => expect(select.value).toBe('d2_laser'))
    fireEvent.click(await screen.findByTestId('costpos-category-delete-2'))
    // Asks first.
    expect(changesApi.deleteCostCategory).not.toHaveBeenCalled()
    fireEvent.click(within(await screen.findByTestId('costpos-category-delete-confirm-2')).getByTestId('confirm-ok'))
    await waitFor(() => expect(changesApi.deleteCostCategory).toHaveBeenCalledWith(5))
  })

  it('offers the Suppliers list under the vendor field and stores a new name on save', async () => {
    positions()
    await screen.findByTestId('costpos-new-2')
    fireEvent.change(screen.getByTestId('costpos-new-tag-2'), { target: { value: 'tool_change' } })
    fireEvent.change(screen.getByTestId('costpos-new-label-2'), { target: { value: 'insert' } })
    // Known suppliers are offered; a new one typed here is created on add.
    const vendor = await screen.findByTestId('costpos-new-vendor-2') as HTMLInputElement
    await waitFor(() => expect(document.querySelector(`#${vendor.getAttribute('list')} option[value="Hasco"]`)).toBeTruthy())
    fireEvent.change(vendor, { target: { value: 'Meusburger' } })
    fireEvent.change(screen.getByTestId('costpos-new-est-2'), { target: { value: '300' } })
    fireEvent.click(screen.getByTestId('costpos-add-2'))
    await waitFor(() => expect(changesApi.createSupplier).toHaveBeenCalledWith('Meusburger'))
    await waitFor(() => expect(changesApi.createCostPosition).toHaveBeenCalledWith(7,
      expect.objectContaining({ vendor_name: 'Meusburger', est_cost: 300, pricing: 'estimate' })))
    // A quoted line carries no vendor of its own — the offers do.
    fireEvent.click(screen.getByTestId('costpos-new-pricing-2-quote'))
    expect(screen.queryByTestId('costpos-new-vendor-2')).toBeNull()
  })

  it('adds partial quotes up and puts the starred alternative on top; parts carry no star', async () => {
    vi.mocked(changesApi.listCostPositions).mockResolvedValue([{
      ...external, effective_cost: null,
      offers: [
        { id: 81, vendor_name: 'Steel', cost: 1000, shipping_cost: null, shipping_included: true,
          lead_time_days: 10, lead_time_unit: 'business_days', favorite: false, is_partial: true },
        { id: 82, vendor_name: 'Coating', cost: 250, shipping_cost: null, shipping_included: true,
          lead_time_days: 5, lead_time_unit: 'calendar_days', favorite: false, is_partial: true },
        { id: 83, vendor_name: 'Alt A', cost: 600, shipping_cost: null, shipping_included: true,
          lead_time_days: 30, lead_time_unit: 'calendar_days', favorite: true, is_partial: false },
        { id: 84, vendor_name: 'Alt B', cost: 700, shipping_cost: null, shipping_included: true,
          lead_time_days: null, lead_time_unit: null, favorite: false, is_partial: false },
      ],
    }] as never)
    positions()
    await screen.findByTestId('costpos-row-11')
    expect(screen.getByTestId('costpos-cost-11').textContent).toContain('1,850.00')
    expect(screen.getByTestId('costpos-lead-11').textContent)
      .toBe(`30 ${t('costpos.unitShort.calendar_days')}`)
    expect(screen.getByTestId('costpos-offer-summary-11').textContent)
      .toBe(`2 ${t('costpos.partsSum')} + 2 ${t('costpos.altSum')}`)
    expect(screen.getByTestId('offer-part-81')).toBeTruthy()
    expect(screen.queryByTestId('offer-fav-81')).toBeNull()
    expect(screen.getByTestId('offer-fav-83').getAttribute('aria-pressed')).toBe('true')
    // The new-offer form asks which kind it is and sends it along.
    fireEvent.change(screen.getByTestId('offer-new-vendor-11'), { target: { value: 'Vendor P' } })
    fireEvent.change(screen.getByTestId('offer-new-cost-11'), { target: { value: '100' } })
    fireEvent.click(screen.getByTestId('offer-new-scope-11-partial'))
    fireEvent.click(screen.getByTestId('offer-add-11'))
    await waitFor(() => expect(changesApi.addCostingOffer).toHaveBeenCalledWith(7, 11,
      expect.objectContaining({ vendor_name: 'Vendor P', is_partial: true })))
  })

  it('sums the department’s money and hours at the foot of the table', async () => {
    positions()
    await screen.findByTestId('costpos-row-11')
    // 5200 from the favourite offer; 12 h standing + 6 h around the vendor.
    const total = screen.getByTestId('costpos-total-2').textContent
    expect(total).toContain('5,200.00')
    expect(total).toContain(formatHours(18))
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
    expect(screen.getByTestId('costpos-cost-11').textContent).toContain('5,200.00')
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
    expect(screen.getByTestId('costpos-cost-11').textContent).toContain('5,400.00')
    expect(screen.getByTestId('costpos-lead-11').textContent)
      .toBe(`20 ${t('costpos.unitShort.calendar_days')}`)
    expect(screen.queryByTestId('costpos-needs-favorite-11')).toBeNull()
  })

  it('prices a single offer without a vote and reads its lead time', async () => {
    vi.mocked(changesApi.listCostPositions).mockResolvedValue([{
      ...external, effective_cost: 5200,
      offers: [{ ...external.offers[0], favorite: false }],
    }] as never)
    positions()
    await screen.findByTestId('costpos-row-11')
    expect(screen.queryByTestId('costpos-needs-favorite-11')).toBeNull()
    expect(screen.getByTestId('costpos-lead-11').textContent)
      .toBe(`30 ${t('costpos.unitShort.business_days')}`)
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
    // No vote, no price and no date — the job is not finished. Hours alone
    // (own coordination time) still show; there is no "-" for the missing
    // price once something real is known.
    expect(screen.getByTestId('costpos-cost-11').textContent).toBe(formatHours(6))
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
    expect(screen.getByTestId('offer-fav-91').getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByTestId('offer-fav-92').getAttribute('aria-pressed')).toBe('false')
    fireEvent.click(screen.getByTestId('offer-fav-92'))
    await waitFor(() => expect(changesApi.updateCostingOffer)
      .toHaveBeenCalledWith(7, 92, { favorite: true }))
    // The star moves the moment it is clicked — the sibling goes dark with it.
    await waitFor(() => expect(screen.getByTestId('offer-fav-92').getAttribute('aria-pressed')).toBe('true'))
    expect(screen.getByTestId('offer-fav-91').getAttribute('aria-pressed')).toBe('false')
  })

  it('deletes a cost line only after a confirm, and names the line on the delete button', async () => {
    vi.mocked(changesApi.deleteCostPosition).mockClear()
    positions()
    const del = await screen.findByTestId('costpos-delete-11')
    expect(del.getAttribute('aria-label')).toBe('Delete cost line: Anlagenumbau')
    fireEvent.click(del)
    expect(changesApi.deleteCostPosition).not.toHaveBeenCalled()
    const dialog = await screen.findByTestId('costpos-delete-confirm-11')
    expect(dialog.textContent).toContain('2 vendor offers')
    // Cancel keeps it.
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(changesApi.deleteCostPosition).not.toHaveBeenCalled()
    fireEvent.click(screen.getByTestId('costpos-delete-11'))
    fireEvent.click(await screen.findByRole('button', { name: 'Delete line' }))
    await waitFor(() => expect(changesApi.deleteCostPosition).toHaveBeenCalledWith(7, 11))
  })

  it('deletes a vendor offer only after a confirm', async () => {
    vi.mocked(changesApi.deleteCostingOffer).mockClear()
    positions()
    const del = await screen.findByTestId('offer-delete-92')
    expect(del.getAttribute('aria-label')).toBe('Delete the offer from Vendor B')
    fireEvent.click(del)
    expect(changesApi.deleteCostingOffer).not.toHaveBeenCalled()
    fireEvent.click(await screen.findByRole('button', { name: 'Delete offer' }))
    await waitFor(() => expect(changesApi.deleteCostingOffer).toHaveBeenCalledWith(7, 92))
  })

  it('shows a plain amount, not a guessed EUR, while the currency is unknown (review)', async () => {
    vi.mocked(changesApi.costingContext).mockRejectedValueOnce(new Error('not yet'))
    positions({ editable: false })
    await screen.findByTestId('offer-cost-91')
    expect(screen.getByTestId('offer-cost-91').textContent).toBe('5,000.00')
    expect(screen.getByTestId('offer-shipping-91').textContent).not.toContain('EUR')
  })

  it('gives a reader the figures and no input at all', async () => {
    positions({ editable: false })
    await screen.findByTestId('costpos-row-11')
    expect(screen.getByTestId('costpos-readonly-2').textContent).toBe(t('costpos.readOnly'))
    expect(screen.queryByTestId('costpos-new-2')).toBeNull()
    expect(screen.queryByTestId('offer-new-11')).toBeNull()
    expect(screen.queryByTestId('costpos-delete-11')).toBeNull()
    // The vote is still visible — Sales needs to know which vendor was chosen.
    expect(screen.getByTestId('offer-fav-91').textContent).toBe(t('costpos.favorite'))
    expect(screen.getByTestId('offer-fav-92').textContent).toBe('')
    expect(screen.getByTestId('offer-vendor-91').textContent).toBe('Vendor A')
    expect(screen.getByTestId('offer-shipping-92').textContent)
      .toContain(t('costpos.shippingIncluded'))
    expect(screen.getByTestId('offer-lead-91').textContent)
      .toBe(`30 ${t('costpos.unitShort.business_days')}`)
    // The effort answers read as plain text for someone who may not write them.
    expect(screen.getByTestId('costpos-effort-value-internal_effort-2').textContent).toBe('12')
    expect(screen.getByTestId('costpos-effort-value-support_effort-2').textContent).toBe('-')
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
    expect(screen.getByTestId('costpos-cost-11').textContent).toContain('5,200.00')
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

describe('CostPositions — cost sheet pricing (spec §15 phase 2)', () => {
  const priced = {
    id: 20, department_id: 2, label: 'Rework drawing', tag: 'sampling', kind: 'own_time',
    pricing: 'estimate', est_cost: null, hours: 5, lead_time_days: null, notes: null,
    effective_cost: null, offers: [], labour_position: 'Engineer',
    rate: 21.5, rate_currency: 'USD', currency: 'USD', rate_unit: 'h',
    rate_source: 'cost_sheet', cost_sheet_version: 2,
    rate_label: 'Cost sheet v2, Tool Engineer, Engineer, 21.50 USD/h',
    rate_missing: false, line_value: 107.5,
  }
  const machine = {
    id: 21, department_id: 2, label: 'Press trial', tag: null, kind: 'machine_time',
    pricing: 'estimate', est_cost: null, hours: 3, lead_time_days: null, notes: null,
    effective_cost: null, offers: [], machine_class_id: 3, machine_class: '200-450 t',
    rate: 85, rate_currency: 'USD', currency: 'USD', rate_unit: 'h',
    rate_label: 'Cost sheet v2, Machine 200-450 t, 85.00 USD/h', rate_missing: false,
    line_value: 255,
  }
  const sampling = {
    id: 22, department_id: 2, label: 'T1', tag: null, kind: 'sampling', pricing: 'estimate',
    est_cost: null, hours: null, trials: 2, lead_time_days: null, notes: null,
    effective_cost: null, offers: [], machine_class_id: 3, machine_class: '200-450 t',
    rate: 1250, rate_currency: 'USD', currency: 'USD', rate_unit: 'trial',
    rate_label: 'Cost sheet v2, Sampling 200-450 t, 1,250.00 USD/trial', rate_missing: false,
    line_value: 2500,
  }
  const missing = {
    id: 23, department_id: 2, label: 'Unrated work', tag: 'sampling', kind: 'own_time',
    pricing: 'estimate', est_cost: null, hours: 4, lead_time_days: null, notes: null,
    effective_cost: null, offers: [], rate: null, currency: 'USD', rate_unit: 'h',
    rate_label: 'No rate in the cost sheet', rate_missing: true, line_value: null,
  }

  beforeEach(() => {
    vi.mocked(changesApi.listCostPositions).mockResolvedValue(
      [priced, machine, sampling, missing] as never)
    vi.mocked(changesApi.costingTags).mockResolvedValue(TAGS as never)
    vi.mocked(changesApi.createCostPosition).mockClear()
  })
  afterEach(cleanup)

  it('shows where each rate comes from and the line value in its currency', async () => {
    positions()
    expect((await screen.findByTestId('costpos-rate-20')).textContent)
      .toBe('Cost sheet v2, Tool Engineer, Engineer, 21.50 USD/h')
    expect(screen.getByTestId('costpos-value-20').textContent).toBe('107.50 USD')
    expect(screen.getByTestId('costpos-cost-21').textContent).toBe(formatHours(3))
    expect(screen.getByTestId('costpos-value-21').textContent).toBe('255.00 USD')
    expect(screen.getByTestId('costpos-kind-21').textContent).toContain('200-450 t')
    expect(screen.getByTestId('costpos-cost-22').textContent).toBe(`2 ${t('costpos.trialsShort')}`)
    expect(screen.getByTestId('costpos-value-22').textContent).toBe('2,500.00 USD')
  })

  it('says "No rate in the cost sheet" and keeps the line out of the total', async () => {
    positions()
    expect((await screen.findByTestId('costpos-norate-23')).textContent).toBe(t('costpos.noRate'))
    expect(screen.queryByTestId('costpos-value-23')).toBeNull()
    const total = screen.getByTestId('costpos-total-2').textContent ?? ''
    // 107.50 + 255 + 2,500 = 2,862.50 USD; the unrated 4 h are not a zero
    expect(total).toContain('2,862.50 USD')
    expect(screen.getByTestId('costpos-unpriced-2').textContent)
      .toBe(t('costpos.unpricedInTotal').replace('{n}', '1'))
  })

  it('adds a machine time line on the change’s class and a sampling line by trials', async () => {
    positions()
    await screen.findByTestId('costpos-row-20')
    fireEvent.change(screen.getByTestId('costpos-new-tag-2'), { target: { value: '__machine_time' } })
    await waitFor(() => expect(
      (screen.getByTestId('costpos-new-class-2') as HTMLSelectElement).value).toBe('3'))
    fireEvent.change(screen.getByTestId('costpos-new-hours-2'), { target: { value: '4' } })
    fireEvent.click(screen.getByTestId('costpos-add-2'))
    await waitFor(() => expect(changesApi.createCostPosition).toHaveBeenCalledWith(7,
      expect.objectContaining({ kind: 'machine_time', hours: 4, machine_class_id: 3,
        label: t('costpos.type.machine') })))

    fireEvent.change(screen.getByTestId('costpos-new-tag-2'), { target: { value: '__sampling' } })
    fireEvent.change(screen.getByTestId('costpos-new-class-2'), { target: { value: '4' } })
    fireEvent.change(screen.getByTestId('costpos-new-trials-2'), { target: { value: '2' } })
    fireEvent.change(screen.getByTestId('costpos-new-label-2'), { target: { value: 'T2' } })
    fireEvent.click(screen.getByTestId('costpos-add-2'))
    await waitFor(() => expect(changesApi.createCostPosition).toHaveBeenLastCalledWith(7,
      expect.objectContaining({ kind: 'sampling', trials: 2, machine_class_id: 4, hours: null })))
  })

  it('picks machines from the change\'s pricing version and keeps an inactive one on its line', async () => {
    const press = (over: Record<string, unknown>) => ({
      id: 1, internal_name: 'P-350', plant_id: 1, clamping_force_t: 350, active: true,
      hourly_rate: null, ...over })
    vi.mocked(costSheetMachinesApi.list).mockResolvedValue({ machines: [
      press({}),
      press({ id: 2, internal_name: 'P-300 old', active: false }),
      press({ id: 3, internal_name: 'P-400 other plant', plant_id: 8 }),
      press({ id: 4, internal_name: 'P-900 other class', clamping_force_t: 900 }),
    ] } as never)
    vi.mocked(changesApi.listCostPositions).mockResolvedValue(
      [{ ...machine, machine_id: 2, machine_name: 'P-300 old' }] as never)
    positions()
    fireEvent.click(await screen.findByTestId('costpos-edit-21'))
    const pick = await screen.findByTestId('costpos-edit-machine-21') as HTMLSelectElement
    // the version valid on the change's creation date, not today's
    expect(costSheetMachinesApi.list).toHaveBeenCalledWith({ version_id: 9 })
    await waitFor(() => expect(pick.options).toHaveLength(3))
    expect(pick.value).toBe('2')
    const names = [...pick.options].map((o) => o.textContent)
    expect(names).toEqual([t('costpos.machineAny'), 'P-350 · 350 t',
      `P-300 old · 350 t (${t('costpos.machineInactive')})`])
  })

  it('offers no labour position on an own-time line: one rate per department', async () => {
    positions()
    await screen.findByTestId('costpos-row-20')
    fireEvent.change(screen.getByTestId('costpos-new-tag-2'), { target: { value: 'trial_support' } })
    expect(screen.queryByTestId('costpos-new-position-2')).toBeNull()
    fireEvent.change(screen.getByTestId('costpos-new-label-2'), { target: { value: 'Check' } })
    fireEvent.change(screen.getByTestId('costpos-new-hours-2'), { target: { value: '2' } })
    fireEvent.click(screen.getByTestId('costpos-add-2'))
    await waitFor(() => expect(changesApi.createCostPosition).toHaveBeenCalledWith(7,
      expect.objectContaining({ kind: 'own_time', hours: 2 })))
    const calls = vi.mocked(changesApi.createCostPosition).mock.calls
    const body = calls[calls.length - 1][1] as unknown as Record<string, unknown>
    expect('labour_position' in body).toBe(false)
  })
})
