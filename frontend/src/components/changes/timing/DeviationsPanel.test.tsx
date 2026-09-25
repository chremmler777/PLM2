import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DeviationsPanel from './DeviationsPanel'
import type { PlanDeviation } from '../../../types/changePlan'
import { planApi } from '../../../api/changePlan'
import { toast } from 'sonner'

vi.mock('../../../api/changePlan', () => ({
  planApi: {
    lockDeviation: vi.fn(), escalateDeviation: vi.fn(),
    lockDeviationGroup: vi.fn(), escalateDeviationGroup: vi.fn(),
  },
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const dev = (over: Partial<PlanDeviation> & { id: number; task_id: number; task_name: string }): PlanDeviation => ({
  old_start: '2026-10-05', old_end: '2026-10-10', new_start: '2026-10-07', new_end: '2026-10-12', slip_days: 2,
  finish_impact_days: 2, reason: 'late', status: 'open', ...over,
})

describe('DeviationsPanel grouped by cause (G18)', () => {
  afterEach(cleanup)
  it('lists each own move followed by the successors it pushed', () => {
    render(<QueryClientProvider client={new QueryClient()}>
      <DeviationsPanel changeId={7} canDecide={false} deviations={[
        dev({ id: 12, task_id: 5, task_name: 'Other own move' }),
        dev({ id: 11, task_id: 3, task_name: 'Sampling', caused_by_task_id: 1, caused_by_task_name: 'Tool rework' }),
        dev({ id: 10, task_id: 1, task_name: 'Tool rework' }),
        dev({ id: 13, task_id: 4, task_name: 'Orphan', caused_by_task_id: 99 }),
      ]} />
    </QueryClientProvider>)
    const rows = screen.getAllByTestId(/^deviation-\d+$/).map((r) => r.getAttribute('data-testid'))
    expect(rows).toEqual(['deviation-12', 'deviation-10', 'deviation-11', 'deviation-13'])
    expect(screen.getByTestId('deviation-11').getAttribute('data-pushed-by')).toBe('10')
    expect(screen.getByTestId('deviation-cause-11').textContent).toBe('pushed by Tool rework')
    expect(screen.queryByTestId('deviation-cause-13')).toBeNull()
  })

  const slip = () => [
    dev({ id: 22, task_id: 3, task_name: 'Sampling', caused_by_task_id: 1, caused_by_task_name: 'Tool rework' }),
    dev({ id: 21, task_id: 2, task_name: 'Measurement', caused_by_task_id: 1, caused_by_task_name: 'Tool rework' }),
    dev({ id: 20, task_id: 1, task_name: 'Tool rework' }),
  ]
  const mount = () => render(<QueryClientProvider client={new QueryClient()}>
    <DeviationsPanel changeId={7} canDecide status="in_implementation" deviations={slip()} />
  </QueryClientProvider>)

  it('one slip is one decision: the move carries Lock and Escalate, the pushed rows none', async () => {
    vi.mocked(planApi.lockDeviation).mockResolvedValue({})
    mount()
    expect(screen.queryByTestId('deviation-lock-21')).toBeNull()
    expect(screen.queryByTestId('deviation-lock-22')).toBeNull()
    expect(screen.getByTestId('deviation-lock-20').textContent).toBe('Lock all 3')
    expect(screen.getByTestId('deviation-group-20').textContent).toBe('moved 2 successors along')
    fireEvent.click(screen.getByTestId('deviation-lock-20'))
    fireEvent.click(screen.getByTestId('deviation-lock-confirm-20'))
    await waitFor(() => expect(planApi.lockDeviation).toHaveBeenCalledTimes(3))
    expect(vi.mocked(planApi.lockDeviation).mock.calls.map((c) => c[1])).toEqual([20, 21, 22])
  })

  it('escalating the move locks what it pushed with a note, and escalates once', async () => {
    vi.mocked(planApi.lockDeviation).mockReset().mockResolvedValue({})
    vi.mocked(planApi.escalateDeviation).mockResolvedValue({ id: 20, escalation_id: 55 })
    mount()
    fireEvent.click(screen.getByTestId('deviation-escalate-20'))
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'SOP moves a week' } })
    fireEvent.click(within(dialog).getByText('Escalate'))
    await waitFor(() => expect(planApi.lockDeviation).toHaveBeenCalledTimes(2))
    expect(planApi.escalateDeviation).toHaveBeenCalledTimes(1)
    expect(planApi.escalateDeviation).toHaveBeenCalledWith(7, 20, 'SOP moves a week')
    expect(vi.mocked(planApi.lockDeviation).mock.calls[0][2])
      .toBe('Pushed by the move of Tool rework, which was escalated to the customer (escalation #55)')
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Escalated to the customer; 2 pushed rows locked'))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('says exactly what happened when a pushed row is refused after the escalation', async () => {
    vi.mocked(planApi.escalateDeviation).mockReset().mockResolvedValue({ id: 20, escalation_id: 55 })
    vi.mocked(planApi.lockDeviation).mockReset().mockResolvedValueOnce({}).mockRejectedValueOnce(new Error('no'))
    vi.mocked(toast.error).mockClear()
    mount()
    fireEvent.click(screen.getByTestId('deviation-escalate-20'))
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'SOP moves a week' } })
    fireEvent.click(within(dialog).getByText('Escalate'))
    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1))
    expect(vi.mocked(toast.error).mock.calls[0][0]).toMatch(/^Escalated; 1 of 2 pushed rows locked, retry to lock the rest\./)
  })

  it('a decided move with open pushed rows offers only "Lock remaining", with an honest note', async () => {
    vi.mocked(planApi.lockDeviation).mockReset().mockResolvedValue({})
    vi.mocked(planApi.escalateDeviation).mockReset()
    const [a, b, root] = slip()
    render(<QueryClientProvider client={new QueryClient()}>
      <DeviationsPanel changeId={7} canDecide status="in_implementation"
        deviations={[a, { ...b, status: 'locked' }, { ...root, status: 'escalated', escalation_id: 55 }]} />
    </QueryClientProvider>)
    expect(screen.queryByTestId('deviation-escalate-20')).toBeNull()
    expect(screen.getByTestId('deviation-lock-20').textContent).toBe('Lock remaining')
    fireEvent.click(screen.getByTestId('deviation-lock-20'))
    fireEvent.click(screen.getByTestId('deviation-lock-confirm-20'))
    await waitFor(() => expect(planApi.lockDeviation).toHaveBeenCalledTimes(1))
    expect(vi.mocked(planApi.lockDeviation).mock.calls[0])
      .toEqual([7, 22, 'Pushed by the move of Tool rework, which was escalated to the customer (escalation #55)'])
    expect(planApi.escalateDeviation).not.toHaveBeenCalled()
  })

  it('a double Enter on the lock note starts one lock run', async () => {
    let release: () => void = () => {}
    vi.mocked(planApi.lockDeviation).mockReset().mockImplementation(() => new Promise((r) => { release = () => r({}) }))
    mount()
    fireEvent.click(screen.getByTestId('deviation-lock-20'))
    const note = screen.getByLabelText('Lock note')
    fireEvent.keyDown(note, { key: 'Enter' })
    await waitFor(() => expect(planApi.lockDeviation).toHaveBeenCalledTimes(1))
    fireEvent.keyDown(note, { key: 'Enter' })
    release()
    await waitFor(() => expect(planApi.lockDeviation).toHaveBeenCalledTimes(2))
    release()
    await waitFor(() => expect(planApi.lockDeviation).toHaveBeenCalledTimes(3))
    release()
    await new Promise((r) => setTimeout(r, 20))
    expect(planApi.lockDeviation).toHaveBeenCalledTimes(3)
  })
})

