/**
 * Deciding the route to the fix (spec §12 Route). Each route says in one
 * line what it is, and the box under it says what deciding it sets in
 * motion before anyone presses the button: the loop back to implementation,
 * the recovery blocks in the plan, the customer mail a concession needs, the
 * follow-up change.
 */
import { useEffect, useState } from 'react'
import { validationIssuesApi } from '../../../api/validationIssues'
import type { IssueActionIn, IssueOut, IssueRoute } from '../../../types/validationIssue'
import { issueCode } from '../../../types/validationIssue'
import { Toggle } from '../offer/ui'
import { inputCls, sectionLabel } from '../offer/offerFormat'
import { FIX_ROUTES, ROUTE } from './issueModel'
import { useIssueMutation } from './useIssueMutation'
import DateInput from '../../gantt/DateInput'
import { X } from 'lucide-react'
import Dialog from '../../common/Dialog'
import Button from '../../common/Button'

const ORDER: IssueRoute[] = ['internal_rework', 'supplier_rework', 'design_change', 'customer_concession', 'follow_up_change']

/** Why a route cannot be decided yet, or null. */
export function routeBlockedReason(issue: IssueOut, route: IssueRoute): string | null {
  if (issue.severity === 3 && !issue.contained_at) return 'Record the containment first (blocks production).'
  if (route !== 'customer_concession' && !issue.root_cause_at) return 'Record the root cause first.'
  return null
}

/** What deciding the route does, in the order it happens. */
export function routeConsequences(route: IssueRoute, issue: IssueOut, changeStatus: string): {
  loopBack: string | null; lines: string[]
} {
  const code = issueCode(issue)
  const fix = FIX_ROUTES.includes(route)
  const loopBack = fix && changeStatus === 'in_validation'
    ? `Loop back: the change goes back to implementation now (reason "${code}: ${issue.title}: <your reason>"). Validation of this check starts again once the fix is done.`
    : null
  const lines: string[] = []
  if (fix) {
    lines.push(`Plan: a recovery group "Recovery ${code}" with one block per fix action and "Re-validation ${code}" is added after the failed validation. SOP and customer approval move with it; after the baseline it is recorded as plan deviations.`)
    lines.push('At least one fix action with an owner is required.')
  }
  if (route === 'supplier_rework') lines.push('Name the supplier. With chargeback on, the supplier carries the cost.')
  if (route === 'design_change') lines.push('The customer is informed by default.')
  if (route === 'customer_concession') {
    lines.push('The customer must be informed: Sales gets the task.')
    lines.push('The issue closes as accepted only when Sales records "accepts the deviation" with the customer mail filed into this issue.')
    lines.push('The root cause may stay open while the customer accepts the part as it is.')
  }
  if (route === 'follow_up_change') {
    lines.push(`A new change is captured in the same project, led by this change's lead, with the reason "Follow-up of this change, ${code}".`)
    lines.push('This issue is transferred and no longer holds up the release; the follow-up carries the work.')
  }
  return { loopBack, lines }
}

interface ActionRow { description: string; department_id: number | null; due_date: string }
const emptyRow = (deptId: number | null): ActionRow => ({ description: '', department_id: deptId, due_date: '' })

