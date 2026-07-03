import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import EscalationsCard from './EscalationsCard'
import { changesApi } from '../api/changes'

vi.mock('../api/changes', () => ({
  changesApi: { myEscalations: vi.fn() },
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>)
}

describe('EscalationsCard', () => {
  afterEach(cleanup)

  it('renders nothing when there are no escalations', async () => {
    vi.mocked(changesApi.myEscalations).mockResolvedValue([])
    const { container } = wrap(<EscalationsCard />)
    await new Promise(r => setTimeout(r, 0))
    expect(container.textContent).toBe('')
  })

  it('lists overdue items with change link and owner', async () => {
    vi.mocked(changesApi.myEscalations).mockResolvedValue([
      { kind: 'wf_task', change_id: 3, change_number: 'CR-2026-0009',
        change_title: 'Tool fix', label: 'Werkzeugänderung umsetzen',
        owner_id: 5, owner_name: 'Eva Eng', due_date: '2026-06-28T00:00:00',
        days_overdue: 4 },
      { kind: 'assessment', change_id: 3, change_number: 'CR-2026-0009',
        change_title: 'Tool fix', label: 'Quality', owner_id: null,
        owner_name: null, due_date: '2026-06-30T00:00:00', days_overdue: 2 },
    ])
    wrap(<EscalationsCard />)
    expect((await screen.findAllByText(/CR-2026-0009/)).length).toBeGreaterThan(0)
    expect(screen.getByText('Eva Eng')).toBeDefined()
    expect(screen.getByText(/Unclaimed/)).toBeDefined()
    expect(screen.getByText(/4d overdue/)).toBeDefined()
    const links = screen.getAllByRole('link')
    expect(links.some(l => l.getAttribute('href') === '/changes/3')).toBe(true)
  })

  it('renders deadline escalations with state label instead of raw days_overdue', async () => {
    vi.mocked(changesApi.myEscalations).mockResolvedValue([
      { kind: 'deadline', change_id: 4, change_number: 'CR-2026-0011',
        change_title: 'Bracket update', label: 'Required by 2026-07-12',
        required_by_date: '2026-07-12T00:00:00', state: 'at_risk',
        days_overdue: -9 },
    ])
    wrap(<EscalationsCard />)
    expect(await screen.findByText(/at risk/)).toBeDefined()
    expect(screen.getByText(/12\.0?7\.2026/)).toBeDefined()
    expect(screen.queryByText(/-9d/)).toBeNull()
  })

  it('shows overdue label for an overdue deadline', async () => {
    vi.mocked(changesApi.myEscalations).mockResolvedValue([
      { kind: 'deadline', change_id: 5, change_number: 'CR-2026-0012',
        change_title: 'Housing fix', label: 'Required by 2026-06-20',
        required_by_date: '2026-06-20T00:00:00', state: 'overdue',
        days_overdue: 12 },
    ])
    wrap(<EscalationsCard />)
    expect(await screen.findByText('overdue')).toBeDefined()
  })
})
