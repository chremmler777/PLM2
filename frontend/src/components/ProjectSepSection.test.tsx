import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import ProjectSepSection from './ProjectSepSection'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../forms/FormPanel', () => ({ default: () => <div>form-panel</div> }))
vi.mock('../forms/ProjectFormsTab', () => ({ default: () => <div>forms-tab</div> }))

const item = {
  id: 7, gate_id: 1, item_no: 12, title_de: 'Machbarkeit', title_en: 'Feasibility study',
  department: 'Engineering', status: 'open', remark: null, responsible_id: null,
  responsible_name: null, completed_at: null, lessons_link: true, form: null,
  references: [], file_count: 2,
}

const sep = {
  active: true,
  gates: [{
    id: 1, project_id: 2, code: 'QG1', seq: 1, phase_de: 'Konzept', phase_en: 'Concept',
    status: 'in_progress', color: 'green', target_date: '2026-10-01',
    pm_signed_name: null, pm_signed_at: null, quality_signed_name: null, quality_signed_at: null,
    progress: { done: 0, open: 1, not_applicable: 0, total: 1, pct: 0 },
    open_risks: 0, items: [item], file_count: 3,
  }],
}

const wrap = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><ProjectSepSection projectId={2} /></MemoryRouter>
    </QueryClientProvider>)

describe('ProjectSepSection file counts', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/sep/projects/2') return Promise.resolve({ data: sep })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('counts the gate files in the header and the item files on the row', async () => {
    wrap()
    fireEvent.click(await screen.findByText(/SEP Q-Gates/))
    expect((await screen.findByTestId('gate-file-count')).textContent).toContain('📎 3')
    expect(screen.getByTestId('sep-files-badge-7').textContent).toContain('📎 2')
    // the lessons link goes through the router (basename-aware) and filters to this project
    expect(screen.getByText('📘 lessons').getAttribute('href')).toBe('/lessons?project=2')
  })

  it('offers a Documents tab beside the checklist', async () => {
    wrap()
    fireEvent.click(await screen.findByText(/SEP Q-Gates/))
    fireEvent.click(await screen.findByText('Documents'))
    expect(await screen.findByTestId('sep-documents-empty')).toBeTruthy()
  })
})
