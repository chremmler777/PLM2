/** ECR-solid §11: the achieved value beside the target (internal changes). */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ChangeDetail } from '../../../types/change'
import { changesApi } from '../../../api/changes'
import AchievedCard, { ConcessionLine, achievedApplies } from './AchievedCard'

vi.mock('../../../api/changes', () => ({ changesApi: { recordAchieved: vi.fn().mockResolvedValue({}) } }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const change = (over: Partial<ChangeDetail> = {}) => ({
  id: 5, status: 'released', customer_relevant: false, target_value: 1, problem_value: 4.2,
  problem_unit: '%', release_v2: true, ...over,
}) as ChangeDetail
const wrap = (ui: React.ReactElement) => render(
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

afterEach(cleanup)

describe('AchievedCard', () => {
  it('applies to internal changes with a target, from validation on', () => {
    expect(achievedApplies(change())).toBe(true)
    expect(achievedApplies(change({ customer_relevant: true }))).toBe(false)
    expect(achievedApplies(change({ target_value: null }))).toBe(false)
    expect(achievedApplies(change({ status: 'approved' }))).toBe(false)
    expect(achievedApplies(change({ release_v2: false }))).toBe(false)
  })
  it('NEGATIVE: no save without a number and a source that names something', () => {
    wrap(<AchievedCard change={change()} canEdit />)
    fireEvent.change(screen.getByTestId('achieved-value'), { target: { value: '0.8' } })
    fireEvent.change(screen.getByTestId('achieved-ref'), { target: { value: 'ok' } })
    expect((screen.getByTestId('achieved-save') as HTMLButtonElement).disabled).toBe(true)
  })
  it('saves value and source', async () => {
    wrap(<AchievedCard change={change()} canEdit />)
    fireEvent.change(screen.getByTestId('achieved-value'), { target: { value: '0.8' } })
    fireEvent.change(screen.getByTestId('achieved-ref'), { target: { value: 'SPC chart line 4, week 41' } })
    fireEvent.click(screen.getByTestId('achieved-save'))
    await waitFor(() => expect(changesApi.recordAchieved).toHaveBeenCalledWith(5,
      { value: 0.8, ref: 'SPC chart line 4, week 41' }))
  })
  it('read-only for others: no input', () => {
    wrap(<AchievedCard change={change({ achieved_value: 0.8, achieved_ref: 'SPC 4' })} canEdit={false} />)
    expect(screen.queryByTestId('achieved-value')).toBeNull()
    expect(screen.getByTestId('achieved-recorded').textContent).toContain('0.8 %')
  })
  it('the header names the concession in force', () => {
    wrap(<ConcessionLine change={{ active_concessions: [{ id: 1, ref: 'VI-1', text: 'Accepted under concession VI-1 until 2026-12-01' }] }} />)
    expect(screen.getByTestId('concession-line').textContent).toBe('Accepted under concession VI-1 until 2026-12-01')
  })
})
