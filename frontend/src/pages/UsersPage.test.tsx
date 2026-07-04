import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import UsersPage from './UsersPage'

// UsersPage talks to the API entirely through the default axios client, plus
// useDepartments (workflowApi.getDepartments) for the department picker.
const clientMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
}))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ userId: 1 }) }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const departments = [
  { id: 10, name: 'R&D', flow_type: 'action', is_active: true, sort_order: 1 },
  { id: 11, name: 'Quality', flow_type: 'action', is_active: true, sort_order: 2 },
]
vi.mock('../hooks/queries/useWorkflows', () => ({
  useDepartments: () => ({ data: departments }),
}))

const user = { id: 2, email: 'eng@test.io', username: 'eng', full_name: 'Eng',
  role: 'engineer', is_active: true }

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('UsersPage departments', () => {
  beforeEach(() => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/users') return Promise.resolve({ data: [user] })
      if (url === '/v1/users/2/departments')
        return Promise.resolve({ data: [{ id: 10, name: 'R&D' }] })
      return Promise.resolve({ data: [] })
    })
    clientMocks.put.mockResolvedValue({ data: [] })
  })
  afterEach(cleanup)

  it('renders membership chips for a user', async () => {
    wrap(<UsersPage />)
    expect(await screen.findByText('R&D')).toBeDefined()
  })

  it('opens the departments modal and saves via PUT', async () => {
    wrap(<UsersPage />)
    const button = await screen.findByRole('button', { name: 'Departments' })
    fireEvent.click(button)

    // Modal lists all departments as checkboxes; R&D pre-checked from memberships.
    const qualityCheckbox = await screen.findByRole('checkbox', { name: 'Quality' })
    fireEvent.click(qualityCheckbox)

    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => {
      expect(clientMocks.put).toHaveBeenCalledWith(
        '/v1/users/2/departments',
        { department_ids: expect.arrayContaining([10, 11]) },
      )
    })
  })
})
