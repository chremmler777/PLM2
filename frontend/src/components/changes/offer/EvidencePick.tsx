/**
 * The customer's evidence picker (spec §0 Evidence, R4): a customer mail or
 * document filed on the change, newest first. Internal uploads (kind
 * 'general', e.g. the baseline drawing) are listed apart and count only once
 * the user ticks "this file came from the customer" (the backend re-tags it
 * customer_file and logs it).
 */
import { t } from '../../../i18n/cmLabels'
import type { Attachment } from '../../../types/change'
import { inputCls } from './offerFormat'

const CUSTOMER_KINDS = new Set(['customer_email', 'customer_file'])
const newest = (a: Attachment, b: Attachment) => b.created_at.localeCompare(a.created_at)

/** Is the picked file an internal upload that still needs the tick? */
export const pickNeedsTick = (attachments: Attachment[], value: string): boolean => {
  if (!value) return false
  const att = attachments.find((a) => String(a.id) === value)
  return !!att && !CUSTOMER_KINDS.has(att.kind ?? 'general')
}

/** The body fields for the pick: the file, and the tick when it needs one. */
export const pickBody = (attachments: Attachment[], value: string) => ({
  attachment_id: Number(value),
  ...(pickNeedsTick(attachments, value) ? { from_customer: true } : {}),
})

export default function EvidencePick({
  id, testId, label, attachments, value, onChange, fromCustomer, onFromCustomer, className = '',
}: {
  id?: string
  testId: string
  label: string
  attachments: Attachment[]
  value: string
  onChange: (v: string) => void
  fromCustomer: boolean
  onFromCustomer: (v: boolean) => void
  className?: string
}) {
  const customer = attachments.filter((a) => CUSTOMER_KINDS.has(a.kind ?? 'general')).sort(newest)
  const other = attachments.filter((a) => (a.kind ?? 'general') === 'general').sort(newest)
  const tick = pickNeedsTick(attachments, value)
  return (
    <div className={`flex min-w-0 flex-1 flex-col gap-1 ${className}`}>
      <select id={id} data-testid={testId} value={value} aria-label={label}
        onChange={(e) => { onChange(e.target.value); onFromCustomer(false) }}
        className={`${inputCls} min-w-0`}>
        <option value="">{t('cust.pickMail')}</option>
        {customer.map((m) => <option key={m.id} value={m.id}>{m.filename}</option>)}
        {other.length > 0 && (
          <optgroup label={t('ev.otherFiles')}>
            {other.map((m) => <option key={m.id} value={m.id}>{m.filename}</option>)}
          </optgroup>
        )}
      </select>
      {tick && (
        <label className="flex items-center gap-1 text-[11px] text-amber-200">
          <input type="checkbox" data-testid={`${testId}-from-customer`} checked={fromCustomer}
            onChange={(e) => onFromCustomer(e.target.checked)} />
          {t('ev.fromCustomer')}
        </label>
      )}
    </div>
  )
}
