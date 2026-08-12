import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CustomerMailLog from './CustomerMailLog'
import { t } from '../../i18n/cmLabels'

vi.mock('../../api/changes', () => ({ changesApi: {} }))
vi.mock('./AttachmentDropzone', () => ({
  default: (p: { kind?: string; assessmentId?: number; concernId?: number; label?: string }) => (
    <div data-testid="dropzone" data-kind={p.kind ?? ''}
      data-assessment={p.assessmentId ?? ''} data-concern={p.concernId ?? ''}>
      {p.label}
    </div>
  ),
}))

const att = (over: Record<string, unknown> = {}) => ({
  id: 1, filename: 'mail.msg', content_type: 'application/vnd.ms-outlook',
  size_bytes: 10, phase: 'baseline', created_at: '2026-07-01T00:00:00',
  kind: 'customer_email', responds_to_id: null, concern_id: null,
  assessment_id: null, ...over,
}) as never

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

describe('CustomerMailLog', () => {
  afterEach(cleanup)

  it('lists the customer mails oldest first and says where they come from', () => {
    wrap(<CustomerMailLog changeId={7} attachments={[
      att({ id: 2, filename: 'reply.msg', created_at: '2026-07-09T00:00:00' }),
      att({ id: 1, filename: 'request.msg', created_at: '2026-07-01T00:00:00' }),
    ]} />)
    expect(screen.getByText(t('mail.title'))).toBeTruthy()
    const links = screen.getAllByRole('link')
    // The thread reads forward: the request, then what came back.
    expect(links.map((l) => l.textContent)).toEqual(['request.msg', 'reply.msg'])
    expect(screen.getByTestId('customer-mails-count').textContent).toBe('2')
  })

  it('keeps other people’s documents out of the mail log', () => {
    wrap(<CustomerMailLog changeId={7} attachments={[
      att({ id: 1, filename: 'mail.msg' }),
      att({ id: 2, filename: 'evidence.pdf', kind: 'change_ppt', assessment_id: 3 }),
      att({ id: 3, filename: 'anything.pdf', kind: 'general' }),
    ]} />)
    expect(screen.getByTestId('customer-mails').textContent).not.toContain('evidence.pdf')
    expect(screen.getByTestId('customer-mails').textContent).not.toContain('anything.pdf')
    expect(screen.getByRole('link', { name: 'mail.msg' })).toBeTruthy()
  })

  it('offers everyone the slot, filed as a customer mail on the change itself', () => {
    wrap(<CustomerMailLog changeId={7} attachments={[]} />)
    expect(screen.getByText(t('mail.none'))).toBeTruthy()
    const zone = screen.getByTestId('dropzone')
    expect(zone.getAttribute('data-kind')).toBe('customer_email')
    // Change-level: it belongs to no assessment and no concern.
    expect(zone.getAttribute('data-assessment')).toBe('')
    expect(zone.getAttribute('data-concern')).toBe('')
    expect(zone.textContent).toBe(t('mail.slot'))
    // The hint tells people what to drop — saved mails, not a live Outlook drag.
    expect(screen.getByText(t('mail.hint'))).toBeTruthy()
  })
})
