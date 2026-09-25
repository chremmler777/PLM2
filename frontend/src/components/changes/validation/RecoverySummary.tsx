/**
 * What the recovery does to the timing (spec §12a): when it ends, where the
 * plan finish lands, and how that sits against the baseline and the release
 * deadline. The group itself is edited in the Gantt, one click away.
 */
import { Link } from 'react-router-dom'
import type { IssueRecoveryOut } from '../../../types/validationIssue'
import { formatDate } from '../../../lib/format'
import { sectionLabel } from '../offer/offerFormat'
import { workingDaysBetween } from './issueModel'

const short = (iso?: string | null) => (iso ? formatDate(iso).slice(0, 5) : '-')

/** The figures the card shows, server counts first, Mon to Fri as a fallback. */
export function recoveryFigures(r: IssueRecoveryOut) {
  const slipBaseline = r.slip_baseline_wd ?? (r.plan_finish && r.baseline_finish
    ? workingDaysBetween(r.baseline_finish, r.plan_finish) : null)
  const slipDeadline = r.slip_deadline_wd ?? (r.plan_finish && r.release_due_date
    ? workingDaysBetween(r.release_due_date, r.plan_finish) : null)
  return { slipBaseline, slipDeadline }
}

/** "Recovery ends 14.11, the plan finish moves +9 wd, 4 wd after the release deadline". */
export function recoverySentence(r: IssueRecoveryOut): string {
  const { slipBaseline, slipDeadline } = recoveryFigures(r)
  const parts = [`Recovery ends ${short(r.finish)}`]
  if (slipBaseline != null) {
    parts.push(slipBaseline > 0 ? `the plan finish moves +${slipBaseline} wd`
      : slipBaseline < 0 ? `the plan finish is ${-slipBaseline} wd ahead of the baseline`
        : 'the plan finish holds the baseline')
  }
  if (slipDeadline != null) {
    parts.push(slipDeadline > 0 ? `${slipDeadline} wd after the release deadline`
      : slipDeadline === 0 ? 'on the release deadline'
        : `${-slipDeadline} wd before the release deadline`)
  }
  return parts.join(', ')
}

export default function RecoverySummary({ changeId, recovery: r }: {
  changeId: number
  recovery: IssueRecoveryOut
}) {
  const { slipBaseline, slipDeadline } = recoveryFigures(r)
  const late = slipDeadline != null && slipDeadline > 0
  const tone = (n: number | null) => n == null ? 'text-slate-100' : n > 0 ? 'text-rose-300' : 'text-emerald-300'
  const cells: [string, string, string, string?, string?][] = [
    ['Recovery finish', 'finish', formatDate(r.finish)],
    ['Plan finish', 'plan-finish', formatDate(r.plan_finish),
      slipBaseline != null ? `${slipBaseline > 0 ? '+' : ''}${slipBaseline} wd vs baseline ${short(r.baseline_finish)}` : 'no baseline',
      tone(slipBaseline)],
    ['Release deadline', 'deadline', formatDate(r.release_due_date),
      slipDeadline == null ? 'no deadline set'
        : slipDeadline > 0 ? `${slipDeadline} wd late` : slipDeadline === 0 ? 'on the day' : `${-slipDeadline} wd to spare`,
      tone(slipDeadline)],
  ]
  return (
    <div data-testid="recovery-summary"
      className={`rounded-lg border px-3 py-2.5 ${late ? 'border-rose-900/70 bg-rose-950/15' : 'border-slate-700 bg-slate-900/40'}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={sectionLabel}>Recovery timing</span>
        <Link to={`/changes/${changeId}?tab=timing&task=${r.summary_task_id}`}
          data-testid="recovery-open-plan"
          className="ml-auto text-xs text-sky-300 hover:text-sky-200 hover:underline">
          Open recovery in the plan
        </Link>
      </div>
      <p data-testid="recovery-sentence" className={`mt-1 text-sm ${late ? 'text-rose-200' : 'text-slate-200'}`}>
        {recoverySentence(r)}.
      </p>
      <div className="mt-2 grid grid-cols-3 gap-3">
        {cells.map(([label, id, value, sub, subTone]) => (
          <div key={id}>
            <div className="text-[11px] text-slate-500">{label}</div>
            <div data-testid={`recovery-${id}`} className="text-sm font-semibold tabular-nums text-slate-100">{value}</div>
            {sub && <div data-testid={`recovery-${id}-sub`} className={`text-[11px] tabular-nums ${subTone ?? 'text-slate-400'}`}>{sub}</div>}
          </div>
        ))}
      </div>
      {late && (
        <p className="mt-2 text-[11px] text-rose-200/80">
          The recovery pushes past the release deadline: Sales needs the customer's decision (new timing or keep the date).
        </p>
      )}
    </div>
  )
}