describe('DeviationsPanel with server groups', () => {
  afterEach(cleanup)
  // one bulk move of two blocks (40, 41) that pushed a successor (42), group 9
  const grouped = () => [
    dev({ id: 42, task_id: 3, task_name: 'Buffer', caused_by_task_id: 2, caused_by_task_name: 'Approval', group_id: 9 }),
    dev({ id: 41, task_id: 2, task_name: 'Approval', group_id: 9 }),
    dev({ id: 40, task_id: 1, task_name: 'Validation', group_id: 9 }),
    // a legacy row caused by a grouped task stays out of the server group
    dev({ id: 30, task_id: 5, task_name: 'Legacy', caused_by_task_id: 2 }),
  ]
  const mount = (rows = grouped()) => render(<QueryClientProvider client={new QueryClient()}>
    <DeviationsPanel changeId={7} canDecide status="in_implementation" deviations={rows} />
  </QueryClientProvider>)

  it('keeps one edit together: the first move leads, the rest follow', () => {
    mount()
    const rows = screen.getAllByTestId(/^deviation-\d+$/).map((r) => r.getAttribute('data-testid'))
    expect(rows).toEqual(['deviation-40', 'deviation-41', 'deviation-42', 'deviation-30'])
    expect(screen.getByTestId('deviation-cause-41').textContent).toBe('moved with Validation')
    expect(screen.getByTestId('deviation-cause-42').textContent).toBe('pushed by Approval')
    expect(screen.getByTestId('deviation-group-40').textContent).toBe('moved with 1 other block, moved 1 successor along')
    expect(screen.queryByTestId('deviation-cause-30')).toBeNull()
    expect(screen.getByTestId('deviation-lock-40').textContent).toBe('Lock all 3')
  })

  it('locks the whole group in one call', async () => {
    vi.mocked(planApi.lockDeviationGroup).mockReset().mockResolvedValue([])
    vi.mocked(planApi.lockDeviation).mockReset()
    vi.mocked(toast.success).mockClear()
    mount()
    fireEvent.click(screen.getByTestId('deviation-lock-40'))
    fireEvent.change(screen.getByLabelText('Lock note'), { target: { value: 'absorbed' } })
    fireEvent.click(screen.getByTestId('deviation-lock-confirm-40'))
    await waitFor(() => expect(planApi.lockDeviationGroup).toHaveBeenCalledWith(7, 9, 'absorbed'))
    expect(planApi.lockDeviationGroup).toHaveBeenCalledTimes(1)
    expect(planApi.lockDeviation).not.toHaveBeenCalled()
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Locked 3 deviations'))
  })

  it('escalates the whole group under one escalation', async () => {
    vi.mocked(planApi.escalateDeviationGroup).mockReset().mockResolvedValue([])
    vi.mocked(planApi.escalateDeviation).mockReset()
    vi.mocked(planApi.lockDeviation).mockReset()
    vi.mocked(toast.success).mockClear()
    mount()
    fireEvent.click(screen.getByTestId('deviation-escalate-40'))
    const dialog = screen.getByRole('dialog')
    expect(dialog.textContent).toContain('The 2 other open rows of this move are escalated with it')
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'SOP moves a week' } })
    fireEvent.click(within(dialog).getByText('Escalate'))
    await waitFor(() => expect(planApi.escalateDeviationGroup).toHaveBeenCalledWith(7, 9, 'SOP moves a week'))
    expect(planApi.escalateDeviation).not.toHaveBeenCalled()
    expect(planApi.lockDeviation).not.toHaveBeenCalled()
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Escalated 3 deviations to the customer together'))
  })

  it('after an escalated move, "Lock remaining" sends the escalation note in one call', async () => {
    vi.mocked(planApi.lockDeviationGroup).mockReset().mockResolvedValue([])
    const [pushed, other, root] = grouped()
    mount([pushed, { ...other, status: 'escalated', escalation_id: 55 }, { ...root, status: 'escalated', escalation_id: 55 }])
    expect(screen.queryByTestId('deviation-escalate-40')).toBeNull()
    fireEvent.click(screen.getByTestId('deviation-lock-40'))
    fireEvent.click(screen.getByTestId('deviation-lock-confirm-40'))
    await waitFor(() => expect(planApi.lockDeviationGroup).toHaveBeenCalledWith(
      7, 9, 'Pushed by the move of Validation, which was escalated to the customer (escalation #55)'))
  })

  it('a refused group call changes nothing and says so', async () => {
    vi.mocked(planApi.lockDeviationGroup).mockReset().mockRejectedValue(new Error('no'))
    vi.mocked(toast.error).mockClear()
    mount()
    fireEvent.click(screen.getByTestId('deviation-lock-40'))
    fireEvent.click(screen.getByTestId('deviation-lock-confirm-40'))
    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1))
    expect(planApi.lockDeviationGroup).toHaveBeenCalledTimes(1)
  })
})
