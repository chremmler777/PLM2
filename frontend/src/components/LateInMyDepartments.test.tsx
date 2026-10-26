import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import LateInMyDepartments from './LateInMyDepartments'

const clientMocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

const wrap = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><LateInMyDepartments /></MemoryRouter>
  </QueryClientProvider>)

describe('LateInMyDepartments', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks() })

  it('renders nothing for someone who manages no department', async () => {
    clientMocks.get.mockResolvedValue({ data: { departments: [], items: [] } })
    const { container } = wrap()
    await new Promise((r) => setTimeout(r, 0))
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/changes/my-department-escalations')
    expect(container.textContent).toBe('')
  })

  it('a manager sees each late item: change, department, owner, due, days late, link', async () => {
    clientMocks.get.mockResolvedValue({ data: {
      departments: [{ id: 1, name: 'Process Engineer' }, { id: 2, name: 'Tool Engineer' }],
      items: [{ kind: 'assessment', change_id: 42, change_number: 'ECR-0042', change_title: 'Gate move',
        department_id: 2, department_name: 'Tool Engineer', label: 'Tool Engineer assessment',
        owner_name: 'Dale', due_date: '2026-10-20T00:00:00', days_overdue: 6 }],
    } })
    wrap()
    const row = await screen.findByTestId('late-dept-row')
    expect(screen.getByText(/Late in my departments \(1\)/)).toBeTruthy()
    expect(screen.getByText(/As manager of Process Engineer, Tool Engineer/)).toBeTruthy()
    expect(row.textContent).toContain('Gate move')
    expect(row.textContent).toContain('Dale')
    expect(row.textContent).toContain('6d late')
    expect(screen.getByText('ECR-0042').getAttribute('href')).toBe('/changes/42')
    // view only: no action buttons
    expect(row.querySelector('button')).toBeNull()
  })

  it('a manager with nothing late reads so', async () => {
    clientMocks.get.mockResolvedValue({ data: { departments: [{ id: 1, name: 'Quality' }], items: [] } })
    wrap()
    expect(await screen.findByTestId('late-in-my-departments-empty')).toBeTruthy()
  })
})
