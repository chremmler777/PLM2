import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import StartAtRiskCard, { type StartAtRiskCardProps } from './StartAtRiskCard'
import client from '../../../api/client'

vi.mock('../../../api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const props = (over: Partial<StartAtRiskCardProps> = {}): StartAtRiskCardProps => ({
  changeId: 7, canAsk: true, isQuality: false, canApprove: false, userId: 5, attachments: [], ...over,
})
const wrap = (p: StartAtRiskCardProps) => render(
  <QueryClientProvider client={new QueryClient()}><StartAtRiskCard {...p} /></QueryClientProvider>)
const state = (over = {}) => ({ data: { available: true, price_open: false, ...over } })

describe('StartAtRiskCard (§7a)', () => {
  afterEach(cleanup)
  beforeEach(() => { vi.clearAllMocks() })

  it('Sales asks with the go-ahead; "ok" is no go-ahead', async () => {
    vi.mocked(client.get).mockResolvedValue(state())
    vi.mocked(client.post).mockResolvedValue(state({ requested_at: '2026-10-15T09:00:00' }))
    wrap(props())
    const ask = await screen.findByTestId('sar-ask') as HTMLButtonElement
    fireEvent.change(screen.getByTestId('sar-ref'), { target: { value: 'ok' } })
    expect(ask.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('sar-ref'), { target: { value: 'Mail 15 Oct: start now' } })
    fireEvent.click(ask)
    await waitFor(() => expect(client.post).toHaveBeenCalledWith('/v1/changes/7/start-at-risk',
      { ref: 'Mail 15 Oct: start now' }))
  })

  it('Quality writes the line; the asker never sees an approve button', async () => {
    vi.mocked(client.get).mockResolvedValue(state({ requested_at: '2026-10-15T09:00:00', requested_by: 5,
      quality_note: 'No PPAP before SOP', quality_by_name: 'Q' }))
    wrap(props({ canApprove: true, userId: 5 }))
    expect(await screen.findByText(/Waiting for a Project Management member/)).toBeDefined()
    expect(screen.queryByTestId('sar-approve')).toBeNull()
    cleanup()
    vi.mocked(client.get).mockResolvedValue(state({ requested_at: '2026-10-15T09:00:00', requested_by: 9 }))
    wrap(props({ isQuality: true }))
    const save = await screen.findByTestId('sar-quality-save') as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('sar-quality-note'), { target: { value: 'first lot 100 % checked' } })
    expect(save.disabled).toBe(false)
  })

  it('once started, every viewer reads it and that the price is open', async () => {
    vi.mocked(client.get).mockResolvedValue(state({ available: false, approved_at: '2026-10-16T09:00:00',
      approved_by_name: 'Pat PM', quality_note: 'No PPAP before SOP', price_open: true }))
    wrap(props({ canAsk: false }))
    const text = (await screen.findByTestId('sar-started')).textContent ?? ''
    expect(text).toContain('approved by Pat PM')
    expect(text).toContain('The price is open')
  })
})
