import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import HoldBanner from './HoldBanner'
import { changesApi } from '../../api/changes'

vi.mock('../../api/changes', () => ({ changesApi: { moveHoldReview: vi.fn() } }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const wrap = (props: Partial<Parameters<typeof HoldBanner>[0]> = {}) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <HoldBanner changeId={7} reviewDate="2026-11-16" reason="waiting for the drawing"
      canMove now="2026-11-02" {...props} />
  </QueryClientProvider>)

describe('HoldBanner (Christoph 2026-11-02)', () => {
  afterEach(cleanup)
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(changesApi.moveHoldReview).mockResolvedValue({} as never)
  })

  it('says until when and why', () => {
    wrap()
    expect(screen.getByTestId('hold-line').textContent).toBe('On hold until 16 Nov 2026: waiting for the drawing')
    expect(screen.queryByTestId('hold-state')).toBeNull()
  })

  it('says what is owed on and after the review date', () => {
    wrap({ now: '2026-11-16' })
    expect(screen.getByTestId('hold-state').textContent).toContain('Review date today')
    cleanup()
    wrap({ now: '2026-11-20' })
    expect(screen.getByTestId('hold-state').textContent).toContain('Review date passed')
  })

  it('sets a new date with a reason', async () => {
    wrap()
    fireEvent.click(screen.getByTestId('hold-move'))
    const save = screen.getByTestId('hold-move-save') as HTMLButtonElement
    expect(save.disabled).toBe(true)              // no reason yet
    fireEvent.change(screen.getByTestId('hold-move-date'), { target: { value: '2026-12-01' } })
    fireEvent.change(screen.getByTestId('hold-move-reason'), { target: { value: 'SOP moved' } })
    fireEvent.click(save)
    await waitFor(() => expect(changesApi.moveHoldReview).toHaveBeenCalledWith(7, '2026-12-01', 'SOP moved'))
  })

  it('offers no move without the right, and no date past ~3 months', () => {
    wrap({ canMove: false })
    expect(screen.queryByTestId('hold-move')).toBeNull()
    cleanup()
    wrap()
    fireEvent.click(screen.getByTestId('hold-move'))
    fireEvent.change(screen.getByTestId('hold-move-date'), { target: { value: '2027-06-01' } })
    fireEvent.change(screen.getByTestId('hold-move-reason'), { target: { value: 'SOP moved' } })
    expect((screen.getByTestId('hold-move-save') as HTMLButtonElement).disabled).toBe(true)
  })
})
