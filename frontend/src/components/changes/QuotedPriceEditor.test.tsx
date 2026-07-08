import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { QuotedPriceEditor } from './QuotedPriceEditor'
import type { ChangeRequest } from '../../types/change'
import { changesApi } from '../../api/changes'

vi.mock('../../api/changes', () => ({
  changesApi: { update: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const change = (over: Partial<ChangeRequest> = {}): ChangeRequest => ({
  id: 7, change_number: 'CR-2026-0007', project_id: 1, title: 'Housing fix',
  change_type: 'tooling', priority: 'medium', status: 'costing',
  raised_by: 1, customer_response: 'pending',
  created_at: '2026-07-01T00:00:00', updated_at: '2026-07-01T00:00:00',
  ...over,
} as ChangeRequest)

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)

describe('QuotedPriceEditor', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('saves the entered price via PATCH when in costing', async () => {
    vi.mocked(changesApi.update).mockResolvedValue(change({ quoted_price: 4200 }))
    render(wrap(<QuotedPriceEditor change={change({ status: 'costing', quoted_price: null })} />))
    const input = screen.getByRole('spinbutton')
    fireEvent.change(input, { target: { value: '4200' } })
    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    await waitFor(() => expect(changesApi.update).toHaveBeenCalledWith(7, { quoted_price: 4200 }))
  })

  it('is editable while quoted', () => {
    render(wrap(<QuotedPriceEditor change={change({ status: 'quoted', quoted_price: 1000 })} />))
    expect(screen.getByRole('spinbutton')).toBeDefined()
  })

  it('shows read-only text outside costing/quoted', () => {
    render(wrap(<QuotedPriceEditor change={change({ status: 'approved', quoted_price: 1000 })} />))
    expect(screen.queryByRole('spinbutton')).toBeNull()
    expect(screen.getByText(/Quoted price/)).toBeDefined()
    expect(screen.getByText('1000')).toBeDefined()
  })

  it('hides the edit control when the viewer is not admin/lead/Sales (canEdit=false)', () => {
    render(wrap(<QuotedPriceEditor change={change({ status: 'costing', quoted_price: 1000 })} canEdit={false} />))
    expect(screen.queryByRole('spinbutton')).toBeNull()
    expect(screen.queryByRole('button', { name: /save/i })).toBeNull()
    expect(screen.getByText(/Quoted price/)).toBeDefined()
    expect(screen.getByText('1000')).toBeDefined()
  })
})
