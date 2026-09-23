import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DfmArchive from './DfmArchive'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('./DfmLedger', () => ({ default: (p: { topicId: number }) => <div data-testid="ledger">topic {p.topicId}</div> }))

const topics = [
  { id: 2, tool_part_id: 7, title: 'Gate position', status: 'open', opened_by: 14, opened_at: '2026-09-24T09:00:00',
    closed_by: null, closed_at: null, entry_count: 3, last_activity: '2026-09-27T10:00:00' },
  { id: 1, tool_part_id: 7, title: 'Draft angles', status: 'finished_confirmed', opened_by: 14, opened_at: '2026-09-10T09:00:00',
    closed_by: 14, closed_at: '2026-09-20T09:00:00', entry_count: 5, last_activity: '2026-09-20T09:00:00' },
]

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><DfmArchive partId={7} onOpenPdf={vi.fn()} /></QueryClientProvider>)
}

describe('DfmArchive', () => {
  beforeEach(() => {
    clientMocks.get.mockReset(); clientMocks.post.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/7/dfm/topics') return Promise.resolve({ data: topics })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('lists topics with status, entry count and last activity', async () => {
    wrap()
    const row = await screen.findByTestId('dfm-topic-2')
    expect(row.textContent).toContain('Gate position')
    expect(row.textContent).toContain('Open')
    expect(row.textContent).toContain('3 entries')
    expect(row.textContent).toContain('2026-09-27')
    expect(screen.getByTestId('dfm-topic-1').textContent).toContain('Finished confirmed')
  })

  it('opens the ledger of the selected topic', async () => {
    wrap()
    fireEvent.click(await screen.findByTestId('dfm-topic-2'))
    expect(screen.getByTestId('ledger').textContent).toBe('topic 2')
  })

  it('creates a topic and selects it', async () => {
    clientMocks.post.mockResolvedValue({ data: { ...topics[0], id: 9, title: 'Cooling layout', entry_count: 0 } })
    wrap()
    fireEvent.click(await screen.findByTestId('dfm-new-topic'))
    fireEvent.change(screen.getByTestId('dfm-topic-title'), { target: { value: 'Cooling layout' } })
    fireEvent.click(screen.getByTestId('dfm-create-topic'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/7/dfm/topics', { title: 'Cooling layout' }))
    await waitFor(() => expect(screen.getByTestId('ledger').textContent).toBe('topic 9'))
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
