import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ConcernStrip from './ConcernStrip'
import { changesApi } from '../../api/changes'

vi.mock('../../api/changes', () => ({
  changesApi: {
    listConcerns: vi.fn(),
    raiseConcern: vi.fn().mockResolvedValue({}),
    withdrawConcern: vi.fn().mockResolvedValue({}),
  },
}))
const authState = vi.hoisted(() => ({ current: { userId: 5, isAdmin: false } }))
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => authState.current }))

const concern = (over = {}) => ({
  id: 1, change_id: 7, kind: 'reject_proposal', note: 'Tool cannot hold tolerance',
  raised_by: 9, raised_by_name: 'Rita RD', raised_at: '2026-08-06T10:00:00',
  withdrawn_at: null, resolved_by_meeting_id: null, is_open: true, ...over,
})

const wrap = (ui: React.ReactElement) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>)

describe('ConcernStrip', () => {
  beforeEach(() => {
    authState.current = { userId: 5, isAdmin: false }
    vi.mocked(changesApi.listConcerns).mockResolvedValue([])
    vi.mocked(changesApi.raiseConcern).mockClear()
    vi.mocked(changesApi.withdrawConcern).mockClear()
  })
  afterEach(cleanup)

  it('names who objects and why, and says it blocks proceed', async () => {
    vi.mocked(changesApi.listConcerns).mockResolvedValue([concern()] as never)
    wrap(<ConcernStrip changeId={7} editable />)
    expect(await screen.findByText('Tool cannot hold tolerance')).toBeDefined()
    expect(screen.getByText(/Rita RD/)).toBeDefined()
    expect(screen.getByText(/1 open — blocks proceed/)).toBeDefined()
  })

  it('offers withdraw only on your own flag', async () => {
    vi.mocked(changesApi.listConcerns).mockResolvedValue([
      concern({ id: 1, raised_by: 9, raised_by_name: 'Rita RD' }),
      concern({ id: 2, raised_by: 5, raised_by_name: 'Me', note: 'Mine' }),
    ] as never)
    wrap(<ConcernStrip changeId={7} editable />)
    await screen.findByText('Mine')
    // One withdraw link — for the flag raised by userId 5.
    const links = screen.getAllByRole('button', { name: /withdraw/ })
    expect(links).toHaveLength(1)
    fireEvent.click(links[0])
    // Scoping withdrawal may explain itself, but does not have to.
    fireEvent.click(screen.getByTestId('concern-withdraw-confirm'))
    await waitFor(() => expect(changesApi.withdrawConcern).toHaveBeenCalledWith(7, 2, undefined))
  })

  it('gives an admin no way to clear someone else\'s flag', async () => {
    authState.current = { userId: 5, isAdmin: true }
    vi.mocked(changesApi.listConcerns).mockResolvedValue([
      concern({ raised_by: 9, raised_by_name: 'Rita RD' })] as never)
    wrap(<ConcernStrip changeId={7} editable />)
    await screen.findByText('Tool cannot hold tolerance')
    expect(screen.queryByRole('button', { name: /withdraw/ })).toBeNull()
  })

  it('raises a flag with its kind and note', async () => {
    wrap(<ConcernStrip changeId={7} editable />)
    fireEvent.click(await screen.findByRole('button', { name: /\+ Flag/ }))
    fireEvent.change(screen.getByLabelText(/Concern kind/), { target: { value: 'reject_proposal' } })
    fireEvent.change(screen.getByLabelText(/^Concern$/), { target: { value: '  no capacity  ' } })
    fireEvent.click(screen.getByRole('button', { name: /^Flag$/ }))
    await waitFor(() => expect(changesApi.raiseConcern)
      .toHaveBeenCalledWith(7, 'reject_proposal', 'no capacity', undefined))
  })

  it('shows settled flags struck through and un-withdrawable', async () => {
    vi.mocked(changesApi.listConcerns).mockResolvedValue([
      concern({ raised_by: 5, is_open: false, resolved_by_meeting_id: 3 })] as never)
    wrap(<ConcernStrip changeId={7} editable />)
    await screen.findByText('Tool cannot hold tolerance')
    expect(screen.getByText(/answered by the decision/)).toBeDefined()
    expect(screen.queryByRole('button', { name: /withdraw/ })).toBeNull()
    expect(screen.queryByText(/blocks proceed/)).toBeNull()
  })

  it('hides the raise control once scoping is closed', async () => {
    wrap(<ConcernStrip changeId={7} editable={false} />)
    await waitFor(() => expect(changesApi.listConcerns).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: /\+ Flag/ })).toBeNull()
  })
})

