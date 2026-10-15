import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import IndexFollowups from './IndexFollowups'
import type { IndexFollowup } from '../../types/change'

const api = vi.hoisted(() => ({
  indexFollowups: vi.fn(), answerRecheck: vi.fn(), answerIndexScope: vi.fn(), answerIndexDeadline: vi.fn(),
}))
vi.mock('../../api/changes', () => ({ changesApi: api }))
vi.mock('../gantt/DateInput', () => ({
  default: (p: { value: string; onChange: (v: string) => void }) => (
    <input data-testid="date" value={p.value} onChange={(e) => p.onChange(e.target.value)} />
  ),
}))

const row = (over: Partial<IndexFollowup> = {}): IndexFollowup => ({
  intake_id: 3, part_id: 9, part_number: '886.197', from_revision: 'C', to_revision: 'D',
  superseded: false, what_changed: ['geometry', 'material'], what_changed_ref: 'Compare CR-118',
  no_change_reason: null, lead_open: true, scope_answer: null, scope_note: null, scope_by_name: null,
  scope_at: null, deadline_open: true, deadline_answer: null, deadline_ref: null,
  deadline_confirm_by: null, deadline_by_name: null,
  rechecks: [{ id: 11, department_id: 2, department_name: 'Process Engineer', areas: ['geometry', 'material'],
    status: 'open', effect: null, answers: [], something_else: null, answered_by_name: null,
    answered_at: null, created_at: '2026-10-15T08:00:00' }],
  ...over,
})

function show(props: Partial<Parameters<typeof IndexFollowups>[0]> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}>
    <IndexFollowups changeId={7} assessments={[{ department_id: 4, submitted_at: null, status: 'active' }]}
      departments={[{ id: 2, name: 'Process Engineer' }, { id: 4, name: 'Toolshop' }]}
      myDepartmentIds={[2]} mayLead={false} isSales={false} leadName="Holmes"
      salesOwnerName="Cody" attachments={[]} {...props} />
  </QueryClientProvider>)
}

describe('IndexFollowups (§1)', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks() })

  it('the department answers every area; nothing preselected; evidence demanded', async () => {
    api.indexFollowups.mockResolvedValue([row()])
    api.answerRecheck.mockResolvedValue([row()])
    show()
    await screen.findByTestId('recheck-11')
    expect(screen.queryByTestId('rc-save')).not.toBeNull()
    const save = screen.getByTestId('rc-save') as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.click(screen.getByTestId('rc-geometry-yes'))
    fireEvent.change(screen.getByTestId('rc-geometry-what'), { target: { value: 'Rib higher: slider' } })
    fireEvent.change(screen.getByTestId('rc-geometry-evidence'), { target: { value: 'Compare p.3' } })
    expect(save.disabled).toBe(true)          // material not answered yet
    fireEvent.click(screen.getByTestId('rc-material-no'))
    fireEvent.change(screen.getByTestId('rc-material-ref'), { target: { value: 'tbd' } })
    expect(save.disabled).toBe(true)          // a ref that says nothing
    fireEvent.change(screen.getByTestId('rc-material-ref'), { target: { value: 'Checklist row M-4' } })
    expect(save.disabled).toBe(false)
    fireEvent.click(save)
    await waitFor(() => expect(api.answerRecheck).toHaveBeenCalledWith(7, 11, {
      answers: [{ area: 'geometry', effect: true, what: 'Rib higher: slider', evidence: 'Compare p.3' },
        { area: 'material', effect: false, ref: 'Checklist row M-4' }],
      something_else: null }))
  })

  it('another department reads who owes it; the lead and Sales questions name their owner', async () => {
    api.indexFollowups.mockResolvedValue([row()])
    show({ myDepartmentIds: [4] })
    await screen.findByTestId('recheck-11')
    expect(screen.queryByTestId('rc-save')).toBeNull()
    expect(screen.getByTestId('recheck-11').textContent).toContain('Process Engineer rechecks')
    expect(screen.getByTestId('lead-question').textContent).toContain('Holmes answers this')
    expect(screen.getByTestId('deadline-question').textContent).toContain('Cody answers this')
    // Toolshop had not submitted: it assesses on D
    expect(screen.getByTestId('assess-on-new').textContent).toContain('assess on D')
  })

  it('the lead answers yes only with what it adds', async () => {
    api.indexFollowups.mockResolvedValue([row({ rechecks: [] })])
    api.answerIndexScope.mockResolvedValue([row({ rechecks: [], lead_open: false, scope_answer: 'no' })])
    show({ mayLead: true })
    await screen.findByTestId('lead-question')
    fireEvent.click(screen.getByTestId('lead-yes'))
    const save = screen.getByTestId('lead-save') as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('lead-note'), { target: { value: 'Clip 886.198' } })
    expect(save.disabled).toBe(false)
  })

  it('Sales: holds needs a mail or a reference', async () => {
    api.indexFollowups.mockResolvedValue([row({ rechecks: [], lead_open: false })])
    api.answerIndexDeadline.mockResolvedValue([row({ rechecks: [], lead_open: false, deadline_open: false })])
    show({ isSales: true })
    await screen.findByTestId('deadline-question')
    fireEvent.click(screen.getByTestId('dl-holds'))
    const save = screen.getByTestId('dl-save') as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('dl-ref'), { target: { value: 'Mail buyer 10-16' } })
    fireEvent.click(save)
    await waitFor(() => expect(api.answerIndexDeadline).toHaveBeenCalledWith(7, 3,
      { answer: 'holds', ref: 'Mail buyer 10-16' }))
  })
})
