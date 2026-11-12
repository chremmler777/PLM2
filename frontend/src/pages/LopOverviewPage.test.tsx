import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import LopOverviewPage from './LopOverviewPage'
import { lopLine } from '../components/lop/lop.fixtures'
import type { LopDepartmentKpi, LopKpi, LopOverview, LopProjectKpi } from '../types/lop'

const clientMocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

// Shapes as lop_kpi.kpi / overview / department_rows and LopMeetings.escalations send them.
const kpi = (over: Partial<LopKpi> = {}): LopKpi => ({
  open: 17, no_control: 3, with_name_and_date_pct: 82, stale: 2, late: 3, avg_days_late: 6.4,
  untouched_last_meeting: 4, on_time_pct_4w: 71, dates_moved_4w: 9, opened_week: 14, closed_week: 19,
  ...over,
})

const projectRow = (over: Partial<LopProjectKpi> = {}): LopProjectKpi => ({
  project_id: 2, code: '2277', name: 'Backpanel', ...kpi(),
  gate: { code: 'K0/RG1', done_pct: 14, target_date: '2026-12-04' },
  pdb: {
    available: true, tools_c: 2, tools_b: 2, tools_a: 1, open_topics: 9, escalated: 3,
    pinned: 1, pdb_without_name_and_date: 8,
  },
  ...over,
})

const deptRow = (over: Partial<LopDepartmentKpi> = {}): LopDepartmentKpi => ({
  department_id: 10, name: 'Quality', ...kpi({ open: 16, stale: 5 }), ...over,
})

const overview = (over: Partial<LopOverview> = {}): LopOverview => ({
  totals: { ...kpi(), pdb_without_name_and_date: 8 },
  projects: [
    projectRow({ project_id: 5, code: '1748', name: 'G6x', gate: null }),
    projectRow(),
  ],
  departments: [deptRow(), deptRow({ department_id: null, name: 'No department', stale: 1 })],
  escalations: [],
  ...over,
})

let data: LopOverview
let linesAnswer: unknown[]

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><LopOverviewPage /></MemoryRouter>
    </QueryClientProvider>)
}

const table = (name: string) => screen.getByRole('table', { name })
const bodyRows = (name: string) => within(table(name)).getAllByRole('row').filter((r) => r.closest('tbody'))

