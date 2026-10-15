import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { NeedByCheck, NeedByLine, NeedByTellCard, ProblemTargetEditor, needByHold, okRef, urgentMissing, workingDaysLeft } from './CaptureV2'
import { PriorityEditor } from './PriorityEditor'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

vi.mock('../../api/changes', () => ({
  changesApi: { update: vi.fn().mockResolvedValue({}), needByTell: vi.fn().mockResolvedValue({}) },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../gantt/DateInput', () => ({
  default: (p: { value: string; onChange: (v: string) => void; 'aria-label'?: string }) => (
    <input aria-label={p['aria-label']} value={p.value} onChange={(e) => p.onChange(e.target.value)} />
  ),
}))

const wrap = (ui: React.ReactElement) => render(
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)
const change = (over: Record<string, unknown> = {}) => ({
  id: 7, status: 'captured', priority: 'medium', customer_relevant: false, origin: 'internal',
  scoping_v2: true, attachments: [], ...over,
}) as never

afterEach(() => { cleanup(); vi.clearAllMocks() })

describe('§2 capture on the change', () => {
  it('internal: value, unit and target are all needed', async () => {
    wrap(<ProblemTargetEditor change={change()} canEdit />)
    const save = screen.getByTestId('problem-save') as HTMLButtonElement
    fireEvent.change(screen.getByTestId('problem-value'), { target: { value: '12.4' } })
    fireEvent.change(screen.getByTestId('problem-target-value'), { target: { value: '12' } })
    expect(save.disabled).toBe(true)              // no unit
    fireEvent.change(screen.getByTestId('problem-unit'), { target: { value: 'g' } })
    expect(save.disabled).toBe(false)
    fireEvent.click(save)
    await waitFor(() => expect(changesApi.update).toHaveBeenCalledWith(7,
      { problem_value: 12.4, problem_unit: 'g', target_value: 12 }))
  })

  it('a customer change has no problem editor', () => {
    wrap(<ProblemTargetEditor change={change({ customer_relevant: true, origin: 'customer' })} canEdit />)
    expect(screen.queryByTestId('problem-target-editor')).toBeNull()
  })

  it('picking Critical asks need-by, reason and evidence before saving', async () => {
    wrap(<PriorityEditor change={change({ customer_relevant: true, origin: 'customer' })} canEdit />)
    fireEvent.change(screen.getByLabelText('Priority'), { target: { value: 'critical' } })
    expect(changesApi.update).not.toHaveBeenCalled()
    const save = screen.getByTestId('urgent-save') as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('Need-by date (urgent)'), { target: { value: '2026-10-30' } })
    fireEvent.change(screen.getByTestId('prio-urgent-reason'), { target: { value: 'safety' } })
    fireEvent.change(screen.getByTestId('prio-urgent-evidence'), { target: { value: '8D-2026-114' } })
    expect(save.disabled).toBe(false)
    fireEvent.click(save)
    await waitFor(() => expect(changesApi.update).toHaveBeenCalledWith(7, {
      priority: 'critical', release_due_date: '2026-10-30T12:00:00',
      urgent_reason: 'safety', urgent_evidence: '8D-2026-114' }))
  })

  it('the header says need-by, days left and the stage', () => {
    wrap(<NeedByLine change={change({ priority: 'critical', status: 'scoping',
      release_due_date: '2099-01-02T12:00:00' })} />)
    expect(screen.getByTestId('need-by-line').textContent).toMatch(/Urgent · Need-by .*wd left · now: /)
  })

  it('proceed is held until the need-by question is answered (urgent only)', () => {
    const urgent = change({ priority: 'critical' })
    expect(needByHold(urgent, { check: '', proposed: '' })).toBeTruthy()
    expect(needByHold(urgent, { check: 'no', proposed: '' })).toBeTruthy()
    expect(needByHold(urgent, { check: 'at_risk', proposed: '' })).toBeUndefined()
    expect(needByHold(change(), { check: '', proposed: '' })).toBeUndefined()
  })

  it('a need-by and a proposed date lie in the future (after the need-by)', () => {
    expect(urgentMissing({ needBy: '2020-01-01', reason: 'line_stop', evidence: 'Mail 2026-10-15' }))
      .toContain(t('next.item.need_by'))
    expect(urgentMissing({ needBy: '2099-01-01', reason: 'line_stop', evidence: 'Mail 2026-10-15' })).toEqual([])
    const urgent = change({ priority: 'critical', release_due_date: '2099-01-02T12:00:00' })
    expect(needByHold(urgent, { check: 'no', proposed: '2099-01-02' })).toBe(t('urgent.proposeLater'))
    expect(needByHold(urgent, { check: 'no', proposed: '2099-01-03' })).toBeUndefined()
  })

  it('start at risk switched off: no start-at-risk option, "No start before PO"', () => {
    const c = change({ priority: 'critical', customer_relevant: true, start_at_risk_on: false,
      release_due_date: '2099-01-02T12:00:00' })
    wrap(<NeedByCheck change={c} value={{ check: '', proposed: '' }} onChange={() => {}} customer />)
    expect(screen.queryByTestId('need-by-at_risk')).toBeNull()
    expect(screen.getByTestId('need-by-no-start-check').textContent).toBe(t('urgent.noStartBeforePo'))
    cleanup()
    wrap(<NeedByLine change={{ ...c, status: 'scoping' }} />)
    expect(screen.getByTestId('need-by-no-start')).toBeTruthy()
  })

  it('Sales tells the customer with evidence; others read who does', async () => {
    const c = change({ priority: 'critical', need_by_check: 'at_risk', sales_owner_name: 'Cody' })
    const { unmount } = wrap(<NeedByTellCard change={c} isSales={false} attachments={[]} />)
    expect(screen.getByTestId('need-by-tell').textContent).toContain('Cody tells the customer')
    unmount()
    wrap(<NeedByTellCard change={c} isSales attachments={[]} />)
    const save = screen.getByTestId('need-by-tell-save') as HTMLButtonElement
    fireEvent.change(screen.getByTestId('need-by-tell-ref'), { target: { value: 'tbd' } })
    expect(save.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('need-by-tell-ref'), { target: { value: 'Mail buyer 10-15' } })
    fireEvent.click(save)
    await waitFor(() => expect(changesApi.needByTell).toHaveBeenCalledWith(7, { ref: 'Mail buyer 10-15' }))
  })

  it('okRef refuses empty words and a lone word without a number', () => {
    for (const bad of ['ok', 'n/a n/a', 'asdfg', 'ok ok', 'tbd']) expect(okRef(bad)).toBe(false)
    for (const good of ['CP-4711 rev 3', 'Mail to customer 2026-10-15', 'title block only', 'PS-2231'])
      expect(okRef(good)).toBe(true)
  })

  it('counts working days only', () => {
    // Fri 16 Oct 2026 -> Mon 19 Oct 2026 is one working day
    expect(workingDaysLeft('2026-10-19T12:00:00', new Date(2026, 9, 16))).toBe(1)
  })
})
