import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ChangeAttachments from './ChangeAttachments'

vi.mock('../../api/changes', () => ({ changesApi: { deleteAttachment: vi.fn() } }))
vi.mock('./AttachmentDropzone', () => ({ default: () => <div data-testid="dropzone" /> }))

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
