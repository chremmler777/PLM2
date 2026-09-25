import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ProjectTeamCard } from './ProjectTeamCard'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)

describe('ProjectTeamCard', () => {
  beforeEach(() => {
    clientMocks.get.mockResolvedValue({ data: [
      { department_id: 6, department_name: 'Project Manager',
        responsible: { id: 3, name: 'Petra PM' },
        members: [{ id: 3, name: 'Petra PM', role: 'main' }, { id: 4, name: 'Paul Two', role: 'backup' }] },
      { department_id: 5, department_name: 'Sales', responsible: null,
        members: [{ id: 7, name: 'Sam Sales', role: 'main' }] },
    ] })
    clientMocks.put.mockResolvedValue({ data: [] })
  })
  afterEach(cleanup)

  it('lists roles with their responsible, unassigned shown for an unset role', async () => {
    wrap(<ProjectTeamCard projectId={2} />)
    await screen.findByText('Petra PM')
    expect(screen.getByText('Unassigned')).toBeDefined()
  })

  it('sets a responsible from that department\'s own members', async () => {
    wrap(<ProjectTeamCard projectId={2} />)
    await screen.findByTestId('team-edit-5')
    fireEvent.click(screen.getByTestId('team-edit-5'))
    const sel = screen.getByTestId('team-select-5') as HTMLSelectElement
    expect([...sel.options].map((o) => o.text)).toEqual(['Unassigned', 'Sam Sales'])
    fireEvent.change(sel, { target: { value: '7' } })
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith(
      '/v1/projects/2/team', { department_id: 5, user_id: 7 }))
  })

  it('clears a responsible', async () => {
    wrap(<ProjectTeamCard projectId={2} />)
    await screen.findByTestId('team-edit-6')
    fireEvent.click(screen.getByTestId('team-edit-6'))
    const sel = screen.getByTestId('team-select-6') as HTMLSelectElement
    fireEvent.change(sel, { target: { value: '' } })
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith(
      '/v1/projects/2/team', { department_id: 6, user_id: null }))
  })
})
