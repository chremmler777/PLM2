/**
 * The extra cost of the fix and who carries it. Cost roles only; everyone
 * else sees that a cost is set, never the amount.
 */
import { useState } from 'react'
import { validationIssuesApi } from '../../../api/validationIssues'
import type { CostBearer, IssueOut } from '../../../types/validationIssue'
import { formatMoney } from '../../../lib/format'
import { NumField, Segmented } from '../offer/ui'
import { BEARER_LABEL } from './issueModel'
import { useIssueMutation } from './useIssueMutation'

export function CostLine({ issue, canSeeCosts }: { issue: IssueOut; canSeeCosts: boolean }) {
  const set = issue.cost_set ?? issue.extra_cost != null
  if (!set) return <span data-testid={`issue-cost-${issue.id}`} className="text-xs text-slate-500">No extra cost recorded</span>
  return (
    <span data-testid={`issue-cost-${issue.id}`} className="text-xs text-slate-300">
      {canSeeCosts && issue.extra_cost != null
        ? <span className="tabular-nums text-slate-100">{formatMoney(issue.extra_cost, issue.currency)}</span>
        : 'Cost set'}
      {issue.cost_bearer ? `, ${BEARER_LABEL[issue.cost_bearer]}` : ''}
    </span>
  )
}

export default function CostForm({ changeId, issue, onDone }: {
  changeId: number
  issue: IssueOut
  onDone?: () => void
}) {
  const [amount, setAmount] = useState<number | null>(issue.extra_cost ?? null)
  const [bearer, setBearer] = useState<CostBearer>(issue.cost_bearer
    ?? (issue.route === 'supplier_rework' && issue.chargeback ? 'supplier' : 'internal'))
  const save = useIssueMutation(changeId,
    () => validationIssuesApi.cost(changeId, issue.id, { extra_cost: amount!, cost_bearer: bearer }),
    { error: 'Could not save the cost', onDone })
  return (
    <div data-testid={`issue-cost-form-${issue.id}`} className="space-y-2 rounded-lg border border-slate-700 bg-slate-900/40 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <NumField value={amount} onChange={setAmount} ariaLabel="Extra cost" testId="cost-amount"
          placeholder="Extra cost" className="w-36" />
        <span className="text-xs text-slate-500">{issue.currency ?? 'EUR'}</span>
        <Segmented<CostBearer> value={bearer} onChange={setBearer} testId="cost-bearer"
          options={(['internal', 'supplier', 'customer'] as CostBearer[]).map((b) => ({ value: b, label: BEARER_LABEL[b] }))} />
      </div>
      {bearer === 'customer' && (
        <p className="text-[11px] text-slate-400">Sales gets a task to quote the fix to the customer.</p>
      )}
      {bearer === 'supplier' && (
        <p className="text-[11px] text-slate-400">Recoverable from the supplier; the P&L books it as such.</p>
      )}
      <button type="button" data-testid="cost-submit" disabled={amount == null || amount < 0 || save.isPending}
        onClick={() => save.mutate(undefined)}
        className="rounded-lg bg-sky-600 px-3 py-1 text-xs font-semibold text-white hover:bg-sky-500 disabled:opacity-50">
        Save cost
      </button>
    </div>
  )
}
