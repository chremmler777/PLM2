import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Sidebar from './Sidebar'
import { changesApi } from '../../api/changes'

const clientMocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('../../api/changes', () => ({ changesApi: { myTasks: vi.fn().mockResolvedValue([]) } }))

const authMock = vi.hoisted(() => ({ current: { role: 'admin' as string | null, username: 'tester', logout: vi.fn() } }))
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => authMock.current }))
vi.mock('./ActsAsSwitch', () => ({ default: () => <div>mock-acts-as-switch</div> }))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('Sidebar nav groups', () => {
  beforeEach(() => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/workflow-instances/open-task-count') return Promise.resolve({ data: { count: 3 } })
      if (url === '/v1/notifications/unread-count') return Promise.resolve({ data: { count: 0 } })
      if (url === '/v1/notifications') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('shows SETUP heading plus Workflows for admin, no Users', async () => {
    authMock.current = { role: 'admin', username: 'tester', logout: vi.fn() }
    wrap(<Sidebar />)
    expect(await screen.findByText('SETUP')).toBeDefined()
    expect(screen.getByText('Workflows')).toBeDefined()
    expect(screen.queryByText('Users')).toBeNull()
  })

  it('shows SETUP and Workflows but not Users for engineer', async () => {
    authMock.current = { role: 'engineer', username: 'tester', logout: vi.fn() }
    wrap(<Sidebar />)
    expect(await screen.findByText('SETUP')).toBeDefined()
    expect(screen.getByText('Workflows')).toBeDefined()
    expect(screen.queryByText('Users')).toBeNull()
  })

  it('hides SETUP heading and Workflows for viewer role', async () => {
    authMock.current = { role: 'viewer', username: 'tester', logout: vi.fn() }
    wrap(<Sidebar />)
    await screen.findByText('Dashboard')
    expect(screen.queryByText('SETUP')).toBeNull()
    expect(screen.queryByText('Workflows')).toBeNull()
    expect(screen.queryByText('Users')).toBeNull()
  })

  it('renders My Tasks badge with open task count', async () => {
    authMock.current = { role: 'admin', username: 'tester', logout: vi.fn() }
    wrap(<Sidebar />)
    expect(await screen.findByText('3')).toBeDefined()
  })
})

describe('Sidebar acting-as control', () => {
  afterEach(cleanup)

  it('offers the act-as switch to an admin only', async () => {
    authMock.current = { role: 'admin', username: 'tester', logout: vi.fn() }
    wrap(<Sidebar />)
    expect(await screen.findByText('mock-acts-as-switch')).toBeDefined()
    cleanup()
    authMock.current = { role: 'engineer', username: 'tester', logout: vi.fn() }
    wrap(<Sidebar />)
    expect(screen.queryByText('mock-acts-as-switch')).toBeNull()
  })
})

describe('Sidebar My Tasks counter', () => {
  beforeEach(() => {
    authMock.current = { role: 'engineer', username: 'tester', logout: vi.fn() }
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/workflow-instances/open-task-count') return Promise.resolve({ data: { count: 3 } })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('sums workflow tasks and change tasks into one badge', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      { kind: 'kickoff' }, { kind: 'assessment' },
    ] as never)
    wrap(<Sidebar />)
    const badge = await screen.findByText('5')
    expect(badge.closest('button')?.textContent).toContain('My Tasks')
  })

  it('shows no badge when nothing is waiting', async () => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/workflow-instances/open-task-count') return Promise.resolve({ data: { count: 0 } })
      return Promise.resolve({ data: [] })
    })
    vi.mocked(changesApi.myTasks).mockResolvedValue([] as never)
    wrap(<Sidebar />)
    const myTasks = await screen.findByRole('button', { name: /My Tasks/ })
    expect(myTasks.textContent?.replace(/[^0-9]/g, '')).toBe('')
  })
})
