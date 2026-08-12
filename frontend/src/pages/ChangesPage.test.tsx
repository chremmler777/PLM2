import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import ChangesPage from './ChangesPage'
import { changesApi } from '../api/changes'
import { t } from '../i18n/cmLabels'

vi.mock('../api/changes', () => ({ changesApi: { list: vi.fn() } }))
vi.mock('../components/changes/StartChangeModal', () => ({ default: () => null }))

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
    expect(link.textContent).toBe(t('procmap.link', 'de'))
    expect(link.getAttribute('href')).toBe('/process-map')
  })

  it('leaves a dash for a change with no project on the row', async () => {
    vi.mocked(changesApi.list).mockResolvedValue([
      row({ project_number: null, project_name: null })] as never)
    wrap()
    await screen.findByText('GB-CM-0001')
    expect(screen.getByText('—')).toBeDefined()
  })
})
