import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { DeadlineEditor } from './DeadlineEditor'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'
import type { ChangeRequest } from '../../types/change'

vi.mock('../../api/changes', () => ({
  changesApi: { update: vi.fn().mockResolvedValue({}) },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const change = (over: Partial<ChangeRequest> = {}): ChangeRequest => ({
  id: 7, change_number: 'CR-2026-0007', project_id: 1, title: 'Housing fix',
  change_type: 'tooling', priority: 'medium', status: 'quoted',
  raised_by: 1, customer_response: 'pending', lead_id: 5, lead_name: 'Eva Eng',
  created_at: '2026-07-01T00:00:00', updated_at: '2026-07-01T00:00:00',
  required_by_date: null, required_by_reason: null, deadline_state: null,
  quoted_at: null, quoted_on_time: null, active_deadline: null,
  release_due_date: null, release_due_reason: null, ...over,
} as ChangeRequest)

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}>
    {ui}
  </QueryClientProvider>
)

describe('DeadlineEditor', () => {
  afterEach(() => { cleanup(); vi.mocked(changesApi.update).mockClear() })

  it('edits release_due_date when kind is release', async () => {
    const { container } = render(wrap(<DeadlineEditor change={change({
      release_due_date: '2026-10-01T23:59:59', release_due_reason: null,
    })} kind="release" />))
    fireEvent.click(screen.getByTestId('deadline-edit'))
    fireEvent.change(container.querySelector('input[type="date"]')!, { target: { value: '2026-11-15' } })
    fireEvent.click(screen.getByText(t('deadline.set')))
    await waitFor(() => expect(changesApi.update).toHaveBeenCalledWith(7, {
      release_due_date: '2026-11-15T23:59:59Z', release_due_reason: null,
    }))
  })

  it('defaults to editing required_by_date (quote kind)', async () => {
    const { container } = render(wrap(<DeadlineEditor change={change({ required_by_date: null })} />))
    fireEvent.click(screen.getByTestId('deadline-edit'))
    fireEvent.change(container.querySelector('input[type="date"]')!, { target: { value: '2026-09-01' } })
    fireEvent.click(screen.getByText(t('deadline.set')))
    await waitFor(() => expect(changesApi.update).toHaveBeenCalledWith(7, {
      required_by_date: '2026-09-01T23:59:59Z', required_by_reason: null,
    }))
  })
})
