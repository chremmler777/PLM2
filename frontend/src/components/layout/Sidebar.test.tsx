import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Sidebar from './Sidebar'
import { changesApi } from '../../api/changes'

const clientMocks = vi.hoisted(() => ({ get: vi.fn() }))
// The badge counts the rows My Tasks lists: workflow tasks (folded by step)
// plus change tasks. Three distinct steps here.
const wfTasks = (n: number) => Array.from({ length: n }, (_, i) => ({
  task_id: i + 1, instance_id: 1, stage_order: 1, step_name: `step ${i}`,
  department_name: 'D', rasic_letter: 'R', overdue: false, due_date: null, mine: false,
}))
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
      if (url === '/v1/workflow-instances/my-tasks') return Promise.resolve({ data: wfTasks(3) })
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
      if (url === '/v1/workflow-instances/my-tasks') return Promise.resolve({ data: wfTasks(3) })
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
    expect(badge.closest('a')?.textContent).toContain('My Tasks')
  })

  it('shows no badge when nothing is waiting', async () => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/workflow-instances/my-tasks') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })
    vi.mocked(changesApi.myTasks).mockResolvedValue([] as never)
    wrap(<Sidebar />)
    const myTasks = await screen.findByRole('link', { name: /My Tasks/ })
    expect(myTasks.textContent?.replace(/[^0-9]/g, '')).toBe('')
  })

  it('counts an R and an A row on the same step once, like the page', async () => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/workflow-instances/my-tasks') return Promise.resolve({ data: [
        ...wfTasks(1), { ...wfTasks(1)[0], task_id: 9, rasic_letter: 'A' }] })
      return Promise.resolve({ data: [] })
    })
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      { kind: 'assessment', change_id: 1, department_id: 2 },
      { kind: 'assessment', change_id: 1, department_id: 2 },
    ] as never)
    wrap(<Sidebar />)
    const badge = await screen.findByText('2')
    expect(badge.closest('a')?.textContent).toContain('My Tasks')
  })
})

describe('Sidebar rail on project pages', () => {
  const RAIL_KEY = 'plm2.sidebar.projectRail'
  const wrapAt = (path: string) => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[path]}><Sidebar /></MemoryRouter>
      </QueryClientProvider>
    )
  }
  const spies: { mockRestore(): void }[] = []

  beforeEach(() => {
    localStorage.clear()
    authMock.current = { role: 'engineer', username: 'tester', logout: vi.fn() }
    clientMocks.get.mockImplementation(() => Promise.resolve({ data: [] }))
  })
  afterEach(() => {
    cleanup()
    while (spies.length) spies.pop()!.mockRestore()
  })

  it('starts as a collapsed 48 px rail with hover labels on a project page', async () => {
    wrapAt('/projects/2')
    const aside = await screen.findByTestId('sidebar')
    expect(aside.getAttribute('data-collapsed')).toBe('true')
    expect(aside.className).toContain('w-12')
    expect(screen.queryByText('Dashboard')).toBeNull()
    expect(screen.getByTitle('Dashboard')).toBeTruthy()
  })

  it('stays expanded on other pages', async () => {
    wrapAt('/dashboard')
    expect((await screen.findByTestId('sidebar')).getAttribute('data-collapsed')).toBe('false')
    expect(screen.getByText('Dashboard')).toBeTruthy()
  })

  it('remembers an expanded rail for the next project page', async () => {
    wrapAt('/projects/2')
    fireEvent.click(await screen.findByTitle('Expand'))
    expect(screen.getByText('Dashboard')).toBeTruthy()
    expect(localStorage.getItem(RAIL_KEY)).toBe('expanded')
    cleanup()
    wrapAt('/projects/7')
    expect((await screen.findByTestId('sidebar')).getAttribute('data-collapsed')).toBe('false')
  })

  it('does not store a toggle made outside project pages', async () => {
    wrapAt('/dashboard')
    fireEvent.click(await screen.findByTitle('Collapse'))
    expect(localStorage.getItem(RAIL_KEY)).toBeNull()
  })

  it('falls back to the collapsed rail and keeps toggling when storage throws', async () => {
    spies.push(vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') }))
    spies.push(vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied') }))
    wrapAt('/projects/2')
    expect((await screen.findByTestId('sidebar')).getAttribute('data-collapsed')).toBe('true')
    fireEvent.click(screen.getByTitle('Expand'))
    expect(screen.getByTestId('sidebar').getAttribute('data-collapsed')).toBe('false')
  })

  it('treats a garbage stored value as the default', async () => {
    localStorage.setItem(RAIL_KEY, '{oops')
    wrapAt('/projects/2')
    expect((await screen.findByTestId('sidebar')).getAttribute('data-collapsed')).toBe('true')
  })
})

describe('Sidebar links', () => {
  afterEach(cleanup)

  it('navigates with real links and keeps the section lit on a detail page', async () => {
    authMock.current = { role: 'viewer', username: 'tester', logout: vi.fn() }
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/changes/21']}><Sidebar /></MemoryRouter>
      </QueryClientProvider>,
    )
    const changes = await screen.findByRole('link', { name: 'Changes' })
    expect(changes.getAttribute('href')).toBe('/changes')
    expect(changes.getAttribute('aria-current')).toBe('page')
    expect(screen.getByRole('link', { name: 'Dashboard' }).getAttribute('aria-current')).toBeNull()
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeTruthy()
  })
})
