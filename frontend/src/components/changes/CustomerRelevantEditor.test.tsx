import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CustomerRelevantEditor } from './CustomerRelevantEditor'
import type { ChangeRequest } from '../../types/change'
import { changesApi } from '../../api/changes'

vi.mock('../../api/changes', () => ({
  changesApi: { update: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const change = (over: Partial<ChangeRequest> = {}): ChangeRequest => ({
  id: 7, change_number: 'CR-2026-0007', project_id: 1, title: 'Housing fix',
  change_type: 'tooling', priority: 'medium', status: 'captured',
  raised_by: 1, customer_response: 'pending', customer_relevant: false,
  created_at: '2026-07-01T00:00:00', updated_at: '2026-07-01T00:00:00',
  ...over,
} as ChangeRequest)

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)

describe('CustomerRelevantEditor', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('shows the current value and no edit control when not editable', () => {
    render(wrap(<CustomerRelevantEditor change={change({ status: 'approved' })} canEdit={false} />))
    expect(screen.getByText('No')).toBeDefined()
    expect(screen.queryByTestId('customer-relevant-edit')).toBeNull()
  })

  it('lets a lead/admin flip the flag while captured, PATCHing customer_relevant', async () => {
    vi.mocked(changesApi.update).mockResolvedValue(change({ customer_relevant: true }))
    render(wrap(<CustomerRelevantEditor change={change({ status: 'captured', customer_relevant: false })} canEdit />))
    fireEvent.click(screen.getByTestId('customer-relevant-edit'))
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'yes' } })
    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    await waitFor(() => expect(changesApi.update).toHaveBeenCalledWith(7, { customer_relevant: true }))
  })

  it('hides the edit control once past scoping even for a lead/admin', () => {
    render(wrap(<CustomerRelevantEditor change={change({ status: 'in_assessment' })} canEdit />))
    expect(screen.queryByTestId('customer-relevant-edit')).toBeNull()
  })
})
