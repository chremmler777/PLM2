import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react'
import DfmAuditLog from './DfmAuditLog'
import type { DfmAuditEvent } from '../../api/dfm'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '/api' }))

const events: DfmAuditEvent[] = [
  { id: 42, at: '2026-09-24T09:15:02.113400', action: 'file_attached', actor: { id: 2, name: 'Engineer' },
    topic: { id: 7, title: 'Gate position' }, entry: { id: 19, kind: 'original', party: 'ktx' }, file: { id: 11, filename: 'dfm_request_A.pdf' },
    details: { filename: 'dfm_request_A.pdf', size: 482113, content_type: 'application/pdf', sha256: '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08' } },
  { id: 41, at: '2026-09-24T09:15:02.101002', action: 'entry_recorded', actor: { id: 2, name: 'Engineer' },
    topic: { id: 7, title: 'Gate position' }, entry: { id: 19, kind: 'original', party: 'ktx' }, file: null,
    details: { kind: 'original', party: 'ktx', addressed_to: ['toolmaker', 'tier1'], reply_to_id: null, note: 'DFM request rev A' } },
  { id: 40, at: '2026-09-24T09:12:40.550210', action: 'topic_opened', actor: { id: 2, name: 'Engineer' },
    topic: { id: 7, title: 'Gate position' }, entry: null, file: null, details: { title: 'Gate position' } },
  { id: 39, at: '2026-09-23T09:12:40.550210', action: 'file_viewed', actor: { id: 3, name: 'Karl Huber' },
    topic: { id: 7, title: 'Gate position' }, entry: { id: 19, kind: 'original', party: 'ktx' }, file: { id: 11, filename: 'dfm_request_A.pdf' },
    details: { filename: 'dfm_request_A.pdf' } },
  { id: 38, at: '2026-09-22T09:12:40.550210', action: 'topic_closed', actor: { id: 2, name: 'Engineer' },
    topic: { id: 7, title: 'Gate position' }, entry: null, file: null, details: { title: 'Gate position', backfilled: true } },
]

function wrap(props: { topicId?: number; onJumpToEntry?: (entryId: number, topicId: number) => void } = {}) {
  return render(<DfmAuditLog partId={7} topicId={props.topicId} onJumpToEntry={props.onJumpToEntry ?? vi.fn()} />)
}

