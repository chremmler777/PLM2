/**
 * The fix actions of an issue. Owners tick theirs; when the last one is done
 * the issue moves to re-validation by itself.
 */
import { useEffect, useState } from 'react'
import { validationIssuesApi } from '../../../api/validationIssues'
import type { IssueActionOut, IssueOut } from '../../../types/validationIssue'
import { daysUntil, formatDate, todayIso } from '../../../lib/format'
import { inputCls, sectionLabel } from '../offer/offerFormat'
import type { IssueViewer } from './issueModel'
import { useIssueMutation } from './useIssueMutation'
import DateInput from '../../gantt/DateInput'

export const mayTick = (a: IssueActionOut, v: IssueViewer) =>
  a.status === 'open' && (a.can_done ?? (!!v.canManage || !!v.isAdmin
    || (v.id != null && a.owner_id === v.id)
    || (a.department_id != null && (v.myDepartmentIds ?? []).includes(a.department_id))))

export default function ActionsChecklist({ changeId, issue, viewer, canAdd, departments, addRequest = 0 }: {
  changeId: number
  issue: IssueOut
  viewer: IssueViewer
  canAdd: boolean
  departments: { id: number; name: string }[]
  /** Bumped by the card's add_action button: opens the add row. */
  addRequest?: number
}) {
  const [adding, setAdding] = useState(false)
  useEffect(() => { if (addRequest > 0 && canAdd) setAdding(true) }, [addRequest, canAdd])
  const [text, setText] = useState('')
  const [dept, setDept] = useState<number | null>(issue.department_id ?? null)
  const [due, setDue] = useState('')
  const done = useIssueMutation(changeId,
    (aid: number) => validationIssuesApi.actionDone(changeId, issue.id, aid),
    { error: 'Could not tick the action' })
  const add = useIssueMutation(changeId, () => validationIssuesApi.addAction(changeId, issue.id, {
    description: text.trim(), department_id: dept, ...(due ? { due_date: due } : {}),
  }), { error: 'Could not add the action', onDone: () => { setAdding(false); setText(''); setDue('') } })

  const open = issue.actions.filter((a) => a.status === 'open').length
  const deptName = (a: IssueActionOut) => a.department_name
    ?? departments.find((d) => d.id === a.department_id)?.name ?? null

  return (
    <div data-testid={`issue-actions-${issue.id}`} className="space-y-1.5">
      <div className="flex items-center gap-2">
        <span className={sectionLabel}>Fix actions</span>
        {issue.actions.length > 0 && (
          <span className={`text-[11px] ${open ? 'text-amber-300' : 'text-emerald-400'}`}>
            {open ? `${open} of ${issue.actions.length} open` : 'all done'}
          </span>
        )}
        {canAdd && !adding && (
          <button type="button" data-testid={`issue-action-add-${issue.id}`} onClick={() => setAdding(true)}
            className="ml-auto text-[11px] text-sky-300 hover:text-sky-200">+ Add action</button>
        )}
      </div>
      {issue.actions.length === 0 && !adding && (
        <p className="text-xs text-slate-500">
          {issue.route ? 'No fix actions on this route.' : 'Fix actions are set when the route is decided.'}
        </p>
      )}
      <ul className="space-y-1">
        {issue.actions.map((a) => {
          const tick = mayTick(a, viewer)
          const overdue = a.status === 'open' && !!a.due_date && daysUntil(a.due_date) < 0
          return (
            <li key={a.id} data-testid={`issue-action-${a.id}`}
              className="flex items-start gap-2 rounded-md px-1 py-0.5">
              <input type="checkbox" checked={a.status === 'done'} disabled={!tick || done.isPending}
                aria-label={`Done: ${a.description}`} data-testid={`issue-action-done-${a.id}`}
                onChange={() => { if (tick) done.mutate(a.id) }}
                className="mt-0.5 h-3.5 w-3.5 accent-emerald-500" />
              <div className="min-w-0 flex-1 text-xs">
                <span className={a.status === 'done' ? 'text-slate-500 line-through' : 'text-slate-200'}>{a.description}</span>
                <span className="ml-2 text-[11px] text-slate-500">
                  {[a.owner_name, deptName(a)].filter(Boolean).join(', ')}
                  {a.due_date && (
                    <span className={overdue ? 'text-rose-300' : ''}>{` · due ${formatDate(a.due_date)}${overdue ? ', overdue' : ''}`}</span>
                  )}
                  {a.status === 'done' && a.done_at ? ` · done ${formatDate(a.done_at)}${a.done_by_name ? ` by ${a.done_by_name}` : ''}` : ''}
                </span>
              </div>
            </li>
          )
        })}
      </ul>
      {adding && (
        <div className="flex flex-wrap items-center gap-2">
          <input autoFocus data-testid={`issue-action-text-${issue.id}`} value={text}
            onChange={(e) => setText(e.target.value)} placeholder="What is done"
            className={`${inputCls} min-w-0 flex-1`} />
          <select aria-label="Owner department" value={dept ?? ''}
            onChange={(e) => setDept(e.target.value ? Number(e.target.value) : null)} className={inputCls}>
            <option value="">Department</option>
            {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          <DateInput aria-label="Due date" min={todayIso()} value={due} commitOnChange
            onChange={setDue} className={`${inputCls} w-32`} />
          <button type="button" data-testid={`issue-action-save-${issue.id}`}
            disabled={!text.trim() || add.isPending} onClick={() => add.mutate(undefined)}
            className="rounded-lg bg-sky-600 px-2.5 py-1 text-xs text-white hover:bg-sky-500 disabled:opacity-50">Add</button>
          <button type="button" onClick={() => setAdding(false)}
            className="px-1 text-xs text-slate-400 hover:text-slate-200">Cancel</button>
        </div>
      )}
    </div>
  )
}
