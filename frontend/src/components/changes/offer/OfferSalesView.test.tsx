/**
 * Christoph 2026-11-09: Sales sees all risks and writes his own, adds other
 * notes, picks cost blocks and supplier quotes, puts a multiplier / overhead
 * on top (never a CBD row), reads the internal breakdown, and finishes with
 * one ZIP; the sent version says who offered it when.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { OfferData, OfferOut } from '../../../types/changeOffer'
import { factorShown } from '../../../types/changeOffer'
import OfferRisksSection from './OfferRisksSection'
import { OfferInternalBreakdown, QuotePicker, SalesMarkupCard } from './OfferSalesBlocks'
import { customerCbd } from './customerCbd'
import { OfferedStamp, PackageButton } from './OfferTab'
import { changeOfferApi } from '../../../api/changeOffer'

vi.mock('../../../api/changeOffer', () => ({
  changeOfferApi: { packageZip: vi.fn() },
}))
vi.mock('../../../api/changes', () => ({ changesApi: {} }))
vi.mock('../../../api/changePlan', () => ({ planApi: { get: vi.fn() } }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

function Harness({ initial, onData, children }: {
  initial: OfferData
  onData: (d: OfferData) => void
  children: (data: OfferData, update: <K extends keyof OfferData>(k: K, v: OfferData[K]) => void) => React.ReactNode
}) {
  const [data, setData] = useState(initial)
  const update = <K extends keyof OfferData>(k: K, v: OfferData[K]) => {
    setData((d) => { const n = { ...d, [k]: v }; onData(n); return n })
  }
  return <>{children(data, update)}</>
}

const totals = {
  base: 1500, factors: [{ key: 'sales_multiplier', label: 'Sales multiplier', amount: 225, show: false }],
  risks_total: 0, scrap: 0, free: 0, total_one_time: 1725, internal_cost: 1600,
  margin_abs: 125, margin_pct: 7.25, sales_markup: 225,
  by_department: [{ department: 'Tool Engineer', amount: 1000, lines: 1 }, { department: 'Design', amount: 500, lines: 1 }],
}

describe('Sales view of the offer', () => {
  afterEach(cleanup)
  beforeEach(() => { vi.clearAllMocks() })

  it('shows every risk source and lets Sales add an own risk and other notes', () => {
    let last: OfferData = {}
    render(
      <Harness onData={(d) => { last = d }} initial={{ risks: [
        { key: 'c:1', source: 'risk', concern_id: 1, label: 'Sink marks', severity: 2, show: false, type: 'pct', value: 0 },
        { key: 'a:2', source: 'assumption', concern_id: null, label: 'Assumed: wall 2.5 mm', show: false, type: 'pct', value: 0 },
        { key: 'e:3', source: 'estimate', concern_id: null, label: 'Priced on an estimate: insert', show: false, type: 'pct', value: 0 },
      ] }}>
        {(data, update) => <OfferRisksSection data={data} update={update} editable currency="EUR" risksTotal={0} />}
      </Harness>)
    expect(screen.getByTestId('risk-source-1').textContent).toBe('Risk register')
    expect(screen.getByTestId('risk-source-a:2').textContent).toBe('Open assumption')
    expect(screen.getByTestId('risk-source-e:3').textContent).toBe('Costing estimate')
    fireEvent.click(screen.getByTestId('risk-add-own'))
    const own = last.risks!.find((r) => r.source === 'sales')!
    expect(own.show).toBe(true)
    fireEvent.change(screen.getByTestId(`risk-text-${own.key}`), { target: { value: 'Resin not released' } })
    expect(last.risks!.find((r) => r.source === 'sales')!.label).toBe('Resin not released')
    fireEvent.change(screen.getByTestId('offer-other-notes'), { target: { value: 'Excludes PPAP 3' } })
    expect(last.other_notes).toBe('Excludes PPAP 3')
    fireEvent.click(screen.getByTestId(`risk-remove-${own.key}`))
    expect(last.risks!.some((r) => r.source === 'sales')).toBe(false)
  })

  it('the multiplier is a hidden factor, folded into the CBD rows', () => {
    let last: OfferData = {}
    render(
      <Harness onData={(d) => { last = d }} initial={{ factors: [] }}>
        {(data, update) => <SalesMarkupCard data={data} update={update} editable currency="EUR" />}
      </Harness>)
    fireEvent.change(screen.getByTestId('markup-multiplier'), { target: { value: '1.15' } })
    const f = last.factors!.find((x) => x.key === 'sales_multiplier')!
    expect(f).toMatchObject({ type: 'multiplier', value: 1.15, enabled: true, show: false })
    // even a stray show: true never makes it a row
    expect(factorShown({ key: 'sales_multiplier', show: true })).toBe(false)
    const rows = customerCbd({
      cost_lines: [
        { key: 'a', label: 'Tool', category: 'external', amount: 1000, include: true, customer_category: 'Tooling' },
        { key: 'b', label: 'Design', category: 'internal', amount: 500, include: true, customer_category: 'Engineering' },
      ],
    }, totals)
    expect(rows.map((r) => r.label)).toEqual(['Engineering', 'Tooling'])
    expect(rows.reduce((s, r) => s + r.amount, 0)).toBeCloseTo(1725, 2)
  })

  it('the internal breakdown says who is doing what, the markup, price and margin', () => {
    render(<OfferInternalBreakdown offer={{ currency: 'EUR', totals } as unknown as OfferOut} />)
    expect(screen.getByTestId('breakdown-dept-Tool Engineer').textContent).toContain('1,000.00')
    expect(screen.getByTestId('breakdown-markup').textContent).toContain('225.00')
    expect(screen.getByTestId('breakdown-price').textContent).toContain('1,725.00')
    expect(screen.getByTestId('breakdown-margin').textContent).toContain('125.00')
  })

  it('picking a quote against the favourite asks for a reason first', () => {
    const onChoose = vi.fn()
    render(<QuotePicker lineKey="pos:9" currency="EUR" onChoose={onChoose} selected={1} quotes={[
      { offer_id: 1, vendor: 'Hasco', total: 1000, recommended: true, chosen: false },
      { offer_id: 2, vendor: 'Meusburger', total: 900, recommended: false, chosen: false },
    ]} />)
    fireEvent.change(screen.getByTestId('quote-pick-pos:9'), { target: { value: '2' } })
    expect(onChoose).not.toHaveBeenCalled()
    const confirm = screen.getByTestId('quote-confirm-pos:9') as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('Reason for choosing against the recommendation'),
      { target: { value: 'cheaper, same steel' } })
    fireEvent.click(confirm)
    expect(onChoose).toHaveBeenCalledWith(2, 'cheaper, same steel')
  })

  it('Download all (ZIP) packs the offer and is busy while it does', async () => {
    let resolve: (b: Blob) => void = () => {}
    vi.mocked(changeOfferApi.packageZip).mockReturnValue(new Promise<Blob>((r) => { resolve = r }))
    const create = vi.fn(() => 'blob:x')
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() })
    render(<QueryClientProvider client={new QueryClient()}>
      <PackageButton changeId={7} offer={{ id: 11, version: 2 } as OfferOut} />
    </QueryClientProvider>)
    const btn = screen.getByTestId('offer-package') as HTMLButtonElement
    expect(btn.disabled).toBe(false)
    fireEvent.click(btn)
    await waitFor(() => expect(btn.disabled).toBe(true))
    expect(btn.textContent).toBe('Packing')
    expect(changeOfferApi.packageZip).toHaveBeenCalledWith(7, 11)
    resolve(new Blob(['zip']))
    await waitFor(() => expect(btn.disabled).toBe(false))
    expect(create).toHaveBeenCalled()
  })

  it('a sent version says who offered it when; a draft says nothing', () => {
    const { rerender } = render(<OfferedStamp offer={{ status: 'draft', version: 1, sent_at: null }} />)
    expect(screen.queryByTestId('offer-offered-stamp')).toBeNull()
    rerender(<OfferedStamp offer={{ status: 'sent', version: 1, sent_at: '2026-11-09T09:00:00', sent_by_name: 'Karl' }} />)
    const text = screen.getByTestId('offer-offered-stamp').textContent ?? ''
    expect(text).toContain('offered on')
    expect(text).toContain('by Karl')
  })
})
