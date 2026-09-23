import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route, useNavigate, type NavigateFunction } from 'react-router-dom'
import ProjectDetailPage from './ProjectDetailPage'
import { FakeBroadcastChannel } from '../testing/fakeBroadcastChannel'
import type { SelectionMessage } from '../hooks/useSelectionChannel'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const stub = vi.hoisted(() => (label: string) => ({ default: () => <div>{label}</div> }))
vi.mock('../components/Viewer3D', () => stub('viewer'))
vi.mock('../components/workflows/RevisionWorkflowSection', () => stub('workflow-section'))
vi.mock('../components/PartBOMSection', () => stub('bom-section'))
vi.mock('../components/PartRelationsSection', () => stub('relations-section'))
vi.mock('../components/ProcessFlowSection', () => stub('process-flow-section'))
vi.mock('../components/PPAPSection', () => stub('ppap-section'))
vi.mock('../components/MilestoneStrip', () => stub('milestones'))
vi.mock('../components/ProjectLessonsSection', () => stub('lessons-section'))
vi.mock('../components/ProjectSepSection', () => ({
  default: ({ view }: { view?: string }) => <div>{view === 'strip' ? 'sep-strip' : view === 'gate' ? 'sep-gate' : 'sep-section'}</div>,
}))
vi.mock('../components/ProjectChangesSection', () => stub('changes-section'))
vi.mock('../components/parts/AssemblyTreeList', () => stub('assemblies'))
vi.mock('../components/parts/UploadDialog', () => stub('upload-dialog'))

// Some tests replace these two; keep them at the jsdom defaults otherwise.
const realOpen = window.open

const LH = { id: 5, part_number: '20-1994-001-0', customer_part_number: '206.882.251', tier1_part_number: 'S00H4X-110', name: '206.882.251 Handle LH', part_type: 'internal_mfg', active_revision_id: 9, item_category: 'article', parent_part_id: null, lifecycle_phase: 'nominated' }
const RH = { id: 6, part_number: '20-1994-002-0', name: '206.882.252 Handle RH', part_type: 'internal_mfg', active_revision_id: 19, item_category: 'article', parent_part_id: null, lifecycle_phase: 'nominated' }
const TOOL = { id: 30, part_number: '199401', name: '1994 TOOL Handle', part_type: 'purchased', active_revision_id: null, item_category: 'tool', parent_part_id: null, lifecycle_phase: 'rfq' }
const structure = { articles: [
  { part_id: 5, part_number: LH.part_number, customer_part_number: '206.882.251', name: LH.name, lifecycle_phase: 'nominated', active_revision_id: 9,
    revisions: [{ id: 9, revision_name: 'E1', customer_index: '003', status: 'approved', phase: 'review', parent_revision_id: null, is_active: true },
                { id: 10, revision_name: 'E1.1', customer_index: null, status: 'draft', phase: 'review', parent_revision_id: 9, is_active: false }],
    related: [{ relation_type: 'produces', direction: 'incoming', label: 'produced by', part_id: 30, part_number: '199401', name: 'TOOL Handle', item_category: 'tool' }],
    mirror_of: null, mirrored_by: [{ part_id: 6, part_number: RH.part_number, customer_part_number: '206.882.252', name: RH.name }] },
  { part_id: 6, part_number: RH.part_number, customer_part_number: '206.882.252', name: RH.name, lifecycle_phase: 'nominated', active_revision_id: 19,
    revisions: [{ id: 19, revision_name: 'E1', customer_index: '003', status: 'approved', phase: 'review', parent_revision_id: null, is_active: true }],
    related: [], mirror_of: { part_id: 5, part_number: LH.part_number, customer_part_number: '206.882.251', name: LH.name }, mirrored_by: [] },
] }

let partsData: unknown[] = [LH, RH, TOOL]

