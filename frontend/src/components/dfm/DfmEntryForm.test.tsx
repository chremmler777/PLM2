import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DfmEntryForm from './DfmEntryForm'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

function wrap(props: Partial<React.ComponentProps<typeof DfmEntryForm>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onDone = vi.fn(); const onCancel = vi.fn()
  render(<QueryClientProvider client={qc}>
    <DfmEntryForm partId={7} topicId={2} party="ktx" onDone={onDone} onCancel={onCancel} {...props} />
  </QueryClientProvider>)
  return { onDone, onCancel }
}

describe('DfmEntryForm', () => {
  beforeEach(() => { clientMocks.post.mockReset(); clientMocks.post.mockResolvedValue({ data: { id: 5 } }) })
  afterEach(cleanup)

  it('offers only the other two parties and posts multipart with party, addressed_to and files', async () => {
    const { onDone } = wrap()
    expect(screen.queryByTestId('addressed-ktx')).toBeNull()
    fireEvent.click(screen.getByTestId('addressed-toolmaker'))
    fireEvent.click(screen.getByTestId('addressed-tier1'))
    fireEvent.change(screen.getByTestId('dfm-note'), { target: { value: 'DFM request rev A' } })
    fireEvent.change(screen.getByTestId('dfm-sent-at'), { target: { value: '2026-09-24' } })
    const file = new File([new Uint8Array([1])], 'dfm_request_A.pdf', { type: 'application/pdf' })
    fireEvent.change(screen.getByTestId('dfm-files-input'), { target: { files: [file] } })
    expect(screen.getByText('dfm_request_A.pdf')).toBeTruthy()
    fireEvent.click(screen.getByTestId('dfm-submit'))

    await waitFor(() => expect(clientMocks.post).toHaveBeenCalled())
    const [url, body] = clientMocks.post.mock.calls[0]
    expect(url).toBe('/v1/parts/7/dfm/topics/2/entries')
    const fd = body as FormData
    expect(fd.get('party')).toBe('ktx')
    expect(JSON.parse(fd.get('addressed_to') as string)).toEqual(['toolmaker', 'tier1'])
    expect(fd.get('note')).toBe('DFM request rev A')
    expect(fd.get('sent_at')).toBe('2026-09-24')
    expect(fd.getAll('files')).toHaveLength(1)
    await waitFor(() => expect(onDone).toHaveBeenCalled())
  })

  it('refuses to send without an addressee', async () => {
    wrap()
    fireEvent.click(screen.getByTestId('dfm-submit'))
    expect(clientMocks.post).not.toHaveBeenCalled()
    expect(screen.getByText(/at least one/)).toBeTruthy()
  })

  it('sends supersedes_id for an update and says it is one', async () => {
    wrap({ party: 'toolmaker', supersedesId: 11 })
    expect(screen.getByTestId('dfm-entry-form').textContent).toContain('Update this entry')
    fireEvent.click(screen.getByTestId('addressed-ktx'))
    fireEvent.click(screen.getByTestId('dfm-submit'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalled())
    expect((clientMocks.post.mock.calls[0][1] as FormData).get('supersedes_id')).toBe('11')
  })

  it('accepts dropped files', () => {
    wrap()
    const file = new File([new Uint8Array([1])], 'study.pdf', { type: 'application/pdf' })
    fireEvent.drop(screen.getByTestId('dfm-dropzone'), { dataTransfer: { files: [file] } })
    expect(screen.getByText('study.pdf')).toBeTruthy()
  })

  it('cancels', () => {
    const { onCancel } = wrap()
    fireEvent.click(screen.getByText('Cancel'))
    expect(onCancel).toHaveBeenCalled()
  })
})
