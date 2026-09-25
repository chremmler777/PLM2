/**
 * Timing tab (spec 2026-09-25 §1 approved / in_implementation).
 *
 * Three steps, one card: build the detailed plan, get every responsible team
 * to confirm it, then "Timing validated" sets the baseline and the plan turns
 * into a tracker. After that every date move is a deviation that PM/Sales lock
 * or escalate. The bank-build decision and the department tracking of stage 8
 * sit underneath, unchanged.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { planApi } from '../../../api/changePlan'
import { CHANGE_STATUS_ORDER, type ChangeRequest, type ChangeStatus } from '../../../types/change'
import BankBuildCard from '../BankBuildCard'
import ImplementationTracking from '../ImplementationTracking'
import GanttPlanner from '../plan/GanttPlanner'
import { formatDate } from '../../../lib/format'
import DeviationsPanel from './DeviationsPanel'
import TeamFeedbackPanel from './TeamFeedbackPanel'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const phase = (s: string) => CHANGE_STATUS_ORDER.indexOf(s as ChangeStatus)

export interface TimingTabProps {
  change: ChangeRequest
  departments: { id: number; name: string; is_active?: boolean }[]
  myDepartmentIds: number[]
  canEditPlan: boolean
  canPublish: boolean
  canSeeAll: boolean
  /** Bank-build mode: Scheduling, PM, lead, admin (not Sales). */
  canSetBankBuild?: boolean
  /** Deviation lock / escalate: PM, Sales, lead, admin. */
  canDecideDeviation?: boolean
  /** Admin answers the team confirmation for any department. */
  isAdmin?: boolean
}

const btn = 'rounded-md border border-slate-600 bg-slate-800 px-2.5 py-1.5 text-xs text-slate-200 hover:bg-slate-700 disabled:opacity-40'
const primary = 'rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-40'