function routeGet(url: string) {
  if (url === '/v1/plants/projects') return Promise.resolve({ data: [{ id: 2, name: 'Seat Trim', code: '1994', status: 'active', customer_naming: 'vw' }] })
  if (url === '/v1/parts/project/2') return Promise.resolve({ data: partsData })
  if (url === '/v1/parts/project/2/structure') return Promise.resolve({ data: structure })
  if (url === '/v1/parts/project/2/paint-overview') return Promise.resolve({ data: [
    { part_id: 6, part_number: RH.part_number, name: RH.name, process: null, layers: [{ layer_order: 1, area: null, notes: null,
      paint: { id: 7, name: 'Black', paint_type: 'basecoat', colour_code: 'RAL 9005', colour_name: 'Black', colour_hex: '#111111', supplier_id: null, supplier_text: null, spec_reference: null, notes: null, is_active: true } }] },
  ] })
  if (url === '/v1/parts/5/revisions') return Promise.resolve({ data: structure.articles[0].revisions.map((r) => ({ ...r, part_id: 5, created_at: '2026-05-28' })) })
  if (url === '/v1/parts/6/revisions') return Promise.resolve({ data: structure.articles[1].revisions.map((r) => ({ ...r, part_id: 6, created_at: '2026-05-28' })) })
  if (url.includes('/bom-tree')) return Promise.resolve({ data: { part_id: 5, part_number: LH.part_number, name: LH.name, revision_name: 'E1', customer_index: '003', lines: [] } })
  if (url === '/v1/sep/projects/2') return Promise.resolve({ data: { active: true, gates: [
    { id: 1, code: 'K0/RG1', status: 'in_progress', color: 'green', phase_en: 'Kick-off', progress: { done: 0, open: 5, not_applicable: 0, total: 5, pct: 0 } },
  ] } })
  if (url === '/v1/lessons/projects/2/references') return Promise.resolve({ data: [] })
  return Promise.resolve({ data: [] })
}

function mount(path = '/projects/2') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path="/projects/:projectId" element={<ProjectDetailPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>)
  return queryClient
}

beforeEach(() => {
  partsData = [LH, RH, TOOL]
  localStorage.clear()
  clientMocks.get.mockReset()
  clientMocks.get.mockImplementation(routeGet)
})
afterEach(() => {
  cleanup()
  window.open = realOpen
  vi.unstubAllGlobals()
})

describe('project header and status nav bar', () => {
  it('shows the gate strip in a nav bar under the header, with nothing open and no slide-over', async () => {
    mount()
    const header = await screen.findByTestId('project-header')
    const nav = screen.getByTestId('project-status-nav')
    expect(header.nextElementSibling).toBe(nav)
    expect(within(nav).getByText('sep-strip')).toBeTruthy()
    expect(within(nav).getByRole('button', { name: /Changes/ })).toBeTruthy()
    expect(within(nav).getByRole('button', { name: /Lessons/ })).toBeTruthy()
    expect(screen.queryByText('sep-section')).toBeNull()
    expect(screen.queryByText('changes-section')).toBeNull()
    expect(screen.queryByText('lessons-section')).toBeNull()
    expect(screen.queryByTestId('status-slideover')).toBeNull()
    expect(screen.queryByTestId('chip-sep')).toBeNull()
    expect(screen.getByTestId('status-panel').hidden).toBe(true)
  })

  it('opens one section inline below the bar, switches between them and closes with Escape', async () => {
    mount()
    fireEvent.click(await screen.findByRole('button', { name: /Lessons/ }))
    const panel = screen.getByTestId('status-panel')
    expect(within(panel).getByText('lessons-section')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Changes/ }))
    expect(within(panel).getByText('changes-section')).toBeTruthy()
    expect(screen.queryByText('lessons-section')).toBeNull()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(panel.hidden).toBe(true)
    expect(screen.queryByText('changes-section')).toBeNull()
    expect(screen.queryByTestId('status-slideover')).toBeNull()
    // the items and detail keep the rest of the fixed-height page
    expect(panel.className).toContain('max-h-[45vh]')
  })

  it('the ⋯ menu still reaches the add-part dialog', async () => {
    mount()
    fireEvent.click(await screen.findByLabelText('Project actions'))
    fireEvent.click(screen.getByText('+ Add Part'))
    expect(screen.getByText('Add New Item')).toBeTruthy()
  })
})

describe('paint on the project page', () => {
  it('does not mount the paint section but keeps the Painted filter', async () => {
    mount()
    expect(await screen.findByText('🎨 Painted (1)')).toBeTruthy()
    expect(screen.queryByTestId('project-paint-toggle')).toBeNull()
  })
})