export default function RouteDialog({ open, changeId, changeStatus, issue, departments, onClose }: {
  open: boolean
  changeId: number
  changeStatus: string
  issue: IssueOut
  departments: { id: number; name: string }[]
  onClose: () => void
}) {
  const [route, setRoute] = useState<IssueRoute | null>(null)
  const [reason, setReason] = useState('')
  const [supplier, setSupplier] = useState('')
  const [chargeback, setChargeback] = useState(false)
  const [inform, setInform] = useState(false)
  const [rows, setRows] = useState<ActionRow[]>([emptyRow(issue.department_id ?? null)])

  useEffect(() => {
    if (!open) return
    setRoute(null); setReason(''); setSupplier(''); setChargeback(false); setInform(!!issue.customer_inform)
    setRows([emptyRow(issue.department_id ?? null)])
  }, [open, issue.id, issue.customer_inform, issue.department_id])

  const save = useIssueMutation(changeId, () => {
    const fix = FIX_ROUTES.includes(route!)
    const actions: IssueActionIn[] = fix ? rows.filter((r) => r.description.trim()).map((r) => ({
      description: r.description.trim(),
      department_id: r.department_id,
      ...(r.due_date ? { due_date: r.due_date } : {}),
    })) : []
    return validationIssuesApi.route(changeId, issue.id, {
      route: route!, reason: reason.trim(),
      ...(route === 'supplier_rework' ? { supplier_name: supplier.trim(), chargeback } : {}),
      customer_inform: route === 'customer_concession' ? true : inform,
      ...(fix ? { actions } : {}),
    })
  }, { error: 'Could not decide the route', onDone: onClose })

  if (!open) return null

  const pick = (r: IssueRoute) => {
    setRoute(r)
    if (r === 'design_change' || r === 'customer_concession') setInform(true)
  }
  const fix = !!route && FIX_ROUTES.includes(route)
  const validActions = rows.filter((r) => r.description.trim()).length
  const missing: string[] = []
  if (!route) missing.push('Pick a route')
  if (route && routeBlockedReason(issue, route)) missing.push(routeBlockedReason(issue, route)!)
  if (!reason.trim()) missing.push('Give the reason')
  if (fix && validActions === 0) missing.push('Add at least one fix action')
  if (route === 'supplier_rework' && !supplier.trim()) missing.push('Name the supplier')
  const cons = route ? routeConsequences(route, issue, changeStatus) : null

  return (
    <Dialog open={open} onClose={onClose} size="lg" busy={save.isPending} closeOnBackdrop={false}
      title={`Decide the route for ${issueCode(issue)}`} description={issue.title} data-testid="route-dialog"
      footer={(
        <>
          {missing.length > 0 && (
            <span data-testid="route-missing" className="mr-auto text-[11px] text-slate-400">{missing[0]}</span>
          )}
          <Button onClick={onClose} disabled={save.isPending}>Cancel</Button>
          <Button variant="primary" data-testid="route-submit" disabled={missing.length > 0} loading={save.isPending}
            onClick={() => save.mutate(undefined)}>
            Decide route
          </Button>
        </>
      )}>
        <div className="space-y-4">
          <div role="radiogroup" aria-label="Route" className="space-y-1.5">
            {ORDER.map((r) => {
              const blocked = routeBlockedReason(issue, r)
              const on = route === r
              return (
                <button key={r} type="button" role="radio" aria-checked={on} disabled={!!blocked}
                  data-testid={`route-option-${r}`} onClick={() => pick(r)}
                  className={`flex w-full items-start gap-3 rounded-lg border px-3 py-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                    on ? 'border-sky-600 bg-sky-950/30' : 'border-slate-700 bg-slate-900/40 hover:border-slate-600'}`}>
                  <span className={`mt-1 h-3 w-3 shrink-0 rounded-full border ${on ? 'border-sky-400 bg-sky-400' : 'border-slate-500'}`} />
                  <span className="min-w-0">
                    <span className="block text-sm text-slate-100">{ROUTE[r].label}</span>
                    <span className="block text-xs text-slate-400">{ROUTE[r].line}</span>
                    {blocked && <span className="block text-[11px] text-amber-300">{blocked}</span>}
                  </span>
                </button>
              )
            })}
          </div>

          {cons && (
            <div data-testid="route-consequences" className="space-y-1.5">
              <div className={sectionLabel}>What happens</div>
              {cons.loopBack && (
                <p role="alert" data-testid="route-loopback"
                  className="rounded-lg border border-amber-700/60 bg-amber-950/40 px-3 py-2 text-sm text-amber-200">
                  {cons.loopBack}
                </p>
              )}
              <ul className="space-y-1">
                {cons.lines.map((l) => (
                  <li key={l} className="flex gap-2 text-xs text-slate-300">
                    <span aria-hidden="true" className="text-slate-400">•</span><span>{l}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {route === 'supplier_rework' && (
            <div className="flex flex-wrap items-center gap-3">
              <input data-testid="route-supplier" value={supplier} onChange={(e) => setSupplier(e.target.value)}
                placeholder="Supplier name" aria-label="Supplier name" className={`${inputCls} min-w-0 flex-1`} />
              <label className="flex items-center gap-2 text-xs text-slate-300">
                <Toggle checked={chargeback} onChange={setChargeback} label="Chargeback" testId="route-chargeback" />
                Chargeback (supplier pays)
              </label>
            </div>
          )}

          {route && route !== 'customer_concession' && route !== 'follow_up_change' && (
            <label className="flex items-center gap-2 text-xs text-slate-300">
              <Toggle checked={inform} onChange={setInform} label="Customer must be informed" testId="route-inform" />
              Customer must be informed
            </label>
          )}

          {fix && (
            <div data-testid="route-actions" className="space-y-1.5">
              <div className={sectionLabel}>Fix actions</div>
              {rows.map((row, idx) => (
                <div key={idx} className="flex flex-wrap items-center gap-2">
                  <input data-testid={`route-action-${idx}`} value={row.description} aria-label={`Fix action ${idx + 1}`}
                    onChange={(e) => setRows(rows.map((x, j) => j === idx ? { ...x, description: e.target.value } : x))}
                    placeholder="What is done" className={`${inputCls} min-w-0 flex-1`} />
                  <select aria-label="Owner department" value={row.department_id ?? ''}
                    onChange={(e) => setRows(rows.map((x, j) => j === idx
                      ? { ...x, department_id: e.target.value ? Number(e.target.value) : null } : x))}
                    className={inputCls}>
                    <option value="">Department</option>
                    {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                  </select>
                  <DateInput aria-label="Due date" value={row.due_date} commitOnChange
                    onChange={(iso) => setRows((rs) => rs.map((x, j) => j === idx ? { ...x, due_date: iso } : x))}
                    className={`${inputCls} w-32`} />
                  {rows.length > 1 && (
                    <button type="button" aria-label="Remove action" onClick={() => setRows(rows.filter((_, j) => j !== idx))}
                      className="rounded p-1 text-slate-400 hover:text-rose-300"><X aria-hidden="true" size={14} /></button>
                  )}
                </div>
              ))}
              <button type="button" data-testid="route-action-add"
                onClick={() => setRows([...rows, emptyRow(issue.department_id ?? null)])}
                className="text-xs text-sky-300 hover:text-sky-200">+ Add action</button>
              <p className="text-[11px] text-slate-400">Without a due date a recovery block lasts 5 working days.</p>
            </div>
          )}

          <label className="block">
            <span className="mb-1 block text-[11px] text-slate-400">Reason (required, recorded on the change)</span>
            <textarea data-testid="route-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)}
              className={`${inputCls} w-full`} />
          </label>
        </div>
    </Dialog>
  )
}
