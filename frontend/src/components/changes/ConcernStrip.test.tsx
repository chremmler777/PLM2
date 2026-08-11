import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ConcernStrip from './ConcernStrip'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

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
      .filter((b) => !(b as HTMLButtonElement).disabled)
    expect(links).toHaveLength(1)
    fireEvent.click(links[0])
    // Scoping withdrawal may explain itself, but does not have to.
    fireEvent.click(screen.getByTestId('concern-withdraw-confirm'))
    await waitFor(() => expect(changesApi.withdrawConcern).toHaveBeenCalledWith(7, 2, undefined))
  })

  it('greys the withdraw control for anyone but the author — admin included', async () => {
    authState.current = { userId: 5, isAdmin: true }
    vi.mocked(changesApi.listConcerns).mockResolvedValue([
      concern({ id: 1, raised_by: 9, raised_by_name: 'Rita RD' })] as never)
    wrap(<ConcernStrip changeId={7} editable />)
    await screen.findByText('Tool cannot hold tolerance')
    const btn = screen.getByTestId('concern-close-1') as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(btn.getAttribute('title')).toBe(t('concern.authorOnlyWithdraw'))
  })

  it('leaves the author their own withdraw', async () => {
    vi.mocked(changesApi.listConcerns).mockResolvedValue([
      concern({ id: 1, raised_by: 5, raised_by_name: 'Me' })] as never)
    wrap(<ConcernStrip changeId={7} editable />)
    await screen.findByText('Tool cannot hold tolerance')
    expect((screen.getByTestId('concern-close-1') as HTMLButtonElement).disabled).toBe(false)
  })

  it('lets Sales settle a team needs-info flag, but nothing else', async () => {
    vi.mocked(changesApi.listConcerns).mockResolvedValue([
      concern({ id: 1, kind: 'needs_info', department_id: null, raised_by: 9, note: 'ask the customer' }),
      concern({ id: 2, kind: 'reject_proposal', department_id: null, raised_by: 9, note: 'would reject' }),
    ] as never)
    wrap(<ConcernStrip changeId={7} editable canAnswer />)
    await screen.findByText('ask the customer')
    const solvable = screen.getByTestId('concern-close-1') as HTMLButtonElement
    expect(solvable.disabled).toBe(false)
    expect(solvable.textContent).toContain(t('concern.markSolved'))
    const other = screen.getByTestId('concern-close-2') as HTMLButtonElement
    expect(other.disabled).toBe(true)
    expect(other.getAttribute('title')).toBe(t('concern.authorOnlyWithdraw'))
  })

  it('tells a non-Sales viewer who may settle a team question', async () => {
    vi.mocked(changesApi.listConcerns).mockResolvedValue([
      concern({ id: 1, kind: 'needs_info', department_id: null, raised_by: 9 })] as never)
    wrap(<ConcernStrip changeId={7} editable />)
    await screen.findByText('Tool cannot hold tolerance')
    const btn = screen.getByTestId('concern-close-1') as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(btn.getAttribute('title')).toBe(t('concern.authorOrSales'))
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

  it('makes a non-Development member choose their department before flagging', async () => {
    wrap(<ConcernStrip changeId={7} editable scoped
      departments={depts} myDepartmentIds={[4]} />)
    fireEvent.click(await screen.findByRole('button', { name: /\+ Flag/ }))
    // Nothing is guessed: the placeholder stands until the user picks.
    const picker = screen.getByLabelText(/Department/) as HTMLSelectElement
    expect(picker.value).toBe('')
    expect(screen.getByText(t('concern.pickDepartment'))).toBeTruthy()
    fireEvent.change(screen.getByLabelText(/^Concern$/), { target: { value: 'gauge missing' } })
    expect((screen.getByRole('button', { name: /^Flag$/ }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(picker, { target: { value: '4' } })
    fireEvent.click(screen.getByRole('button', { name: /^Flag$/ }))
    await waitFor(() => expect(changesApi.raiseConcern)
      .toHaveBeenCalledWith(7, 'needs_info', 'gauge missing', 4))
  })

  it('preselects Development for a member of several departments', async () => {
    const many = [
      { id: 2, name: 'Quality', is_active: true },
      { id: 5, name: 'Manufacturing Engineer', is_active: true },
      { id: 6, name: 'Development', is_active: true },
    ]
    wrap(<ConcernStrip changeId={7} editable scoped
      departments={many} myDepartmentIds={[5, 6]} />)
    fireEvent.click(await screen.findByRole('button', { name: /\+ Flag/ }))
    // Development is the master role, whichever membership comes first — and
    // being preselected, no placeholder is offered.
    expect((screen.getByLabelText(/Department/) as HTMLSelectElement).value).toBe('6')
    expect(screen.queryByText(t('concern.pickDepartment'))).toBeNull()
  })

  it('offers an admin every department, still unpicked', async () => {
    authState.current = { userId: 5, isAdmin: true }
    wrap(<ConcernStrip changeId={7} editable scoped departments={depts} myDepartmentIds={[]} />)
    fireEvent.click(await screen.findByRole('button', { name: /\+ Flag/ }))
    const picker = screen.getByLabelText(/Department/) as HTMLSelectElement
    // Placeholder + the two active departments; nothing preselected for an
    // admin who is in none of them.
    expect(picker.value).toBe('')
    expect(picker.querySelectorAll('option')).toHaveLength(3)
    fireEvent.change(screen.getByLabelText(/^Concern$/), { target: { value: 'no capacity' } })
    expect((screen.getByRole('button', { name: /^Flag$/ }) as HTMLButtonElement).disabled).toBe(true)
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

describe('ConcernStrip attribution in scoping', () => {
  const depts = [
    { id: 2, name: 'Quality', is_active: true },
    { id: 6, name: 'Packaging Engineer', is_active: true },
    { id: 8, name: 'Logistics', is_active: false },
  ]

  beforeEach(() => {
    authState.current = { userId: 5, isAdmin: false }
    vi.mocked(changesApi.listConcerns).mockResolvedValue([])
    vi.mocked(changesApi.raiseConcern).mockClear()
    vi.mocked(changesApi.withdrawConcern).mockClear()
  })
  afterEach(cleanup)

  it('defaults to Team and sends no department', async () => {
    wrap(<ConcernStrip changeId={7} editable departments={depts} />)
    fireEvent.click(await screen.findByRole('button', { name: /\+ Flag/ }))
    const picker = screen.getByLabelText(/Department/) as HTMLSelectElement
    expect(picker.value).toBe('')
    // Team plus the two active departments — no membership restriction here.
    expect(picker.querySelectorAll('option')).toHaveLength(3)
    expect(screen.queryByText('Logistics')).toBeNull()
    fireEvent.change(screen.getByLabelText(/^Concern$/), { target: { value: 'whole team issue' } })
    fireEvent.click(screen.getByRole('button', { name: /^Flag$/ }))
    await waitFor(() => expect(changesApi.raiseConcern)
      .toHaveBeenCalledWith(7, 'needs_info', 'whole team issue', undefined))
  })

  it('attributes the flag to a department when one is picked', async () => {
    wrap(<ConcernStrip changeId={7} editable departments={depts} />)
    fireEvent.click(await screen.findByRole('button', { name: /\+ Flag/ }))
    fireEvent.change(screen.getByLabelText(/Department/), { target: { value: '6' } })
    fireEvent.change(screen.getByLabelText(/^Concern$/), { target: { value: 'box will not fit' } })
    fireEvent.click(screen.getByRole('button', { name: /^Flag$/ }))
    await waitFor(() => expect(changesApi.raiseConcern)
      .toHaveBeenCalledWith(7, 'needs_info', 'box will not fit', 6))
  })

  it('chips the attributed department and still frees a team flag to be dropped without a note', async () => {
    vi.mocked(changesApi.listConcerns).mockResolvedValue([
      concern({ id: 1, raised_by: 5, department_id: 6, note: 'box will not fit' }),
      concern({ id: 2, raised_by: 5, department_id: null, note: 'team-wide' }),
    ] as never)
    wrap(<ConcernStrip changeId={7} editable departments={depts} />)
    expect(await screen.findByText('Packaging Engineer')).toBeDefined()
    // The team flag needs no resolution note; the attributed one does.
    const withdrawLinks = screen.getAllByRole('button', { name: /withdraw/ })
    fireEvent.click(withdrawLinks[1])
    expect((screen.getByTestId('concern-withdraw-confirm') as HTMLButtonElement).disabled).toBe(false)
  })
})

describe('ConcernStrip refused flag', () => {
  beforeEach(() => {
    authState.current = { userId: 5, isAdmin: false }
    vi.mocked(changesApi.listConcerns).mockResolvedValue([])
    vi.mocked(changesApi.raiseConcern).mockReset()
  })
  afterEach(cleanup)

  it('shows the API refusal next to the form and keeps what was typed', async () => {
    vi.mocked(changesApi.raiseConcern).mockRejectedValue({
      response: { status: 400, data: { detail:
        'Only Project Management, the change lead, or an admin may manage scoping meetings' } },
    })
    wrap(<ConcernStrip changeId={7} editable />)
    fireEvent.click(await screen.findByRole('button', { name: /\+ Flag/ }))
    fireEvent.change(screen.getByLabelText(/^Concern$/), { target: { value: 'tool risk' } })
    fireEvent.click(screen.getByRole('button', { name: /^Flag$/ }))
    const alert = await screen.findByTestId('concern-error')
    expect(alert.textContent).toContain('Only Project Management')
    // The form stays open with the note — the failure must not eat the typing.
    expect((screen.getByLabelText(/^Concern$/) as HTMLInputElement).value).toBe('tool risk')
  })
})
