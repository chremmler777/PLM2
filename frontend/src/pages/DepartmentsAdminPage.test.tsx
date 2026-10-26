import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DepartmentsAdminPage from './DepartmentsAdminPage'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const auth = vi.hoisted(() => ({ current: { role: 'admin' as string | null } }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth.current }))

const person = (id: number, name: string, is_active = true) =>
  ({ id, name, username: name.toLowerCase(), email: `${name.toLowerCase()}@ktx.test`, is_active })
const DEPTS = [
  { id: 1, name: 'Sales', is_active: true, sort_order: 1, hub_role: 'plm2_Sales', manager_id: 10,
    manager_name: 'Karl', manager_active: true, warnings: [],
    members: [person(10, 'Karl'), person(11, 'Jubei'), person(12, 'Roman'), person(13, 'Gone', false)] },
  { id: 2, name: 'Quality', is_active: true, sort_order: 2, hub_role: null, manager_id: null,
    manager_name: null, manager_active: null, members: [],
    warnings: [{ code: 'no_hub_role', level: 'red', text: 'No AdminPanel role mapped: nobody can become a member' },
      { code: 'no_members', level: 'red', text: 'No members' },
      { code: 'no_manager', level: 'amber', text: 'No manager defined' }] },
  { id: 3, name: 'Scheduling', is_active: false, sort_order: 9, hub_role: null, manager_id: null,
    manager_name: null, manager_active: null, members: [], warnings: [] },
]

const wrap = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <DepartmentsAdminPage />
  </QueryClientProvider>)

describe('DepartmentsAdminPage', () => {
  beforeEach(() => {
    auth.current = { role: 'admin' }
    clientMocks.get.mockImplementation(async (url: string) =>
      url === '/v1/departments/overview' ? { data: DEPTS } : { data: [] })
    clientMocks.put.mockImplementation(async () => ({ data: DEPTS[0] }))
    clientMocks.post.mockImplementation(async (url: string) =>
      ({ data: url.includes('/3/') ? { ...DEPTS[2], is_active: true } : { ...DEPTS[1], is_active: false } }))
  })
  afterEach(() => { cleanup(); vi.clearAllMocks() })

  it('everyone reads it: members, manager and warnings, without edit controls', async () => {
    auth.current = { role: 'engineer' }
    wrap()
    expect((await screen.findByTestId('dept-manager-ro-1')).textContent).toContain('Karl')
    expect(screen.queryByTestId('dept-manager-1')).toBeNull()
    expect(screen.queryByTestId('dept-retire-1')).toBeNull()
    const warn = screen.getByTestId('dept-warnings-2')
    expect([...warn.querySelectorAll('li')].map((l) => l.dataset.code)).toEqual(['no_hub_role', 'no_members', 'no_manager'])
  })

  it('members are read-only chips with name and mailto email; no add or remove', async () => {
    wrap()
    const chip = await screen.findByTestId('dept-member-1-11')
    expect(within(chip).getByText('jubei@ktx.test').getAttribute('href')).toBe('mailto:jubei@ktx.test')
    expect(within(chip).queryByRole('button')).toBeNull()
    expect(screen.queryByPlaceholderText('Add person')).toBeNull()
  })

  it('the manager select offers only the active members of the department', async () => {
    wrap()
    const sel = await screen.findByTestId('dept-manager-1') as HTMLSelectElement
    expect(sel.value).toBe('10')
    expect([...sel.options].map((o) => o.text)).toEqual(['No manager', 'Karl', 'Jubei', 'Roman'])
    fireEvent.change(sel, { target: { value: '12' } })
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/departments/1/manager', { user_id: 12 }))
    fireEvent.click(screen.getByTestId('dept-manager-clear-1'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/departments/1/manager', { user_id: null }))
  })

  it('admin retires a department after confirming; retired ones are collapsed with Activate', async () => {
    wrap()
    fireEvent.click(await screen.findByTestId('dept-retire-2'))
    fireEvent.click(within(await screen.findByTestId('dept-retire-confirm')).getByRole('button', { name: 'Retire' }))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/departments/2/deactivate'))
    const btn = screen.getByRole('button', { name: /Retired departments/ })
    expect(screen.queryByTestId('retired-3')).toBeNull()
    fireEvent.click(btn)
    fireEvent.click(within(screen.getByTestId('retired-3')).getByRole('button', { name: 'Activate' }))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/departments/3/activate'))
  })
})
