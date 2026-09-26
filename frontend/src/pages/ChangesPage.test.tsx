import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation } from 'react-router-dom'
import ChangesPage from './ChangesPage'
import { changesApi } from '../api/changes'
import { t } from '../i18n/cmLabels'

vi.mock('../api/changes', () => ({ changesApi: { list: vi.fn() } }))
vi.mock('../components/changes/StartChangeModal', () => ({ default: () => null }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ userId: 5 }) }))

const row = (over: Record<string, unknown> = {}) => ({
  id: 1, change_number: 'GB-CM-0001', title: 'Clip rattles', change_type: 'physical_part',
  status: 'scoping', priority: 'medium', customer_relevant: true,
  required_by_date: null, release_due_date: null, active_deadline: null, deadline_state: null,
  project_number: '1864', project_name: 'VW426 Atlas', ...over,
})

const wrap = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><ChangesPage /></MemoryRouter>
  </QueryClientProvider>)

describe('ChangesPage project column', () => {
  afterEach(cleanup)

  it('leads each row with the project, number first', async () => {
    vi.mocked(changesApi.list).mockResolvedValue([row()] as never)
    wrap()
    const cell = await screen.findByText('1864 · VW426 Atlas')
    // The project is the first column, ahead of the change number.
    expect(cell.closest('tr')?.firstElementChild?.contains(cell)).toBe(true)
    expect(screen.getByText('GB-CM-0001')).toBeDefined()
  })

  it('points at the process map from the list header', async () => {
    vi.mocked(changesApi.list).mockResolvedValue([] as never)
    wrap()
    const link = screen.getByTestId('process-map-link')
    expect(link.textContent).toBe(t('procmap.link'))
    expect(link.getAttribute('href')).toBe('/process-map')
  })

  it('leaves a dash for a change with no project on the row', async () => {
    vi.mocked(changesApi.list).mockResolvedValue([
      row({ project_number: null, project_name: null })] as never)
    wrap()
    await screen.findByText('GB-CM-0001')
    expect(screen.getByText('-')).toBeDefined()
  })
})

