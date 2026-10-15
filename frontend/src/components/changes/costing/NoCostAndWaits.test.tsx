import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  NoCostButton, SupplierWaitDecisions, SupplierWaitLine, SupplierWaitPanel, noCostWords,
} from './NoCostAndWaits'
import { changesApi } from '../../../api/changes'
import { t } from '../../../i18n/cmLabels'
import type { SupplierWait } from '../../../types/change'

vi.mock('../../../api/changes', () => ({
  changesApi: {
    departmentNoCost: vi.fn().mockResolvedValue({}),
    startSupplierWait: vi.fn().mockResolvedValue([]),
    closeSupplierWait: vi.fn().mockResolvedValue([]),
  },
}))

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)
const wait = (over: Partial<SupplierWait> = {}): SupplierWait => ({
  id: 4, change_id: 7, department_id: 3, department_name: 'Toolshop', phase: 'costing',
  vendor_name: 'FZ', asked_on: '2026-10-07', expected_by: '2026-11-03', is_open: true,
  overdue: false, chip: 'day 9 of 27', ...over,
})

afterEach(() => { cleanup(); vi.clearAllMocks() })

describe('NoCostButton (C18)', () => {
  it('Toolshop asks whether toolmakers spend time; absorbed needs hours', async () => {
    render(wrap(<NoCostButton changeId={7} departmentId={3} departmentName="Toolshop" />))
    fireEvent.click(screen.getByTestId('nocost-open-3'))
    expect(screen.getByTestId('nocost-form-3').textContent).toContain(t('nocost.toolshopAsk'))
    const save = screen.getByTestId('nocost-save-3') as HTMLButtonElement
    expect(save.disabled).toBe(true)                      // nothing preselected
    fireEvent.click(screen.getByTestId('nocost-3-absorbed'))
    expect(save.disabled).toBe(true)                      // 0 hours is no work
    fireEvent.change(screen.getByTestId('nocost-hours-3'), { target: { value: '6' } })
    fireEvent.click(save)
    await waitFor(() => expect(changesApi.departmentNoCost).toHaveBeenCalledWith(
      7, 3, { reason: 'absorbed', hours: 6 }))
  })

  it('names the answer in words', () => {
    expect(noCostWords({ reason: 'absorbed', hours: 6 })).toBe('absorbed (6 h)')
    expect(noCostWords(undefined)).toBeNull()
  })
})

describe('supplier waits (spec §4/§5)', () => {
  it('the department records a wait with vendor and expected date', async () => {
    render(wrap(<SupplierWaitPanel changeId={7} departmentId={3} waits={[]} editable />))
    fireEvent.click(screen.getByTestId('supwait-open-3'))
    const save = screen.getByTestId('supwait-save-3') as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('supwait-vendor-3'), { target: { value: 'FZ' } })
    fireEvent.change(screen.getByTestId('supwait-expected-3'), { target: { value: '2026-11-03' } })
    expect(save.disabled).toBe(false)
    fireEvent.click(save)
    await waitFor(() => expect(changesApi.startSupplierWait).toHaveBeenCalledWith(7,
      expect.objectContaining({ department_id: 3, vendor_name: 'FZ', expected_by: '2026-11-03' })))
  })

  it('only the run team gets "Price on estimate"', async () => {
    const { rerender } = render(wrap(
      <SupplierWaitDecisions changeId={7} waits={[wait()]} canDecide={false} />))
    expect(screen.queryByTestId('supwait-estimate-4')).toBeNull()
    rerender(wrap(<SupplierWaitDecisions changeId={7} waits={[wait()]} canDecide />))
    fireEvent.click(screen.getByTestId('supwait-estimate-4'))
    await waitFor(() => expect(changesApi.closeSupplierWait).toHaveBeenCalledWith(
      7, 4, { reason: 'price_on_estimate' }))
  })

  it('the header says who we wait on since when', () => {
    render(<SupplierWaitLine change={{ open_supplier_waits: [wait()] }} />)
    expect(screen.getByTestId('supwait-line').textContent).toContain('Waiting on FZ since')
    expect(screen.getByTestId('supwait-line').textContent).toContain('Toolshop, day 9 of 27')
  })
})
