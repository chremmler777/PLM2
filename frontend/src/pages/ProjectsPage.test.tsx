import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import ProjectsPage from './ProjectsPage'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

describe('ProjectsPage team marker', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks() })

  it('marks a project whose team is not defined in red, not the complete one', async () => {
    clientMocks.get.mockImplementation(async (url: string) =>
      url === '/v1/projects/team-gaps' ? { data: { 1: 3 } }
        : url.includes('projects') ? { data: [
          { id: 1, code: '1994', name: 'Seat Trim', status: 'active' },
          { id: 2, code: '2277', name: 'Backpanel', status: 'active' }] }
          : { data: [] })
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><ProjectsPage /></MemoryRouter></QueryClientProvider>)
    const chip = await screen.findByTestId('team-incomplete-1')
    expect(chip.textContent).toContain('Team incomplete')
    expect(chip.getAttribute('title')).toBe('3 department(s) without a responsible')
    expect(screen.queryByTestId('team-incomplete-2')).toBeNull()
  })
})