describe('grouped slim item rows', () => {
  it('groups the items by category in a fixed order and hides empty groups', async () => {
    mount()
    await screen.findByTestId('group-toggle-article')
    expect(screen.getAllByTestId(/^group-toggle-/).map((el) => el.getAttribute('data-testid')))
      .toEqual(['group-toggle-article', 'group-toggle-tool'])
    expect(screen.getByTestId('group-toggle-article').textContent).toContain('Articles')
    expect(screen.getByTestId('group-toggle-article').textContent).toContain('2')
  })

  it('shows thumbnail, short name, revision and phase on line 1, the labelled numbers and icons on line 2', async () => {
    mount()
    const lh = await screen.findByTestId('item-row-5')
    await within(lh).findByTestId('row-rev-5')
    expect(within(lh).getByTestId('row-thumb-5')).toBeTruthy()
    // the name span holds the short name alone (customer number stripped)
    expect(within(lh).getByText('Handle LH')).toBeTruthy()
    expect(within(lh).getByTestId('row-rev-5').textContent).toBe('E1 · 003')
    expect(within(lh).getByTestId('row-phase-5').textContent).toBe('nominated')
    expect(within(lh).getByTestId('row-numbers-5').textContent)
      .toBe('KTX 20-1994-001-0 · Tier 1 S00H4X-110 · OEM 206.882.251')
    expect(within(lh).getByTestId('row-proposal-5')).toBeTruthy()
    const rh = screen.getByTestId('item-row-6')
    expect(within(rh).getByTestId('tree-mirror-of-6')).toBeTruthy()
    expect(await within(rh).findByTestId('paint-swatch-6')).toBeTruthy()
    // no part-type badge on the rows any more
    expect(screen.queryByText('internal mfg')).toBeNull()
  })

  it('shows the internal number on line 1 when there is no customer number, and only once', async () => {
    mount()
    const tool = await screen.findByTestId('item-row-30')
    expect(tool.children[0].textContent).toContain('199401')
    expect(tool.children[0].textContent).toContain('TOOL Handle')
    expect(tool.textContent!.split('199401').length - 1).toBe(1)
  })

  it('collapses a group from its header', async () => {
    mount()
    fireEvent.click(await screen.findByTestId('group-toggle-tool'))
    expect(screen.getByTestId('group-toggle-tool').getAttribute('aria-expanded')).toBe('false')
    expect(screen.queryByTestId('item-row-30')).toBeNull()
  })

  it('search finds a part nested under an assembly whose own name does not match', async () => {
    partsData = [
      { id: 40, part_number: '1994-40', name: 'Seat frame assy', part_type: 'sub_assembly', item_category: 'article', active_revision_id: null, parent_part_id: null },
      { id: 41, part_number: '1994-41', name: 'Bracket inner', part_type: 'internal_mfg', item_category: 'article', active_revision_id: null, parent_part_id: 40 },
      LH, TOOL,
    ]
    mount()
    await screen.findByTestId('item-row-41')
    fireEvent.change(screen.getByLabelText('Search items'), { target: { value: 'bracket' } })
    expect(screen.getByText('Items (1 of 4)')).toBeTruthy()
    expect(screen.getByTestId('item-row-41')).toBeTruthy()
    expect(screen.queryByTestId('item-row-40')).toBeNull()
    fireEvent.change(screen.getByLabelText('Search items'), { target: { value: '' } })
    expect(screen.getByTestId('item-row-40')).toBeTruthy()
  })
})

describe('fixed-height layout', () => {
  it('fills the viewport, never scrolls as a whole, and scrolls the list on its own', async () => {
    mount()
    const page = await screen.findByTestId('project-page')
    expect(page.className).toContain('h-full')
    expect(page.className).toContain('overflow-hidden')
    expect(screen.getByTestId('items-scroll').className).toContain('overflow-y-auto')
    expect(screen.getByRole('separator', { name: 'Resize items list' })).toBeTruthy()
  })

  it('opens with the splitter where it was left last time', async () => {
    localStorage.setItem('plm2.project.splitLeft', '520')
    mount()
    expect((await screen.findByRole('separator')).getAttribute('aria-valuenow')).toBe('520')
  })
})

