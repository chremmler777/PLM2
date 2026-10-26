import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DepartmentsAdminPage from './DepartmentsAdminPage'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const auth = vi.hoisted(() => ({ current: { role: 'admin' as string | null } }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth.current }))

const DEPTS = [
  { id: 1, name: 'Process Engineer', is_active: true, sort_order: 1, manager_id: 10,
    manager_name: 'Christoph D', manager_active: true,
    members: [{ id: 11, name: 'Holmes', username: 'holmes', email: 'holmes@ktx.test', is_active: true }] },
  { id: 2, name: 'Tool Engineer', is_active: true, sort_order: 2, manager_id: null,
    manager_name: null, manager_active: null, members: [] },
  { id: 3, name: 'Old Role', is_active: false, sort_order: 9, manager_id: null,
    manager_name: null, manager_active: null, members: [] },
]
const USERS = [
  { id: 10, username: 'cd', email: 'cd@ktx.test', full_name: 'Christoph D', is_active: true },
  { id: 11, username: 'holmes', email: 'holmes@ktx.test', full_name: 'Holmes', is_active: true },
  { id: 12, username: 'payne', email: 'payne@ktx.test', full_name: 'Payne', is_active: true },
  { id: 13, username: 'gone', email: 'gone@ktx.test', full_name: 'Gone', is_active: false },
]

const wrap = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <DepartmentsAdminPage />
  </QueryClientProvider>)

describe('DepartmentsAdminPage', () => {
  beforeEach(() => {
    auth.current = { role: 'admin' }
    clientMocks.get.mockImplementation(async (url: string) =>
      url === '/v1/departments/admin' ? { data: DEPTS } : url === '/v1/users' ? { data: USERS } : { data: [] })
    clientMocks.put.mockImplementation(async (url: string) => ({ data: { ...DEPTS[0], id: Number(url.split('/')[3]) } }))
    clientMocks.post.mockResolvedValue({ data: { ...DEPTS[2], is_active: true } })
  })
  afterEach(() => { cleanup(); vi.clearAllMocks() })

  it('shows a no-access note to a non-admin and calls nothing', () => {
    auth.current = { role: 'engineer' }
    wrap()
    expect(screen.getByTestId('departments-no-access')).toBeTruthy()
    expect(clientMocks.get).not.toHaveBeenCalled()
  })

  it('one card per active department with its manager; only active users to pick', async () => {
    wrap()
    const sel = await screen.findByTestId('dept-manager-1') as HTMLSelectElement
    expect(sel.value).toBe('10')
    expect([...sel.options].map((o) => o.text)).toEqual(['No manager', 'Christoph D', 'Holmes', 'Payne'])
    expect(screen.getByTestId('dept-card-2')).toBeTruthy()
    expect(screen.queryByTestId('dept-card-3')).toBeNull()
  })

  it('sets and clears a manager', async () => {
    wrap()
    fireEvent.change(await screen.findByTestId('dept-manager-2'), { target: { value: '12' } })
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/departments/2/manager', { user_id: 12 }))
    fireEvent.click(screen.getByTestId('dept-manager-clear-1'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/departments/1/manager', { user_id: null }))
  })

  it('members show name and mailto email; remove and add replace the list', async () => {
    wrap()
    const chip = await screen.findByTestId('dept-member-1-11')
    expect(within(chip).getByText('holmes@ktx.test').getAttribute('href')).toBe('mailto:holmes@ktx.test')
    fireEvent.click(within(chip).getByRole('button', { name: 'Remove Holmes from Process Engineer' }))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/departments/1/members', { user_ids: [] }))
    fireEvent.change(screen.getByTestId('dept-add-1'), { target: { value: 'pay' } })
    fireEvent.click(await screen.findByTestId('dept-add-option-1-12'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/departments/1/members', { user_ids: [11, 12] }))
  })

  it('the add picker offers no inactive user and no current member', async () => {
    wrap()
    fireEvent.change(await screen.findByTestId('dept-add-1'), { target: { value: 'o' } })
    expect(screen.queryByTestId('dept-add-option-1-13')).toBeNull()   // Gone, inactive
    expect(screen.queryByTestId('dept-add-option-1-11')).toBeNull()   // Holmes, member
  })

  it('retired departments collapsed at the bottom, activated by the toggle', async () => {
    wrap()
    const btn = await screen.findByRole('button', { name: /Retired departments \(1\)/ })
    expect(screen.queryByTestId('retired-3')).toBeNull()
    fireEvent.click(btn)
    fireEvent.click(within(screen.getByTestId('retired-3')).getByRole('button', { name: 'Activate' }))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/departments/3/activate'))
  })
})
