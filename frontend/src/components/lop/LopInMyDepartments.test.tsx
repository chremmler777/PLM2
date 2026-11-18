import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import LopInMyDepartments from './LopInMyDepartments'

const clientMocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

const wrap = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><LopInMyDepartments /></MemoryRouter>
  </QueryClientProvider>)

const line = (over: Record<string, unknown>) => ({
  id: 1, project_id: 12, project_code: '1748', project_name: 'G6X UBV', kind: 'task', status: 'open',
  title: 'Gage R&R', text: null, department_name: 'APQP', responsible_name: 'Apurva Mhetre',
  additional_owners: [], due_date: '2026-11-20', late: false, days_late: 0, ...over })

describe('LopInMyDepartments', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks() })

  it('renders nothing for someone who manages no department', async () => {
    clientMocks.get.mockResolvedValue({ data: { departments: [], lines: [] } })
    const { container } = wrap()
    await new Promise((r) => setTimeout(r, 0))
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/lop/departments/mine')
    expect(container.textContent).toBe('')
  })

  it('a manager sees every open line of the team, late first, with owner and link', async () => {
    clientMocks.get.mockResolvedValue({ data: {
      departments: [{ id: 4, name: 'APQP' }, { id: 12, name: 'Quality' }],
      lines: [line({}), line({ id: 2, title: 'Gage quote', responsible_name: 'George Richardson',
        due_date: '2026-11-10', late: true, days_late: 8 })],
    } })
    wrap()
    const rows = await screen.findAllByTestId('lop-dept-row')
    expect(screen.getByText(/LOP in my departments \(2\)/)).toBeTruthy()
    expect(screen.getByTestId('lop-dept-late-count').textContent).toBe('1 late')
    expect(screen.getByText(/As manager of APQP, Quality/)).toBeTruthy()
    expect(rows[0].textContent).toContain('Gage quote')          // the late one first
    expect(rows[0].textContent).toContain('George Richardson')
    expect(rows[1].textContent).toContain('Apurva Mhetre')
    expect(screen.getAllByText('1748')[0].getAttribute('href')).toBe('/projects/12/lop')
    expect(rows[0].querySelector('button')).toBeNull()           // view only
  })

  it('a manager with no open line reads so', async () => {
    clientMocks.get.mockResolvedValue({ data: { departments: [{ id: 4, name: 'APQP' }], lines: [] } })
    wrap()
    expect(await screen.findByTestId('lop-in-my-departments-empty')).toBeTruthy()
  })
})
