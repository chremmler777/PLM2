import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import UploadDialog from './UploadDialog'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const parsed = (filename: string, over: Record<string, unknown> = {}) => ({
  filename, customer_part_number: '206.881.479', variant: null, kind: 'PCA',
  kind_label: 'PCA engineering master: full construction model.', model_type: 'TM',
  customer_index: '003', release: 'B-RELEASE', dated: '2026-05-28', ...over,
})
const f = (name: string) => new File(['x'], name, { type: 'application/octet-stream' })
const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)

const baseProps = {
  open: true, partId: 7,
  currentRevision: { id: 9, revision_name: 'E1', customer_index: '003', phase: 'review' as const },
  revisionNames: ['E1'], officialOnly: false, projectNaming: 'vw' as const,
  onClose: vi.fn(), onDone: vi.fn(),
}

describe('UploadDialog', () => {
  beforeEach(() => {
    clientMocks.get.mockReset(); clientMocks.post.mockReset()
    baseProps.onDone.mockClear(); baseProps.onClose.mockClear()
    clientMocks.get.mockImplementation((_url: string, cfg?: { params?: { filenames: string[]; convention?: string } }) => {
      const names: string[] = cfg?.params?.filenames ?? []
      const conv = cfg?.params?.convention ?? 'vw'
      return Promise.resolve({ data: {
        convention: conv === 'none' ? null : conv, conventions: { vw: 'VW group', scout: 'Scout' },
        rows: names.map((n) => conv === 'none'
          ? parsed(n, { kind: null, kind_label: null, customer_index: null })
          : parsed(n, { customer_index: n.includes('__004__') ? '004' : '003', kind: n.includes('DMU') ? 'DMU' : 'PCA' })),
      } })
    })
    clientMocks.post.mockResolvedValue({ data: { id: 42, revision_name: 'E2' } })
  })
  afterEach(cleanup)

  it('lists files with detected kind and index, and defaults to attach when the index matches', async () => {
    wrap(<UploadDialog {...baseProps} initialFiles={[f('206_881_479____PCA_TM__003_____X.CATPart'), f('206_881_479____DMU_TM__003_____X.CATPart')]} />)
    await screen.findByText('PCA')
    expect(screen.getByText('DMU')).toBeTruthy()
    expect(screen.getAllByText('003').length).toBeGreaterThan(0)
    expect((screen.getByLabelText(/Attach to E1/) as HTMLInputElement).checked).toBe(true)
  })

  it('defaults to next customer data when the detected index differs and prefills it', async () => {
    wrap(<UploadDialog {...baseProps} initialFiles={[f('206_881_479____PCA_TM__004_____X.CATPart')]} />)
    await screen.findByText('PCA')
    expect((screen.getByLabelText(/Next customer data/) as HTMLInputElement).checked).toBe(true)
    const idx = screen.getByLabelText('Customer index') as HTMLInputElement
    expect(idx.value).toBe('004')
    expect(screen.getByText(/current 003/)).toBeTruthy()
    expect(screen.getByText(/detected 004/)).toBeTruthy()
    expect((screen.getByLabelText('Received on') as HTMLInputElement).value).toBe('2026-05-28')
  })

  it('warns on mixed indexes and leaves the index empty', async () => {
    wrap(<UploadDialog {...baseProps} initialFiles={[f('a____PCA_TM__003__.CATPart'), f('b____PCA_TM__004__.CATPart')]} />)
    await screen.findByText(/different customer indexes/i)
    fireEvent.click(screen.getByLabelText(/Next customer data/))
    expect((screen.getByLabelText('Customer index') as HTMLInputElement).value).toBe('')
  })

  it('re-parses when the convention changes', async () => {
    wrap(<UploadDialog {...baseProps} initialFiles={[f('206_881_479____PCA_TM__003_____X.CATPart')]} />)
    await screen.findByText('PCA')
    fireEvent.change(screen.getByLabelText('Naming convention'), { target: { value: 'none' } })
    await waitFor(() => expect(clientMocks.get).toHaveBeenLastCalledWith('/v1/parts/7/files/parse',
      expect.objectContaining({ params: expect.objectContaining({ convention: 'none' }) })))
  })

  it('proposal level hides the customer index', async () => {
    wrap(<UploadDialog {...baseProps} initialFiles={[f('x.pdf')]} />)
    await screen.findByLabelText(/Attach to E1/)
    fireEvent.click(screen.getByLabelText(/Next proposal/))
    expect(screen.queryByLabelText('Customer index')).toBeNull()
    expect(screen.getByText(/E1\.1/)).toBeTruthy()
  })

  it('creates the major with the overridden index, then uploads every file with kind and note', async () => {
    wrap(<UploadDialog {...baseProps} initialFiles={[f('206_881_479____PCA_TM__004_____X.CATPart'), f('206_881_479____DMU_TM__004_____X.CATPart')]} />)
    await screen.findByText('PCA')
    fireEvent.change(screen.getByLabelText('Customer index'), { target: { value: '004a' } })
    fireEvent.click(screen.getByText('Upload'))
    await waitFor(() => expect(baseProps.onDone).toHaveBeenCalledWith(42))
    expect(clientMocks.post.mock.calls[0][0]).toBe('/v1/parts/7/revisions/customer-data')
    expect(clientMocks.post.mock.calls[0][1]).toEqual(expect.objectContaining({ statement: 'review', received_at: '2026-05-28', customer_index: '004a' }))
    const uploads = clientMocks.post.mock.calls.slice(1)
    expect(uploads).toHaveLength(2)
    expect(uploads[0][0]).toBe('/v1/parts/7/revisions/42/files')
    const fd = uploads[0][1] as FormData
    expect(fd.get('file_type')).toBe('cad')
    expect(fd.get('kind')).toBe('PCA')
    expect(String(fd.get('note'))).toContain('engineering master')
  })

  it('attach level uploads to the current revision without creating anything', async () => {
    wrap(<UploadDialog {...baseProps} initialFiles={[f('206_881_479____PCA_TM__003_____X.CATPart')]} />)
    await screen.findByText('PCA')
    fireEvent.click(screen.getByText('Upload'))
    await waitFor(() => expect(baseProps.onDone).toHaveBeenCalledWith(9))
    expect(clientMocks.post.mock.calls.every((c) => c[0] === '/v1/parts/7/revisions/9/files')).toBe(true)
  })

  it('stops on the first failed upload and reports which landed', async () => {
    clientMocks.post
      .mockResolvedValueOnce({ data: { id: 1 } })
      .mockRejectedValueOnce({ response: { data: { detail: 'Unsupported file extension' } } })
    wrap(<UploadDialog {...baseProps} initialFiles={[f('a____PCA_TM__003__.CATPart'), f('b____DMU_TM__003__.CATPart'), f('c____DRW_TZ__001__.pdf')]} />)
    await screen.findAllByText('PCA')
    fireEvent.click(screen.getByText('Upload'))
    await screen.findByText(/1 of 3 uploaded/)
    expect(screen.getByText(/Unsupported file extension/)).toBeTruthy()
    expect(baseProps.onDone).not.toHaveBeenCalled()
  })

  it('lets the user change a file type and remove a file', async () => {
    wrap(<UploadDialog {...baseProps} initialFiles={[f('scan.pdf'), f('x____PCA_TM__003__.CATPart')]} />)
    await screen.findAllByText('PCA')
    const types = screen.getAllByLabelText('File type') as HTMLSelectElement[]
    expect(types[0].value).toBe('drawing')
    fireEvent.change(types[0], { target: { value: 'document' } })
    expect(types[0].value).toBe('document')
    fireEvent.click(screen.getAllByLabelText('Remove file')[1])
    expect(screen.queryByText('PCA')).toBeNull()
  })
})
