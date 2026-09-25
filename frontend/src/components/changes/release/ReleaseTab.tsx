/**
 * The Release tab (spec 2026-09-25 section 7): the work is done, now prove it
 * holds and hand the change over. Four steps in order: validation checks,
 * release checklist, lessons learned, release and close. Once released, a
 * closing summary puts plan against actual.
 */
import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { changesApi } from '../../../api/changes'
import { changeReleaseApi } from '../../../api/changeRelease'
import { planApi } from '../../../api/changePlan'
import type { ChangeDetail } from '../../../types/change'
import type { TaskOut } from '../../../types/changePlan'
import ValidationPanel from '../ValidationPanel'
import ImplementationPanel from '../ImplementationPanel'
import PnlCard from '../PnlCard'
import { StepSection } from '../offer/ui'
import { fmtDate, sectionLabel } from '../offer/offerFormat'
import ReleaseChecklist from './ReleaseChecklist'
import { releaseKey } from './releaseKeys'
import LessonsStep from './LessonsStep'
import IssuesPanel, { issueBlockers, useValidationIssues } from '../validation/IssuesPanel'
import { isIssueOpen } from '../../../types/validationIssue'

export interface ReleaseTabProps {
  change: ChangeDetail
  departments: { id: number; name: string }[]
  myDepartmentIds: number[]
  canSeeAll: boolean
  canAcknowledge: boolean
  /** PM, the change lead, admin. */
  canManage: boolean
  onAdvance: (to: string) => void
  advancing: boolean
  /** The viewer, for the 4-eyes rule on the route of an issue they raised. */
  viewerId?: number | null
  isAdmin?: boolean
  /** Sales records the customer's decision on validation issues. */
  isSales?: boolean
  /** Deep link ?issue=<id>: the issue card to open and scroll to. */
  focusIssueId?: number | null
}

/**
 * The release guard's blockers plus one line per open validation issue,
 * unless the guard already names the issues itself.
 */
export function releaseBlockers(guard: string[], issues: Parameters<typeof issueBlockers>[0]): string[] {
  const named = guard.some((b) => /validation issue|\bVI-\d+/i.test(b))
  return named ? guard : [...issueBlockers(issues), ...guard]
}

const AFTER: string[] = ['released', 'closed']

