import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import SepItemFiles from './SepItemFiles'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

const toastMocks = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock('sonner', () => ({ toast: toastMocks }))

const fileRow = (over: Record<string, unknown> = {}) => ({
  id: 11, item_id: 7, filename: 'dfmea.pdf', content_type: 'application/pdf',
  size_bytes: 2048, sha256: 'ab', uploaded_by: 3, uploaded_by_name: 'Eva Eng',
  uploaded_at: '2026-09-01T00:00:00', ...over,
})

const wrap = (ui: React.ReactElement) =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      {ui}
    </QueryClientProvider>)

describe('SepItemFiles', () => {
  beforeEach(() => {
    clientMocks.get.mockReset(); clientMocks.post.mockReset(); clientMocks.delete.mockReset()
    toastMocks.success.mockReset(); toastMocks.error.mockReset()
    clientMocks.get.mockResolvedValue({ data: [] })
  })
  afterEach(cleanup)

  it('shows the count the SEP payload already knows, without fetching', () => {
    wrap(<SepItemFiles itemId={7} projectId={2} fileCount={3} />)
    expect(screen.getByTestId('sep-files-badge-7').textContent).toContain('📎 3')
    expect(clientMocks.get).not.toHaveBeenCalled()
  })

  it('posts both picked files in one multipart request and lists what came back', async () => {
    clientMocks.post.mockResolvedValueOnce({ data: [fileRow(), fileRow({ id: 12, filename: 'spec.docx' })] })
    clientMocks.get.mockResolvedValue({ data: [fileRow(), fileRow({ id: 12, filename: 'spec.docx' })] })
    wrap(<SepItemFiles itemId={7} projectId={2} fileCount={0} />)

    fireEvent.change(screen.getByTestId('sep-files-input-7'), {
      target: { files: [new File(['a'], 'dfmea.pdf'), new File(['b'], 'spec.docx')] },
    })

    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledTimes(1))
    const [url, form, cfg] = clientMocks.post.mock.calls[0]
    expect(url).toBe('/v1/sep/items/7/files')
    const sent = (form as FormData).getAll('files') as File[]
    expect(sent.map((f) => f.name)).toEqual(['dfmea.pdf', 'spec.docx'])
    // The JSON default must be cleared or the browser writes no boundary.
    expect((cfg as { headers: Record<string, unknown> }).headers['Content-Type']).toBeUndefined()

    // Upload opens the list and the row refreshes from the server.
    expect(await screen.findByText('dfmea.pdf')).toBeTruthy()
    expect(screen.getByText('spec.docx')).toBeTruthy()
    expect(screen.getByTestId('sep-files-badge-7').textContent).toContain('📎 2')
  })

  it('downloads through the item file endpoint', async () => {
    clientMocks.get.mockResolvedValue({ data: [fileRow()] })
    wrap(<SepItemFiles itemId={7} projectId={2} fileCount={1} />)
    fireEvent.click(screen.getByTestId('sep-files-badge-7'))
    const link = await screen.findByText('dfmea.pdf')
    expect(link.getAttribute('href')).toContain('/v1/sep/items/7/files/11/download')
  })

  it('asks once inline, then DELETEs and drops the row', async () => {
    clientMocks.get.mockResolvedValueOnce({ data: [fileRow()] })
    clientMocks.get.mockResolvedValue({ data: [] })
    clientMocks.delete.mockResolvedValueOnce({ status: 204 })
    wrap(<SepItemFiles itemId={7} projectId={2} fileCount={1} />)
    fireEvent.click(screen.getByTestId('sep-files-badge-7'))
    await screen.findByText('dfmea.pdf')

    fireEvent.click(screen.getByLabelText('Delete dfmea.pdf'))
    fireEvent.click(screen.getByText('Remove'))

    await waitFor(() =>
      expect(clientMocks.delete).toHaveBeenCalledWith('/v1/sep/items/7/files/11'))
    await waitFor(() => expect(screen.queryByText('dfmea.pdf')).toBeNull())
  })

  it('says what the 413 said when a file is too large', async () => {
    clientMocks.post.mockRejectedValueOnce({
      response: { status: 413, data: { detail: 'File huge.stp exceeds 100MB' } },
    })
    wrap(<SepItemFiles itemId={7} projectId={2} fileCount={0} />)
    fireEvent.change(screen.getByTestId('sep-files-input-7'), {
      target: { files: [new File(['x'], 'huge.stp')] },
    })
    await waitFor(() =>
      expect(toastMocks.error).toHaveBeenCalledWith('File huge.stp exceeds 100MB'))
  })
})
