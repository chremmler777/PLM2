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
    vi.mocked(auditApi.verify).mockResolvedValue({ valid: true, checked: 42, first_broken_id: null })
  })
  afterEach(cleanup)

  it('renders entries with humanized actions and chain badge', async () => {
    wrap(<AuditTimeline correlationId="CR-2026-0007" />)
    expect(await screen.findByText('gate decided')).toBeDefined()
    expect(screen.getByText('wf started')).toBeDefined()
    expect(screen.getByText(/chain intact/)).toBeDefined()
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
})
