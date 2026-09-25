/**
 * Review 2dd5 fixes on the validation issue UI: reachability after the loop
 * back (F1), quoting the fix (F2), the escalation pulse (F5) and the polish
 * round (F6: de-escalate, edit, file delete, 409 detail, status chip, new
 * timing date, fixing info).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { toast } from 'sonner'
import type { IssueOut } from '../../../types/validationIssue'
import { validationIssuesApi } from '../../../api/validationIssues'
import { changesApi } from '../../../api/changes'
import IssueCard from './IssueCard'
import IssuesPanel from './IssuesPanel'
import EscalationBadge from './EscalationBadge'
import { customerDecisionBlocked } from './CustomerDecisionForm'
import { mayDeleteIssueFile } from './IssueDropzone'
import { issuePatch } from './IssueEditForm'
import { issueSteps, needsAck, statusChipLabel } from './issueModel'
import { errDetail } from './useIssueMutation'
import CockpitSummary from '../CockpitSummary'
import TransitionConfirmDialog from '../TransitionConfirmDialog'
import { issueTabFor, releaseOpenByIssues, isIssueActionKind } from '../../../lib/issueTabs'
import { issueWaits } from '../../../lib/waitStates'
import type { ChangeDetail } from '../../../types/change'

vi.mock('../../../api/validationIssues', () => ({
  validationIssuesKey: (id: number) => ['change', id, 'validation-issues'],
  validationIssuesApi: {
    list: vi.fn(), create: vi.fn(), update: vi.fn(), contain: vi.fn(), rootCause: vi.fn(),
    route: vi.fn(), customer: vi.fn(), cost: vi.fn(), addAction: vi.fn(), actionDone: vi.fn(),
    close: vi.fn(), escalate: vi.fn(), deescalate: vi.fn(), fixQuoted: vi.fn(), acknowledge: vi.fn(),
  },
}))
vi.mock('../../../api/changes', () => ({
  changesApi: { uploadAttachment: vi.fn(), deleteAttachment: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const departments = [{ id: 2, name: 'Development' }, { id: 4, name: 'Tool Shop' }]

const issue = (over: Partial<IssueOut> = {}): IssueOut => ({
  id: 11, change_id: 7, number: 2, title: 'Tool cannot run', category: 'tool', severity: 2,
  department_id: 4, department_name: 'Tool Shop', description: 'Slide jams at 40 strokes',
  status: 'open', created_by: 5, created_by_name: 'Rita Raiser', created_at: '2026-09-24T08:00:00',
  actions: [], attachments: [], escalation_level: 1, escalations: [], next_acts: [], extra_acts: [], ...over,
})

const qcWrap = (ui: React.ReactElement) => render(
  <MemoryRouter>
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>
  </MemoryRouter>)

const card = (i: IssueOut, viewer = {}, extra: Record<string, unknown> = {}) => qcWrap(
  <IssueCard changeId={7} changeStatus="in_validation" issue={i} viewer={viewer} departments={departments} {...extra} />)

afterEach(cleanup)
beforeEach(() => {
  vi.clearAllMocks()
  for (const fn of Object.values(validationIssuesApi)) vi.mocked(fn).mockResolvedValue({} as never)
  vi.mocked(changesApi.deleteAttachment).mockResolvedValue({} as never)
})

describe('F1 where the issues live', () => {
  it('Timing during the loop back, Release otherwise', () => {
    expect(issueTabFor('in_implementation')).toBe('timing')
    expect(issueTabFor('in_validation')).toBe('release')
    expect(issueTabFor('released')).toBe('release')
  })

  it('the Release tab stays open in implementation once an issue exists', () => {
    expect(releaseOpenByIssues('in_implementation', 1)).toBe(true)
    expect(releaseOpenByIssues('in_implementation', 0)).toBe(false)
    expect(releaseOpenByIssues('approved', 3)).toBe(false)
  })

  it('issue waits point at the tab for the status and carry the issue id', () => {
    const open = [issue({ id: 21, number: 1, status: 'fixing', escalation_level: 2 })]
    const loop = issueWaits(open, 'in_implementation')
    expect(loop.every((w) => w.tab === 'timing')).toBe(true)
    expect(loop.map((w) => w.issueId)).toEqual([21, 21])
    expect(issueWaits(open, 'in_validation').every((w) => w.tab === 'release')).toBe(true)
  })

  it('a deep-linked card is ringed and opened, closed ones unfold for it', async () => {
    vi.mocked(validationIssuesApi.list).mockResolvedValue([
      issue({ id: 11 }), issue({ id: 12, number: 3, status: 'closed', title: 'Old one' }),
    ])
    qcWrap(<IssuesPanel changeId={7} changeStatus="in_implementation" departments={departments}
      viewer={{}} canRaise={false} focusIssueId={12} title="Validation issues / recovery" hint="Back in implementation" />)
    const target = await screen.findByTestId('issue-card-12')
    expect(target.getAttribute('data-highlight')).toBe('true')
    expect(screen.getByTestId('issue-card-11').getAttribute('data-highlight')).toBeNull()
    expect(screen.getByText('Validation issues / recovery')).toBeDefined()
    expect(screen.getByText('Back in implementation')).toBeDefined()
  })

  it('cockpit issue actions open the issue tab for the status with the issue id', () => {
    const onAction = vi.fn()
    const change = {
      id: 7, change_number: 'CR-2026-0007', project_id: 1, title: 'x', change_type: 'tooling',
      priority: 'medium', status: 'in_implementation', raised_by: 1, customer_response: 'accepted',
      created_at: '2026-07-01T00:00:00', updated_at: '2026-07-01T00:00:00',
      impacted_items: [], assessments: [], attachments: [],
    } as unknown as ChangeDetail
    qcWrap(<CockpitSummary change={change} gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false}
      actions={[
        { kind: 'validation_issue_action', label: 'Finish the fix actions of VI-1', target_tab: 'release', issue_id: 21 },
        { kind: 'assessment', label: 'Submit', target_tab: 'assessments', assessment_id: 1 },
      ]}
      onAction={onAction} />)
    fireEvent.click(screen.getByTestId('action-validation_issue_action-21'))
    expect(onAction).toHaveBeenCalledWith('timing', 21)
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }))
    expect(onAction).toHaveBeenLastCalledWith('assessments')
    expect(isIssueActionKind('validation_issue_escalation')).toBe(true)
    expect(isIssueActionKind('assessment')).toBe(false)
  })

  it('a wait row passes its issue id along', () => {
    const onGo = vi.fn()
    const change = {
      id: 7, change_number: 'CR-2026-0007', project_id: 1, title: 'x', change_type: 'tooling',
      priority: 'medium', status: 'in_implementation', raised_by: 1, customer_response: 'accepted',
      created_at: '2026-07-01T00:00:00', updated_at: '2026-07-01T00:00:00',
      impacted_items: [], assessments: [], attachments: [],
    } as unknown as ChangeDetail
    qcWrap(<CockpitSummary change={change} gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false}
      waits={issueWaits([issue({ id: 21, number: 1, status: 'fixing' })], 'in_implementation')} onGo={onGo} />)
    fireEvent.click(screen.getByTestId('wait-validation-issue-21').querySelector('button')!)
    expect(onGo).toHaveBeenCalledWith('timing', 21)
  })
})

describe('F2 quote the fix', () => {
  it('Sales sees "Quote the fix" as the primary act, confirms, and the fix-quoted call is made', async () => {
    card(issue({ cost_bearer: 'customer', extra_acts: ['quote_fix'], next_acts: ['escalate', 'attach'] }), { isSales: true })
    const btn = screen.getByTestId('issue-primary-11')
    expect(btn.getAttribute('data-act')).toBe('quote_fix')
    fireEvent.click(btn)
    expect(screen.getByRole('dialog', { name: 'Quote the fix of VI-2' })).toBeDefined()
    fireEvent.change(screen.getByTestId('issue-quote-note-11'), { target: { value: 'Q-2026-114 to Mr. Buyer' } })
    fireEvent.click(screen.getByTestId('issue-quote-confirm-11'))
    await waitFor(() => expect(validationIssuesApi.fixQuoted).toHaveBeenCalledWith(7, 11, 'Q-2026-114 to Mr. Buyer'))
  })

  it('with another primary act, the quote sits under "Also"; once quoted it is a fact, not an act', () => {
    card(issue({ cost_bearer: 'customer', extra_acts: ['quote_fix'], next_acts: ['customer'], customer_inform: true }))
    expect(screen.getByTestId('issue-primary-11').getAttribute('data-act')).toBe('customer')
    expect(screen.getByTestId('issue-act-quote_fix-11')).toBeDefined()
    cleanup()
    card(issue({ cost_bearer: 'customer', extra_acts: [], fix_quoted_at: '2026-09-25T04:05:57', fix_quoted_by_name: 'Sam Sales' }))
    expect(screen.queryByTestId('issue-act-quote_fix-11')).toBeNull()
    expect(screen.getByTestId('issue-fix-quoted-11').textContent).toContain('Sam Sales')
  })
})

describe('F5 escalation pulse', () => {
  it('no pulse at level 1, pulse at level 2 while unacknowledged', () => {
    render(<EscalationBadge level={1} unacknowledged />)
    expect(screen.queryByTestId('escalation-dot-pulse')).toBeNull()
    cleanup()
    render(<EscalationBadge level={2} unacknowledged />)
    expect(screen.getByTestId('escalation-dot-pulse')).toBeDefined()
  })

  it('needs_ack drives the card: an acknowledged-by-nobody de-escalation does not pulse', () => {
    const esc = (over = {}) => ({ id: 1, level: 2 as const, reason: 'r', created_at: '2026-09-24T08:00:00', ...over })
    expect(needsAck(esc({ needs_ack: false }))).toBe(false)
    expect(needsAck(esc())).toBe(true)
    expect(needsAck(esc({ level: 1 }))).toBe(false)
    expect(needsAck(esc({ trigger: 'deescalate' }))).toBe(false)
    card(issue({ escalation_level: 2, escalations: [esc({ needs_ack: false })], escalation: { level: 2, unacknowledged: false } }))
    expect(screen.queryByTestId('escalation-dot-pulse')).toBeNull()
    cleanup()
    card(issue({ escalation_level: 2, escalations: [esc({ needs_ack: true })], escalation: { level: 2, unacknowledged: true } }))
    expect(screen.getAllByTestId('escalation-dot-pulse').length).toBeGreaterThan(0)
  })
})

describe('F6 polish', () => {
  it('PM lowers the escalation with a reason', async () => {
    card(issue({ escalation_level: 3, extra_acts: ['deescalate'] }), { canManage: true })
    fireEvent.click(screen.getByTestId('issue-deescalate-11'))
    const go = screen.getByTestId('issue-deescalate-confirm-11') as HTMLButtonElement
    expect(go.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('issue-deescalate-reason-11'), { target: { value: 'Supplier confirmed the date' } })
    fireEvent.click(go)
    await waitFor(() => expect(validationIssuesApi.deescalate).toHaveBeenCalledWith(7, 11,
      { level: 2, reason: 'Supplier confirmed the date' }))
  })

  it('no lower button without the backend act', () => {
    card(issue({ escalation_level: 3, extra_acts: [] }), { canManage: true })
    expect(screen.queryByTestId('issue-deescalate-11')).toBeNull()
  })

  it('edits the issue: only changed fields go out, customer_inform included', async () => {
    card(issue({ next_acts: ['edit'] }))
    fireEvent.click(screen.getByTestId('issue-act-edit-11'))
    fireEvent.change(screen.getByTestId('edit-title'), { target: { value: 'Slide jams' } })
    fireEvent.change(screen.getByTestId('edit-department'), { target: { value: '2' } })
    fireEvent.click(screen.getByTestId('edit-inform'))
    fireEvent.click(screen.getByTestId('edit-submit'))
    await waitFor(() => expect(validationIssuesApi.update).toHaveBeenCalledWith(7, 11,
      { title: 'Slide jams', department_id: 2, customer_inform: true }))
  })

  it('issuePatch leaves unchanged fields out', () => {
    const i = issue({ affected_tool_ref: 'T-1' })
    expect(issuePatch(i, {
      title: i.title, description: i.description, severity: 3, category: 'tool', department_id: 4,
      affected_tool_ref: '', customer_inform: false,
    })).toEqual({ severity: 3, affected_tool_ref: null })
  })

  it('no edit link without the edit act', () => {
    card(issue({ next_acts: ['escalate'] }))
    expect(screen.queryByTestId('issue-act-edit-11')).toBeNull()
  })

  it('deletes an issue file when the backend allows it, and not otherwise', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const file = (id: number, can_delete?: boolean) => ({
      id, filename: `f${id}.pdf`, content_type: 'application/pdf', size_bytes: 1, phase: 'post_scoping' as const,
      created_at: '2026-09-24T08:00:00', uploaded_by: 9, validation_issue_id: 11, can_delete,
    })
    card(issue({ attachments: [file(1, true), file(2, false)] }))
    expect(screen.queryByLabelText('Delete f2.pdf')).toBeNull()
    fireEvent.click(screen.getByLabelText('Delete f1.pdf'))
    await waitFor(() => expect(changesApi.deleteAttachment).toHaveBeenCalledWith(7, 1))
  })

  it('without can_delete: uploader, PM, lead or admin while the issue is open', () => {
    const f = { id: 1, filename: 'a', content_type: '', size_bytes: 1, phase: 'post_scoping' as const,
      created_at: '', uploaded_by: 9 }
    expect(mayDeleteIssueFile(issue(), f, { id: 9 })).toBe(true)
    expect(mayDeleteIssueFile(issue(), f, { id: 8 })).toBe(false)
    expect(mayDeleteIssueFile(issue(), f, { canManage: true })).toBe(true)
    expect(mayDeleteIssueFile(issue({ status: 'accepted' }), f, { canManage: true })).toBe(false)
  })

  it('a 409 object detail reads as its message in the toast', async () => {
    expect(errDetail({ response: { data: { detail: { message: 'Plan changed meanwhile', revision: 4 } } } }))
      .toBe('Plan changed meanwhile')
    expect(errDetail({ response: { data: { detail: [{ msg: 'field required' }] } } })).toBe('field required')
    expect(errDetail({ response: { data: { detail: 'plain' } } })).toBe('plain')
    vi.mocked(validationIssuesApi.deescalate).mockRejectedValue(
      { response: { status: 409, data: { detail: { message: 'Recovery plan moved: reload' } } } })
    card(issue({ escalation_level: 2, extra_acts: ['deescalate'] }), { canManage: true })
    fireEvent.click(screen.getByTestId('issue-deescalate-11'))
    fireEvent.change(screen.getByTestId('issue-deescalate-reason-11'), { target: { value: 'x' } })
    fireEvent.click(screen.getByTestId('issue-deescalate-confirm-11'))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Recovery plan moved: reload'))
  })

  it('the status chip names the root cause once found', () => {
    expect(statusChipLabel(issue({ root_cause_at: '2026-09-24' }))).toBe('Root cause found')
    expect(statusChipLabel(issue({ contained_at: '2026-09-24' }))).toBe('Contained')
    expect(statusChipLabel(issue({ status: 'fixing', root_cause_at: 'x' }))).toBe('Fixing')
    card(issue({ status: 'contained', contained_at: 'x', root_cause_at: 'y' }))
    expect(screen.getByTestId('issue-status-11').textContent).toBe('Root cause found')
  })

  it('a new timing date in the past is refused', () => {
    const i = issue()
    expect(customerDecisionBlocked(i, 'new_timing', 'agreed', '2026-09-01', '2026-09-25'))
      .toBe('The new release date cannot be in the past')
    expect(customerDecisionBlocked(i, 'new_timing', 'agreed', '2026-09-25', '2026-09-25')).toBeNull()
  })

  it('the end-implementation dialog names the issues still fixing, as info', () => {
    render(<TransitionConfirmDialog onClose={() => {}} onConfirm={() => {}} confirm={{
      to: 'in_validation', title: 'End implementation', consequence: 'c', open: [], allClear: 'all done',
      confirmLabel: 'Move to validation', info: ['Still fixing: VI-1 Clip hole'],
    }} />)
    expect(screen.getByTestId('confirm-info').textContent).toContain('Still fixing: VI-1 Clip hole')
    expect(screen.getByTestId('confirm-clear')).toBeDefined()
  })
})

describe('follow-ups: recheck, add_action, acts after close', () => {
  it('recheck is the primary act and points at the linked check in the validation panel', () => {
    const row = document.createElement('li')
    row.setAttribute('data-testid', 'validation-check-27-measured')
    const scroll = vi.fn()
    row.scrollIntoView = scroll
    document.body.appendChild(row)
    card(issue({
      status: 'revalidation', route: 'internal_rework', check_id: 58, check_key: 'measured', check_department_id: 27,
      check: { id: 58, check_key: 'measured', label: 'Part measured', department_id: 27, department_name: 'Tool Engineer' },
      next_acts: ['recheck', 'escalate', 'edit'], primary_act: 'recheck',
    }))
    const btn = screen.getByTestId('issue-primary-11')
    expect(btn.getAttribute('data-act')).toBe('recheck')
    expect(btn.textContent).toBe('Re-check the validation')
    fireEvent.click(btn)
    expect(scroll).toHaveBeenCalled()
    expect(screen.getByTestId('issue-recheck-11').textContent).toContain('Part measured')
    expect(screen.getByTestId('issue-recheck-11').textContent).toContain('(Tool Engineer)')
    row.remove()
  })

  it('the backend primary_act wins: add_action leads after a failed re-validation and opens the add row', () => {
    card(issue({
      status: 'fixing', route: 'internal_rework',
      actions: [{ id: 1, description: 'Rework slide', status: 'done' }],
      next_acts: ['cost', 'add_action', 'escalate', 'edit'], primary_act: 'add_action',
    }), { canManage: true })
    const btn = screen.getByTestId('issue-primary-11')
    expect(btn.getAttribute('data-act')).toBe('add_action')
    expect(screen.queryByTestId('issue-action-text-11')).toBeNull()
    fireEvent.click(btn)
    expect(screen.getByTestId('issue-action-text-11')).toBeDefined()
  })

  it('a new fix action takes its due date as dd.mm.yyyy text, sent as ISO', async () => {
    card(issue({
      status: 'fixing', route: 'internal_rework', actions: [],
      next_acts: ['add_action', 'edit'], primary_act: 'add_action',
    }), { canManage: true })
    fireEvent.click(screen.getByTestId('issue-primary-11'))
    fireEvent.change(screen.getByTestId('issue-action-text-11'), { target: { value: 'Rework slide' } })
    const due = screen.getByLabelText('Due date') as HTMLInputElement
    expect(due.type).toBe('text')
    fireEvent.change(due, { target: { value: '05.10.2030' } })
    fireEvent.click(screen.getByTestId('issue-action-save-11'))
    await waitFor(() => expect(validationIssuesApi.addAction).toHaveBeenCalledWith(7, 11,
      expect.objectContaining({ description: 'Rework slide', due_date: '2030-10-05' })))
  })

  it('primary_act null means no primary button, even with a non-quiet act listed', () => {
    card(issue({ next_acts: ['cost', 'edit'], primary_act: null }))
    expect(screen.queryByTestId('issue-primary-11')).toBeNull()
  })

  it('a closed issue offers a late cost from extra_acts and saves it', async () => {
    card(issue({ status: 'closed', cost_set: true, extra_cost: 1800, cost_bearer: 'internal',
      next_acts: [], extra_acts: ['cost'] }), { canSeeCosts: true }, { defaultOpen: true })
    fireEvent.click(screen.getByTestId('issue-act-late-cost-11'))
    expect(screen.getByTestId('issue-act-late-cost-11').textContent).toBe('Correct the cost')
    expect(screen.getByTestId('issue-cost-late-11')).toBeDefined()
    fireEvent.click(screen.getByTestId('cost-submit'))
    await waitFor(() => expect(validationIssuesApi.cost).toHaveBeenCalledWith(7, 11, { extra_cost: 1800, cost_bearer: 'internal' }))
  })

  it('a closed issue with a customer-paid fix still offers the quote', () => {
    card(issue({ status: 'closed', cost_set: true, cost_bearer: 'customer', next_acts: [], extra_acts: ['quote_fix'] }),
      { isSales: true })
    expect(screen.getByTestId('issue-primary-11').getAttribute('data-act')).toBe('quote_fix')
  })

  it('in implementation a fixed issue names the re-check step instead of a button', () => {
    card(issue({ status: 'revalidation', route: 'internal_rework',
      actions: [{ id: 1, description: 'Rework slide', status: 'done' }],
      next_acts: ['escalate', 'edit'], primary_act: null }), { canManage: true },
    { changeStatus: 'in_implementation' })
    expect(screen.queryByTestId('issue-primary-11')).toBeNull()
    expect(screen.getByTestId('issue-recheck-waits-11').textContent).toContain('back in validation')
  })

  it('a failed re-check refreshes the card: the note closes and fixing is current again', () => {
    const row = document.createElement('div')
    row.setAttribute('data-testid', 'validation-check-4-part_measured')
    document.body.appendChild(row)
    const base = { route: 'internal_rework' as const, check_key: 'part_measured', check_department_id: 4,
      actions: [{ id: 1, description: 'Rework slide', status: 'done' as const }] }
    const qc = new QueryClient()
    const ui = (i: IssueOut) => (
      <MemoryRouter><QueryClientProvider client={qc}>
        <IssueCard changeId={7} changeStatus="in_validation" issue={i} viewer={{ canManage: true }} departments={departments} />
      </QueryClientProvider></MemoryRouter>)
    const { rerender } = render(ui(issue({ ...base, status: 'revalidation',
      next_acts: ['recheck', 'edit'], primary_act: 'recheck' })))
    fireEvent.click(screen.getByTestId('issue-primary-11'))
    expect(screen.getByTestId('issue-recheck-11')).toBeDefined()
    const failed = issue({ ...base, status: 'fixing', next_acts: ['add_action', 'edit'], primary_act: 'add_action' })
    rerender(ui(failed))
    expect(screen.queryByTestId('issue-recheck-11')).toBeNull()
    expect(issueSteps(failed).find((st) => st.state === 'current')?.key).toBe('fixing')
    row.remove()
  })

  it('the new My Actions kinds are issue acts', () => {
    expect(isIssueActionKind('validation_issue_recheck')).toBe(true)
    expect(isIssueActionKind('validation_issue_add_action')).toBe(true)
  })
})
