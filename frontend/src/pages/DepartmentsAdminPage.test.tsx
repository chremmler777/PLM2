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
  { id: 1, name: 'Sales', is_active: true, sort_order: 1, hub_role: 'plm2_Sales',
    head_id: 11, head_name: 'Jubei', head_email: 'jubei@ktx.test', head_active: true,
    manager_id: 10, manager_name: 'Karl', manager_email: 'karl@ktx.test', manager_active: true,
    warnings: [{ code: 'member_inactive', level: 'amber', text: 'Member Gone is inactive' }],
    members: [person(10, 'Karl'), person(11, 'Jubei'), person(12, 'Roman'), person(13, 'Gone', false)] },
  { id: 2, name: 'Quality', is_active: true, sort_order: 2, hub_role: null,
    head_id: null, head_name: null, head_email: null, head_active: null,
    manager_id: null, manager_name: null, manager_email: null, manager_active: null, members: [],
    warnings: [{ code: 'no_hub_role', level: 'red', text: 'No AdminPanel role mapped: nobody can become a member' },
      { code: 'no_members', level: 'red', text: 'No members' },
      { code: 'no_manager', level: 'amber', text: 'No manager defined' }] },
  { id: 3, name: 'Scheduling', is_active: false, sort_order: 9, hub_role: null,
    head_id: null, head_name: null, head_email: null, head_active: null,
    manager_id: null, manager_name: null, manager_email: null, manager_active: null, members: [], warnings: [] },
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
    expect(screen.queryByTestId('dept-head-1')).toBeNull()
    expect(screen.queryByTestId('dept-admin-1')).toBeNull()
    expect(screen.queryByTestId('dept-retire-1')).toBeNull()
    expect(screen.queryByRole('combobox')).toBeNull()
    // the head banner reads the same for everyone
    expect(screen.getByTestId('dept-head-banner-1').textContent).toContain('Jubei')
    const warn = screen.getByTestId('dept-warnings-2')
    expect([...warn.querySelectorAll('li')].map((l) => l.dataset.code)).toEqual(['no_hub_role', 'no_members', 'no_manager'])
  })

  it('the manager is the yellow card headline, the head the second line: name, mailto email, label; no head named is calm, not a warning', async () => {
    wrap()
    const banner = await screen.findByTestId('dept-head-banner-1')
    expect(within(banner).getByText('Jubei')).toBeTruthy()
    expect(within(banner).getByText('Head')).toBeTruthy()
    expect(within(banner).getByText('jubei@ktx.test').getAttribute('href')).toBe('mailto:jubei@ktx.test')
    // the manager (yellow) sits above the head line in the card
    const card = screen.getByTestId('dept-card-1')
    const mgr = within(card).getByTestId('dept-manager-ro-1')
    expect(mgr.compareDocumentPosition(banner) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(mgr.className).toContain('yellow')
    expect(mgr.textContent).toContain('Karl')
    expect(within(mgr).getByText('karl@ktx.test').getAttribute('href')).toBe('mailto:karl@ktx.test')
    // badges in the member list
    expect(within(screen.getByTestId('dept-member-1-11')).getByText('Head')).toBeTruthy()
    expect(within(screen.getByTestId('dept-member-1-10')).getByText('Manager')).toBeTruthy()
    expect(screen.getByTestId('dept-count-1').textContent).toBe('4 members')
    expect(screen.getByTestId('dept-head-none-2').textContent).toBe('No head named')
    expect(screen.queryByTestId('dept-head-banner-2')).toBeNull()
  })

  it('warnings: amber chips, red only for the serious ones; the card border turns red', async () => {
    wrap()
    const amber = await screen.findByTestId('dept-warnings-1')
    expect([...amber.querySelectorAll('li')].map((l) => l.dataset.level)).toEqual(['amber'])
    expect(screen.getByTestId('dept-card-1').className).not.toContain('border-red')
    const red = screen.getByTestId('dept-warnings-2')
    expect([...red.querySelectorAll('li')].map((l) => l.dataset.level)).toEqual(['red', 'red', 'amber'])
    expect(screen.getByTestId('dept-card-2').className).toContain('border-red')
  })

  it('a head who left is shown flagged until replaced', async () => {
    const left = { ...DEPTS[0], head_id: 99, head_name: 'Former', head_email: 'former@ktx.test',
      warnings: [{ code: 'head_not_member', level: 'red', text: 'Head Former is no longer a member' }] }
    clientMocks.get.mockImplementation(async () => ({ data: [left] }))
    wrap()
    expect((await screen.findByTestId('dept-head-banner-1')).textContent).toContain('no longer a member')
    const sel = screen.getByTestId('dept-head-1') as HTMLSelectElement
    expect(sel.value).toBe('99')
    expect([...sel.options].map((o) => o.text)).toContain('Former (no longer a member)')
  })

  it('the head select offers only active members; set and clear call the head API', async () => {
    wrap()
    const sel = await screen.findByTestId('dept-head-1') as HTMLSelectElement
    expect(sel.value).toBe('11')
    expect([...sel.options].map((o) => o.text)).toEqual(['No head named', 'Karl', 'Jubei', 'Roman'])
    fireEvent.change(sel, { target: { value: '12' } })
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/departments/1/head', { user_id: 12 }))
    fireEvent.click(screen.getByTestId('dept-head-clear-1'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/departments/1/head', { user_id: null }))
  })

  it('shows an error with retry when the overview fails, and an empty state', async () => {
    clientMocks.get.mockImplementationOnce(async () => { throw new Error('boom') })
    wrap()
    expect((await screen.findByTestId('dept-error')).textContent).toContain('Could not load')
    clientMocks.get.mockImplementation(async () => ({ data: [DEPTS[2]] }))
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByTestId('dept-empty')).toBeTruthy()
  })

  it('members are read-only rows with name and mailto email; no add or remove', async () => {
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
