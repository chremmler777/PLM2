import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { toast } from 'sonner'
import DfmEntryForm from './DfmEntryForm'
import { cardActions, newOriginalStep, type DfmStep } from './dfmFlow'
import { relayEntries } from './dfmFixtures'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

function wrap(step: DfmStep = newOriginalStep()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onDone = vi.fn(); const onCancel = vi.fn()
  render(<QueryClientProvider client={qc}>
    <DfmEntryForm partId={7} topicId={2} step={step} onDone={onDone} onCancel={onCancel} />
  </QueryClientProvider>)
  return { onDone, onCancel }
}
const posted = () => clientMocks.post.mock.calls[0][1] as FormData
const es = relayEntries()
const action = (id: number, key: string) => cardActions(es.find((e) => e.id === id)!, es).find((a) => a.key === key)!.step

describe('DfmEntryForm', () => {
  beforeEach(() => { clientMocks.post.mockReset(); clientMocks.post.mockResolvedValue({ data: { id: 5 } }); vi.mocked(toast.error).mockReset() })
  afterEach(cleanup)

  it('records an original: pick from and to, note, date and files', async () => {
    const { onDone } = wrap()
    expect(screen.getByTestId('dfm-step-sentence').textContent).toBe('Original from Toolmaker to KTX')
    fireEvent.click(screen.getByTestId('dfm-from-ktx'))
    expect(screen.queryByTestId('addressed-ktx')).toBeNull()
    fireEvent.click(screen.getByTestId('addressed-toolmaker'))
    fireEvent.click(screen.getByTestId('addressed-tier1'))
    expect(screen.getByTestId('dfm-step-sentence').textContent).toBe('Original from KTX to Toolmaker, Tier 1')
    fireEvent.change(screen.getByTestId('dfm-note'), { target: { value: 'DFM request rev A' } })
    fireEvent.change(screen.getByTestId('dfm-sent-at'), { target: { value: '2026-09-24' } })
    const file = new File([new Uint8Array([1])], 'dfm_request_A.pdf', { type: 'application/pdf' })
    fireEvent.change(screen.getByTestId('dfm-files-input'), { target: { files: [file] } })
    expect(screen.getByText('dfm_request_A.pdf')).toBeTruthy()
    fireEvent.click(screen.getByTestId('dfm-submit'))

    await waitFor(() => expect(clientMocks.post).toHaveBeenCalled())
    expect(clientMocks.post.mock.calls[0][0]).toBe('/v1/parts/7/dfm/topics/2/entries')
    const fd = posted()
    expect(fd.get('party')).toBe('ktx')
    expect(fd.get('kind')).toBe('original')
    expect(fd.has('reply_to_id')).toBe(false)
    expect(JSON.parse(fd.get('addressed_to') as string)).toEqual(['toolmaker', 'tier1'])
    expect(fd.get('note')).toBe('DFM request rev A')
    expect(fd.get('sent_at')).toBe('2026-09-24')
    expect(fd.getAll('files')).toHaveLength(1)
    await waitFor(() => expect(onDone).toHaveBeenCalled())
  })

  it('refuses an original without an addressee', () => {
    wrap()
    fireEvent.click(screen.getByTestId('addressed-ktx'))
    fireEvent.click(screen.getByTestId('dfm-submit'))
    expect(clientMocks.post).not.toHaveBeenCalled()
    expect(screen.getByText(/at least one/)).toBeTruthy()
  })

  it('answers with a fixed sender and addressee, optional copy to the third party', async () => {
    wrap(action(5, 'answer-ktx'))
    expect(screen.getByTestId('dfm-step-sentence').textContent).toBe('Answer from KTX to Toolmaker on Question #5')
    expect(screen.queryByTestId('dfm-from-ktx')).toBeNull()
    expect((screen.getByTestId('addressed-toolmaker') as HTMLInputElement).disabled).toBe(true)
    fireEvent.click(screen.getByTestId('addressed-tier1'))
    fireEvent.click(screen.getByTestId('dfm-submit'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalled())
    const fd = posted()
    expect(fd.get('party')).toBe('ktx')
    expect(fd.get('kind')).toBe('answer')
    expect(fd.get('reply_to_id')).toBe('5')
    expect(JSON.parse(fd.get('addressed_to') as string)).toEqual(['toolmaker', 'tier1'])
  })

  it('forwards from KTX to the party that has not seen it', async () => {
    wrap(action(5, 'forward-tier1'))
    expect(screen.getByTestId('dfm-step-sentence').textContent).toBe('Forward from KTX to Tier 1 of Question #5')
    expect(screen.queryByTestId('addressed-toolmaker')).toBeNull()
    fireEvent.click(screen.getByTestId('dfm-submit'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalled())
    expect(posted().get('kind')).toBe('forward')
    expect(posted().get('reply_to_id')).toBe('5')
    expect(JSON.parse(posted().get('addressed_to') as string)).toEqual(['tier1'])
  })

  it('records an update with supersedes_id and keeps kind and reply link', async () => {
    wrap(action(4, 'update'))
    expect(screen.getByTestId('dfm-step-sentence').textContent).toBe('Update of Answer #4 from KTX to Toolmaker')
    fireEvent.click(screen.getByTestId('dfm-submit'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalled())
    expect(posted().get('supersedes_id')).toBe('4')
    expect(posted().get('kind')).toBe('answer')
    expect(posted().get('reply_to_id')).toBe('1')
  })

  it('shows a 422 array detail as a string toast', async () => {
    clientMocks.post.mockRejectedValue({ response: { status: 422, data: { detail: [{ loc: ['body', 'party'], msg: 'Field required', type: 'missing' }] } } })
    wrap(action(5, 'answer-ktx'))
    fireEvent.click(screen.getByTestId('dfm-submit'))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Field required'))
  })

  it('accepts dropped files', () => {
    wrap()
    const file = new File([new Uint8Array([1])], 'study.pdf', { type: 'application/pdf' })
    fireEvent.drop(screen.getByTestId('dfm-dropzone'), { dataTransfer: { files: [file] } })
    expect(screen.getByText('study.pdf')).toBeTruthy()
  })

  it('keeps chosen files although the browser empties the live file list when the input is reset', async () => {
    const { onDone } = wrap()
    const input = screen.getByTestId('dfm-files-input') as HTMLInputElement
    const file = new File(['%PDF-1.4'], 'dfm_rev1.pdf', { type: 'application/pdf' })
    // A real FileList is live: resetting input.value empties it. Emulate that.
    const live: File[] = [file]
    Object.defineProperty(input, 'files', { configurable: true, get: () => live })
    Object.defineProperty(input, 'value', { configurable: true, get: () => '', set: () => { live.length = 0 } })
    fireEvent.change(input)
    expect(await screen.findByText('dfm_rev1.pdf')).toBeTruthy()
    fireEvent.click(screen.getByTestId('dfm-submit'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalled())
    expect((posted().getAll('files') as File[]).map((f) => f.name)).toEqual(['dfm_rev1.pdf'])
    await waitFor(() => expect(onDone).toHaveBeenCalled())
  })

  it('cancels', () => {
    const { onCancel } = wrap()
    fireEvent.click(screen.getByText('Cancel'))
    expect(onCancel).toHaveBeenCalled()
  })
})
