import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import DetailPane from './DetailPane'
import type { ArticleSelection } from '../../hooks/useArticleSelection'
import type { Part, PartRevision, Project } from './projectTypes'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const stub = vi.hoisted(() => (label: string) => ({ default: () => <div>{label}</div> }))
vi.mock('../Viewer3D', () => stub('viewer'))
const dialogs = vi.hoisted(() => ({
  upload: null as Record<string, unknown> | null,
  customerData: null as Record<string, unknown> | null,
}))
vi.mock('../parts/UploadDialog', () => ({
  default: (props: Record<string, unknown>) => { dialogs.upload = props; return <div>upload-dialog</div> },
}))
vi.mock('../parts/CustomerDataDialog', () => ({
  default: (props: Record<string, unknown>) => { dialogs.customerData = props; return <div>customer-data-dialog</div> },
}))

const project = { id: 2, name: 'Seat Trim', code: '1994', status: 'active', customer_naming: 'vw' } as unknown as Project
const part = (id: number, active: number | null): Part =>
  ({ id, part_number: `20-1994-00${id}-0`, name: `Part ${id}`, part_type: 'internal_mfg', active_revision_id: active, item_category: 'article', parent_part_id: null }) as Part
const rev = (id: number, part_id: number, revision_name: string): PartRevision =>
  ({ id, part_id, revision_name, phase: 'review', status: 'draft', created_at: '2026-05-28', customer_index: null })
const parts = [part(5, 9), part(6, 19), part(7, null), part(8, null)]
const revisions: Record<number, PartRevision[]> = {
  5: [rev(9, 5, 'E1'), rev(10, 5, 'E1.1')],
  6: [rev(19, 6, 'E1')],
  7: [],
  8: [],
}

function selection(partId: number, revisionId: number | null): ArticleSelection {
  return {
    partId, revisionId, viewingFileId: null, openDocId: null, partRevisions: revisions[partId],
    selectPart: vi.fn(), openPart: vi.fn(), selectRevision: vi.fn(), pickRevision: vi.fn(),
    setRevisionId: vi.fn(), setViewingFileId: vi.fn(), setOpenDocId: vi.fn(),
  }
}

function mount(sel: ArticleSelection) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const ui = (s: ArticleSelection) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DetailPane projectId={2} project={project} parts={parts} structure={undefined} sel={s}
          tab="documents" onTabChange={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>
  )
  const view = render(ui(sel))
  return (next: ArticleSelection) => view.rerender(ui(next))
}

function dropFile() {
  const f = new File(['x'], 'a.CATPart')
  fireEvent.drop(screen.getByTestId('upload-dropzone'), { dataTransfer: { files: [f] } })
}

describe('DetailPane dialogs keep their target when the selection moves (pop-out follows the main window)', () => {
  beforeEach(() => {
    dialogs.upload = null
    dialogs.customerData = null
    clientMocks.get.mockReset()
    clientMocks.get.mockResolvedValue({ data: [] })
    clientMocks.post.mockReset()
    clientMocks.post.mockResolvedValue({ data: { revision_name: 'E1' } })
  })
  afterEach(cleanup)

  it('keeps the upload dialog on the revision it was opened for when another revision gets selected', () => {
    const select = mount(selection(5, 9))
    dropFile()
    expect(screen.getByText('upload-dialog')).toBeTruthy()
    select(selection(5, 10))
    expect(dialogs.upload).toEqual(expect.objectContaining({ partId: 5 }))
    expect((dialogs.upload as { currentRevision: { id: number } }).currentRevision.id).toBe(9)
  })

  it('never lets the upload dialog retarget to another part', () => {
    const select = mount(selection(5, 9))
    dropFile()
    expect(screen.getByText('upload-dialog')).toBeTruthy()
    dialogs.upload = null
    select(selection(6, 19))
    // Either the dialog went away with its part, or it still targets part 5.
    if (screen.queryByText('upload-dialog')) {
      expect(dialogs.upload).toEqual(expect.objectContaining({ partId: 5 }))
    }
    expect((dialogs.upload as Record<string, unknown> | null)?.partId).not.toBe(6)
  })

  it('never posts customer data to a part selected after the dialog opened', async () => {
    const select = mount(selection(7, null))
    fireEvent.click(screen.getByText('+ Customer data'))
    expect(screen.getByText('customer-data-dialog')).toBeTruthy()
    select(selection(8, null))
    if (screen.queryByText('customer-data-dialog')) {
      (dialogs.customerData as { onSubmit(v: unknown): void }).onSubmit({ statement: 'review' })
      await Promise.resolve()
    }
    expect(clientMocks.post).not.toHaveBeenCalledWith(expect.stringContaining('/v1/parts/8/'), expect.anything())
  })
})
