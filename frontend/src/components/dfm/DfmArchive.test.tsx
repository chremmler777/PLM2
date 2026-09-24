import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DfmArchive from './DfmArchive'
import { relaySummary } from './dfmFixtures'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('./DfmFlow', () => ({
  default: (p: { topicId: number; onBack(): void; onPopOut?: () => void }) => (
    <div data-testid="flow">
      <span data-testid="flow-topic">topic {p.topicId}</span>
      <button data-testid="flow-back" onClick={p.onBack}>back</button>
      {p.onPopOut && <button data-testid="flow-popout" onClick={p.onPopOut}>pop</button>}
    </div>
  ),
}))
const windowMocks = vi.hoisted(() => ({ openDfmWindow: vi.fn() }))
vi.mock('./dfmWindow', () => windowMocks)

const topics = [
  relaySummary({ id: 2, title: 'Gate position', waiting_on: [{ party: 'tier1', count: 1, oldest_days: 4 }],
    last_step: { kind: 'forward', party: 'ktx', addressed_to: ['tier1'], date: '2026-09-19' }, entry_count: 3 }),
  relaySummary({ id: 3, title: 'Cooling', waiting_on: [], all_answered: true, entry_count: 1,
    last_step: { kind: 'answer', party: 'ktx', addressed_to: ['toolmaker'], date: '2026-09-20' } }),
  relaySummary({ id: 1, title: 'Draft angles', status: 'finished_confirmed', closed_by: 14, closed_at: '2026-09-20T09:00:00' }),
]

function wrap(props: { initialTopic?: number; inWindow?: boolean } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><DfmArchive partId={7} onOpenPdf={vi.fn()} {...props} /></QueryClientProvider>)
}

describe('DfmArchive', () => {
  beforeEach(() => {
    clientMocks.get.mockReset(); clientMocks.post.mockReset(); windowMocks.openDfmWindow.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/7/dfm/topics') return Promise.resolve({ data: topics })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('lists topics with status, waiting summary, last step and message count', async () => {
    wrap()
    const row = await screen.findByTestId('dfm-topic-2')
    expect(row.textContent).toContain('Gate position')
    expect(row.textContent).toContain('Open')
    expect(screen.getByTestId('dfm-topic-waiting-2').textContent).toBe('waiting on Tier 1 · 4 d')
    expect(screen.getByTestId('dfm-topic-last-2').textContent).toBe('Forward KTX → Tier 1 09-19')
    expect(row.textContent).toContain('3 messages')
    expect(screen.getByTestId('dfm-topic-waiting-3').textContent).toBe('all answered')
    expect(screen.getByTestId('dfm-topic-3').textContent).toContain('1 message')
    expect(screen.getByTestId('dfm-topic-1').textContent).toContain('Finished confirmed')
    expect(screen.queryByTestId('dfm-topic-waiting-1')).toBeNull()
  })

  it('opens the selected topic in place of the list, and the breadcrumb returns to the list', async () => {
    wrap()
    fireEvent.click(await screen.findByTestId('dfm-topic-2'))
    expect(screen.getByTestId('flow-topic').textContent).toBe('topic 2')
    expect(screen.queryByTestId('dfm-topic-3')).toBeNull()
    expect(screen.queryByTestId('dfm-new-topic')).toBeNull()
    fireEvent.click(screen.getByTestId('flow-back'))
    expect(screen.queryByTestId('flow')).toBeNull()
    expect(screen.getByTestId('dfm-topic-3')).toBeTruthy()
  })

  it('opens the archive in its own window, with the open topic', async () => {
    wrap()
    fireEvent.click(await screen.findByTestId('dfm-popout'))
    expect(windowMocks.openDfmWindow).toHaveBeenCalledWith(7, null)
    fireEvent.click(screen.getByTestId('dfm-topic-2'))
    fireEvent.click(screen.getByTestId('flow-popout'))
    expect(windowMocks.openDfmWindow).toHaveBeenLastCalledWith(7, 2)
  })

  it('in its own window: starts on the asked topic and offers no further pop-out', async () => {
    wrap({ initialTopic: 3, inWindow: true })
    expect((await screen.findByTestId('flow-topic')).textContent).toBe('topic 3')
    expect(screen.queryByTestId('flow-popout')).toBeNull()
    fireEvent.click(screen.getByTestId('flow-back'))
    expect(await screen.findByTestId('dfm-topic-2')).toBeTruthy()
    expect(screen.queryByTestId('dfm-popout')).toBeNull()
  })

  it('creates a topic and selects it', async () => {
    clientMocks.post.mockResolvedValue({ data: { ...topics[0], id: 9, title: 'Cooling layout', entry_count: 0 } })
    wrap()
    fireEvent.click(await screen.findByTestId('dfm-new-topic'))
    fireEvent.change(screen.getByTestId('dfm-topic-title'), { target: { value: 'Cooling layout' } })
    fireEvent.click(screen.getByTestId('dfm-create-topic'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/7/dfm/topics', { title: 'Cooling layout' }))
    await waitFor(() => expect(screen.getByTestId('flow-topic').textContent).toBe('topic 9'))
  })

  it('says when there is nothing yet', async () => {
    clientMocks.get.mockImplementation(() => Promise.resolve({ data: [] }))
    wrap()
    expect((await screen.findByTestId('dfm-archive')).textContent).toContain('No DFM topic yet')
  })

  it('shows an error line when the topics query fails', async () => {
    clientMocks.get.mockImplementation(() => Promise.reject(new Error('network down')))
    wrap()
    expect((await screen.findByTestId('dfm-archive-error')).textContent).toContain('Could not load the DFM archive')
  })
})
