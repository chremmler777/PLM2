/** A5-02: the measurer's own limits wait on Quality's one click. */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { changesApi } from '../../../api/changes'
import type { ValidationCheck } from '../../../types/change'
import { LimitsConfirm, MeasurementHistory } from './MeasurementForm'

vi.mock('../../../api/changes', () => ({ changesApi: { confirmValidationLimits: vi.fn() } }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const check = (over: Partial<ValidationCheck> = {}): ValidationCheck => ({
  check_key: 'weight', label_en: 'Part weight', status: 'passed', computed: true, unit_short: 'g',
  lower_limit: 480, upper_limit: 530, spec_source: 'drawing 886.197 D', check_id: 9,
  limits_set_by_name: 'Tool', limits_pending: true, can_confirm_limits: true, measurements: [],
  ...over,
} as ValidationCheck)
const wrap = (ui: React.ReactElement) => render(
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

afterEach(cleanup)

describe('A5-02 limits confirm', () => {
  it('shows the setter and that the pass waits on Quality', () => {
    wrap(<MeasurementHistory check={check()} id="x" />)
    expect(screen.getByTestId('validation-limits-x').textContent).toContain('set by Tool')
    expect(screen.getByTestId('validation-limits-pending-x').textContent).toContain('counts once Quality confirms')
  })
  it('no button for a viewer the backend refuses', () => {
    wrap(<LimitsConfirm changeId={7} check={check({ can_confirm_limits: false })} id="x" />)
    expect(screen.queryByTestId('validation-limits-ok-x')).toBeNull()
  })
  it('one click confirms; a correction needs a source reference', async () => {
    vi.mocked(changesApi.confirmValidationLimits).mockResolvedValue({} as never)
    wrap(<LimitsConfirm changeId={7} check={check()} id="x" />)
    fireEvent.click(screen.getByTestId('validation-limits-correct-x'))
    fireEvent.change(screen.getByTestId('validation-limits-lower-x'), { target: { value: '495' } })
    fireEvent.change(screen.getByTestId('validation-limits-upper-x'), { target: { value: '515' } })
    fireEvent.change(screen.getByTestId('validation-limits-source-x'), { target: { value: 'ok' } })
    expect(screen.getByTestId('validation-limits-save-x')).toHaveProperty('disabled', true)
    fireEvent.click(screen.getByTestId('validation-limits-ok-x'))
    await waitFor(() => expect(changesApi.confirmValidationLimits).toHaveBeenCalledWith(7, 9, {}))
  })
})