describe('detail tabs under a pinned header', () => {
  const selectLH = async () => {
    fireEvent.click(await screen.findByTestId('item-row-5'))
    return screen.findByTestId('detail-header')
  }

  it('pins header and tab bar while only the tab content scrolls', async () => {
    mount()
    const header = await selectLH()
    expect(header.textContent).toContain('206.882.251 Handle LH')
    expect(within(header).getByText('internal mfg')).toBeTruthy()
    expect((await within(header).findByTestId('detail-active-revision')).textContent).toBe('E1 · 003')
    expect(within(header).getByTestId('detail-phase').textContent).toBe('nominated')
    expect(screen.getByRole('tablist', { name: 'Detail sections' })).toBeTruthy()
    expect(screen.getByTestId('detail-scroll').className).toContain('overflow-y-auto')
    expect(screen.getByTestId('detail-pane').className).not.toContain('overflow-y-auto')
    expect(await screen.findByTestId('rev-tab-9')).toBeTruthy()

    fireEvent.click(screen.getByTestId('detail-tab-links'))
    expect(screen.queryByTestId('rev-tab-9')).toBeNull()
    expect(screen.getByTestId('detail-header')).toBe(header)
    expect(screen.getByTestId('relation-chip-30')).toBeTruthy()
    expect(screen.getByText('relations-section')).toBeTruthy()
  })

  it('shows the existing sections under BOM, Workflow and Changelog', async () => {
    mount()
    await selectLH()
    await screen.findByTestId('rev-tab-9')
    fireEvent.click(screen.getByTestId('detail-tab-bom'))
    expect(await screen.findByTestId('bom-tree-section')).toBeTruthy()
    expect(screen.getByText('bom-section')).toBeTruthy()
    fireEvent.click(screen.getByTestId('detail-tab-workflow'))
    expect(screen.getByText('workflow-section')).toBeTruthy()
    expect(screen.getByText('ppap-section')).toBeTruthy()
    fireEvent.click(screen.getByTestId('detail-tab-changelog'))
    expect(await screen.findByText('No changelog entries yet')).toBeTruthy()
  })

  it('keeps the selected tab when switching items', async () => {
    mount()
    await selectLH()
    fireEvent.click(screen.getByTestId('detail-tab-bom'))
    fireEvent.click(screen.getByTestId('item-row-6'))
    await waitFor(() => expect(screen.getByTestId('detail-header').textContent).toContain('Handle RH'))
    expect(screen.getByTestId('detail-tab-bom').getAttribute('aria-selected')).toBe('true')
  })

  it('shows a prompt instead of an empty pane when nothing is selected', async () => {
    mount()
    expect(await screen.findByText('Select an item from the list')).toBeTruthy()
  })
})

describe('keyboard in the items list', () => {
  const current = () => screen.getAllByTestId(/^item-row-/).find((el) => el.getAttribute('aria-current') === 'true')?.getAttribute('data-row-id')

  it('moves the selection with up and down and the detail follows', async () => {
    mount()
    await screen.findByTestId('item-row-5')
    const list = screen.getByTestId('items-scroll')
    fireEvent.keyDown(list, { key: 'ArrowDown' })
    await waitFor(() => expect(screen.getByTestId('detail-header').textContent).toContain('Handle LH'))
    fireEvent.keyDown(list, { key: 'ArrowDown' })
    await waitFor(() => expect(screen.getByTestId('detail-header').textContent).toContain('Handle RH'))
    fireEvent.keyDown(list, { key: 'ArrowDown' })
    fireEvent.keyDown(list, { key: 'ArrowDown' })
    expect(current()).toBe('30')
    fireEvent.keyDown(list, { key: 'ArrowUp' })
    expect(current()).toBe('6')
  })

  it('expands and collapses the selected row with right and left', async () => {
    mount()
    await within(await screen.findByTestId('item-row-5')).findByTestId('row-rev-5')
    fireEvent.click(screen.getByTestId('item-row-5'))
    const list = screen.getByTestId('items-scroll')
    fireEvent.keyDown(list, { key: 'ArrowRight' })
    expect(await screen.findByTestId('tree-rev-10')).toBeTruthy()
    fireEvent.keyDown(list, { key: 'ArrowLeft' })
    expect(screen.queryByTestId('tree-rev-10')).toBeNull()
  })

  it('ignores arrows typed in the search box', async () => {
    mount()
    fireEvent.click(await screen.findByTestId('item-row-5'))
    fireEvent.keyDown(screen.getByLabelText('Search items'), { key: 'ArrowDown' })
    expect(current()).toBe('5')
  })

  it('jumps to the first visible row when the selection sits in a collapsed group', async () => {
    mount()
    fireEvent.click(await screen.findByTestId('item-row-30'))
    fireEvent.click(screen.getByTestId('group-toggle-tool'))
    fireEvent.keyDown(screen.getByTestId('items-scroll'), { key: 'ArrowDown' })
    expect(current()).toBe('5')
  })
})

