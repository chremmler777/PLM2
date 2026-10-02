import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import ProjectStatusNav from './ProjectStatusNav'
import { relaySummary } from '../dfm/dfmFixtures'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../../forms/FormPanel', () => ({ default: () => <div>form-panel</div> }))
vi.mock('../../forms/ProjectFormsTab', () => ({ default: () => <div>forms-tab</div> }))
vi.mock('../ProjectChangesSection', () => ({ default: () => <div>changes-section</div> }))
vi.mock('../ProjectLessonsSection', () => ({ default: () => <div>lessons-section</div> }))
vi.mock('../dfm/DfmArchive', () => ({
  default: (p: { scope: { kind: string; id: number } }) => <div data-testid="dfm-archive-stub">dfm {p.scope.kind} {p.scope.id}</div>,
}))

const gate = (id: number, code: string, status: string, pct: number, title: string) => ({
  id, project_id: 2, code, seq: id, phase_de: title, phase_en: title, status, color: 'green',
  target_date: null, pm_signed_name: null, pm_signed_at: null, quality_signed_name: null, quality_signed_at: null,
  progress: { done: 0, open: 4, not_applicable: 0, total: 4, pct }, open_risks: 0, file_count: 0,
  items: [{ id: id * 10, gate_id: id, item_no: 1, title_de: `${code} item`, title_en: `${code} work package`,
    department: 'Engineering', status: 'open', remark: null, responsible_id: null, responsible_name: null,
    completed_at: null, lessons_link: false, form: null, references: [], file_count: 0 }],
})

const sep = {
  active: true,
  gates: [gate(1, 'K0/RG1', 'in_progress', 25, 'Kick-off'), gate(2, 'K1/RG2', 'pending', 0, 'Concept')],
  rollup: { total: { pct: 12, done: 1, total: 8 } },
}

function mount() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><ProjectStatusNav projectId={2} /></MemoryRouter>
    </QueryClientProvider>)
}

const navButton = (name: RegExp) => screen.getByRole('button', { name })
const panel = () => screen.getByTestId('status-panel')

