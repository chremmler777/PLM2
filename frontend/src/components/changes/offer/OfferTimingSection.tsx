/**
 * Step 1 of the offer: the rough timing. The quote plan Gantt (shared
 * component) plus how the offer states it: included or not, weeks from order
 * and the disclaimer that keeps the dates a draft.
 */
import { useQuery } from '@tanstack/react-query'
import { RotateCcw } from 'lucide-react'
import GanttPlanner from '../plan/GanttPlanner'
import { planApi } from '../../../api/changePlan'
import type { OfferData } from '../../../types/changeOffer'
import { DEFAULT_DISCLAIMER, fmtDate, inputCls, planWeeks, quotePlanKey } from './offerFormat'
import { Field, NumField, Toggle } from './ui'

export default function OfferTimingSection({
  changeId, changeNumber, data, update, editable, fieldsDisabled, readOnly = false,
}: {
  changeId: number
  /** For export file names. */
  changeNumber?: string
  /** Absent before an offer exists: the Gantt alone. */
  data?: OfferData
  update?: <K extends keyof OfferData>(key: K, value: OfferData[K]) => void
  editable: boolean
  /** True while a costing refresh is rewriting the draft: disables only the
   * offer's own timing fields below, never the Gantt planner above (it is
   * its own tool, unaffected by the offer refresh). */
  fieldsDisabled?: boolean
  /** The customer accepted: the quote plan is the offered timing and stays as
   *  it was (the planner renders read-only, without its editing tools). */
  readOnly?: boolean
}) {
  const { data: plan } = useQuery({
    queryKey: quotePlanKey(changeId),
    queryFn: () => planApi.get(changeId, 'quote'),
  })
  const timing = data?.timing ?? { include: true }
  // The plan summary's span leaves idea blocks out (backend plan_out), so
  // the weeks never count an option; the offer's own weeks_from_order too.
  const auto = planWeeks(plan?.summary)
  const milestones = timing.milestones ?? []
  const set = (patch: Partial<NonNullable<OfferData['timing']>>) =>
    update?.('timing', { ...timing, ...patch })

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-400">
        {readOnly
          ? 'The timing the customer accepted. It stays as offered; the detailed plan takes over from here.'
          : 'Rough timing for the offer. Move blocks, run work in parallel, add a bank build idea and safety buffers. Dates are revisited after order.'}
      </p>
      <div className="-mx-1 overflow-x-auto" data-testid="offer-timing-planner" data-readonly={readOnly || undefined}>
        <GanttPlanner changeId={changeId} plan="quote" changeNumber={changeNumber} compact={readOnly} />
      </div>
      {data && update && (
        <fieldset disabled={fieldsDisabled} aria-busy={fieldsDisabled}
          className="m-0 grid items-start gap-3 rounded-lg border border-slate-700 bg-slate-900/40 p-3 sm:grid-cols-[auto_12rem_minmax(0,1fr)]">
          <label className="flex items-center gap-2 self-center whitespace-nowrap pt-4 text-sm text-slate-200">
            <Toggle checked={timing.include !== false} disabled={!editable || readOnly} label="Include timing in the offer"
              testId="timing-include" onChange={(v) => set({ include: v })} />
            Include in offer
          </label>
          <Field label={auto != null ? `Weeks from order (plan: ${auto})` : 'Weeks from order'}>
            <div className="flex min-w-0 items-center gap-1">
              <NumField value={timing.weeks_from_order} disabled={!editable || readOnly || timing.include === false}
                ariaLabel="Weeks from order" testId="timing-weeks" className="w-20 min-w-0"
                onChange={(v) => set({ weeks_from_order: v })} />
              <span className="text-xs text-slate-500">weeks</span>
              {editable && !readOnly && auto != null && auto !== timing.weeks_from_order && (
                <button type="button" title="Take the weeks from the plan" aria-label={`Take the weeks from the plan (${auto})`}
                  className="inline-flex h-6 w-6 items-center justify-center rounded text-sky-300 hover:bg-slate-800 hover:text-sky-200"
                  onClick={() => set({ weeks_from_order: auto })}>
                  <RotateCcw aria-hidden="true" size={13} />
                </button>
              )}
            </div>
          </Field>
          <Field label="Disclaimer (italic in the offer)">
            <textarea rows={2} className={`${inputCls} w-full`}
              disabled={!editable || readOnly || timing.include === false}
              value={timing.disclaimer ?? DEFAULT_DISCLAIMER}
              onChange={(e) => set({ disclaimer: e.target.value })} />
          </Field>
        </fieldset>
      )}
      {data && milestones.length > 0 && (
        <div data-testid="offer-timing-milestones">
          <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-slate-500">Milestones in the offer</p>
          <ul className="flex flex-wrap gap-1.5">
            {milestones.map((m, i) => (
              <li key={`${m.label}-${m.date}-${i}`} data-testid="offer-timing-milestone" data-idea={m.idea || undefined}
                title={m.idea ? 'Option: an idea block of the quote plan, not committed. It does not count in the weeks from order.' : undefined}
                className={m.idea
                  ? 'inline-flex items-center gap-1.5 rounded border border-dashed border-slate-500 bg-[repeating-linear-gradient(135deg,transparent_0_4px,rgba(148,163,184,0.18)_4px_6px)] px-2 py-0.5 text-xs text-slate-300'
                  : 'inline-flex items-center gap-1.5 rounded border border-slate-700 bg-slate-800/60 px-2 py-0.5 text-xs text-slate-200'}>
                <span className="font-medium">{m.label}</span>
                <span className="tabular-nums text-slate-400">{fmtDate(m.date)}</span>
                {m.idea && (
                  <span className="rounded bg-slate-700 px-1 text-[10px] font-semibold uppercase tracking-wide text-slate-200">Option</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
