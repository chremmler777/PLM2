import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import NegotiationCard from './NegotiationCard'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

vi.mock('../../api/changes', () => ({
  changesApi: {
    listNegotiations: vi.fn(),
    addNegotiation: vi.fn(),
    deleteNegotiation: vi.fn(),
  },
}))

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

let auth = { userId: 5, username: 'sales.anna' }
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => auth }))

const round = (over: Record<string, unknown> = {}) => ({
  id: 1, channel: 'call', note: 'customer wants 10% off',
  counter_price: null, is_final: false,
  created_by: 5, created_by_name: 'sales.anna',
  created_at: '2026-08-01T09:00:00', ...over,
}) as never

const wrap = (props: { status?: string; canWrite?: boolean } = {}) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <NegotiationCard changeId={7} status={props.status ?? 'quoted'}
      canWrite={props.canWrite ?? true} />
  </QueryClientProvider>)

describe('NegotiationCard', () => {
  afterEach(cleanup)
  beforeEach(() => {
    vi.clearAllMocks()
    auth = { userId: 5, username: 'sales.anna' }
    vi.mocked(changesApi.listNegotiations).mockResolvedValue([])
    vi.mocked(changesApi.addNegotiation).mockResolvedValue({} as never)
    vi.mocked(changesApi.deleteNegotiation).mockResolvedValue({} as never)
  })

  it('reads the rounds forward, each named by the channel it happened on', async () => {
    // Served out of order on purpose: the card, not the API, decides the order.
    vi.mocked(changesApi.listNegotiations).mockResolvedValue([
      round({ id: 2, channel: 'email', note: 'sent revised offer',
        created_at: '2026-08-05T09:00:00' }),
      round({ id: 1, channel: 'call', created_at: '2026-08-01T09:00:00' }),
      round({ id: 3, channel: 'meeting', note: 'met at their plant',
        created_at: '2026-08-09T09:00:00' }),
    ] as never)
    wrap()
    await waitFor(() => expect(screen.getByTestId('negotiation-round-1')).toBeTruthy())
    const ids = Array.from(document.querySelectorAll('[data-testid^="negotiation-round-"]'))
      .map((el) => el.getAttribute('data-testid'))
    expect(ids).toEqual([
      'negotiation-round-1', 'negotiation-round-2', 'negotiation-round-3',
    ])
    expect(screen.getByTestId('negotiation-channel-1').textContent)
      .toBe(t('negotiation.channel.call'))
    expect(screen.getByTestId('negotiation-channel-2').textContent)
      .toBe(t('negotiation.channel.email'))
    expect(screen.getByTestId('negotiation-channel-3').textContent)
      .toBe(t('negotiation.channel.meeting'))
    // The round carries its date and who recorded it.
    expect(screen.getByTestId('negotiation-round-1').textContent).toContain('2026-08-01')
    expect(screen.getByTestId('negotiation-round-1').textContent).toContain('sales.anna')
  })

  it('marks the final round and states the price it ended on', async () => {
    vi.mocked(changesApi.listNegotiations).mockResolvedValue([
      round({ id: 1, counter_price: 1200 }),
      round({ id: 2, channel: 'meeting', note: 'agreed', counter_price: 1100,
        is_final: true, created_at: '2026-08-09T09:00:00' }),
    ] as never)
    wrap()
    await waitFor(() => expect(screen.getByTestId('negotiation-final-badge-2')).toBeTruthy())
    expect(screen.getByTestId('negotiation-final-badge-2').textContent)
      .toBe(t('negotiation.final'))
    // Only the result carries the badge — the earlier round is plain history.
    expect(screen.queryByTestId('negotiation-final-badge-1')).toBeNull()
    expect(screen.getByTestId('negotiation-final-price').textContent).toBe('1100.00')
  })

  it('points at the acceptance controls once there is a result', async () => {
    vi.mocked(changesApi.listNegotiations).mockResolvedValue([
      round({ id: 2, is_final: true, counter_price: 1100 }),
    ] as never)
    wrap()
    await waitFor(() => expect(screen.getByTestId('negotiation-goahead-hint')).toBeTruthy())
    expect(screen.getByTestId('negotiation-goahead-hint').textContent)
      .toBe(t('negotiation.goAheadHint'))
  })

  it('says nothing about a go-ahead while the negotiation is still running', async () => {
    vi.mocked(changesApi.listNegotiations).mockResolvedValue([round()] as never)
    wrap()
    await waitFor(() => expect(screen.getByTestId('negotiation-round-1')).toBeTruthy())
    expect(screen.queryByTestId('negotiation-outcome')).toBeNull()
    expect(screen.queryByTestId('negotiation-goahead-hint')).toBeNull()
  })

  it('posts the round the writer typed', async () => {
    wrap()
    await waitFor(() => expect(screen.getByTestId('negotiation-add')).toBeTruthy())
    fireEvent.click(screen.getByTestId('negotiation-add'))
    fireEvent.change(screen.getByTestId('negotiation-channel-select'), { target: { value: 'email' } })
    fireEvent.change(screen.getByTestId('negotiation-note'),
      { target: { value: 'they came back with a number' } })
    fireEvent.change(screen.getByTestId('negotiation-counter-price'), { target: { value: '950.5' } })
    fireEvent.click(screen.getByTestId('negotiation-submit'))
    await waitFor(() => expect(changesApi.addNegotiation).toHaveBeenCalled())
    expect(vi.mocked(changesApi.addNegotiation).mock.calls[0]).toEqual([7, {
      channel: 'email', note: 'they came back with a number', counter_price: 950.5,
    }])
  })

  it('sends is_final only when the writer ticked the box', async () => {
    wrap()
    await waitFor(() => expect(screen.getByTestId('negotiation-add')).toBeTruthy())
    fireEvent.click(screen.getByTestId('negotiation-add'))
    fireEvent.change(screen.getByTestId('negotiation-note'), { target: { value: 'agreed at 1100' } })
    fireEvent.change(screen.getByTestId('negotiation-counter-price'), { target: { value: '1100' } })
    fireEvent.click(screen.getByTestId('negotiation-final-check'))
    fireEvent.click(screen.getByTestId('negotiation-submit'))
    await waitFor(() => expect(changesApi.addNegotiation).toHaveBeenCalled())
    expect(vi.mocked(changesApi.addNegotiation).mock.calls[0][1]).toEqual({
      channel: 'meeting', note: 'agreed at 1100', counter_price: 1100, is_final: true,
    })
  })

  it('refuses an empty round', async () => {
    wrap()
    await waitFor(() => expect(screen.getByTestId('negotiation-add')).toBeTruthy())
    fireEvent.click(screen.getByTestId('negotiation-add'))
    expect((screen.getByTestId('negotiation-submit') as HTMLButtonElement).disabled).toBe(true)
  })

  it('lets a writer drop their own round but not someone else\'s', async () => {
    vi.mocked(changesApi.listNegotiations).mockResolvedValue([
      round({ id: 1 }),
      round({ id: 2, created_by: 9, created_by_name: 'sales.bert' }),
    ] as never)
    wrap()
    await waitFor(() => expect(screen.getByTestId('negotiation-delete-1')).toBeTruthy())
    expect(screen.queryByTestId('negotiation-delete-2')).toBeNull()
    fireEvent.click(screen.getByTestId('negotiation-delete-1'))
    await waitFor(() => expect(changesApi.deleteNegotiation).toHaveBeenCalledWith(7, 1))
  })

  it('is read-only for anyone who is not Sales, lead or admin', async () => {
    vi.mocked(changesApi.listNegotiations).mockResolvedValue([round()] as never)
    wrap({ canWrite: false })
    await waitFor(() => expect(screen.getByTestId('negotiation-round-1')).toBeTruthy())
    expect(screen.queryByTestId('negotiation-add')).toBeNull()
    expect(screen.queryByTestId('negotiation-form')).toBeNull()
    expect(screen.queryByTestId('negotiation-delete-1')).toBeNull()
    // The record itself still reads.
    expect(screen.getByTestId('negotiation-round-1').textContent)
      .toContain('customer wants 10% off')
  })

  it('closes the log once the change has moved past quoted', async () => {
    // Approved and beyond, the negotiation is history — nothing is added to it
    // and nothing is taken out.
    vi.mocked(changesApi.listNegotiations).mockResolvedValue([round()] as never)
    wrap({ status: 'approved' })
    await waitFor(() => expect(screen.getByTestId('negotiation-round-1')).toBeTruthy())
    expect(screen.queryByTestId('negotiation-add')).toBeNull()
    expect(screen.queryByTestId('negotiation-delete-1')).toBeNull()
  })

  it('says so when no round has happened yet', async () => {
    wrap()
    await waitFor(() => expect(screen.getByTestId('negotiation-none')).toBeTruthy())
    expect(screen.getByTestId('negotiation-none').textContent).toBe(t('negotiation.none'))
  })
})
