import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RevisionFileRow } from './RevisionFileRow'
import { formatDate } from '../../lib/format'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

const file = (over: Record<string, unknown> = {}) => ({
  id: 3, revision_id: 9, filename: 'housing.step', file_type: 'cad_native',
  mime_type: 'application/step', file_size: 2_000_000, cad_format: 'step',
  has_viewer: true, uploaded_at: '2026-07-01T00:00:00', ...over,
}) as never

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

describe('RevisionFileRow provenance', () => {
  afterEach(cleanup)

  it('names who uploaded the revision file and when', () => {
    wrap(<RevisionFileRow file={file({ uploaded_by: 5, uploaded_by_name: 'Eva Eng' })}
      isViewing={false} locked={false} />)
    expect(screen.getByTestId('uploaded-by').textContent)
      .toContain(`Eva Eng · ${formatDate('2026-07-01T00:00:00')}`)
  })

  it('shows the date alone for a file with no recorded uploader', () => {
    wrap(<RevisionFileRow file={file()} isViewing={false} locked={false} />)
    expect(screen.getByTestId('uploaded-by').textContent).not.toContain('·')
  })

  it('shows the data kind chip and the note', () => {
    wrap(<RevisionFileRow file={file({ kind: 'PCA', note: 'PCA engineering master: open this one in CATIA.' })}
      isViewing={false} locked={false} />)
    expect(screen.getByText('PCA')).toBeTruthy()
    expect(screen.getByText(/open this one in CATIA/)).toBeTruthy()
  })

  it('renders nothing extra for a file without kind or note', () => {
    wrap(<RevisionFileRow file={file()} isViewing={false} locked={false} />)
    expect(screen.queryByTestId('file-kind')).toBeNull()
    expect(screen.queryByTestId('file-note')).toBeNull()
  })

  it('shows Open when an onOpen handler is given', () => {
    const onOpen = vi.fn()
    wrap(<RevisionFileRow file={file({ file_type: 'drawing', mime_type: 'application/pdf', filename: 'd.pdf' })} isViewing={false} locked={false} onOpen={onOpen} />)
    fireEvent.click(screen.getByText('Open'))
    expect(onOpen).toHaveBeenCalled()
  })

  it('deleting a file refetches the revision workflow (3D evidence may be gone)', async () => {
    clientMocks.delete.mockResolvedValue({})
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    render(<QueryClientProvider client={qc}>
      <RevisionFileRow file={file()} isViewing={false} locked={false} />
    </QueryClientProvider>)
    fireEvent.click(screen.getByText('Delete'))
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({ queryKey: ['workflow', 'revision', 9, 'instance'] }))
  })
})
