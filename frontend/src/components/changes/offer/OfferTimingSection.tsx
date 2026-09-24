/**
 * Step 1 of the offer: the rough timing. The quote plan Gantt (shared
 * component) plus how the offer states it: included or not, weeks from order
 * and the disclaimer that keeps the dates a draft.
 */
import { useQuery } from '@tanstack/react-query'
import GanttPlanner from '../plan/GanttPlanner'
import { planApi } from '../../../api/changePlan'
import type { OfferData } from '../../../types/changeOffer'
import { DEFAULT_DISCLAIMER, inputCls, planWeeks, quotePlanKey } from './offerFormat'
import { Field, NumField, Toggle } from './ui'

export default function OfferTimingSection({
  changeId, data, update, editable,
}: {
  changeId: number
  /** Absent before an offer exists: the Gantt alone. */
  data?: OfferData
  update?: <K extends keyof OfferData>(key: K, value: OfferData[K]) => void
  editable: boolean
}) {
  const { data: plan } = useQuery({
    queryKey: quotePlanKey(changeId),
    queryFn: () => planApi.get(changeId, 'quote'),
  })
  const timing = data?.timing ?? { include: true }
  const auto = planWeeks(plan?.summary?.duration_days)
  const set = (patch: Partial<NonNullable<OfferData['timing']>>) =>
    update?.('timing', { ...timing, ...patch })

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-400">
        Rough timing for the offer. Move blocks, run work in parallel, add a bank build idea and safety buffers.
        Dates are revisited after order.
      </p>
      <div className="-mx-1 overflow-x-auto">
        <GanttPlanner changeId={changeId} plan="quote" />
      </div>
      {data && update && (
        <div className="grid gap-3 rounded-lg border border-slate-700 bg-slate-900/40 p-3 sm:grid-cols-[auto_10rem_minmax(0,1fr)]">
          <label className="flex items-center gap-2 self-end pb-1.5 text-sm text-slate-200">
            <Toggle checked={timing.include !== false} disabled={!editable} label="Include timing in the offer"
              testId="timing-include" onChange={(v) => set({ include: v })} />
            Include in offer
          </label>
          <Field label={auto != null ? `Weeks from order (plan: ${auto})` : 'Weeks from order'}>
            <div className="flex items-center gap-1">
              <NumField value={timing.weeks_from_order} disabled={!editable || timing.include === false}
                ariaLabel="Weeks from order" testId="timing-weeks"
                onChange={(v) => set({ weeks_from_order: v })} />
              {editable && auto != null && auto !== timing.weeks_from_order && (
                <button type="button" title="Take the weeks from the plan"
                  className="text-xs text-sky-300 hover:text-sky-200"
                  onClick={() => set({ weeks_from_order: auto })}>↺</button>
              )}
            </div>
          </Field>
          <Field label="Disclaimer (italic in the offer)">
            <textarea rows={2} className={`${inputCls} w-full`}
              disabled={!editable || timing.include === false}
              value={timing.disclaimer ?? DEFAULT_DISCLAIMER}
              onChange={(e) => set({ disclaimer: e.target.value })} />
          </Field>
        </div>
      )}
    </div>
  )
}
