import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AuditTimeline from './AuditTimeline'
import { auditApi } from '../../api/audit'

vi.mock('../../api/audit', () => ({
  auditApi: { list: vi.fn(), verify: vi.fn(), downloadCsv: vi.fn() },
}))

const entry = (over: Record<string, unknown>) => ({
  id: 1, entity_type: 'change', entity_id: 7, action: 'status_changed',
  user_id: 5, timestamp: '2026-07-01T10:00:00', old_values: '{"status": "captured"}',
  new_values: '{"status": "in_assessment"}', correlation_id: 'CR-2026-0007',
  log_level: 'info', ...over,
})

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('AuditTimeline', () => {
  beforeEach(() => {
    vi.mocked(auditApi.list).mockResolvedValue([
      entry({ id: 2, action: 'gate_decided', entity_type: 'change' }),
      entry({ id: 1, action: 'wf_started', entity_type: 'wf_instance', entity_id: 3 }),
    ])
    vi.mocked(auditApi.verify).mockResolvedValue({
      valid: true, checked: 42, first_broken_id: null,
      correlation_entries: 2, correlation_ok: true,
    })
  })
  afterEach(cleanup)

  it('renders entries with humanized actions and chain badge', async () => {
    wrap(<AuditTimeline correlationId="CR-2026-0007" />)
    expect(await screen.findByText('gate decided')).toBeDefined()
    expect(screen.getByText('wf started')).toBeDefined()
    expect(screen.getByText(/chain intact/)).toBeDefined()
    expect(auditApi.verify).toHaveBeenCalledWith({ correlation_id: 'CR-2026-0007' })
  })

  it('shows correlation-scoped broken wording when correlation_ok is false', async () => {
    vi.mocked(auditApi.verify).mockResolvedValue({
      valid: true, checked: 42, first_broken_id: null,
      correlation_entries: 2, correlation_ok: false,
    })
    wrap(<AuditTimeline correlationId="CR-2026-0007" />)
    expect(await screen.findByText(/chain broken/)).toBeDefined()
  })

  it('filters by entity type and exports', async () => {
    wrap(<AuditTimeline correlationId="CR-2026-0007" />)
    await screen.findByText('gate decided')
    fireEvent.click(screen.getByRole('button', { name: 'wf_instance' }))
    expect(screen.queryByText('gate decided')).toBeNull()
    expect(screen.getByText('wf started')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: /Export CSV/ }))
    expect(auditApi.downloadCsv).toHaveBeenCalledWith({ correlation_id: 'CR-2026-0007' })
  })

  it('groups entries under UTC day headings suffixed "(UTC)"', async () => {
    vi.mocked(auditApi.list).mockResolvedValue([
      // 23:30 UTC on 2026-07-01 - a local-timezone browser (e.g. UTC+2)
      // would incorrectly bucket this into 2026-07-02 if grouping used
      // local time instead of UTC.
      entry({ id: 1, action: 'gate_decided', timestamp: '2026-07-01T23:30:00Z' }),
    ])
    wrap(<AuditTimeline correlationId="CR-2026-0007" />)
    await screen.findByText('gate decided')
    expect(screen.getByText(/\(UTC\)/)).toBeDefined()
  })

  it('buckets entries straddling midnight UTC into two distinct day headings', async () => {
    // One entry 30 minutes before midnight UTC on 2026-07-01, one 30 minutes
    // after - these must land on two DIFFERENT UTC calendar days. A
    // local-timezone (non-UTC) grouping bug would merge them into one
    // heading for browsers ahead of UTC, or could otherwise miscompute the
    // date. Assert both expected UTC-dated headings are present.
    vi.mocked(auditApi.list).mockResolvedValue([
      entry({ id: 2, action: 'gate_decided', timestamp: '2026-07-02T00:30:00Z' }),
      entry({ id: 1, action: 'wf_started', timestamp: '2026-07-01T23:30:00Z' }),
    ])
    wrap(<AuditTimeline correlationId="CR-2026-0007" />)
    await screen.findByText('gate decided')

    const expectedDay1 = `${new Date('2026-07-01T23:30:00Z').toLocaleDateString(undefined, { timeZone: 'UTC' })} (UTC)`
    const expectedDay2 = `${new Date('2026-07-02T00:30:00Z').toLocaleDateString(undefined, { timeZone: 'UTC' })} (UTC)`
    expect(expectedDay1).not.toBe(expectedDay2)
    expect(screen.getByText(expectedDay1)).toBeDefined()
    expect(screen.getByText(expectedDay2)).toBeDefined()
  })

  it('shows a truncation notice when entries hit the fetch limit', async () => {
    const many = Array.from({ length: 1000 }, (_, i) => entry({ id: i + 1 }))
    vi.mocked(auditApi.list).mockResolvedValue(many)
    wrap(<AuditTimeline correlationId="CR-2026-0007" />)
    expect(await screen.findByText(/newest 1000/)).toBeDefined()
  })

  it('does not show a truncation notice when under the fetch limit', async () => {
    wrap(<AuditTimeline correlationId="CR-2026-0007" />)
    await screen.findByText('gate decided')
    expect(screen.queryByText(/newest 1000/)).toBeNull()
  })
})