describe('ChangesPage list polish (spec §16)', () => {
  afterEach(cleanup)
  const rows = () => screen.getAllByTestId(/^change-row-/)

  it('shows human labels for type, priority and status, number and pill never wrap', async () => {
    vi.mocked(changesApi.list).mockResolvedValue([
      row({ status: 'in_assessment', priority: 'high' }),
      row({ id: 2, change_number: 'GB-CM-0002', change_type: 'tooling' })] as never)
    wrap()
    await screen.findByText('GB-CM-0001')
    expect(screen.getByText('Physical part')).toBeDefined()
    expect(screen.getByText('High')).toBeDefined()
    const pill = screen.getByTestId('change-status-1')
    expect(pill.textContent).toBe('In Assessment')
    expect(pill.className).toContain('whitespace-nowrap')
    expect(screen.getByText('GB-CM-0001').closest('td')?.className).toContain('whitespace-nowrap')
    expect(screen.queryByText('physical_part')).toBeNull()
  })

  it('searches number, title and project', async () => {
    vi.mocked(changesApi.list).mockResolvedValue([
      row(), row({ id: 2, change_number: 'GB-CM-0002', title: 'Grille carrier', project_number: '1539', project_name: 'BMW G05' }),
    ] as never)
    wrap()
    await screen.findByText('GB-CM-0002')
    const search = screen.getByTestId('changes-search')
    fireEvent.change(search, { target: { value: 'grille' } })
    expect(rows()).toHaveLength(1)
    expect(screen.getByText('GB-CM-0002')).toBeDefined()
    fireEvent.change(search, { target: { value: 'vw426' } })
    expect(screen.getByText('GB-CM-0001')).toBeDefined()
    expect(screen.queryByText('GB-CM-0002')).toBeNull()
    fireEvent.change(search, { target: { value: '0002' } })
    expect(screen.getByText('GB-CM-0002')).toBeDefined()
    fireEvent.change(search, { target: { value: 'nothing like it' } })
    expect(screen.getByText(t('changes.noMatch'))).toBeDefined()
  })

  it('filters to mine: is_mine when sent, else the lead', async () => {
    vi.mocked(changesApi.list).mockResolvedValue([
      row({ id: 1, lead_id: 5 }),
      row({ id: 2, change_number: 'GB-CM-0002', lead_id: 9 }),
      row({ id: 3, change_number: 'GB-CM-0003', lead_id: 9, is_mine: true }),
      row({ id: 4, change_number: 'GB-CM-0004', lead_id: 5, is_mine: false }),
    ] as never)
    wrap()
    await screen.findByText('GB-CM-0004')
    fireEvent.click(screen.getByTestId('changes-mine'))
    expect(rows().map((r) => within(r).getByRole('link').textContent)).toEqual(['GB-CM-0001', 'GB-CM-0003'])
  })

  it('sorts overdue first on request', async () => {
    vi.mocked(changesApi.list).mockResolvedValue([
      row({ id: 1, active_deadline: 'quote', required_by_date: '2099-01-01', deadline_state: 'on_track' }),
      row({ id: 2, change_number: 'GB-CM-0002', active_deadline: 'quote', required_by_date: '2020-01-01', deadline_state: 'on_track' }),
      row({ id: 3, change_number: 'GB-CM-0003', deadline_state: 'overdue', active_deadline: 'release', release_due_date: '2098-01-01' }),
    ] as never)
    wrap()
    await screen.findByText('GB-CM-0003')
    fireEvent.change(screen.getByTestId('changes-sort'), { target: { value: 'recent' } })
    expect(within(rows()[0]).getByRole('link').textContent).toBe('GB-CM-0001')
    fireEvent.change(screen.getByTestId('changes-sort'), { target: { value: 'overdue' } })
    const order = rows().map((r) => within(r).getByRole('link').textContent)
    expect(order.slice(0, 2).sort()).toEqual(['GB-CM-0002', 'GB-CM-0003'])
    expect(order[2]).toBe('GB-CM-0001')
  })

  it('hides the Type column when every row has the same type, and Medium priority', async () => {
    vi.mocked(changesApi.list).mockResolvedValue([row(), row({ id: 2, change_number: 'GB-CM-0002', priority: 'critical' })] as never)
    wrap()
    await screen.findByText('GB-CM-0002')
    expect(screen.queryByRole('columnheader', { name: 'Type' })).toBeNull()
    expect(screen.queryByText('Physical part')).toBeNull()
    expect(screen.getByTestId('change-priority-1').textContent).toBe('')
    expect(screen.getByTestId('change-priority-2').textContent).toBe('Critical')
  })

  it('sorts open overdue changes first and ended ones last by default', async () => {
    vi.mocked(changesApi.list).mockResolvedValue([
      row({ id: 1, status: 'closed' }),
      row({ id: 2, change_number: 'GB-CM-0002' }),
      row({ id: 3, change_number: 'GB-CM-0003', deadline_state: 'overdue', active_deadline: 'quote', required_by_date: '2020-01-01' }),
    ] as never)
    wrap()
    await screen.findByText('GB-CM-0003')
    expect(rows().map((r) => within(r).getByRole('link').textContent)).toEqual(['GB-CM-0003', 'GB-CM-0002', 'GB-CM-0001'])
  })

  it('puts the viewer own changes first: own overdue, own open, overdue, open, ended', async () => {
    const late = { deadline_state: 'overdue', active_deadline: 'quote', required_by_date: '2020-01-01' }
    vi.mocked(changesApi.list).mockResolvedValue([
      row({ id: 1, status: 'closed', is_mine: true }),
      row({ id: 2, change_number: 'GB-CM-0002' }),
      row({ id: 3, change_number: 'GB-CM-0003', ...late }),
      row({ id: 4, change_number: 'GB-CM-0004', is_mine: true }),
      row({ id: 5, change_number: 'GB-CM-0005', is_mine: true, ...late }),
    ] as never)
    wrap()
    await screen.findByText('GB-CM-0005')
    expect(rows().map((r) => within(r).getByRole('link').textContent)).toEqual(
      ['GB-CM-0005', 'GB-CM-0004', 'GB-CM-0003', 'GB-CM-0002', 'GB-CM-0001'])
    expect((screen.getByTestId('changes-sort') as HTMLSelectElement).selectedOptions[0].textContent)
      .toBe(t('changes.sortAction'))
  })

  it('ignores an unknown ?status and says "no match" for an empty status filter', async () => {
    vi.mocked(changesApi.list).mockResolvedValue([] as never)
    const view = (url: string) => render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={[url]}><ChangesPage /></MemoryRouter>
      </QueryClientProvider>)
    view('/changes?status=bogus')
    expect(await screen.findByText('No changes yet')).toBeDefined()
    expect(vi.mocked(changesApi.list)).toHaveBeenLastCalledWith({})
    expect((screen.getByLabelText(t('changes.statusFilter')) as HTMLSelectElement).value).toBe('')
    cleanup()
    view('/changes?status=released')
    expect(await screen.findByText(t('changes.noMatch'))).toBeDefined()
    expect(vi.mocked(changesApi.list)).toHaveBeenLastCalledWith({ status: 'released' })
    expect(screen.queryByText('No changes yet')).toBeNull()
  })

  it('keeps search, mine, intake and sort in the URL', async () => {
    vi.mocked(changesApi.list).mockResolvedValue([
      row({ id: 1, lead_id: 5 }), row({ id: 2, change_number: 'GB-CM-0002', title: 'Grille', lead_id: 9 }),
    ] as never)
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={['/changes?q=grille&sort=recent']}><ChangesPage /></MemoryRouter>
      </QueryClientProvider>)
    await screen.findByText('GB-CM-0002')
    expect((screen.getByTestId('changes-search') as HTMLInputElement).value).toBe('grille')
    expect((screen.getByTestId('changes-sort') as HTMLSelectElement).value).toBe('recent')
    expect(rows()).toHaveLength(1)
  })

  it('names the stage owner: the server word, else the role badge for the stage', async () => {
    vi.mocked(changesApi.list).mockResolvedValue([
      row({ id: 1, status: 'captured' }),
      row({ id: 2, change_number: 'GB-CM-0002', status: 'scoping', stage_owner: 'Eva PM' }),
    ] as never)
    wrap()
    await screen.findByText('GB-CM-0002')
    expect(screen.getByTestId('change-owner-2').textContent).toBe('Eva PM')
    expect(within(screen.getByTestId('change-owner-1')).getByTestId('stage-responsible')).toBeDefined()
  })

  it('shows Rejected, Rejected closed and Canceled distinctly, without a deadline chip', async () => {
    vi.mocked(changesApi.list).mockResolvedValue([
      row({ id: 1, status: 'rejected', active_deadline: 'quote', required_by_date: '2020-01-01', deadline_state: 'overdue' }),
      row({ id: 2, change_number: 'GB-CM-0002', status: 'closed', rejected_at: '2026-09-01T00:00:00' }),
      row({ id: 3, change_number: 'GB-CM-0003', status: 'cancelled', active_deadline: 'quote', required_by_date: '2020-01-01' }),
      row({ id: 4, change_number: 'GB-CM-0004', status: 'closed' }),
    ] as never)
    wrap()
    await screen.findByText('GB-CM-0004')
    expect(screen.getByTestId('change-status-1').textContent).toBe('Rejected')
    expect(screen.getByTestId('change-status-2').textContent).toBe('Rejected, closed')
    expect(screen.getByTestId('change-status-2').className).toContain('bg-red-900')
    expect(screen.getByTestId('change-status-3').textContent).toBe('Canceled')
    expect(screen.getByTestId('change-status-4').textContent).toBe('Closed')
    expect(screen.queryByTestId('deadline-chip')).toBeNull()
  })

  it('keeps the deadline chip on a running change', async () => {
    vi.mocked(changesApi.list).mockResolvedValue([
      row({ active_deadline: 'quote', required_by_date: '2099-01-01', deadline_state: 'on_track' })] as never)
    wrap()
    expect(await screen.findByTestId('deadline-chip')).toBeDefined()
  })
})

