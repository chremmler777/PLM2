import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import MyTasksPage from './MyTasksPage'

// MyTasksPage fetches workflow tasks via useMyTasks -> workflowApi.getMyTasks ->
// client.get('/v1/workflow-instances/my-tasks'); departments + SEP + lessons all
// go through the same axios client (default export). changesApi is a separate module.
const clientMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('../api/changes', () => ({
  changesApi: { myTasks: vi.fn().mockResolvedValue([]), acceptAssessment: vi.fn() },
}))

const myTask = (over: Record<string, unknown>) => ({
  task_id: 1, instance_id: 9, status: 'active', is_actionable: true,
  rasic_letter: 'R', department_name: 'IE', step_name: 'do it',
  stage_order: 1, stage_name: 'S1', part_id: 4, part_number: 'P-1',
  part_name: 'Housing', project_id: 2, revision_id: 7, revision_name: 'ECR1.1',
  instance_started_at: '2026-07-01T00:00:00',
  owner_id: null, owner_name: null, accepted_at: null,
  due_date: '2026-06-30T00:00:00', overdue: true, mine: false,
  ...over,
})

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>)
}

describe('MyTasksPage ownership', () => {
  beforeEach(() => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url.includes('/workflow-instances/my-tasks'))
        return Promise.resolve({ data: [
          myTask({ task_id: 1, mine: true, owner_id: 5, owner_name: 'Eva Eng' }),
          myTask({ task_id: 2, step_name: 'unclaimed step', overdue: false,
                   due_date: '2026-07-30T00:00:00' }),
        ] })
      return Promise.resolve({ data: [] })
    })
    clientMocks.post.mockResolvedValue({ data: {} })
  })
  afterEach(cleanup)

  it('shows owner, overdue flag, and Accept on unclaimed rows', async () => {
    wrap(<MyTasksPage />)
    expect(await screen.findByText('Eva Eng')).toBeDefined()
    expect(screen.getByText(/overdue/)).toBeDefined()
    const accept = screen.getByRole('button', { name: /Accept/ })
    fireEvent.click(accept)
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith(
      '/v1/workflow-instances/9/tasks/2/accept'))
  })
})