const DAY = 86_400_000
const dayOf = (iso: string) => {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return Math.round(Date.UTC(y, m - 1, d) / DAY)
}
const isoOf = (day: number) => new Date(day * DAY).toISOString().slice(0, 10)
/** The last day a span occupies, as the Timing grid shows it: a milestone sits on its start. */
const lastDayOf = (start: number, endExcl: number) => (endExcl > start ? endExcl - 1 : start)
const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`

/**
 * Plan against baseline and actual, read the way the Timing tab reads it:
 * finishes are the inclusive last day of the latest real task.
 */
export function closingFigures(tasks: TaskOut[]) {
  const real = tasks.filter((t) => !t.is_idea && !t.is_summary)
  // end_date is the server's own, exclusive and calendar-aware (weekends,
  // holidays, constraints) — start_date + duration_days is plain day
  // arithmetic and can disagree with it.
  const planEnds = real.map((t) => lastDayOf(dayOf(t.start_date), dayOf(t.end_date)))
  const baseEnds = real.filter((t) => t.baseline_start && t.baseline_finish)
    .map((t) => lastDayOf(dayOf(t.baseline_start!), dayOf(t.baseline_finish!)))
  const planned = planEnds.length ? Math.max(...planEnds) : null
  const baseline = baseEnds.length ? Math.max(...baseEnds) : null
  const open = real.filter((t) => !t.actual_finish && (t.progress_pct ?? 0) < 100).length
  const finished = real.filter((t) => !!t.actual_finish).map((t) => dayOf(t.actual_finish!))
  const actual = real.length > 0 && open === 0 && finished.length ? Math.max(...finished) : null
  const slipped = real.filter((t) => t.baseline_finish && dayOf(t.end_date) > dayOf(t.baseline_finish)).length
  const against = actual ?? planned
  const slip = baseline != null && against != null ? against - baseline : null
  return {
    planned: planned != null ? isoOf(planned) : null,
    baseline: baseline != null ? isoOf(baseline) : null,
    actual: actual != null ? isoOf(actual) : null,
    open, slipped, slip, count: real.length,
  }
}

function ClosingSummary({ change, departments, canSeeCosts }: {
  change: ChangeDetail; departments: { id: number; name: string }[]; canSeeCosts: boolean
}) {
  const { data: plan } = useQuery({
    queryKey: ['change', change.id, 'plan', 'detailed'],
    queryFn: () => planApi.get(change.id, 'detailed'),
  })
  const f = closingFigures(plan?.tasks ?? [])
  const slipText = f.slip == null ? '-' : f.slip === 0 ? 'on time'
    : f.slip > 0 ? `${f.slip} d late` : `${-f.slip} d early`
  const detail = [
    f.slipped ? `${plural(f.slipped, 'task')} slipped` : null,
    f.open ? `${plural(f.open, 'task')} open` : null,
  ].filter(Boolean).join(', ')
  const cells: [string, string, string, string?][] = [
    ['Baseline finish', 'baseline-finish', fmtDate(f.baseline)],
    ['Planned finish', 'planned-finish', fmtDate(f.planned)],
    ['Actual finish', 'actual-finish', f.actual ? fmtDate(f.actual) : f.open ? plural(f.open, 'open task') : '-'],
    ['Against baseline', 'against-baseline', slipText, detail || undefined],
  ]
  return (
    <section data-testid="release-summary" className="rounded-xl border border-emerald-900/70 bg-emerald-950/10 p-4 space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-emerald-400">✓</span>
        <h3 className="text-sm font-semibold text-slate-100">
          {change.status === 'closed' ? 'Change closed' : 'Change released'}
        </h3>
      </div>
      {f.count > 0 && (
        <div className="grid gap-3 sm:grid-cols-4">
          {cells.map(([k, id, v, sub]) => (
            <div key={k}>
              <div className={sectionLabel}>{k}</div>
              <div data-testid={`summary-${id}`}
                className={`mt-0.5 text-lg font-semibold tabular-nums ${id === 'against-baseline' && f.slip != null
                  ? f.slip > 0 ? 'text-rose-400' : f.slip < 0 ? 'text-emerald-400' : 'text-slate-100'
                  : id === 'actual-finish' && !f.actual ? 'text-amber-300' : 'text-slate-100'}`}>{v}</div>
              {sub && <div data-testid={`summary-${id}-detail`} className="text-[11px] text-slate-400">{sub}</div>}
            </div>
          ))}
        </div>
      )}
      <PnlCard change={change} departments={departments} canSeeCosts={canSeeCosts} />
    </section>
  )
}

function Collapsible({ title, children, testId }: { title: string; children: ReactNode; testId?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <section data-testid={testId} className="rounded-xl border border-slate-700 bg-slate-800/40">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm text-slate-200 hover:bg-slate-800/60">
        <span className={`text-slate-500 transition-transform ${open ? 'rotate-90' : ''}`}>▸</span>
        {title}
      </button>
      {open && <div className="border-t border-slate-700/70 p-4">{children}</div>}
    </section>
  )
}

export default function ReleaseTab({
  change, departments, myDepartmentIds, canSeeAll, canAcknowledge, canManage, onAdvance, advancing,
  viewerId = null, isAdmin = false, isSales = false, focusIssueId = null,
}: ReleaseTabProps) {
  const { data: release } = useQuery({
    queryKey: releaseKey(change.id),
    queryFn: () => changeReleaseApi.get(change.id),
  })
  const { data: validation } = useQuery({
    queryKey: ['change', change.id, 'validation'],
    queryFn: () => changesApi.validationState(change.id),
  })
  const { data: issues = [] } = useValidationIssues(change.id)
  const inValidation = change.status === 'in_validation'
  const after = AFTER.includes(change.status)
  const openIssues = issues.filter(isIssueOpen).length

  const validationDone = after || ((validation?.departments?.length ?? 0) > 0 && openIssues === 0
    && (validation?.departments ?? []).every((d) => d.checks.every((c) => c.retired || c.status === 'passed')))
  const checklistDone = after || (!!release && release.checks.length > 0 && release.open_count === 0)
  const lessonsDone = !!release?.lessons?.done_at
  const releasedDone = after

  const steps: [string, boolean, string][] = [
    ['Validation checks', validationDone, 'release-validation'],
    ['Release checklist', checklistDone, 'release-checklist'],
    ['Lessons learned', lessonsDone, 'release-lessons'],
    ['Release & close', releasedDone, 'release-final'],
  ]
  const blockers = releaseBlockers(release?.blockers ?? [], issues)

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-700 bg-slate-800/60 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-100">Release</h2>
        <p className="mt-0.5 text-xs text-slate-400">
          The work is done. Departments confirm it holds, the owners tick the release checklist, the team records its
          lessons, then PM releases the change and closes it.
        </p>
        <ol data-testid="release-progress" className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {steps.map(([label, done, id], i) => (
            <li key={id}>
              <a href={`#${id}`} onClick={(e) => {
                e.preventDefault()
                document.getElementById(id)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
              }}
                className={`flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs ${done
                  ? 'border-emerald-800 bg-emerald-950/30 text-emerald-200' : 'border-slate-700 bg-slate-900/40 text-slate-300'}`}>
                <span className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold ${done
                  ? 'bg-emerald-600 text-white' : 'bg-slate-700 text-slate-300'}`}>{done ? '✓' : i + 1}</span>
                {label}
              </a>
            </li>
          ))}
        </ol>
      </div>

      {after && <ClosingSummary change={change} departments={departments} canSeeCosts={canSeeAll} />}

      <StepSection id="release-validation" n={1} title="Validation checks" done={validationDone}
        right={openIssues > 0 ? (
          <span data-testid="release-validation-issues" className="text-xs text-amber-300">
            {openIssues} issue{openIssues === 1 ? '' : 's'} open
          </span>
        ) : undefined}>
        <IssuesPanel changeId={change.id} changeStatus={change.status} departments={departments}
          viewer={{ id: viewerId, isAdmin, canManage, isSales, canSeeCosts: canSeeAll, myDepartmentIds }}
          canRaise={canManage || (validation?.departments ?? []).some((d) => myDepartmentIds.includes(d.department_id))}
          releaseDueDate={change.release_due_date} focusIssueId={focusIssueId} />
        <ValidationPanel changeId={change.id} status={change.status}
          departments={departments} myDepartmentIds={myDepartmentIds}
          canSeeAll={canSeeAll} canAcknowledge={canAcknowledge} canEscalate={canSeeAll}
          canRaiseAny={canManage} />
      </StepSection>

      <StepSection id="release-checklist" n={2} title="Release checklist" done={checklistDone}
        right={release ? (
          <span className={`text-xs ${release.open_count ? 'text-amber-300' : 'text-emerald-400'}`}>
            {release.open_count ? `${release.open_count} open` : 'all done'}
          </span>
        ) : undefined}
        hint="Each point is owned by a department. Not applicable needs a note.">
        {release ? (
          <ReleaseChecklist changeId={change.id} checks={release.checks} myDepartmentIds={myDepartmentIds}
            canManage={canManage} editable={inValidation} />
        ) : <p className="text-xs text-slate-500">Loading checklist</p>}
      </StepSection>

      <StepSection id="release-lessons" n={3} title="Lessons learned" done={lessonsDone}
        hint="What should go differently on the next change? Lessons land in the lessons learned register, linked to this change.">
        {release ? (
          <LessonsStep changeId={change.id} lessons={release.lessons}
            canAdd={inValidation || change.status === 'released'} canComplete={canManage && inValidation} />
        ) : null}
      </StepSection>

      <StepSection id="release-final" n={4} title="Release & close" done={releasedDone}>
        {inValidation && (
          <div className="space-y-2">
            {blockers.length > 0 && (
              <div data-testid="release-blockers-info"
                className="rounded-lg border border-amber-900/60 bg-amber-950/20 px-3 py-2">
                <ul data-testid="release-blockers" className="space-y-1">
                  {blockers.map((b) => (
                    <li key={b} className="text-xs text-amber-300">⏳ {b}</li>
                  ))}
                </ul>
                {canManage && (
                  <p className="mt-1 text-[11px] text-slate-400">
                    Releasing anyway asks for a deviation with a reason, which is recorded on the change.
                  </p>
                )}
              </div>
            )}
            {canManage ? (
              <button type="button" data-testid="release-change"
                disabled={advancing}
                onClick={() => onAdvance('released')}
                className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-600 disabled:opacity-50">
                Release change
              </button>
            ) : <p className="text-xs text-slate-500">PM releases the change once every step is done.</p>}
          </div>
        )}
        {change.status === 'released' && (
          canManage ? (
            <button type="button" data-testid="close-change" disabled={advancing}
              onClick={() => onAdvance('closed')}
              className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:opacity-50">
              Close change
            </button>
          ) : <p className="text-xs text-slate-500">Released. PM closes the change.</p>
        )}
        {change.status === 'closed' && <p className="text-xs text-emerald-400">✓ Closed.</p>}
      </StepSection>

      <Collapsible title="Revisions (ECN)" testId="release-revisions">
        <ImplementationPanel changeId={change.id} />
      </Collapsible>
    </div>
  )
}
