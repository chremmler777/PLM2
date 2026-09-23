import { useState } from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import DetailPane from './DetailPane'
import type { ArticleSelection } from '../../hooks/useArticleSelection'
import type { Part, PartRevision, Project } from './projectTypes'
import type { DetailTab } from './detailTabs'
import { relaySummary, relayTopic } from '../dfm/dfmFixtures'

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

describe('DetailPane branches on a tool selection', () => {
  const toolPart: Part = {
    id: 20, part_number: '199403', name: 'Tool 199403', part_type: 'purchased', active_revision_id: null,
    item_category: 'tool', parent_part_id: null,
    tool_cavities: null, toolmaker_id: null, tool_tonnage_class: null, tool_cycle_time_s: null,
  } as Part
  const allParts = [...parts, toolPart]
  const toolRelations = [
    { id: 1, relation_type: 'produces', direction: 'outgoing', other_part_id: 5, other_part_number: '20-1994-005-0',
      other_part_name: 'Part 5', other_item_category: 'article', other_active_revision_name: 'E1', other_active_customer_index: null, notes: '2 cavities' },
  ]

  function toolSelection(): ArticleSelection {
    return {
      partId: 20, revisionId: null, viewingFileId: null, openDocId: null, partRevisions: [],
      selectPart: vi.fn(), openPart: vi.fn(), selectRevision: vi.fn(), pickRevision: vi.fn(),
      setRevisionId: vi.fn(), setViewingFileId: vi.fn(), setOpenDocId: vi.fn(),
    }
  }

  function Harness({ sel, initialTab = 'documents' }: { sel: ArticleSelection; initialTab?: DetailTab }) {
    const [tab, setTab] = useState<DetailTab>(initialTab)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <DetailPane projectId={2} project={project} parts={allParts} structure={undefined} sel={sel}
            tab={tab} onTabChange={setTab} />
        </MemoryRouter>
      </QueryClientProvider>
    )
  }

  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/20/relations') return Promise.resolve({ data: toolRelations })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('shows the DFM tab with the archive when a tool is selected, even with an article tab remembered', async () => {
    render(<Harness sel={toolSelection()} initialTab="documents" />)
    expect(screen.getByTestId('detail-tab-dfm').getAttribute('aria-selected')).toBe('true')
    expect(await screen.findByTestId('dfm-archive')).toBeTruthy()
    expect(screen.queryByTestId('detail-tab-documents')).toBeNull()
    expect(screen.queryByTestId('detail-tab-bom')).toBeNull()
    expect(screen.queryByTestId('detail-tab-workflow')).toBeNull()
  })

  it('shows the Tool tab with produced-article chips and the tool fields card', async () => {
    const sel = toolSelection()
    render(<Harness sel={sel} />)
    fireEvent.click(screen.getByTestId('detail-tab-tool'))
    const chips = await screen.findByTestId('produced-articles')
    expect(chips.textContent).toContain('Part 5')
    expect(screen.getByTestId('edit-tool-cavities')).toBeTruthy()
    expect(screen.getByTestId('toolmaker-select')).toBeTruthy()
    fireEvent.click(screen.getByText(/Part 5/))
    expect(sel.openPart).toHaveBeenCalledWith(5)
  })

  it('shows Documents when an article is selected after a tool, not the dfm/tool tabs', () => {
    render(<Harness sel={selection(5, 9)} initialTab="dfm" />)
    expect(screen.getByTestId('detail-tab-documents').getAttribute('aria-selected')).toBe('true')
    expect(screen.queryByTestId('detail-tab-dfm')).toBeNull()
    expect(screen.queryByTestId('detail-tab-tool')).toBeNull()
  })

  it('scrolls an opened DFM pdf into view and shows a title bar naming the message, with a close button', async () => {
    const scrollSpy = vi.fn()
    Element.prototype.scrollIntoView = scrollSpy
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/20/relations') return Promise.resolve({ data: toolRelations })
      if (url === '/v1/parts/20/dfm/topics') return Promise.resolve({ data: [relaySummary({ id: 1, tool_part_id: 20 })] })
      if (url === '/v1/parts/20/dfm/topics/1') return Promise.resolve({ data: relayTopic() })
      return Promise.resolve({ data: [] })
    })
    render(<Harness sel={toolSelection()} initialTab="dfm" />)
    fireEvent.click(await screen.findByTestId('dfm-topic-1'))
    fireEvent.click(await screen.findByTestId('dfm-file-41'))
    expect(scrollSpy).toHaveBeenCalledWith(expect.objectContaining({ behavior: 'smooth', block: 'start' }))
    expect((await screen.findByTestId('doc-header')).textContent).toContain('Original #1 · Toolmaker to KTX')
    fireEvent.click(screen.getByTestId('doc-close'))
    expect(screen.queryByTestId('doc-header')).toBeNull()
  })
})
