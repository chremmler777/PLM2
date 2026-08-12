import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ValidationPanel, { departmentOpenChecks, weightAckOutstanding } from './ValidationPanel'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

vi.mock('../../api/changes', () => ({
  changesApi: {
    validationState: vi.fn(),
    setValidationCheck: vi.fn(),
    acknowledgeWeightDelta: vi.fn(),
    transition: vi.fn(),
  },
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const departments = [{ id: 2, name: 'Development' }, { id: 4, name: 'Tool Engineer' }]

const check = (over: Record<string, unknown> = {}) => ({
  check_key: 'sampled', status: 'open', value: null, note: null,
  checked_by_name: null, checked_at: null, ...over,
})

const state = (over: Record<string, unknown> = {}) => ({
  departments: [{ department_id: 4, checks: [check()] }],
  planned_cycle_time_min_per_part: null,
  weight_estimate_g: null, validated_weight_g: null, weight_delta_g: null,
  weight_ack_at: null, ...over,
})

const render_ = (props: Record<string, unknown> = {}) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ValidationPanel changeId={7} status="in_validation" departments={departments}
      myDepartmentIds={[4]} canSeeAll={false} {...props} />
  </QueryClientProvider>)

describe('validation helpers', () => {
  it('counts anything that is not an explicit pass as still owed', () => {
    expect(departmentOpenChecks({ department_id: 4, checks: [
      check({ status: 'passed' }), check({ check_key: 'measured', status: 'failed' }),
      check({ check_key: 'weight', status: 'open' }),
    ] } as never)).toBe(2)
  })

  it('asks for an acknowledgement only on a non-zero, unanswered delta', () => {
    expect(weightAckOutstanding(state({ weight_delta_g: 12 }) as never)).toBe(true)
    expect(weightAckOutstanding(state({ weight_delta_g: 0 }) as never)).toBe(false)
    expect(weightAckOutstanding(state({
      weight_delta_g: 12, weight_ack_at: '2026-08-11T09:00:00' }) as never)).toBe(false)
    expect(weightAckOutstanding(null)).toBe(false)
  })
})

describe('ValidationPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(changesApi.setValidationCheck).mockResolvedValue({} as never)
    vi.mocked(changesApi.acknowledgeWeightDelta).mockResolvedValue({} as never)
    vi.mocked(changesApi.transition).mockResolvedValue({} as never)
  })
  afterEach(cleanup)

  it('passes a check for the viewer’s own department', async () => {
    vi.mocked(changesApi.validationState).mockResolvedValue(state() as never)
    render_()
    fireEvent.click(await screen.findByTestId('validation-pass-4-sampled'))
    await waitFor(() => expect(changesApi.setValidationCheck).toHaveBeenCalledWith(7, {
      department_id: 4, check_key: 'sampled', status: 'passed',
    }))
  })

  it('will not take a fail without a reason', async () => {
    vi.mocked(changesApi.validationState).mockResolvedValue(state() as never)
    render_()
    fireEvent.click(await screen.findByTestId('validation-fail-4-sampled'))
    const confirm = screen.getByTestId('validation-fail-confirm-4-sampled') as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    expect(screen.getByText(t('validation.failNoteRequired'))).toBeDefined()

    fireEvent.change(screen.getByTestId('validation-note-4-sampled'),
      { target: { value: 'cavity 3 out of tolerance' } })
    fireEvent.click(screen.getByTestId('validation-fail-confirm-4-sampled'))
    await waitFor(() => expect(changesApi.setValidationCheck).toHaveBeenCalledWith(7, {
      department_id: 4, check_key: 'sampled', status: 'failed',
      note: 'cavity 3 out of tolerance',
    }))
  })

  it('shows the costing assumption next to the measured cycle time, and sends the value', async () => {
    vi.mocked(changesApi.validationState).mockResolvedValue(state({
      departments: [{ department_id: 4, checks: [check({ check_key: 'cycle_time' })] }],
      planned_cycle_time_min_per_part: 1.4,
    }) as never)
    render_()
    expect((await screen.findByTestId('validation-assumption-4-cycle_time')).textContent)
      .toBe(t('validation.cycleAssumption').replace('{x}', '1.4'))

    // Nothing to pass until there is a measurement to pass with.
    expect((screen.getByTestId('validation-pass-4-cycle_time') as HTMLButtonElement).disabled)
      .toBe(true)
    fireEvent.change(screen.getByTestId('validation-value-4-cycle_time'),
      { target: { value: '96' } })
    fireEvent.click(screen.getByTestId('validation-pass-4-cycle_time'))
    await waitFor(() => expect(changesApi.setValidationCheck).toHaveBeenCalledWith(7, {
      department_id: 4, check_key: 'cycle_time', status: 'passed', value: 96,
    }))
  })

  it('states the weight delta and gates the acknowledgement on Sales', async () => {
    vi.mocked(changesApi.validationState).mockResolvedValue(state({
      departments: [{ department_id: 4, checks: [
        check({ check_key: 'weight', status: 'passed', value: 512 })] }],
      weight_estimate_g: 500, validated_weight_g: 512, weight_delta_g: 12,
    }) as never)

    // A department sees the consequence but does not answer for it.
    render_()
    expect((await screen.findByTestId('validation-weight-strip')).textContent)
      .toContain(t('validation.quoteUpdate').replace('{x}', '+12'))
    expect(screen.queryByTestId('validation-weight-ack')).toBeNull()
    cleanup()

    render_({ canAcknowledge: true, canSeeAll: true })
    fireEvent.change(await screen.findByTestId('validation-weight-ack-note'),
      { target: { value: 'price sheet reissued' } })
    fireEvent.click(screen.getByTestId('validation-weight-ack'))
    await waitFor(() => expect(changesApi.acknowledgeWeightDelta)
      .toHaveBeenCalledWith(7, 'price sheet reissued'))
  })

  it('says who acknowledged the delta instead of offering it again', async () => {
    vi.mocked(changesApi.validationState).mockResolvedValue(state({
      weight_delta_g: -8, weight_ack_at: '2026-08-11T09:00:00',
      weight_ack_by_name: 'Sara Sales', weight_ack_note: 'no price change',
    }) as never)
    render_({ canAcknowledge: true })
    expect((await screen.findByTestId('validation-weight-acked')).textContent)
      .toContain('Sara Sales')
    expect(screen.queryByTestId('validation-weight-ack')).toBeNull()
  })

  it('carries the revision-bump wording on Development’s row', async () => {
    vi.mocked(changesApi.validationState).mockResolvedValue(state({
      departments: [{ department_id: 2, checks: [check({ check_key: 'revision_bump' })] }],
    }) as never)
    render_({ myDepartmentIds: [2] })
    expect((await screen.findByTestId('validation-hint-2-revision_bump')).textContent)
      .toBe(t('validation.hint.revision_bump'))
  })

  it('shows only the viewer’s own block, and counts the rest', async () => {
    vi.mocked(changesApi.validationState).mockResolvedValue(state({
      departments: [
        { department_id: 4, checks: [check()] },
        { department_id: 2, checks: [check({ check_key: 'revision_bump' })] },
      ],
    }) as never)
    render_()
    expect(await screen.findByTestId('validation-block-4')).toBeDefined()
    expect(screen.queryByTestId('validation-block-2')).toBeNull()
    expect(screen.getByTestId('validation-others').textContent)
      .toBe(t('validation.others').replace('{n}', '1'))
  })

  it('lets PM/Sales/lead/admin read every block and write none of them', async () => {
    vi.mocked(changesApi.validationState).mockResolvedValue(state({
      departments: [
        { department_id: 4, checks: [check()] },
        { department_id: 2, checks: [check({ check_key: 'revision_bump' })] },
      ],
    }) as never)
    render_({ canSeeAll: true, myDepartmentIds: [] })
    expect(await screen.findByTestId('validation-block-4')).toBeDefined()
    expect(screen.getByTestId('validation-block-2')).toBeDefined()
    // Seeing the board is not the same as answering for somebody else's check.
    expect(screen.queryByTestId('validation-pass-4-sampled')).toBeNull()
  })

  it('escalates back to implementation with a written reason', async () => {
    vi.mocked(changesApi.validationState).mockResolvedValue(state({
      departments: [{ department_id: 4, checks: [
        check({ check_key: 'measured', status: 'failed', note: 'flatness out' })] }],
    }) as never)
    render_({ canEscalate: true, canSeeAll: true })
    fireEvent.click(await screen.findByTestId('validation-escalate'))
    expect(screen.getByText(t('validation.escalateWarning'))).toBeDefined()

    fireEvent.change(screen.getByRole('dialog').querySelector('textarea')!,
      { target: { value: 'flatness out of tolerance — retool and replan' } })
    fireEvent.click(screen.getByRole('button', { name: t('validation.escalateSubmit') }))
    await waitFor(() => expect(changesApi.transition).toHaveBeenCalledWith(
      7, 'in_implementation', { reason: 'flatness out of tolerance — retool and replan' }))
  })

  it('is the record, not a form, once the change has moved on', async () => {
    vi.mocked(changesApi.validationState).mockResolvedValue(state({
      departments: [{ department_id: 4, checks: [check({
        status: 'passed', checked_by_name: 'Tim Tool',
        checked_at: '2026-08-10T09:00:00' })] }],
    }) as never)
    render_({ status: 'released', canEscalate: true, canAcknowledge: true })
    expect(await screen.findByTestId('validation-readonly')).toBeDefined()
    expect(screen.getByTestId('validation-checkedby-4-sampled').textContent)
      .toContain('Tim Tool')
    expect(screen.queryByTestId('validation-pass-4-sampled')).toBeNull()
    expect(screen.queryByTestId('validation-escalate')).toBeNull()
  })
})