describe('ChangesPage column sort and filter', () => {
  afterEach(cleanup)
  const rows = () => screen.getAllByTestId(/^change-row-/)
  const numbers = () => rows().map((r) => within(r).getByRole('link').textContent)
  let search = ''
  function Loc() { search = useLocation().search; return null }
  const view = (url = '/changes') => render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[url]}><ChangesPage /><Loc /></MemoryRouter>
    </QueryClientProvider>)
  const data = () => [
    row({ id: 1, priority: 'low', status: 'scoping' }),
    row({ id: 2, change_number: 'GB-CM-0002', priority: 'critical', status: 'costing',
      project_number: '1539', project_name: 'BMW G05' }),
    row({ id: 3, change_number: 'GB-CM-0003', priority: 'high', status: 'captured' }),
  ]

  it('sorts by a column over the list order, in the URL; the sort dropdown takes it back', async () => {
    vi.mocked(changesApi.list).mockResolvedValue(data() as never)
    view()
    await screen.findByText('GB-CM-0003')
    const priority = screen.getByRole('button', { name: 'Priority' })
    fireEvent.click(priority)
    expect(numbers()).toEqual(['GB-CM-0002', 'GB-CM-0003', 'GB-CM-0001'])
    expect(priority.closest('th')?.getAttribute('aria-sort')).toBe('ascending')
    expect(new URLSearchParams(search).get('csort')).toBe('priority:asc')
    const sortSelect = screen.getByTestId('changes-sort') as HTMLSelectElement
    expect(sortSelect.value).toBe('column')
    expect(sortSelect.selectedOptions[0].textContent).toBe('By Priority, ascending')
    fireEvent.click(priority)
    expect(numbers()).toEqual(['GB-CM-0001', 'GB-CM-0003', 'GB-CM-0002'])
    // picking a list order drops the column sort
    fireEvent.change(sortSelect, { target: { value: 'recent' } })
    expect(new URLSearchParams(search).get('csort')).toBeNull()
    expect(new URLSearchParams(search).get('sort')).toBe('recent')
    expect(numbers()).toEqual(['GB-CM-0001', 'GB-CM-0002', 'GB-CM-0003'])
  })

  it('filters by the shown status label and project, keeps it in the URL, clears', async () => {
    vi.mocked(changesApi.list).mockResolvedValue(data() as never)
    view('/changes?q=gb-cm')
    await screen.findByText('GB-CM-0003')
    fireEvent.click(screen.getByRole('button', { name: 'Filter Status' }))
    const d = screen.getByRole('dialog', { name: 'Filter Status' })
    fireEvent.click(within(d).getByRole('checkbox', { name: 'Select all' }))
    fireEvent.click(within(d).getByRole('checkbox', { name: 'Costing' }))
    fireEvent.click(within(d).getByRole('checkbox', { name: 'Scoping' }))
    fireEvent.click(within(d).getByRole('button', { name: 'Apply' }))
    expect(numbers()).toEqual(['GB-CM-0001', 'GB-CM-0002'])
    const params = new URLSearchParams(search)
    expect(params.getAll('f.status').sort()).toEqual(['Costing', 'Scoping'])
    expect(params.get('q')).toBe('gb-cm')
    expect(screen.getByTestId('table-filter-bar').textContent).toContain('2 of 3 rows')

    fireEvent.click(screen.getByRole('button', { name: 'Filter Project' }))
    const p = screen.getByRole('dialog', { name: 'Filter Project' })
    // only the values the status filter leaves: both projects are still there
    fireEvent.change(within(p).getByRole('searchbox'), { target: { value: 'bmw' } })
    fireEvent.click(within(p).getByRole('button', { name: 'Apply' }))
    expect(numbers()).toEqual(['GB-CM-0002'])
    expect(screen.getByTestId('table-filter-bar').textContent).toContain('2 filters active')

    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(rows()).toHaveLength(3)
    expect([...new URLSearchParams(search).keys()]).toEqual(['q'])
  })

  it('restores column filters and sort from a shared link, next to the old parameters', async () => {
    vi.mocked(changesApi.list).mockResolvedValue(data() as never)
    view('/changes?f.priority=High&f.priority=Critical&csort=number:desc&sort=recent&f.bogus=1')
    await screen.findByText('GB-CM-0003')
    expect(numbers()).toEqual(['GB-CM-0003', 'GB-CM-0002'])
    expect(screen.getByRole('button', { name: 'Filter Priority' }).getAttribute('data-active')).toBe('true')
    expect(screen.getByRole('button', { name: 'Number' }).closest('th')?.getAttribute('aria-sort'))
      .toBe('descending')
    expect(screen.getByText(/1 filter active/)).toBeDefined()
  })

  it('says no match when the column filters leave nothing', async () => {
    vi.mocked(changesApi.list).mockResolvedValue(data() as never)
    view('/changes?f.owner=Nobody')
    expect(await screen.findByText(t('changes.noMatch'))).toBeDefined()
  })
})
