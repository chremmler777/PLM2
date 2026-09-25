import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DeviationsPanel from './DeviationsPanel'
import type { PlanDeviation } from '../../../types/changePlan'

vi.mock('../../../api/changePlan', () => ({ planApi: { lockDeviation: vi.fn(), escalateDeviation: vi.fn() } }))
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))

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
})