function Step({ n, title, detail, state }: {
  n: number; title: string; detail: string; state: 'done' | 'current' | 'todo'
}) {
  const dot = state === 'done' ? 'bg-emerald-600 text-white border-emerald-500'
    : state === 'current' ? 'bg-sky-700 text-white border-sky-500' : 'bg-slate-900 text-slate-500 border-slate-600'
  return (
    <li className="flex min-w-0 flex-1 items-start gap-2" data-testid={`timing-step-${n}`} data-state={state}>
      <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold ${dot}`}>
        {state === 'done' ? '✓' : n}
      </span>
      <div className="min-w-0">
        <p className={`text-sm ${state === 'todo' ? 'text-slate-500' : 'text-slate-100'}`}>{title}</p>
        <p className="truncate text-xs text-slate-400">{detail}</p>
      </div>
    </li>
  )
}

export default function TimingTab({
  change, departments, myDepartmentIds, canEditPlan, canPublish, canSeeAll,
  canSetBankBuild = false, canDecideDeviation = false, isAdmin = false,
}: TimingTabProps) {
  const qc = useQueryClient()
  const id = change.id
  const { data: plan } = useQuery({
    queryKey: ['change', id, 'plan', 'detailed'], queryFn: () => planApi.get(id, 'detailed'),
  })
  const { data: feedback, isPending: feedbackPending, isError: feedbackError, refetch: refetchFeedback } = useQuery({
    queryKey: ['change', id, 'plan-feedback'], queryFn: () => planApi.feedback(id),
  })
  const baseline = !!plan?.baseline_set || !!feedback?.validated_at
  const { data: deviations = [] } = useQuery({
    queryKey: ['change', id, 'plan-deviations'], queryFn: () => planApi.deviations(id),
    enabled: baseline,
  })

  const status = change.status
  const implementing = phase(status) >= phase('in_implementation')
  const mode = baseline || implementing ? 'track' : 'plan'
  const tasks = plan?.tasks ?? []
  const empty = !!plan && tasks.length === 0
  const required = feedback?.required ?? []
  const confirmed = required.filter((r) => r.verdict === 'confirmed' && !r.stale).length
  const ideas = tasks.filter((t) => t.is_idea).length
  const errors = plan?.validation.errors.length ?? 0

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ['change', id] })
    qc.invalidateQueries({ queryKey: ['change-my-actions', id] })
  }
  const seed = useMutation({
    mutationFn: () => planApi.seed(id, 'detailed'),
    onSuccess: (p) => { qc.setQueryData(['change', id, 'plan', 'detailed'], p); invalidateAll() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not create the detailed plan'),
  })
  const validate = useMutation({
    mutationFn: () => planApi.validateTiming(id),
    onSuccess: () => { toast.success('Timing validated. The baseline is set.'); invalidateAll() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not validate the timing'),
  })
  const publish = useMutation({
    mutationFn: () => planApi.publishPlan(id),
    onSuccess: () => { toast.success('Plan published to the customer'); invalidateAll() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not publish the plan'),
  })
  const exportAs = (fmt: 'xml' | 'csv') =>
    (fmt === 'xml' ? planApi.exportXml(id, 'detailed') : planApi.exportCsv(id, 'detailed'))
      .catch((e: unknown) => toast.error(errDetail(e) ?? 'Export failed'))

  // Why "Validate timing" is not available yet, in the words of the backend guard.
  const blockers: string[] = []
  if (status !== 'approved' && status !== 'in_implementation') blockers.push('Timing is validated while the change is approved or in implementation.')
  if (tasks.length === 0) blockers.push('Create the detailed plan first.')
  if (errors > 0) blockers.push(`Fix ${errors} plan error${errors === 1 ? '' : 's'} (see the issues above the chart).`)
  if (ideas > 0) blockers.push(`Resolve ${ideas} idea block${ideas === 1 ? '' : 's'}: turn ${ideas === 1 ? 'it' : 'them'} into real tasks or delete ${ideas === 1 ? 'it' : 'them'}.`)
  const waiting = required.filter((r) => !(r.verdict === 'confirmed' && !r.stale))
  if (waiting.length > 0) {
    const concern = waiting.filter((r) => r.verdict === 'concern' && !r.stale)
    const rest = waiting.filter((r) => !(r.verdict === 'concern' && !r.stale))
    if (concern.length) blockers.push(`Open concern from ${concern.map((r) => r.department_name).join(', ')}.`)
    if (rest.length) blockers.push(`Waiting for confirmation from ${rest.map((r) => r.department_name).join(', ')}.`)
  }
  const canValidate = canEditPlan || canPublish
  const timingValidated = !!change.timing_validated_at || !!feedback?.validated_at
  const internal = !change.customer_relevant

  const step1: 'done' | 'current' = tasks.length > 0 ? 'done' : 'current'
  // Until the feedback arrives the confirmations are unknown: keep step 2 open.
  const feedbackLoading = feedbackPending
  const step2 = tasks.length === 0 ? 'todo' : baseline ? 'done' : feedbackLoading || waiting.length > 0 ? 'current' : 'done'
  const step3 = baseline ? 'done' : step2 === 'done' ? 'current' : 'todo'

  return (
    <div className="space-y-4" data-testid="timing-tab">
      <section className="rounded-lg border border-slate-700 bg-slate-800 p-4 space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-xs uppercase tracking-wide text-slate-500">Timing</h3>
            <p className="mt-1 text-sm text-slate-200">
              {baseline
                ? 'Timing is validated. Track progress against the baseline; every date move is recorded as a deviation.'
                : 'Validate the timing with every team, then track it.'}
            </p>
          </div>
          {tasks.length > 0 && (
            <div className="flex gap-2">
              <button type="button" className={btn} onClick={() => exportAs('xml')} aria-label="Export to MS Project">MS Project</button>
              <button type="button" className={btn} onClick={() => exportAs('csv')} aria-label="Export as CSV">CSV</button>
            </div>
          )}
        </div>

        <ol className="flex flex-col gap-3 sm:flex-row sm:gap-6">
          <Step n={1} title="Detailed plan" state={step1}
            detail={tasks.length > 0 ? `${tasks.length} task${tasks.length === 1 ? '' : 's'}` : 'Copy the quote plan and refine it'} />
          <Step n={2} title="Team confirmation" state={step2}
            detail={feedbackError && !baseline ? 'Could not load confirmations'
              : feedbackLoading && !baseline ? 'Loading confirmations'
              : required.length > 0 ? `${confirmed} of ${required.length} confirmed` : 'Every responsible team confirms'} />
          <Step n={3} title={baseline ? 'Timing validated' : 'Validate timing'} state={step3}
            detail={baseline
              ? `${formatDate(feedback?.validated_at ?? change.timing_validated_at)}${feedback?.validated_by_name ? `, ${feedback.validated_by_name}` : ''}`
              : 'Timing validated sets the baseline'} />
        </ol>

        {feedbackError && !baseline && (
          <button type="button" data-testid="timing-feedback-error"
            className="text-xs text-red-300 underline hover:text-red-200"
            onClick={() => refetchFeedback()}>
            Could not load confirmations. Retry
          </button>
        )}

        <div className="border-t border-slate-700 pt-3" data-testid="timing-primary">
          {empty ? (
            canEditPlan ? (
              <div className="flex flex-wrap items-center gap-3">
                <button type="button" className={primary} disabled={seed.isPending} onClick={() => seed.mutate()}
                  data-testid="timing-seed">Create detailed plan from quote plan</button>
                <span className="text-xs text-slate-400">Copies every block of the quote plan, links and ideas included. Then refine it with the teams.</span>
              </div>
            ) : (
              <p className="text-sm text-slate-400">The detailed plan is not created yet. PM, Scheduling or Sales start it from the quote plan.</p>
            )
          ) : !baseline ? (
            canValidate ? (
              <div className="space-y-2">
                <button type="button" className={primary} disabled={blockers.length > 0 || validate.isPending}
                  onClick={() => validate.mutate()} data-testid="timing-validate">Validate timing</button>
                {blockers.length > 0 ? (
                  <ul className="space-y-0.5 text-xs text-amber-200/90" data-testid="timing-blockers">
                    {blockers.map((b) => <li key={b} className="flex gap-1.5"><span className="text-amber-400">&#8226;</span>{b}</li>)}
                  </ul>
                ) : (
                  <p className="text-xs text-slate-400">Every team confirmed. Validating sets the baseline; later date changes need a reason.</p>
                )}
              </div>
            ) : (
              <p className="text-sm text-slate-400">
                {waiting.length > 0 ? 'Waiting for every team to confirm. PM, Scheduling or Sales then validate the timing.' : 'Every team confirmed. PM, Scheduling or Sales validate the timing next.'}
              </p>
            )
          ) : (
            <div className="flex flex-wrap items-center gap-3">
              {change.plan_published_at ? (
                <p className="text-sm text-emerald-300" data-testid="timing-published">
                  Published to the customer {formatDate(change.plan_published_at)}{change.plan_published_by_name ? ` by ${change.plan_published_by_name}` : ''}.
                </p>
              ) : status !== 'approved' ? (
                <p className="text-sm text-slate-400">Timing validated. Track progress below.</p>
              ) : !change.bank_build_mode ? (
                <p className="text-sm text-amber-200/90" data-testid="timing-publish-needs-mode">
                  {internal
                    ? 'Set how the change reaches the line (bank build below) before implementation starts.'
                    : 'Set how the change reaches the line first (bank build below), then the plan can go to the customer.'}
                </p>
              ) : internal ? (
                // Internal changes have no customer to publish to.
                <p className="text-sm text-slate-300" data-testid="timing-validated-internal">Timing validated. Track progress below.</p>
              ) : !timingValidated ? null : canPublish ? (
                <>
                  <button type="button" className={primary} disabled={publish.isPending}
                    onClick={() => publish.mutate()} data-testid="timing-publish">Publish plan to customer</button>
                  <span className="text-xs text-slate-400">Records that Sales sent the validated timing to the customer. Export it above to attach.</span>
                </>
              ) : (
                <p className="text-sm text-slate-400">Sales publishes the validated plan to the customer.</p>
              )}
            </div>
          )}
        </div>
      </section>

      {plan && tasks.length > 0 && !plan.can_edit && !plan.can_edit_dates && (
        <p data-testid="timing-readonly"
          className="inline-flex items-center gap-1.5 rounded-full border border-slate-600 bg-slate-800 px-2.5 py-0.5 text-[11px] text-slate-400"
          title="PM, Scheduling, Sales, the change lead and admins edit the plan; teams update the progress of their own tasks.">
          Read only{plan.progress_department_ids?.length ? ': you update the progress of your own tasks' : ''}
        </p>
      )}
      {/* The detailed plan is created by the "Create detailed plan" button in
          the card above; the Gantt's own seed button would be a second way in. */}
      <GanttPlanner changeId={id} plan="detailed" mode={mode} hideSeed />

      {tasks.length > 0 && (
        <TeamFeedbackPanel changeId={id} feedback={feedback} myDepartmentIds={myDepartmentIds}
          isAdmin={isAdmin} canRespond={!baseline && status === 'approved'} />
      )}

      {baseline && (
        <DeviationsPanel changeId={id} deviations={deviations} canDecide={canDecideDeviation} status={status} />
      )}

      {/* Publishing lives in the Timing card above: only a validated timing goes to the customer. */}
      <BankBuildCard change={change} canSetMode={canSetBankBuild} canPublish={canPublish} hidePublish />

      {implementing && (
        <ImplementationTracking changeId={id} status={status} departments={departments}
          myDepartmentIds={myDepartmentIds} canSeeAll={canSeeAll} canEscalate={canPublish} />
      )}
    </div>
  )
}
