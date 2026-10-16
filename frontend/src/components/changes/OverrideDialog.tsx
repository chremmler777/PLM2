import { useId, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { TriangleAlert } from 'lucide-react'
import Dialog from '../common/Dialog'
import Button from '../common/Button'
import { changesApi } from '../../api/changes'
import { toastError } from '../../lib/apiError'
import { t } from '../../i18n/cmLabels'
import { STATUS_LABELS } from '../../lib/changeStatus'
import { ABSORB_REASONS, OVERRIDE_REASONS, absorbNoteProblem, deciderGroup, deciderText, overrideNoteProblem, ruleText } from '../../lib/overrideRules'
import type { ChangeStatus } from '../../types/change'

const fieldCls =
  'mt-1 w-full rounded-lg border border-slate-600 bg-slate-900 p-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none'

interface Common {
  changeId: number
  customerRelevant: boolean
  leadName?: string | null
  onClose: () => void
  onDone?: () => void
}

/** One reason pick, nothing preselected: a radio group. */
function ReasonPick({ name, options, prefix, value, onChange }: {
  name: string
  options: readonly string[]
  prefix: string
  value: string
  onChange: (v: string) => void
}) {
  return (
    <fieldset>
      <legend className="block text-sm text-slate-300">{t('override.why')}</legend>
      <div className="mt-1 grid gap-1 sm:grid-cols-2">
        {options.map((o) => (
          <label key={o} className="flex items-center gap-2 rounded-lg border border-slate-700 px-2 py-1.5 text-sm text-slate-200">
            <input type="radio" name={name} value={o} checked={value === o}
              data-testid={`${name}-${o}`} onChange={() => onChange(o)} />
            {t(`${prefix}.${o}`)}
          </label>
        ))}
      </div>
    </fieldset>
  )
}

/**
 * C6 (spec §0 "Override"): one button on a soft block opens this. The
 * override is bound to the rule it names: it lifts that rule only. A reason
 * pick and a note are required; the dialog says whose OK it then needs
 * (never the asker's).
 */
export default function OverrideDialog({ changeId, customerRelevant, leadName, onClose, onDone, to, rule }: Common & {
  to: ChangeStatus
  /** The soft rule (cm_rules key); none = the first rule without an override. */
  rule?: string | null
}) {
  const qc = useQueryClient()
  const [code, setCode] = useState('')
  const [note, setNote] = useState('')
  const noteId = useId()
  const noteRef = useRef<HTMLTextAreaElement>(null)
  const who = deciderText(deciderGroup(rule, to, customerRelevant), leadName)
  // R4: the same rule as the backend; said once the user started typing
  const problem = overrideNoteProblem(code, note)
  const ask = useMutation({
    mutationFn: () => changesApi.proposeDeviation(changeId, {
      to_status: to, reason: note.trim(), reason_code: code, ...(rule ? { guard_key: rule } : {}),
    }),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
      toast.success(t('override.sent').replace('{n}', String(d.id)))
      onDone?.()
      onClose()
    },
    onError: (e: unknown) => toastError(e, t('override.failed')),
  })
  return (
    <Dialog open onClose={onClose} busy={ask.isPending} closeOnBackdrop={false}
      data-testid="override-dialog"
      title={t('override.title').replace('{rule}', ruleText(rule))}
      description={t('override.lead').replace('{status}', STATUS_LABELS[to] ?? to)}
      initialFocus={noteRef as React.RefObject<HTMLElement>}
      footer={(
        <>
          <Button onClick={onClose} disabled={ask.isPending}>{t('common.cancel')}</Button>
          <Button variant="primary" data-testid="override-submit"
            disabled={!code || !!problem} loading={ask.isPending}
            onClick={() => ask.mutate()}>{t('override.submit')}</Button>
        </>
      )}>
      <div className="space-y-3">
        <ReasonPick name="override-reason" options={OVERRIDE_REASONS} prefix="override.reason"
          value={code} onChange={setCode} />
        <div>
          <label htmlFor={noteId} className="block text-sm text-slate-300">{t('override.note')}</label>
          <textarea id={noteId} ref={noteRef} data-testid="override-note"
            className={`${fieldCls} min-h-[70px]`} placeholder={t('override.notePlaceholder')}
            value={note} onChange={(e) => setNote(e.target.value)} />
          {note.trim() && problem && (
            <p data-testid="override-note-hint" className="mt-1 text-xs text-amber-300">{problem}</p>
          )}
        </div>
        <p data-testid="override-needs" className="flex items-start gap-2 rounded-lg border border-amber-700/60 bg-amber-950/40 px-3 py-2 text-xs text-amber-200">
          <TriangleAlert aria-hidden="true" size={14} className="mt-0.5 shrink-0 text-amber-300" />
          <span>{t('override.needs').replace('{who}', who)}</span>
        </p>
      </div>
    </Dialog>
  )
}

/**
 * HARD #9's exit (spec §0): absorb the open price. Reason pick + note; the
 * OK of a Project Management or Management member (internal: the approver)
 * clears it.
 */
export function AbsorbDialog({ changeId, customerRelevant, approvers, onClose, onDone }: Common & {
  /** HARD #8: the internal approvers in words (stage-state), named instead of "the internal approver". */
  approvers?: string | null
}) {
  const qc = useQueryClient()
  const [code, setCode] = useState('')
  const [note, setNote] = useState('')
  const noteId = useId()
  const noteRef = useRef<HTMLTextAreaElement>(null)
  const who = !customerRelevant && approvers
    ? approvers
    : deciderText(deciderGroup('price_open', 'closed', customerRelevant))
  const problem = absorbNoteProblem(code, note)
  const ask = useMutation({
    mutationFn: () => changesApi.absorb(changeId, { reason_code: code, note: note.trim() }),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
      toast.success(t('absorb.sent').replace('{n}', String(d.id)))
      onDone?.()
      onClose()
    },
    onError: (e: unknown) => toastError(e, t('absorb.failed')),
  })
  return (
    <Dialog open onClose={onClose} busy={ask.isPending} closeOnBackdrop={false}
      data-testid="absorb-dialog" title={t('absorb.title')} description={t('absorb.lead')}
      initialFocus={noteRef as React.RefObject<HTMLElement>}
      footer={(
        <>
          <Button onClick={onClose} disabled={ask.isPending}>{t('common.cancel')}</Button>
          <Button variant="primary" data-testid="absorb-submit"
            disabled={!code || !!problem} loading={ask.isPending}
            onClick={() => ask.mutate()}>{t('absorb.submit')}</Button>
        </>
      )}>
      <div className="space-y-3">
        <ReasonPick name="absorb-reason" options={ABSORB_REASONS} prefix="absorb.reason"
          value={code} onChange={setCode} />
        <div>
          <label htmlFor={noteId} className="block text-sm text-slate-300">{t('absorb.note')}</label>
          <textarea id={noteId} ref={noteRef} data-testid="absorb-note"
            className={`${fieldCls} min-h-[70px]`} placeholder={t('absorb.notePlaceholder')}
            value={note} onChange={(e) => setNote(e.target.value)} />
          {note.trim() && problem && (
            <p data-testid="absorb-note-hint" className="mt-1 text-xs text-amber-300">{problem}</p>
          )}
        </div>
        <p data-testid="absorb-needs" className="text-xs text-amber-200">
          {t('override.needs').replace('{who}', who)}
        </p>
      </div>
    </Dialog>
  )
}
