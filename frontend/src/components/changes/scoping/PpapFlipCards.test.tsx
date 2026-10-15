import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CustomerFlipCard, PpapDecisionCard } from './PpapFlipCards'
import { changesApi } from '../../../api/changes'
import { t } from '../../../i18n/cmLabels'

vi.mock('../../../api/changes', () => ({
  changesApi: {
    ppapDecision: vi.fn().mockResolvedValue({}),
    answerCustomerFlip: vi.fn().mockResolvedValue({}),
  },
}))
vi.mock('../../gantt/DateInput', () => ({
  default: (p: { value: string; onChange: (v: string) => void }) => (
    <input data-testid="date" value={p.value} onChange={(e) => p.onChange(e.target.value)} />
  ),
}))

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)
const change = (over: Record<string, unknown> = {}) => ({
  id: 7, status: 'scoping', customer_relevant: false, origin: 'internal',
  impacted_items: [{ id: 1, part_id: 21, part_number: '886.197' }], ...over,
}) as never

afterEach(() => { cleanup(); vi.clearAllMocks() })

describe('PpapDecisionCard', () => {
  it('yes with no impacted parts yet names the lead who adds them first', () => {
    render(wrap(<PpapDecisionCard change={change({ impacted_items: [], lead_name: 'Holmes' })}
      isQuality editable onChanged={() => {}} />))
    fireEvent.click(screen.getByTestId('ppap-yes'))
    expect(screen.getByTestId('ppap-no-parts').textContent).toContain('Holmes adds them first')
    expect((screen.getByTestId('ppap-save') as HTMLButtonElement).disabled).toBe(true)
  })

  it('Quality answers no with basis and reference; nothing preselected', async () => {
    render(wrap(<PpapDecisionCard change={change()} isQuality editable onChanged={() => {}} />))
    expect(screen.queryByTestId('ppap-save')).toBeNull()
    fireEvent.click(screen.getByTestId('ppap-no'))
    const save = screen.getByTestId('ppap-save') as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('ppap-basis'), { target: { value: 'control_plan' } })
    fireEvent.change(screen.getByTestId('ppap-ref'), { target: { value: 'ok' } })
    expect(save.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('ppap-ref'), { target: { value: 'CP-4711 rev 3' } })
    fireEvent.click(save)
    await waitFor(() => expect(changesApi.ppapDecision).toHaveBeenCalledWith(7,
      { answer: 'no', basis: 'control_plan', ref: 'CP-4711 rev 3' }))
  })

  it('yes needs the parts and says Sales gets a task', async () => {
    render(wrap(<PpapDecisionCard change={change()} isQuality editable onChanged={() => {}} />))
    fireEvent.click(screen.getByTestId('ppap-yes'))
    expect(screen.getByText(t('ppap.yesMeans'))).toBeTruthy()
    expect((screen.getByTestId('ppap-save') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByTestId('ppap-part-21'))
    fireEvent.click(screen.getByTestId('ppap-save'))
    await waitFor(() => expect(changesApi.ppapDecision).toHaveBeenCalledWith(7,
      { answer: 'yes', part_ids: [21] }))
  })

  it('anyone else reads who owes it, no controls', () => {
    render(wrap(<PpapDecisionCard change={change()} isQuality={false} editable onChanged={() => {}} />))
    expect(screen.getByTestId('ppap-owner').textContent).toBe(t('ppap.qualityOwes'))
    expect(screen.queryByTestId('ppap-no')).toBeNull()
  })
})

describe('CustomerFlipCard', () => {
  const flipped = change({ customer_relevant: true, origin: 'customer',
    customer_flip_at: '2026-10-15T10:00:00Z', customer_flip_reason: 'ppap_decision yes',
    sales_owner_name: 'Sally' })
  it('Sales answers offer needed with the quote deadline', async () => {
    render(wrap(<CustomerFlipCard change={flipped} isSales editable attachments={[]}
      onChanged={() => {}} />))
    fireEvent.click(screen.getByTestId('flip-offer'))
    const save = screen.getByTestId('flip-save') as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('date'), { target: { value: '2026-11-20' } })
    fireEvent.click(save)
    await waitFor(() => expect(changesApi.answerCustomerFlip).toHaveBeenCalledWith(7,
      { answer: 'offer', quote_deadline: '2026-11-20T12:00:00' }))
  })

  it('notification only needs a mail or a real reference', () => {
    render(wrap(<CustomerFlipCard change={flipped} isSales editable attachments={[]}
      onChanged={() => {}} />))
    fireEvent.click(screen.getByTestId('flip-notification'))
    fireEvent.change(screen.getByTestId('flip-ref'), { target: { value: 'tbd' } })
    expect((screen.getByTestId('flip-save') as HTMLButtonElement).disabled).toBe(true)
  })

  it('not Sales: names who answers', () => {
    render(wrap(<CustomerFlipCard change={flipped} isSales={false} editable attachments={[]}
      onChanged={() => {}} />))
    expect(screen.getByTestId('flip-owner').textContent).toContain('Sally')
    expect(screen.queryByTestId('flip-offer')).toBeNull()
  })
})