describe('ConcernStrip in the assessment phase', () => {
  const depts = [{ id: 2, name: 'Quality' }, { id: 4, name: 'Tooling' }]

  beforeEach(() => {
    authState.current = { userId: 5, isAdmin: false }
    vi.mocked(changesApi.listConcerns).mockResolvedValue([])
    vi.mocked(changesApi.raiseConcern).mockClear()
    vi.mocked(changesApi.withdrawConcern).mockClear()
  })
  afterEach(cleanup)

  it('raises the flag for the raiser own department', async () => {
    wrap(<ConcernStrip changeId={7} editable scoped
      departments={depts} myDepartmentIds={[4]} />)
    fireEvent.click(await screen.findByRole('button', { name: /\+ Flag/ }))
    // Only the member's own department is offered, and it is preselected.
    const picker = screen.getByLabelText(/Department/) as HTMLSelectElement
    expect(picker.value).toBe('4')
    expect(picker.querySelectorAll('option')).toHaveLength(1)
    fireEvent.change(screen.getByLabelText(/^Concern$/), { target: { value: 'gauge missing' } })
    fireEvent.click(screen.getByRole('button', { name: /^Flag$/ }))
    await waitFor(() => expect(changesApi.raiseConcern)
      .toHaveBeenCalledWith(7, 'needs_info', 'gauge missing', 4))
  })

  it('offers an admin every department', async () => {
    authState.current = { userId: 5, isAdmin: true }
    wrap(<ConcernStrip changeId={7} editable scoped departments={depts} myDepartmentIds={[]} />)
    fireEvent.click(await screen.findByRole('button', { name: /\+ Flag/ }))
    expect((screen.getByLabelText(/Department/) as HTMLSelectElement)
      .querySelectorAll('option')).toHaveLength(2)
  })

  it('will not drop a department flag without saying how it was addressed', async () => {
    vi.mocked(changesApi.listConcerns).mockResolvedValue([
      concern({ id: 3, raised_by: 5, department_id: 4, note: 'gauge missing' })] as never)
    wrap(<ConcernStrip changeId={7} editable scoped departments={depts} myDepartmentIds={[4]} />)
    fireEvent.click(await screen.findByRole('button', { name: /withdraw/ }))
    const confirm = screen.getByTestId('concern-withdraw-confirm') as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('concern-withdraw-note'),
      { target: { value: 'gauge ordered, lead time 3w' } })
    fireEvent.click(screen.getByTestId('concern-withdraw-confirm'))
    await waitFor(() => expect(changesApi.withdrawConcern)
      .toHaveBeenCalledWith(7, 3, 'gauge ordered, lead time 3w'))
  })

  it('shows the department and, once settled, how it was addressed', async () => {
    vi.mocked(changesApi.listConcerns).mockResolvedValue([
      concern({ id: 3, raised_by: 5, department_id: 4, is_open: false,
        withdrawn_at: '2026-08-07T09:00:00', resolution_note: 'gauge ordered' })] as never)
    wrap(<ConcernStrip changeId={7} editable scoped departments={depts} myDepartmentIds={[4]} />)
    expect(await screen.findByText('Tooling')).toBeDefined()
    expect(screen.getByText(/gauge ordered/)).toBeDefined()
  })
})