describe('pop-out detail window from the project page', () => {
  beforeEach(() => {
    FakeBroadcastChannel.reset()
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel)
    // This main window's owner id; its pop-out echoes it in hello and bye.
    sessionStorage.setItem('plm2.project.windowOwner', 'owner-a')
  })
  afterEach(() => sessionStorage.clear())

  const hello: SelectionMessage = { type: 'hello', owner: 'owner-a' }
  const bye: SelectionMessage = { type: 'bye', owner: 'owner-a' }

  const popout = () => {
    const got: SelectionMessage[] = []
    const channel = new FakeBroadcastChannel('plm2-project-2')
    channel.onmessage = (e) => { got.push(e.data as SelectionMessage) }
    return { channel, got }
  }

  it('opens the detail in a named window and shows the list as a table', async () => {
    const open = vi.fn(() => ({ closed: false }) as unknown as Window)
    window.open = open
    mount()
    fireEvent.click(await screen.findByTestId('item-row-5'))
    await screen.findByTestId('rev-tab-9')
    fireEvent.click(screen.getByLabelText('Open detail in new window'))
    expect(open).toHaveBeenCalledWith('/projects/2/detail?part=5&rev=9&owner=owner-a', 'plm2-detail-2', expect.any(String))
    expect(await screen.findByTestId('items-table')).toBeTruthy()
    expect(screen.queryByTestId('detail-pane')).toBeNull()
    expect(screen.queryByRole('separator')).toBeNull()
  })

  it('answers a hello with the selection and posts every change', async () => {
    const p = popout()
    mount()
    await screen.findByTestId('item-row-5')
    act(() => p.channel.postMessage(hello))
    expect(await screen.findByTestId('items-table')).toBeTruthy()
    expect(p.got).toContainEqual({ type: 'select', partId: null, revisionId: null })
    fireEvent.click(screen.getByTestId('table-row-6'))
    await waitFor(() => expect(p.got).toContainEqual({ type: 'select', partId: 6, revisionId: 19 }))
    expect(screen.getByTestId('table-row-6').getAttribute('aria-selected')).toBe('true')
  })

  it('never posts the previous item\'s revision together with a newly selected item', async () => {
    const p = popout()
    mount()
    await screen.findByTestId('item-row-5')
    act(() => p.channel.postMessage(hello))
    fireEvent.click(await screen.findByTestId('table-row-5'))
    await waitFor(() => expect(p.got).toContainEqual({ type: 'select', partId: 5, revisionId: 9 }))
    fireEvent.click(screen.getByTestId('table-row-6'))
    await waitFor(() => expect(p.got).toContainEqual({ type: 'select', partId: 6, revisionId: 19 }))
    expect(p.got).not.toContainEqual({ type: 'select', partId: 6, revisionId: 9 })
  })

  it('ignores a hello from the pop-out of another main window', async () => {
    const p = popout()
    mount()
    await screen.findByTestId('item-row-5')
    act(() => p.channel.postMessage({ type: 'hello', owner: 'owner-b' }))
    act(() => p.channel.postMessage({ type: 'hello' }))
    expect(screen.queryByTestId('items-table')).toBeNull()
    expect(p.got.filter((m) => m.type === 'select')).toEqual([])
    act(() => p.channel.postMessage(hello))
    expect(await screen.findByTestId('items-table')).toBeTruthy()
  })

  it('ignores a bye from the pop-out of another main window', async () => {
    const p = popout()
    mount()
    await screen.findByTestId('item-row-5')
    act(() => p.channel.postMessage(hello))
    await screen.findByTestId('items-table')
    act(() => p.channel.postMessage({ type: 'bye', owner: 'owner-b' }))
    expect(screen.getByTestId('items-table')).toBeTruthy()
  })

  it('keeps the same owner id across a reload of the main window', async () => {
    sessionStorage.clear()
    const open = vi.fn(() => ({ closed: false }) as unknown as Window)
    window.open = open
    mount()
    fireEvent.click(await screen.findByTestId('item-row-5'))
    await screen.findByTestId('rev-tab-9')
    fireEvent.click(screen.getByLabelText('Open detail in new window'))
    const url = new URL(String((open.mock.calls[0] as unknown[])[0]), 'http://x')
    const owner = url.searchParams.get('owner')
    expect(owner).toBeTruthy()
    cleanup()
    const p = popout()
    mount()
    await screen.findByTestId('item-row-5')
    act(() => p.channel.postMessage({ type: 'hello', owner: owner! }))
    expect(await screen.findByTestId('items-table')).toBeTruthy()
  })

  it('asks on load whether a pop-out is already open', async () => {
    const p = popout()
    mount()
    await screen.findByTestId('item-row-5')
    expect(p.got).toContainEqual({ type: 'ping' })
  })

  it('brings the detail back when the pop-out says bye', async () => {
    const p = popout()
    mount()
    await screen.findByTestId('item-row-5')
    act(() => p.channel.postMessage(hello))
    await screen.findByTestId('items-table')
    act(() => p.channel.postMessage(bye))
    expect(screen.queryByTestId('items-table')).toBeNull()
    expect(screen.getByRole('separator')).toBeTruthy()
  })

  it('notices a pop-out that was closed without saying bye', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    try {
      const win = { closed: false }
      window.open = vi.fn(() => win as unknown as Window)
      mount()
      fireEvent.click(await screen.findByTestId('item-row-5'))
      fireEvent.click(await screen.findByLabelText('Open detail in new window'))
      await screen.findByTestId('items-table')
      win.closed = true
      act(() => { vi.advanceTimersByTime(1000) })
      expect(screen.queryByTestId('items-table')).toBeNull()
      expect(screen.getByTestId('detail-pane')).toBeTruthy()
    } finally {
      vi.useRealTimers()
    }
  })

  it('still notices the pop-out closing after it reloaded (bye, then hello again)', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    try {
      const win = { closed: false }
      window.open = vi.fn(() => win as unknown as Window)
      const p = popout()
      mount()
      fireEvent.click(await screen.findByTestId('item-row-5'))
      fireEvent.click(await screen.findByLabelText('Open detail in new window'))
      await screen.findByTestId('items-table')
      act(() => p.channel.postMessage(bye))
      act(() => p.channel.postMessage(hello))
      await screen.findByTestId('items-table')
      win.closed = true
      act(() => { vi.advanceTimersByTime(1000) })
      expect(screen.queryByTestId('items-table')).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })

  it('shows the table columns, with cavities once the tool fields exist', async () => {
    partsData = [LH, RH, { ...TOOL, tool_cavities: 2 }]
    const p = popout()
    mount()
    await screen.findByTestId('item-row-5')
    act(() => p.channel.postMessage(hello))
    const table = await screen.findByTestId('items-table')
    expect(within(table).getAllByRole('columnheader').map((th) => th.textContent))
      .toEqual(['Image', 'KTX no.', 'Customer no.', 'Tier 1', 'Name', 'Phase', 'Revision', 'Tool', 'Cavities'])
    await waitFor(() => expect(within(within(table).getByTestId('table-row-5')).getAllByRole('cell').map((td) => td.textContent))
      .toEqual(['', '20-1994-001-0', '206.882.251', 'S00H4X-110', 'Handle LH', 'nominated', 'E1 · 003', '199401', '2']))
  })

  it('leaves the cavities column out before the tool fields exist', async () => {
    const p = popout()
    mount()
    await screen.findByTestId('item-row-5')
    act(() => p.channel.postMessage(hello))
    const table = await screen.findByTestId('items-table')
    expect(within(table).queryByText('Cavities')).toBeNull()
  })

  it('starts another project with its detail pane, not in the previous project\'s table mode', async () => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/plants/projects') return Promise.resolve({ data: [
        { id: 2, name: 'Seat Trim', code: '1994', status: 'active', customer_naming: 'vw' },
        { id: 3, name: 'Door Trim', code: '1995', status: 'active', customer_naming: 'vw' }] })
      if (url === '/v1/parts/project/3') return Promise.resolve({ data: [{ ...RH, id: 40, part_number: '20-1995-001-0', name: 'Door handle' }] })
      return routeGet(url)
    })
    const nav: { go: NavigateFunction | null } = { go: null }
    const Nav = () => { nav.go = useNavigate(); return null }
    const p = popout()
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={['/projects/2']}>
          <Nav />
          <Routes><Route path="/projects/:projectId" element={<ProjectDetailPage />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>)
    await screen.findByTestId('item-row-5')
    act(() => p.channel.postMessage(hello))
    await screen.findByTestId('items-table')
    act(() => { nav.go!('/projects/3') })
    expect(await screen.findByTestId('item-row-40')).toBeTruthy()
    expect(screen.queryByTestId('items-table')).toBeNull()
    expect(screen.getByTestId('detail-column')).toBeTruthy()
  })

  it('offers no pop-out when the browser has no BroadcastChannel', async () => {
    vi.stubGlobal('BroadcastChannel', undefined)
    mount()
    fireEvent.click(await screen.findByTestId('item-row-5'))
    await screen.findByTestId('detail-header')
    expect(screen.queryByLabelText('Open detail in new window')).toBeNull()
  })
})
