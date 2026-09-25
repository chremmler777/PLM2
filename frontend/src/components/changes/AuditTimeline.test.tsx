import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AuditTimeline from './AuditTimeline'
import { formatDate } from '../../lib/format'
import { auditApi } from '../../api/audit'

vi.mock('../../api/audit', () => ({
  auditApi: { list: vi.fn(), verify: vi.fn(), downloadCsv: vi.fn() },
}))
vi.mock('../../api/changes', () => ({
  changesApi: { changelog: vi.fn().mockResolvedValue([]) },
}))
import { changesApi } from '../../api/changes'
import { formatDateTime } from '../../lib/format'

const entry = (over: Record<string, unknown>) => ({
  id: 1, entity_type: 'change', entity_id: 7, action: 'status_changed',
  user_id: 5, user_name: 'Dana Lee', timestamp: '2026-07-01T10:00:00',
  old_values: '{"status": "captured"}',
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

  it('shows who acted and renders the change as prose, not raw JSON', async () => {
    vi.mocked(auditApi.list).mockResolvedValue([
      entry({ id: 3, action: 'status_changed', user_name: 'Dana Lee',
              old_values: '"captured"', new_values: '"in_assessment"' }),
      entry({ id: 2, action: 'attachment_added', user_name: 'Sam Ito',
              old_values: null, new_values: '{"filename": "deck.pptx"}' }),
    ])
    wrap(<AuditTimeline correlationId="CR-2026-0007" />)
    // Who
    expect(await screen.findByText('Dana Lee')).toBeDefined()
    expect(screen.getByText('Sam Ito')).toBeDefined()
    // Human-readable payload, no braces/quotes/keys-as-JSON
    expect(screen.getByText(/Captured → In Assessment/)).toBeDefined()
    expect(screen.getByText(/deck\.pptx/)).toBeDefined()
    expect(screen.queryByText(/\{/)).toBeNull()
    expect(screen.queryByText(/"filename"/)).toBeNull()
  })

  it('names the department an admin acted as, and reads resolved values in words', async () => {
    vi.mocked(auditApi.list).mockResolvedValue([
      entry({ id: 4, action: 'impacted_added', user_name: 'admin', real_user_name: 'Chris D',
              acting_as_department_name: 'Project Manager',
              old_values: null, new_values: '{"part_id": 2267}', display_values: { part_id: '3457-10' } }),
      entry({ id: 3, action: 'scoping_meeting_recorded', user_name: 'Dana Lee',
              old_values: null, new_values: '{"meeting_id": 27, "channel": "email"}' }),
      entry({ id: 2, action: 'deadline_set', user_name: 'Dana Lee',
              old_values: null, new_values: '"2026-09-30 23:59:59"' }),
    ])
    wrap(<AuditTimeline correlationId="CR-2026-0007" />)
    expect((await screen.findByTestId('audit-acting')).textContent).toBe('(as Project Manager)')
    expect(screen.getByText(/Chris D/)).toBeDefined()
    expect(screen.getByText(/part: 3457-10/)).toBeDefined()
    expect(screen.queryByText(/2267/)).toBeNull()
    expect(screen.getByText(/meeting: #27, channel: E-?mail/i)).toBeDefined()
    expect(screen.getByText(/30\.09\.2026 23:59/)).toBeDefined()
  })

  it('falls back to "System" when there is no actor', async () => {
    vi.mocked(auditApi.list).mockResolvedValue([
      entry({ id: 1, action: 'gate_decided', user_name: null, user_id: null }),
    ])
    wrap(<AuditTimeline correlationId="CR-2026-0007" />)
    expect(await screen.findByText('System')).toBeDefined()
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
    fireEvent.click(screen.getByRole('button', { name: 'Wf instance' }))
    expect(screen.queryByText('gate decided')).toBeNull()
    expect(screen.getByText('wf started')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: /Export CSV/ }))
    expect(auditApi.downloadCsv).toHaveBeenCalledWith({ correlation_id: 'CR-2026-0007' })
  })

  it('groups entries under a local-day heading with no "(UTC)" suffix', async () => {
    vi.mocked(auditApi.list).mockResolvedValue([
      entry({ id: 1, action: 'gate_decided', timestamp: '2026-07-01T10:00:00Z' }),
    ])
    wrap(<AuditTimeline correlationId="CR-2026-0007" />)
    await screen.findByText('gate decided')
    expect(screen.queryByText(/\(UTC\)/)).toBeNull()
    const expectedDay = formatDate('2026-07-01T10:00:00Z')
    expect(screen.getByText(expectedDay)).toBeDefined()
  })

  it('buckets entries straddling local midnight into two distinct day headings', async () => {
    // The test environment pins TZ=Europe/Berlin (UTC+2 in July), where local
    // midnight falls at 22:00 UTC. Naive timestamps (no "Z") are read as UTC
    // by parseApiDateTime, so 21:30 UTC / 22:30 UTC straddle that boundary:
    // 23:30 local on 2026-07-01 and 00:30 local on 2026-07-02.
    vi.mocked(auditApi.list).mockResolvedValue([
      entry({ id: 2, action: 'gate_decided', timestamp: '2026-07-01T22:30:00' }),
      entry({ id: 1, action: 'wf_started', timestamp: '2026-07-01T21:30:00' }),
    ])
    wrap(<AuditTimeline correlationId="CR-2026-0007" />)
    await screen.findByText('gate decided')

    const expectedDay1 = formatDate('2026-07-01T21:30:00Z')
    const expectedDay2 = formatDate('2026-07-01T22:30:00Z')
    expect(expectedDay1).not.toBe(expectedDay2)
    expect(screen.getByText(expectedDay1)).toBeDefined()
    expect(screen.getByText(expectedDay2)).toBeDefined()
  })

  it('shows a truncation notice when entries hit the fetch limit', async () => {
    const many = Array.from({ length: 1000 }, (_, i) => entry({ id: i + 1 }))
    vi.mocked(auditApi.list).mockResolvedValue(many)
    wrap(<AuditTimeline correlationId="CR-2026-0007" />)
    expect(await screen.findByText(/newest 1000/)).toBeDefined()
    // Rendering 1000 rows under full-suite parallel load regularly breaches the
    // default 5s — a real flake, not a real failure.
  }, 15000)

  it('does not show a truncation notice when under the fetch limit', async () => {
    wrap(<AuditTimeline correlationId="CR-2026-0007" />)
    await screen.findByText('gate decided')
    expect(screen.queryByText(/newest 1000/)).toBeNull()
  })

  it('reads the change trail by change id and tells a global break from its own (spec §16)', async () => {
    vi.mocked(auditApi.verify).mockResolvedValue({
      valid: false, checked: 42, first_broken_id: 9, correlation_entries: 2, correlation_ok: false,
      change_entries: 2, change_ok: true, change_first_broken_id: null, break_scope: 'global',
    })
    wrap(<AuditTimeline correlationId="CR-2026-0007" changeId={7} />)
    const badge = await screen.findByTestId('audit-chain')
    expect(badge.textContent).toContain('global chain is broken at #9, outside this change')
    expect(auditApi.list).toHaveBeenCalledWith(expect.objectContaining({ change_id: 7 }))
    expect(auditApi.verify).toHaveBeenCalledWith({ correlation_id: 'CR-2026-0007', change_id: 7 })
  })

  it('flags a break inside the change\'s own entries in red', async () => {
    vi.mocked(auditApi.verify).mockResolvedValue({
      valid: false, checked: 42, first_broken_id: 2, change_entries: 2, change_ok: false,
      change_first_broken_id: 2, break_scope: 'change',
    })
    wrap(<AuditTimeline correlationId="CR-2026-0007" changeId={7} />)
    const badge = await screen.findByTestId('audit-chain')
    expect(badge.textContent).toContain("broken inside this change's entries (at #2)")
    expect(badge.className).toContain('red')
  })

  it('shows audit values and entity types in words, days as dd.mm.yyyy', async () => {
    vi.mocked(auditApi.list).mockResolvedValue([
      entry({ id: 4, action: 'field_changed', old_values: '{"verdict": "pending"}',
        new_values: '{"verdict": "feasible_with_conditions"}', entity_type: 'change_assessment' }),
    ])
    wrap(<AuditTimeline correlationId="CR-2026-0007" changeId={7} />)
    expect(await screen.findByText(/verdict: Not answered yet → verdict: Feasible with conditions/)).toBeDefined()
    expect(screen.getByText('01.07.2026')).toBeDefined()
    expect(screen.getAllByText(/Change assessment/).length).toBeGreaterThan(0)
  })

  it('names what an id refers to, drops ids a name already says, and reads moments in local time', async () => {
    vi.mocked(auditApi.list).mockResolvedValue([
      entry({ id: 5, action: 'back_to_scoping', old_values: null,
        new_values: '{"superseded_assessment_ids": [258, 259]}' }),
      entry({ id: 6, action: 'assessment_superseded', new_values: null,
        old_values: '{"assessment_id": 258, "department_id": 28, "department_name": "Development", '
          + '"submitted_at": "2026-09-25T12:17:00"}' }),
      entry({ id: 7, action: 'scoping_meeting_recorded', old_values: null,
        new_values: '{"meeting_id": 41, "channel": "meeting"}' }),
    ])
    wrap(<AuditTimeline correlationId="CR-2026-0007" />)
    expect(await screen.findByText(/superseded assessments: #258, #259/)).toBeDefined()
    const superseded = screen.getByText(/assessment: #258/).textContent ?? ''
    expect(superseded).toContain('department name: Development')
    expect(superseded).not.toContain('department:')
    expect(superseded).toContain(`submitted at: ${formatDateTime('2026-09-25T12:17:00')}`)
    expect(screen.getByText(/meeting: #41/)).toBeDefined()
  })

  it('shows the reason back to scoping was taken with', async () => {
    vi.mocked(auditApi.list).mockResolvedValue([
      entry({ id: 5, action: 'back_to_scoping', old_values: null, timestamp: '2026-09-25T12:17:30',
        new_values: '{"superseded_assessment_ids": [258]}' }),
    ])
    vi.mocked(changesApi.changelog).mockResolvedValue([
      { id: 1, action: 'back_to_scoping', action_description: 'Back to scoping', performed_by: 1,
        performed_at: '2026-09-25T12:17:31', notes: 'Hole cannot move, rescope with Tooling' },
    ])
    wrap(<AuditTimeline correlationId="CR-2026-0007" changeId={7} />)
    expect((await screen.findByTestId('audit-reason-5')).textContent)
      .toBe('(reason: Hole cannot move, rescope with Tooling)')
  })
})
