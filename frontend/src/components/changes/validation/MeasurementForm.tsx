/**
 * ECR-solid §10: a computed check (weight, cycle time, APQP's dimensions).
 *
 * The verdict is not picked, it is computed: sample size n, the smallest and
 * the largest value, the measuring report or device id (cycle time: the
 * lot), held against the limits the first measurement fixed. PASS only if
 * both lie inside. A retest adds a row, keeps the failed one, and says what
 * changed since (parameter / tool / material / method + reference).
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { changesApi } from '../../../api/changes'
import { validationIssuesKey } from '../../../api/validationIssues'
import type { RetestChangeKind, ValidationCheck, ValidationMeasurementIn } from '../../../types/change'
import { readNumberInput } from '../../../lib/format'
import { toastError } from '../../../lib/apiError'
import { btnSm } from '../../common/buttonStyles'
import { t } from '../../../i18n/cmLabels'
import { refOk } from '../../../lib/evidence'

const KINDS: RetestChangeKind[] = ['parameter', 'tool', 'material', 'method']
const fieldCls = 'bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100'

/** A reference that names something: the shared rule (lib/evidence). */
export { refOk }

export interface MeasureDraft {
  n: string; min: string; max: string; ref: string; lot: string
  lower: string; upper: string; source: string
  kind: RetestChangeKind | ''; changed: string
}

/** The body to send, or why not yet (null body). Pure, tested on its own. */
export function measurementBody(check: Pick<ValidationCheck, 'lower_limit' | 'upper_limit' | 'needs_lot' | 'status'>,
  d: MeasureDraft): { body: ValidationMeasurementIn | null; why: string | null } {
  const n = Number(d.n)
  if (!Number.isInteger(n) || n < 1) return { body: null, why: t('validation.sampleSize') }
  const lo = readNumberInput(d.min).value
  const hi = readNumberInput(d.max).value
  if (lo == null || hi == null) return { body: null, why: `${t('validation.min')} / ${t('validation.max')}` }
  if (lo > hi) return { body: null, why: 'Min > Max' }
  if (!refOk(d.ref)) return { body: null, why: t('validation.measuringRef') }
  if (check.needs_lot && !refOk(d.lot)) return { body: null, why: t('validation.lotRef') }
  const body: ValidationMeasurementIn = { sample_size: n, min_value: lo, max_value: hi, measuring_ref: d.ref.trim() }
  if (check.needs_lot) body.lot_ref = d.lot.trim()
  if (check.lower_limit == null || check.upper_limit == null) {
    const l = readNumberInput(d.lower).value
    const u = readNumberInput(d.upper).value
    if (l == null || u == null || l >= u) return { body: null, why: t('validation.limits') }
    if (!refOk(d.source)) return { body: null, why: t('validation.specSource') }
    Object.assign(body, { lower_limit: l, upper_limit: u, spec_source: d.source.trim() })
  }
  if (check.status === 'failed') {
    if (!d.kind || !refOk(d.changed)) return { body: null, why: t('validation.whatChanged') }
    Object.assign(body, { what_changed_kind: d.kind, what_changed_ref: d.changed.trim() })
  }
  return { body, why: null }
}

