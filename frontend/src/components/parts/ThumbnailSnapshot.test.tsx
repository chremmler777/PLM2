import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ThumbnailSnapshot from './ThumbnailSnapshot'
import { resetAutoCaptureForTests, type CaptureFn } from '../../lib/thumbnail'

const clientMocks = vi.hoisted(() => ({ put: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
const toastMocks = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock('sonner', () => ({ toast: toastMocks }))

const png = () => new Blob(['png'], { type: 'image/png' })

function mount(props: { partId?: number; hasThumbnail?: boolean; capture: CaptureFn | null; auto?: boolean }) {
  const qc = new QueryClient()
  const spy = vi.spyOn(qc, 'invalidateQueries')
  const ui = (p: typeof props) => (
    <QueryClientProvider client={qc}>
      <ThumbnailSnapshot partId={p.partId ?? 5} hasThumbnail={p.hasThumbnail ?? false} capture={p.capture} auto={p.auto ?? true} />
    </QueryClientProvider>
  )
  const view = render(ui(props))
  return { spy, rerender: (p: typeof props) => view.rerender(ui(p)) }
}

describe('ThumbnailSnapshot', () => {
  beforeEach(() => {
    resetAutoCaptureForTests()
    clientMocks.put.mockReset().mockResolvedValue({ data: {} })
    toastMocks.success.mockReset()
    toastMocks.error.mockReset()
  })
  afterEach(cleanup)

  it('captures and uploads once when the part has no thumbnail, then refreshes the thumbnail queries', async () => {
    const capture = vi.fn(async () => png())
    const { spy, rerender } = mount({ capture })
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledTimes(1))
    expect(clientMocks.put.mock.calls[0][0]).toBe('/v1/parts/5/thumbnail')
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['project-structure'] }))
    // a new capture for the same part (model reloaded) does not upload again
    rerender({ capture: vi.fn(async () => png()) })
    cleanup()
    mount({ capture: vi.fn(async () => png()) })
    await new Promise((r) => setTimeout(r, 0))
    expect(capture).toHaveBeenCalledTimes(1)
    expect(clientMocks.put).toHaveBeenCalledTimes(1)
  })

  it('does not capture when the part already has a thumbnail, or the view is not its own', async () => {
    const capture = vi.fn(async () => png())
    mount({ capture, hasThumbnail: true })
    cleanup()
    mount({ partId: 6, capture, auto: false })
    await new Promise((r) => setTimeout(r, 0))
    expect(capture).not.toHaveBeenCalled()
    expect(clientMocks.put).not.toHaveBeenCalled()
  })

  it('waits for the viewer before capturing and fails silently', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { rerender } = mount({ capture: null })
    expect(screen.queryByTestId('set-thumbnail')).toBeNull()
    clientMocks.put.mockRejectedValue(new Error('boom'))
    rerender({ capture: vi.fn(async () => png()) })
    await waitFor(() => expect(warn).toHaveBeenCalled())
    expect(toastMocks.error).not.toHaveBeenCalled()
    warn.mockRestore()
  })

  it('Set as thumbnail posts the current view even when a thumbnail exists', async () => {
    const capture = vi.fn(async () => png())
    mount({ capture, hasThumbnail: true })
    fireEvent.click(screen.getByTestId('set-thumbnail'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledTimes(1))
    const [url, body] = clientMocks.put.mock.calls[0]
    expect(url).toBe('/v1/parts/5/thumbnail')
    expect((body as FormData).get('file')).toBeTruthy()
    await waitFor(() => expect(toastMocks.success).toHaveBeenCalledWith('Thumbnail updated'))
  })

  it('Set as thumbnail reports a failed upload', async () => {
    clientMocks.put.mockRejectedValue({ response: { data: { detail: 'Thumbnail too large' } } })
    mount({ capture: vi.fn(async () => png()), hasThumbnail: true })
    fireEvent.click(screen.getByTestId('set-thumbnail'))
    await waitFor(() => expect(toastMocks.error).toHaveBeenCalledWith('Thumbnail too large'))
  })
})
