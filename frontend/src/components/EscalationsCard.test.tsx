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
})