describe('ProjectStatusNav', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/sep/projects/2') return Promise.resolve({ data: sep })
      if (url === '/v1/changes') return Promise.resolve({ data: [{ id: 1, status: 'scoping' }, { id: 2, status: 'closed' }] })
      if (url === '/v1/lessons/projects/2/references') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('shows the collapsed gate strip, Changes and Lessons with nothing open on load', async () => {
    mount()
    const bar = screen.getByTestId('project-status-nav')
    expect(await within(bar).findByRole('button', { name: /K0\/RG1/ })).toBeTruthy()
    expect(within(bar).getByRole('button', { name: /K1\/RG2/ })).toBeTruthy()
    expect(bar.textContent).toContain('SEP Q-Gates')
    expect(bar.textContent).toContain('current: K0/RG1')
    expect(bar.textContent).toContain('total 12% · 1/8 work packages')
    expect((await within(bar).findByRole('button', { name: /Changes \(1\)/ }))).toBeTruthy()
    const lessons = await within(bar).findByRole('button', { name: /Lessons/ })
    await vi.waitFor(() => expect(lessons.className).toContain('amber'))
    for (const b of within(bar).getAllByRole('button')) {
      if (b.hasAttribute('aria-expanded')) expect(b.getAttribute('aria-expanded')).toBe('false')
    }
    expect(panel().hidden).toBe(true)
    expect(screen.queryByText('K0/RG1 work package')).toBeNull()
    expect(screen.queryByTestId('status-slideover')).toBeNull()
  })

  it('points each nav item at the panel region', async () => {
    mount()
    const chip = await screen.findByRole('button', { name: /K0\/RG1/ })
    const id = panel().id
    expect(id).toBeTruthy()
    expect(chip.getAttribute('aria-controls')).toBe(id)
    expect(navButton(/Changes/).getAttribute('aria-controls')).toBe(id)
    expect(navButton(/Lessons/).getAttribute('aria-controls')).toBe(id)
  })

  it('opens the clicked gate review below the bar, and another gate replaces it', async () => {
    mount()
    fireEvent.click(await screen.findByRole('button', { name: /K1\/RG2/ }))
    expect(navButton(/K1\/RG2/).getAttribute('aria-expanded')).toBe('true')
    expect(panel().hidden).toBe(false)
    expect(within(panel()).getByText('K1/RG2 work package')).toBeTruthy()
    fireEvent.click(navButton(/K0\/RG1/))
    expect(navButton(/K1\/RG2/).getAttribute('aria-expanded')).toBe('false')
    expect(within(panel()).getByText('K0/RG1 work package')).toBeTruthy()
    expect(within(panel()).queryByText('K1/RG2 work package')).toBeNull()
  })

  it('opening Lessons closes the gate review; the gate strip stays', async () => {
    mount()
    fireEvent.click(await screen.findByRole('button', { name: /K0\/RG1/ }))
    fireEvent.click(navButton(/Lessons/))
    expect(within(panel()).getByText('lessons-section')).toBeTruthy()
    expect(within(panel()).queryByText('K0/RG1 work package')).toBeNull()
    expect(navButton(/Lessons/).getAttribute('aria-expanded')).toBe('true')
    expect(navButton(/K0\/RG1/).getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(navButton(/Changes/))
    expect(within(panel()).getByText('changes-section')).toBeTruthy()
    expect(within(panel()).queryByText('lessons-section')).toBeNull()
    expect(navButton(/K0\/RG1/)).toBeTruthy()
  })

  it('clicking the active item again closes its panel', async () => {
    mount()
    fireEvent.click(await screen.findByRole('button', { name: /K0\/RG1/ }))
    fireEvent.click(navButton(/K0\/RG1/))
    expect(panel().hidden).toBe(true)
    fireEvent.click(navButton(/Lessons/))
    fireEvent.click(navButton(/Lessons/))
    expect(panel().hidden).toBe(true)
    expect(screen.queryByText('lessons-section')).toBeNull()
  })

  it('closes the open panel with Escape', async () => {
    mount()
    fireEvent.click(await screen.findByRole('button', { name: /Changes/ }))
    expect(screen.getByText('changes-section')).toBeTruthy()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(panel().hidden).toBe(true)
    expect(screen.queryByText('changes-section')).toBeNull()
  })

  it('leaves Escape typed in a field of the panel alone', async () => {
    mount()
    fireEvent.click(await screen.findByRole('button', { name: /K0\/RG1/ }))
    const remark = within(panel()).getByPlaceholderText('Remark / actions…')
    fireEvent.keyDown(remark, { key: 'Escape' })
    expect(panel().hidden).toBe(false)
  })

  it('bounds the panel height and scrolls it on its own', async () => {
    mount()
    fireEvent.click(await screen.findByRole('button', { name: /K0\/RG1/ }))
    expect(panel().className).toContain('max-h-[45vh]')
    expect(panel().className).toContain('overflow-y-auto')
  })

  it('shows Tooling DFM without a count when no topic is open, neutral', async () => {
    mount()
    const btn = await screen.findByTestId('status-nav-dfm')
    expect(btn.textContent).toContain('Tooling DFM')
    expect(btn.textContent).not.toMatch(/Tooling DFM \d/)
    expect(btn.className).toContain('border-slate-600')
  })

  it('counts open general DFM topics and turns amber while one waits on KTX', async () => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/projects/2/dfm/topics') return Promise.resolve({ data: [
        relaySummary({ id: 1, project_id: 2, tool_part_id: null, waiting_on: [{ party: 'ktx', count: 1, oldest_days: 2 }] }),
        relaySummary({ id: 2, project_id: 2, tool_part_id: null, waiting_on: [] }),
        relaySummary({ id: 3, project_id: 2, tool_part_id: null, status: 'finished_confirmed', waiting_on: [] }),
      ] })
      return Promise.resolve({ data: [] })
    })
    mount()
    const btn = await screen.findByTestId('status-nav-dfm')
    await vi.waitFor(() => expect(btn.textContent).toContain('Tooling DFM 2'))
    expect(btn.className).toContain('amber')
  })

  it('stays neutral when open topics wait on others than KTX', async () => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/projects/2/dfm/topics') return Promise.resolve({ data: [
        relaySummary({ id: 1, project_id: 2, tool_part_id: null, waiting_on: [{ party: 'tier1', count: 1, oldest_days: 2 }] }),
      ] })
      return Promise.resolve({ data: [] })
    })
    mount()
    const btn = await screen.findByTestId('status-nav-dfm')
    await vi.waitFor(() => expect(btn.textContent).toContain('Tooling DFM 1'))
    expect(btn.className).not.toContain('amber')
  })

  it('opens the project-wide DFM archive in the panel', async () => {
    mount()
    fireEvent.click(await screen.findByTestId('status-nav-dfm'))
    expect(panel().hidden).toBe(false)
    expect(within(panel()).getByTestId('dfm-archive-stub').textContent).toBe('dfm project 2')
    expect(screen.getByTestId('status-nav-dfm').getAttribute('aria-expanded')).toBe('true')
    fireEvent.click(navButton(/Changes/))
    expect(within(panel()).queryByTestId('dfm-archive-stub')).toBeNull()
  })
})
