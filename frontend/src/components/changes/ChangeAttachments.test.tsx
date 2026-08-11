import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ChangeAttachments from './ChangeAttachments'
import { t } from '../../i18n/cmLabels'

vi.mock('../../api/changes', () => ({ changesApi: { deleteAttachment: vi.fn() } }))
vi.mock('./AttachmentDropzone', () => ({
  default: (props: { kind?: string; respondsToId?: number }) => (
    <div data-testid="dropzone" data-kind={props.kind ?? ''}
      data-responds-to={props.respondsToId ?? ''} />
  ),
}))

const att = (over: Record<string, unknown>) => ({
  id: 1, filename: 'f.pdf', content_type: 'application/pdf', size_bytes: 10,
  phase: 'baseline', created_at: '2026-07-01T00:00:00', ...over,
})
const change = (over: Record<string, unknown> = {}) => ({
  id: 7, status: 'scoping', attachments: [], ...over,
}) as never

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

describe('ChangeAttachments', () => {
  afterEach(cleanup)

  it('splits baseline and post-scoping documents into two lists', () => {
    wrap(<ChangeAttachments change={change({
      status: 'in_assessment',
      attachments: [att({ id: 1, filename: 'base.pdf', phase: 'baseline' }),
                    att({ id: 2, filename: 'later.pdf', phase: 'post_scoping' })],
    })} />)
    expect(screen.getByText(/Initial documentation/i)).toBeTruthy()
    expect(screen.getByText(/Changes after scoping/i)).toBeTruthy()
    expect(screen.getByText('📎 base.pdf')).toBeTruthy()
    expect(screen.getByText('📎 later.pdf')).toBeTruthy()
  })

  it('lets baseline docs be deleted while still in scoping', () => {
    wrap(<ChangeAttachments change={change({
      status: 'scoping', attachments: [att({ id: 1, filename: 'base.pdf' })],
    })} />)
    expect(screen.getByLabelText('Delete base.pdf')).toBeTruthy()
  })

  it('freezes baseline docs (no delete control) once scoping has ended', () => {
    wrap(<ChangeAttachments change={change({
      status: 'in_assessment', attachments: [att({ id: 1, filename: 'base.pdf', phase: 'baseline' })],
    })} />)
    expect(screen.queryByLabelText('Delete base.pdf')).toBeNull()
    expect(screen.getByText(/frozen/i)).toBeTruthy()
  })

  it('keeps post-scoping docs deletable', () => {
    wrap(<ChangeAttachments change={change({
      status: 'in_assessment', attachments: [att({ id: 2, filename: 'later.pdf', phase: 'post_scoping' })],
    })} />)
    expect(screen.getByLabelText('Delete later.pdf')).toBeTruthy()
  })
})

describe('ChangeAttachments provenance', () => {
  afterEach(cleanup)

  it('names who uploaded the file and when', () => {
    wrap(<ChangeAttachments change={change({
      attachments: [att({
        id: 1, filename: 'base.pdf', created_at: '2026-07-01T00:00:00',
        uploaded_by: 5, uploaded_by_name: 'Eva Eng',
      })],
    })} />)
    const line = screen.getByText(/Eva Eng/)
    expect(line.textContent).toContain(new Date('2026-07-01T00:00:00').toLocaleDateString())
  })

  it('falls back to the date alone when the uploader is unknown', () => {
    wrap(<ChangeAttachments change={change({
      attachments: [att({ id: 1, filename: 'base.pdf', created_at: '2026-07-01T00:00:00' })],
    })} />)
    const line = screen.getByText(new Date('2026-07-01T00:00:00').toLocaleDateString())
    expect(line.textContent).not.toContain('·')
  })
})

describe('ChangeAttachments needs-info loop', () => {
  afterEach(cleanup)

  it('chips the request and reads its answer underneath', () => {
    wrap(<ChangeAttachments change={change({
      attachments: [
        att({ id: 1, filename: 'question.msg', kind: 'info_request' }),
        att({ id: 2, filename: 'answer.msg', kind: 'info_response', responds_to_id: 1 }),
        att({ id: 3, filename: 'spec.pdf' }),
      ],
    })} />)
    expect(screen.getByTestId('attach-kind-info_request').textContent).toBe(t('attach.infoRequest'))
    expect(screen.getByTestId('attach-kind-info_response').textContent).toBe(t('attach.infoResponse'))
    // The answer sits inside the request's block, not loose in the list.
    const request = screen.getByText(/question.msg/).closest('li')?.parentElement?.closest('li')
    expect(request?.textContent).toContain('answer.msg')
    // A plain document gets no chip at all.
    const plain = screen.getByText(/spec.pdf/).closest('li')
    expect(plain?.querySelector('[data-testid^="attach-kind"]')).toBeNull()
    // Answered requests stop asking for an answer.
    expect(screen.queryByTestId('attach-response-1')).toBeNull()
  })

  it('offers a response slot preset to the request it answers', () => {
    wrap(<ChangeAttachments change={change({
      attachments: [att({ id: 1, filename: 'question.msg', kind: 'info_request' })],
    })} />)
    fireEvent.click(screen.getByTestId('attach-response-1'))
    const slots = screen.getAllByTestId('dropzone')
    const responseSlot = slots.find((s) => s.getAttribute('data-kind') === 'info_response')
    expect(responseSlot?.getAttribute('data-responds-to')).toBe('1')
  })
})