export function MeasurementHistory({ check, id }: { check: ValidationCheck; id: string }) {
  const rows = check.measurements ?? []
  const who = check.limits_set_by_name ?? '-'
  return (
    <div className="space-y-0.5">
      {check.lower_limit != null && check.upper_limit != null && (
        <p data-testid={`validation-limits-${id}`} className="text-[11px] text-slate-400">
          {t('validation.limitsFixed').replace('{lo}', String(check.lower_limit))
            .replace('{hi}', String(check.upper_limit)).replace('{u}', check.unit_short ?? '')
            .replace('{src}', check.spec_source ?? '-')}
          {check.limits_set_by_name && `, ${t('validation.limitsSetBy').replace('{who}', who)}`}
          {check.limits_confirmed_by_name && `, ${t('validation.limitsConfirmedBy').replace('{who}', check.limits_confirmed_by_name)}`}
        </p>
      )}
      {check.limits_pending && (
        <p data-testid={`validation-limits-pending-${id}`} className="text-[11px] text-amber-300">
          {t('validation.limitsPending').replace('{who}', who)}
        </p>
      )}
      {rows.length > 0 && (
        <ul data-testid={`validation-measurements-${id}`} aria-label={t('validation.measurements')} className="space-y-0.5">
          {rows.map((m) => (
            <li key={m.id} className="flex flex-wrap items-center gap-1.5 text-[11px] text-slate-300">
              <span className={`rounded px-1 py-px font-semibold ${m.result === 'passed'
                ? 'bg-emerald-900/70 text-emerald-200' : 'bg-red-900/80 text-red-100'}`}>
                {t(`validation.status.${m.result}`)}
              </span>
              <span className="tabular-nums">{m.line}</span>
              {m.what_changed_kind && (
                <span className="text-slate-400">
                  ({t('validation.retestTitle')}: {t(`validation.changed.${m.what_changed_kind}`)}, {m.what_changed_ref})
                </span>
              )}
              {m.measured_by_name && <span className="text-slate-500">{m.measured_by_name}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function MeasurementForm({ changeId, deptId, check, id, prefillNominal }: {
  changeId: number
  deptId: number
  check: ValidationCheck
  id: string
  /** The weight the quote was built on: a starting point for the limits. */
  prefillNominal?: number | null
}) {
  const qc = useQueryClient()
  const [d, setD] = useState<MeasureDraft>({
    n: '', min: '', max: '', ref: '', lot: '', lower: '', upper: '', source: '', kind: '', changed: '',
  })
  const set = (k: keyof MeasureDraft) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setD((x) => ({ ...x, [k]: e.target.value }))
  const { body, why } = measurementBody(check, d)
  const firstLimits = check.lower_limit == null || check.upper_limit == null
  const retest = check.status === 'failed'
  const post = useMutation({
    mutationFn: () => changesApi.setValidationCheck(changeId, {
      department_id: deptId, check_key: String(check.check_key), measurement: body!,
    }),
    onSuccess: () => {
      setD((x) => ({ ...x, n: '', min: '', max: '', kind: '', changed: '' }))
      qc.invalidateQueries({ queryKey: ['change', changeId, 'validation'] })
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
      qc.invalidateQueries({ queryKey: ['change', changeId, 'release'] })
      qc.invalidateQueries({ queryKey: validationIssuesKey(changeId) })
    },
    onError: (e: unknown) => toastError(e, 'Could not record the measurement'),
  })
  const u = check.unit_short ?? ''
  return (
    <div data-testid={`validation-measure-${id}`} className="space-y-1.5 rounded border border-slate-700 bg-slate-900/30 p-2">
      <p className="text-[11px] text-slate-400">{t('validation.measureIntro')}</p>
      {firstLimits && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-slate-400">{t('validation.limits')} ({u})</span>
          <input data-testid={`validation-lower-${id}`} aria-label={t('validation.lower')} placeholder={t('validation.lower')}
            inputMode="decimal" value={d.lower} onChange={set('lower')} className={`w-24 ${fieldCls}`} />
          <input data-testid={`validation-upper-${id}`} aria-label={t('validation.upper')} placeholder={t('validation.upper')}
            inputMode="decimal" value={d.upper} onChange={set('upper')} className={`w-24 ${fieldCls}`} />
          <input data-testid={`validation-source-${id}`} aria-label={t('validation.specSource')}
            placeholder={prefillNominal != null ? `${t('validation.specSource')}: ${prefillNominal} ${u}` : t('validation.specSource')}
            value={d.source} onChange={set('source')} className={`flex-1 min-w-[12rem] ${fieldCls}`} />
        </div>
      )}
      <div className="flex flex-wrap items-center gap-1.5">
        <input data-testid={`validation-n-${id}`} aria-label={t(check.needs_lot ? 'validation.sampleSizeCycles' : 'validation.sampleSize')}
          placeholder={t(check.needs_lot ? 'validation.sampleSizeCycles' : 'validation.sampleSize')}
          inputMode="numeric" value={d.n} onChange={set('n')} className={`w-20 ${fieldCls}`} />
        <input data-testid={`validation-min-${id}`} aria-label={`${t('validation.min')} (${u})`} placeholder={`${t('validation.min')} (${u})`}
          inputMode="decimal" value={d.min} onChange={set('min')} className={`w-24 ${fieldCls}`} />
        <input data-testid={`validation-max-${id}`} aria-label={`${t('validation.max')} (${u})`} placeholder={`${t('validation.max')} (${u})`}
          inputMode="decimal" value={d.max} onChange={set('max')} className={`w-24 ${fieldCls}`} />
        <input data-testid={`validation-ref-${id}`} aria-label={t('validation.measuringRef')} placeholder={t('validation.measuringRef')}
          value={d.ref} onChange={set('ref')} className={`flex-1 min-w-[10rem] ${fieldCls}`} />
        {check.needs_lot && (
          <input data-testid={`validation-lot-${id}`} aria-label={t('validation.lotRef')} placeholder={t('validation.lotRef')}
            value={d.lot} onChange={set('lot')} className={`w-32 ${fieldCls}`} />
        )}
      </div>
      {retest && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-amber-300">{t('validation.whatChanged')}</span>
          <select data-testid={`validation-changed-kind-${id}`} aria-label={t('validation.whatChanged')}
            value={d.kind} onChange={set('kind')} className={fieldCls}>
            <option value="">-</option>
            {KINDS.map((k) => <option key={k} value={k}>{t(`validation.changed.${k}`)}</option>)}
          </select>
          <input data-testid={`validation-changed-ref-${id}`} aria-label={t('validation.whatChangedRef')}
            placeholder={t('validation.whatChangedRef')} value={d.changed} onChange={set('changed')}
            className={`flex-1 min-w-[12rem] ${fieldCls}`} />
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" data-testid={`validation-measure-submit-${id}`} disabled={!body || post.isPending}
          onClick={() => post.mutate()} className={btnSm.secondary}>
          {t('validation.measure')}
        </button>
        {why && (d.n || d.min || d.max || d.ref) && (
          <span data-testid={`validation-measure-why-${id}`} className="text-[11px] text-slate-400">{why}</span>
        )}
      </div>
    </div>
  )
}

/** A5-02 / D5: APQP's one click on the measurer's limits, or a correction
 *  (the latest measurement is judged against the corrected limits). Shown
 *  only when the backend says this viewer may (can_confirm_limits). */
export function LimitsConfirm({ changeId, check, id }: { changeId: number; check: ValidationCheck; id: string }) {
  const qc = useQueryClient()
  const [correcting, setCorrecting] = useState(false)
  const [lo, setLo] = useState('')
  const [hi, setHi] = useState('')
  const [src, setSrc] = useState('')
  const loR = readNumberInput(lo)
  const hiR = readNumberInput(hi)
  const correctionOk = loR.value !== null && hiR.value !== null && loR.value < hiR.value && refOk(src)
  const save = useMutation({
    mutationFn: (corrected: boolean) => changesApi.confirmValidationLimits(changeId, check.check_id!,
      corrected ? { lower_limit: loR.value!, upper_limit: hiR.value!, spec_source: src.trim() } : {}),
    onSuccess: () => {
      setCorrecting(false)
      qc.invalidateQueries({ queryKey: ['change', changeId, 'validation'] })
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
      qc.invalidateQueries({ queryKey: ['change', changeId, 'release'] })
      qc.invalidateQueries({ queryKey: validationIssuesKey(changeId) })
    },
    onError: (e: unknown) => toastError(e, 'Could not confirm the limits'),
  })
  if (!check.can_confirm_limits || check.check_id == null) return null
  const u = check.unit_short ?? ''
  return (
    <div data-testid={`validation-limits-confirm-${id}`} className="flex flex-wrap items-center gap-1.5">
      <button type="button" data-testid={`validation-limits-ok-${id}`} disabled={save.isPending}
        onClick={() => save.mutate(false)} className={btnSm.primary}>
        {t('validation.limitsConfirm')}
      </button>
      {!correcting ? (
        <button type="button" data-testid={`validation-limits-correct-${id}`} onClick={() => setCorrecting(true)}
          className={btnSm.ghost}>{t('validation.limitsCorrect')}</button>
      ) : (
        <>
          <input aria-label={`${t('validation.lower')} (${u})`} placeholder={`${t('validation.lower')} (${u})`} inputMode="decimal"
            data-testid={`validation-limits-lower-${id}`} value={lo} onChange={(e) => setLo(e.target.value)} className={`w-24 ${fieldCls}`} />
          <input aria-label={`${t('validation.upper')} (${u})`} placeholder={`${t('validation.upper')} (${u})`} inputMode="decimal"
            data-testid={`validation-limits-upper-${id}`} value={hi} onChange={(e) => setHi(e.target.value)} className={`w-24 ${fieldCls}`} />
          <input aria-label={t('validation.specSource')} placeholder={t('validation.specSource')}
            data-testid={`validation-limits-source-${id}`} value={src} onChange={(e) => setSrc(e.target.value)}
            className={`flex-1 min-w-[12rem] ${fieldCls}`} />
          <button type="button" data-testid={`validation-limits-save-${id}`} disabled={!correctionOk || save.isPending}
            onClick={() => save.mutate(true)} className={btnSm.secondary}>{t('validation.limitsCorrectSave')}</button>
        </>
      )}
    </div>
  )
}
