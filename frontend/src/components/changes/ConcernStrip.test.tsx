import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ConcernStrip from './ConcernStrip'
import { changesApi } from '../../api/changes'

vi.mock('../../api/changes', () => ({
  changesApi: {
    listConcerns: vi.fn(),
    raiseConcern: vi.fn().mockResolvedValue({}),
    withdrawConcern: vi.fn().mockResolvedValue({}),
  },
}))
const authState = vi.hoisted(() => ({ current: { userId: 5, isAdmin: false } }))
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => authState.current }))

const concern = (over = {}) => ({
  id: 1, change_id: 7, kind: 'reject_proposal', note: 'Tool cannot hold tolerance',
  raised_by: 9, raised_by_name: 'Rita RD', raised_at: '2026-08-06T10:00:00',
  withdrawn_at: null, resolved_by_meeting_id: null, is_open: true, ...over,
})

const wrap = (ui: React.ReactElement) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>)

describe('ConcernStrip', () => {
  beforeEach(() => {
    authState.current = { userId: 5, isAdmin: false }
    vi.mocked(changesApi.listConcerns).mockResolvedValue([])
    vi.mocked(changesApi.raiseConcern).mockClear()
    vi.mocked(changesApi.withdrawConcern).mockClear()
  })
  afterEach(cleanup)

  it('names who objects and why, and says it blocks proceed', async () => {
    vi.mocked(changesApi.listConcerns).mockResolvedValue([concern()] as never)
    wrap(<ConcernStrip changeId={7} editable />)
    expect(await screen.findByText('Tool cannot hold tolerance')).toBeDefined()
    expect(screen.getByText(/Rita RD/)).toBeDefined()
    expect(screen.getByText(/1 open — blocks proceed/)).toBeDefined()
  })

  it('offers withdraw only on your own flag', async () => {
    vi.mocked(changesApi.listConcerns).mockResolvedValue([
      concern({ id: 1, raised_by: 9, raised_by_name: 'Rita RD' }),
      concern({ id: 2, raised_by: 5, raised_by_name: 'Me', note: 'Mine' }),
    ] as never)
    wrap(<ConcernStrip changeId={7} editable />)
    await screen.findByText('Mine')
    // One withdraw link — for the flag raised by userId 5.
    const links = screen.getAllByRole('button', { name: /withdraw/ })
    expect(links).toHaveLength(1)
    fireEvent.click(links[0])
    await waitFor(() => expect(changesApi.withdrawConcern).toHaveBeenCalledWith(7, 2))
  })

  it('gives an admin no way to clear someone else\'s flag', async () => {
    authState.current = { userId: 5, isAdmin: true }
    vi.mocked(changesApi.listConcerns).mockResolvedValue([
      concern({ raised_by: 9, raised_by_name: 'Rita RD' })] as never)
    wrap(<ConcernStrip changeId={7} editable />)
    await screen.findByText('Tool cannot hold tolerance')
    expect(screen.queryByRole('button', { name: /withdraw/ })).toBeNull()
  })

  it('raises a flag with its kind and note', async () => {
    wrap(<ConcernStrip changeId={7} editable />)
    fireEvent.click(await screen.findByRole('button', { name: /\+ Flag/ }))
    fireEvent.change(screen.getByLabelText(/Concern kind/), { target: { value: 'reject_proposal' } })
    fireEvent.change(screen.getByLabelText(/^Concern$/), { target: { value: '  no capacity  ' } })
    fireEvent.click(screen.getByRole('button', { name: /^Flag$/ }))
    await waitFor(() => expect(changesApi.raiseConcern)
      .toHaveBeenCalledWith(7, 'reject_proposal', 'no capacity'))
  })

  it('shows settled flags struck through and un-withdrawable', async () => {
    vi.mocked(changesApi.listConcerns).mockResolvedValue([
      concern({ raised_by: 5, is_open: false, resolved_by_meeting_id: 3 })] as never)
    wrap(<ConcernStrip changeId={7} editable />)
    await screen.findByText('Tool cannot hold tolerance')
    expect(screen.getByText(/answered by the decision/)).toBeDefined()
    expect(screen.queryByRole('button', { name: /withdraw/ })).toBeNull()
    expect(screen.queryByText(/blocks proceed/)).toBeNull()
  })

  it('hides the raise control once scoping is closed', async () => {
    wrap(<ConcernStrip changeId={7} editable={false} />)
    await waitFor(() => expect(changesApi.listConcerns).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: /\+ Flag/ })).toBeNull()
  })
})