describe('LopOverviewPage', () => {
  beforeEach(() => {
    data = overview()
    linesAnswer = []
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/lop/overview') return Promise.resolve({ data })
      if (url === '/v1/lop/lines') return Promise.resolve({ data: linesAnswer })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('shows control share as the first tile', async () => {
    mount()
    const tiles = await screen.findAllByTestId('lop-tile')
    expect(tiles[0].textContent).toContain('Lines with a name and a date')
    expect(tiles[0].textContent).toContain('82 %')
    expect(tiles.map((t) => t.getAttribute('data-kpi'))).toEqual([
      'control', 'stale', 'late', 'untouched', 'on_time', 'moved', 'week', 'pdb',
    ])
    expect(tiles[2].textContent).toContain('6.4')
    expect(tiles[7].textContent).toContain('PDB topics without name and date')
  })

  it('lists projects by number with gate readiness and PDB columns', async () => {
    mount()
    await screen.findByRole('table', { name: 'By project' })
    const rows = bodyRows('By project')
    expect(rows[0].textContent).toMatch(/^1748/)
    expect(rows[1].textContent).toMatch(/^2277/)
    const r = within(rows[1])
    expect(r.getByRole('link', { name: '2277' }).getAttribute('href')).toBe('/projects/2/lop')
    expect(rows[1].textContent).toContain('Backpanel')
    expect(rows[1].textContent).toContain('K0/RG1 · 14 % · Dec 4')
    expect(rows[1].textContent).toContain('2 / 2 / 1')
    const cells = r.getAllByRole('cell').map((c) => c.textContent)
    expect(cells.slice(-3)).toEqual(['9', '3', '8'])
    expect(rows[0].textContent).toContain('no gate')
  })

  it('says when a gate has no target date', async () => {
    data = overview({ projects: [projectRow({ gate: { code: 'K0/RG1', done_pct: 14, target_date: null } })] })
    mount()
    await screen.findByRole('table', { name: 'By project' })
    expect(bodyRows('By project')[0].textContent).toContain('K0/RG1 · 14 % · no gate date')
  })

  it('shows "PDB not reachable" in the PDB columns when available is false', async () => {
    data = overview({
      projects: [projectRow({
        pdb: {
          available: false, tools_c: null, tools_b: null, tools_a: null, open_topics: null,
          escalated: null, pinned: 1, pdb_without_name_and_date: null,
        },
      })],
    })
    mount()
    await screen.findByRole('table', { name: 'By project' })
    const row = bodyRows('By project')[0]
    const cell = within(row).getByText('PDB not reachable')
    expect(cell.closest('td')?.getAttribute('colspan')).toBe('4')
    expect(row.textContent).not.toContain('0 / 0 / 0')
  })

  const pdbDown = { available: false, tools_c: null, tools_b: null, tools_a: null, open_topics: null,
    escalated: null, pinned: 0, pdb_without_name_and_date: null }

  it('shows the PDB topic total alone when PDB answered for every project', async () => {
    mount()
    const tile = (await screen.findAllByTestId('lop-tile'))[7]
    expect(tile.querySelector('dd')?.textContent).toBe('8')
    expect(tile.textContent).not.toContain('not reachable')
  })

  it('says n/a for the PDB topic total when PDB answered for no project', async () => {
    data = overview({
      totals: { ...kpi(), pdb_without_name_and_date: 0 },
      projects: [projectRow({ pdb: pdbDown }), projectRow({ project_id: 5, code: '1748', pdb: pdbDown })],
    })
    mount()
    const tile = (await screen.findAllByTestId('lop-tile'))[7]
    expect(tile.querySelector('dd')?.textContent).toBe('n/a')
    expect(tile.textContent).toContain('PDB not reachable')
  })

  it('names how many projects are missing from the PDB topic total', async () => {
    data = overview({
      totals: { ...kpi(), pdb_without_name_and_date: 8 },
      projects: [projectRow({ project_id: 5, code: '1748', pdb: pdbDown }), projectRow()],
    })
    mount()
    const tile = (await screen.findAllByTestId('lop-tile'))[7]
    expect(tile.querySelector('dd')?.textContent).toBe('8')
    expect(tile.textContent).toContain('PDB not reachable for 1 of 2 projects')
  })

  it('scopes the grouped headers of the project table', async () => {
    mount()
    await screen.findByRole('table', { name: 'By project' })
    const heads = within(table('By project')).getAllByRole('columnheader')
    expect(heads[0].textContent).toBe('Project')
    expect(heads.filter((h) => h.getAttribute('scope') === 'colgroup').map((h) => h.textContent)).toEqual(['LOP lines', 'PDB'])
    expect(heads.every((h) => ['col', 'colgroup'].includes(h.getAttribute('scope') ?? ''))).toBe(true)
  })

  it('shows n/a for a null percentage', async () => {
    data = overview({
      totals: { ...kpi({ with_name_and_date_pct: null, on_time_pct_4w: null, open: 0, no_control: 0 }), pdb_without_name_and_date: 0 },
      projects: [projectRow({ on_time_pct_4w: null, gate: { code: 'K1/RG2', done_pct: null, target_date: null } })],
    })
    mount()
    const tiles = await screen.findAllByTestId('lop-tile')
    expect(tiles[0].textContent).toContain('n/a')
    expect(tiles[4].textContent).toContain('n/a')
    expect(tiles[0].textContent).not.toMatch(/NaN|0 %/)
    const row = bodyRows('By project')[0]
    expect(row.textContent).toContain('n/a')
    expect(row.textContent).toContain('K1/RG2 · n/a · no gate date')
    expect(row.textContent).not.toContain('NaN')
  })

  it('opens the stale lines of a department when its stale count is clicked', async () => {
    linesAnswer = [{
      ...lopLine({ id: 14, project_id: 2, text: 'Gauge concept released to supplier', department_name: 'Quality',
        responsible_name: 'Quinn Quality', due_date: '2026-11-03', days_late: 8, late: true, stale: true }),
      project_code: '2277',
    }]
    mount()
    await screen.findByRole('table', { name: 'By department' })
    const quality = bodyRows('By department')[0]
    const stale = within(quality).getByRole('button', { name: /5 .*no update/i })
    stale.focus()
    fireEvent.click(stale)
    await waitFor(() => expect(clientMocks.get).toHaveBeenCalledWith(
      '/v1/lop/lines', { params: { department_id: 10, flag: 'stale' } }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('heading').textContent).toMatch(/No update for 14 days.*Quality/)
    const line = await within(dialog).findByText('Gauge concept released to supplier')
    expect(line.closest('a')?.getAttribute('href')).toBe('/projects/2/lop')
    expect(dialog.textContent).toContain('2277')
    expect(dialog.textContent).toContain('Quinn Quality')
    expect(dialog.textContent).toContain('Nov 3 · 8 d late')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(document.activeElement).toBe(stale)
  })

  it('asks for department 0 behind the "No department" row', async () => {
    mount()
    await screen.findByRole('table', { name: 'By department' })
    const none = bodyRows('By department')[1]
    expect(none.textContent).toContain('No department')
    fireEvent.click(within(none).getByRole('button', { name: /1 .*no update/i }))
    await waitFor(() => expect(clientMocks.get).toHaveBeenCalledWith(
      '/v1/lop/lines', { params: { department_id: 0, flag: 'stale' } }))
  })

  it('opens the late lines of a project from its row and all late lines from the tile', async () => {
    mount()
    await screen.findByRole('table', { name: 'By project' })
    fireEvent.click(within(bodyRows('By project')[1]).getByRole('button', { name: /3 late/i }))
    await waitFor(() => expect(clientMocks.get).toHaveBeenCalledWith(
      '/v1/lop/lines', { params: { project_id: 2, flag: 'late' } }))
    expect(await screen.findByText('Nothing to show.')).toBeTruthy()
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    const lateTile = screen.getAllByTestId('lop-tile')[2]
    fireEvent.click(within(lateTile).getByRole('button'))
    await waitFor(() => expect(clientMocks.get).toHaveBeenCalledWith(
      '/v1/lop/lines', { params: { flag: 'late' } }))
  })

  it('shows the escalation list with project number and days', async () => {
    data = overview({
      escalations: [{
        kind: 'line', project_code: '2277', project_id: 2, since: '2026-11-03', reason: 'late',
        line: lopLine({ id: 14, project_id: 2, text: 'Gauge concept', department_name: 'Quality',
          responsible_name: 'Quinn Quality', late: true, days_late: 8, due_date: '2026-11-03' }),
      }],
    })
    mount()
    const list = await screen.findByRole('list', { name: 'Escalated' })
    const item = within(list).getByRole('listitem')
    expect(item.textContent).toContain('2277 · #14 Gauge concept · Quality · Quinn Quality')
    expect(item.textContent).toContain('late at two meetings in a row since Nov 3')
    expect(item.textContent).toContain('8 d late')
    expect(within(item).getByRole('link').getAttribute('href')).toBe('/projects/2/lop')
  })

  it('lists a no-meeting escalation under the PM\'s name', async () => {
    data = overview({
      escalations: [{ kind: 'no_meeting', project_code: '1748', project_id: 5, pm_name: 'Paula PM', since: '2026-10-28' }],
    })
    mount()
    const list = await screen.findByRole('list', { name: 'Escalated' })
    const item = within(list).getByRole('listitem')
    expect(item.textContent).toContain('1748 · no LOP meeting since Oct 28 · PM Paula PM')
    expect(within(item).getByRole('link').getAttribute('href')).toBe('/projects/5/lop')
  })

  it('words the reason the server gives for each escalated line', async () => {
    const esc = (id: number, reason: 'hand' | 'late' | 'stale' | 'late_or_stale') => ({
      kind: 'line' as const, project_code: '2277', project_id: 2, since: '2026-11-03', reason,
      // the line's own flags today say nothing about why it escalated
      line: lopLine({ id, project_id: 2, text: `Line ${id}`, late: true, stale: true }),
    })
    data = overview({ escalations: [esc(1, 'hand'), esc(2, 'late'), esc(3, 'stale'), esc(4, 'late_or_stale')] })
    mount()
    const items = within(await screen.findByRole('list', { name: 'Escalated' })).getAllByRole('listitem')
    expect(items[0].textContent).toContain('escalated by the PM in the last meeting (Nov 3)')
    expect(items[1].textContent).toContain('late at two meetings in a row since Nov 3')
    expect(items[2].textContent).toContain('no update at two meetings in a row since Nov 3')
    expect(items[3].textContent).toContain('late or without update at two meetings in a row since Nov 3')
  })

  it('says when nothing is escalated', async () => {
    mount()
    expect(await screen.findByText('Nothing escalated.')).toBeTruthy()
  })

  it('shows the server\'s detail when the overview cannot be loaded', async () => {
    clientMocks.get.mockImplementation(() => Promise.reject({ response: { status: 500, data: { detail: 'Database is busy' } } }))
    mount()
    expect((await screen.findByRole('alert')).textContent).toContain('Database is busy')
  })
})