describe('DfmAuditLog', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/7/dfm/audit') return Promise.resolve({ data: events })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('renders events newest first with plain-word actions', async () => {
    wrap()
    await screen.findByTestId('dfm-audit-row-42')
    const rows = screen.getAllByTestId(/dfm-audit-row-/)
    expect(rows.map((r) => r.getAttribute('data-testid'))).toEqual([
      'dfm-audit-row-42', 'dfm-audit-row-41', 'dfm-audit-row-40', 'dfm-audit-row-39', 'dfm-audit-row-38',
    ])
    expect(screen.getByTestId('dfm-audit-row-42').textContent).toContain('File attached')
    expect(screen.getByTestId('dfm-audit-row-41').textContent).toContain('Message recorded')
    expect(screen.getByTestId('dfm-audit-row-40').textContent).toContain('Topic opened')
    expect(screen.getByTestId('dfm-audit-row-39').textContent).toContain('File viewed')
    expect(screen.getByTestId('dfm-audit-row-38').textContent).toContain('Topic finished')
  })

  it('shows a kind badge and from -> to for message events', async () => {
    wrap()
    const row = await screen.findByTestId('dfm-audit-row-41')
    expect(within(row).getByTestId('dfm-audit-kind').textContent).toBe('Original')
    expect(row.textContent).toContain('KTX')
    expect(row.textContent).toContain('Toolmaker')
    expect(row.textContent).toContain('Tier 1')
  })

  it('shows filename, size and a short sha256 prefix with the full value in a tooltip for file_attached', async () => {
    wrap()
    const row = await screen.findByTestId('dfm-audit-row-42')
    expect(row.textContent).toContain('dfm_request_A.pdf')
    expect(row.textContent).toContain('471 KB')
    const sha = within(row).getByTestId('dfm-audit-sha')
    expect(sha.textContent).toBe('9f86d08188')
    expect(sha.getAttribute('title')).toBe('9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08')
  })

  it('marks a backfilled event as reconstructed with a tooltip', async () => {
    wrap()
    const row = await screen.findByTestId('dfm-audit-row-38')
    const marker = within(row).getByTestId('dfm-audit-reconstructed')
    expect(marker.textContent).toContain('reconstructed')
    expect(marker.getAttribute('title')).toMatch(/rebuilt from existing data/i)
  })

  it('does not mark a non-backfilled event as reconstructed', async () => {
    wrap()
    const row = await screen.findByTestId('dfm-audit-row-42')
    expect(within(row).queryByTestId('dfm-audit-reconstructed')).toBeNull()
  })

  it('shows a topic column only in tool-wide view', async () => {
    wrap()
    let row = await screen.findByTestId('dfm-audit-row-42')
    expect(within(row).getByTestId('dfm-audit-topic').textContent).toContain('Gate position')
    cleanup()
    clientMocks.get.mockImplementation((url: string) =>
      url === '/v1/parts/7/dfm/audit' ? Promise.resolve({ data: events }) : Promise.resolve({ data: [] }))
    wrap({ topicId: 7 })
    row = await screen.findByTestId('dfm-audit-row-42')
    expect(within(row).queryByTestId('dfm-audit-topic')).toBeNull()
    const calls = clientMocks.get.mock.calls.filter((c) => c[0] === '/v1/parts/7/dfm/audit')
    expect(calls[calls.length - 1]?.[1]?.params?.topic_id).toBe(7)
  })

  it('filters by action group client-side', async () => {
    wrap()
    await screen.findByTestId('dfm-audit-row-42')
    fireEvent.change(screen.getByTestId('dfm-audit-filter'), { target: { value: 'messages' } })
    await waitFor(() => {
      const rows = screen.getAllByTestId(/dfm-audit-row-/)
      expect(rows.map((r) => r.getAttribute('data-testid'))).toEqual(['dfm-audit-row-41'])
    })
    fireEvent.change(screen.getByTestId('dfm-audit-filter'), { target: { value: 'views' } })
    await waitFor(() => {
      const rows = screen.getAllByTestId(/dfm-audit-row-/)
      expect(rows.map((r) => r.getAttribute('data-testid'))).toEqual(['dfm-audit-row-39'])
    })
  })

  it('loads older events with before_id and appends them', async () => {
    // A full page (100) signals more may follow; the button then pages with before_id.
    const fullPage: DfmAuditEvent[] = Array.from({ length: 100 }, (_, i) => ({ ...events[0], id: 200 - i }))
    clientMocks.get.mockImplementation((url: string, config?: { params?: Record<string, unknown> }) => {
      if (url !== '/v1/parts/7/dfm/audit') return Promise.resolve({ data: [] })
      if (config?.params?.before_id === 101) return Promise.resolve({ data: events })
      return Promise.resolve({ data: fullPage })
    })
    wrap()
    await screen.findByTestId('dfm-audit-row-200')
    fireEvent.click(screen.getByTestId('dfm-audit-load-older'))
    await waitFor(() => {
      const call = clientMocks.get.mock.calls.find((c) => c[1]?.params?.before_id === 101)
      expect(call).toBeTruthy()
    })
    await screen.findByTestId('dfm-audit-row-42')
  })

  it('links a message/file row to "#N" that switches back to the flow and highlights it', async () => {
    const onJump = vi.fn()
    wrap({ onJumpToEntry: onJump })
    const row = await screen.findByTestId('dfm-audit-row-42')
    fireEvent.click(within(row).getByTestId('dfm-audit-jump-19'))
    expect(onJump).toHaveBeenCalledWith(19, 7)
  })

  it('renders a CSV export link using the app API base, with topic_id in topic view', async () => {
    wrap()
    await screen.findByTestId('dfm-audit-row-42')
    expect(screen.getByTestId('dfm-audit-csv').getAttribute('href')).toBe('/api/v1/parts/7/dfm/audit.csv')
    cleanup()
    clientMocks.get.mockImplementation((url: string) =>
      url === '/v1/parts/7/dfm/audit' ? Promise.resolve({ data: events }) : Promise.resolve({ data: [] }))
    wrap({ topicId: 7 })
    await screen.findByTestId('dfm-audit-row-42')
    expect(screen.getByTestId('dfm-audit-csv').getAttribute('href')).toBe('/api/v1/parts/7/dfm/audit.csv?topic_id=7')
  })
})
