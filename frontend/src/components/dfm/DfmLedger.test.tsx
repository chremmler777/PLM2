import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DfmLedger, { initials, shortDate } from './DfmLedger'
import type { DfmEntry, DfmTopicDetail } from '../../api/dfm'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '/api' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('./DfmEntryForm', () => ({ default: (p: { party: string; supersedesId?: number | null }) =>
  <div data-testid="entry-form">{p.party}:{p.supersedesId ?? 'new'}</div> }))

const entry = (over: Record<string, unknown>) => ({
  id: 1, topic_id: 2, party: 'ktx', addressed_to: ['toolmaker', 'tier1'], note: 'DFM request rev A', sent_at: '2026-09-24',
  supersedes_id: null, recorded_by: 14, recorded_by_name: 'Christoph Demmler', recorded_at: '2026-09-24T10:00:00', files: [], history: [], ...over,
} as unknown as DfmEntry)
const topic = (over: Partial<DfmTopicDetail> = {}): DfmTopicDetail => ({
  id: 2, tool_part_id: 7, title: 'Gate position', status: 'open', opened_by: 14, opened_at: '2026-09-24T09:00:00',
  closed_by: null, closed_at: null, entry_count: 3, last_activity: '2026-09-27T10:00:00',
  entries: [
    entry({ id: 1, files: [{ id: 41, entry_id: 1, original_filename: 'dfm_request_A.pdf', file_size: 10, content_type: 'application/pdf', uploaded_by: 14, uploaded_by_name: 'Christoph Demmler', uploaded_at: '2026-09-24T10:00:00' }] }),
    entry({ id: 2, party: 'toolmaker', addressed_to: ['ktx'], note: 'DFM study rev 1', sent_at: '2026-09-26', recorded_at: '2026-09-26T08:00:00',
      files: [{ id: 42, entry_id: 2, original_filename: 'volumes.xlsx', file_size: 10, content_type: 'application/vnd.ms-excel', uploaded_by: 14, uploaded_by_name: 'Christoph Demmler', uploaded_at: '2026-09-26T08:00:00' }] }),
    entry({ id: 4, addressed_to: ['toolmaker'], note: 'answer, 2 points open', sent_at: '2026-09-27', recorded_at: '2026-09-27T10:00:00', supersedes_id: 3,
      recorded_by_name: 'Karl Huber', history: [entry({ id: 3, addressed_to: ['toolmaker'], note: 'answer, 3 points open', sent_at: '2026-09-26', recorded_at: '2026-09-26T12:00:00' })] }),
  ],
  ...over,
})

function wrap(onOpenPdf = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><DfmLedger partId={7} topicId={2} onOpenPdf={onOpenPdf} /></QueryClientProvider>)
  return onOpenPdf
}

describe('DfmLedger', () => {
  beforeEach(() => {
    clientMocks.get.mockReset(); clientMocks.post.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/7/dfm/topics/2') return Promise.resolve({ data: topic() })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('puts entries in their party column, in time order, with the addressed-to line', async () => {
    wrap()
    const ledger = await screen.findByTestId('dfm-ledger')
    const rows = ledger.querySelectorAll('[data-testid^="dfm-entry-"]')
    expect(Array.from(rows).map((r) => r.getAttribute('data-testid'))).toEqual(['dfm-entry-1', 'dfm-entry-2', 'dfm-entry-4'])
    expect(Array.from(rows).map((r) => r.getAttribute('data-party'))).toEqual(['ktx', 'toolmaker', 'ktx'])
    expect(screen.getByTestId('dfm-entry-1').textContent).toContain('09-24 → Toolmaker, Tier 1')
    expect(screen.getByTestId('dfm-entry-2').textContent).toContain('09-26 → KTX')
    expect(screen.getByTestId('dfm-entry-1').textContent).toContain('↑CD')
    expect(screen.getByTestId('dfm-entry-4').textContent).toContain('↑KH')
    expect(screen.getByTestId('dfm-column-toolmaker').textContent).toContain('Toolmaker')
  })

  it('marks an updated entry and collapses the earlier version', async () => {
    wrap()
    const updated = await screen.findByTestId('dfm-entry-4')
    expect(updated.textContent).toContain('(updated)')
    expect(updated.textContent).toContain('1 earlier version')
    expect(updated.textContent).not.toContain('answer, 3 points open')
    fireEvent.click(within(updated).getByTestId('dfm-history-4'))
    expect(updated.textContent).toContain('answer, 3 points open')
  })

  it('opens PDFs in the pane and downloads other files', async () => {
    const onOpenPdf = wrap()
    fireEvent.click(await screen.findByTestId('dfm-file-41'))
    expect(onOpenPdf).toHaveBeenCalledWith({ fileId: 41, filename: 'dfm_request_A.pdf', kind: 'pdf', revisionName: 'Gate position', inlineUrl: '/api/v1/parts/7/dfm/files/41/inline' })
    const link = screen.getByTestId('dfm-file-42') as HTMLAnchorElement
    expect(link.tagName).toBe('A')
    expect(link.href).toContain('/api/v1/parts/7/dfm/files/42/download')
  })

  it('opens the entry form under a column and the update form on an own entry', async () => {
    wrap()
    fireEvent.click(await screen.findByTestId('dfm-add-tier1'))
    expect(screen.getByTestId('entry-form').textContent).toBe('tier1:new')
    fireEvent.click(screen.getByTestId('dfm-update-4'))
    expect(screen.getByTestId('entry-form').textContent).toBe('ktx:4')
  })

  it('finishes an open topic', async () => {
    clientMocks.post.mockResolvedValue({ data: topic({ status: 'finished_confirmed' }) })
    wrap()
    fireEvent.click(await screen.findByTestId('dfm-finish'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/7/dfm/topics/2/close'))
  })

  it('renders a finished topic read-only with Reopen', async () => {
    clientMocks.get.mockImplementation(() => Promise.resolve({ data: topic({ status: 'finished_confirmed', closed_at: '2026-10-01T09:00:00' }) }))
    clientMocks.post.mockResolvedValue({ data: topic() })
    wrap()
    expect(await screen.findByTestId('dfm-reopen')).toBeTruthy()
    expect(screen.queryByTestId('dfm-finish')).toBeNull()
    expect(screen.queryByTestId('dfm-add-ktx')).toBeNull()
    expect(screen.queryByTestId('dfm-update-4')).toBeNull()
    expect(screen.getByTestId('dfm-ledger').textContent).toContain('Finished confirmed')
    fireEvent.click(screen.getByTestId('dfm-reopen'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/7/dfm/topics/2/reopen'))
  })
})

describe('helpers', () => {
  it('initials and short dates', () => {
    expect(initials('Christoph Demmler')).toBe('CD')
    expect(initials('karl')).toBe('K')
    expect(initials(null)).toBe('?')
    expect(shortDate('2026-09-24')).toBe('09-24')
    expect(shortDate('2026-09-24T10:00:00')).toBe('09-24')
  })
})
