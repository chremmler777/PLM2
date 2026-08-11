/**
 * The department's assessment checklist: the questions the business asks of
 * every department, plus the ones only that department is asked. Rows are off by
 * default; ticking one asks what has to be done, and a row that offers choices
 * asks which applies. Anything the list does not cover goes in as a free line,
 * the way the paper form always allowed.
 *
 * The questions come from the backend so adding one is never a frontend change.
 * Answers are keyed, which is what makes them comparable across changes; rows
 * stored under the older activity-catalog shape are shown but not editable.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { changesApi } from '../../../api/changes'
import AttachmentDropzone from '../AttachmentDropzone'
import { AttachmentRow } from '../AttachmentRow'
import { t } from '../../../i18n/cmLabels'
import type { Attachment, ChecklistItemDef } from '../../../types/change'
import type { DepartmentFieldsProps } from './types'

/** Ticking this asks a supplier for money and dates — so it asks for the RFQ. */
const RFQ_ITEM = 'modification_external'

/** A keyed answer, or a free line the department wrote itself. */
export interface ImpactItem {
  key?: string
  label?: string
  impacted: boolean
  remark?: string
  choice?: string
  /** Legacy shape: answers stored against the activity catalog. */
  activity_id?: number | null
}

export const impactsOf = (
  value: Record<string, unknown> | null | undefined,
): ImpactItem[] =>
  value && Array.isArray(value.impacts) ? (value.impacts as ImpactItem[]) : []

/** How many areas a submitted assessment says are impacted. */
export function impactedCount(details: Record<string, unknown> | null | undefined): number {
  return impactsOf(details).filter((i) => i.impacted).length
}

/** Rows written under the old activity-catalog shape — read-only history. */
const isLegacy = (i: ImpactItem) => i.key === undefined && i.activity_id !== undefined

const idOf = (i: ImpactItem) => i.key ?? `free:${i.label ?? ''}`

export default function ActivityChecklist({
  departmentId, value, onChange, lang = 'en',
  changeId, assessmentId, attachments = [], onUploaded,
}: DepartmentFieldsProps & {
  departmentId: number
  lang?: 'de' | 'en'
  /** Present when the checklist can collect documents of its own (the RFQ). */
  changeId?: number
  assessmentId?: number
  attachments?: Attachment[]
  onUploaded?: () => void
}) {
  const { data: items = [] } = useQuery({
    queryKey: ['assessment-checklist', departmentId],
    queryFn: () => changesApi.assessmentChecklist(departmentId),
  })
  const [freeLines, setFreeLines] = useState<string[]>([])
  const impacts = impactsOf(value)
  const legacy = impacts.filter(isLegacy)

  const answerFor = (id: string): ImpactItem =>
    impacts.find((i) => !isLegacy(i) && idOf(i) === id)
      ?? (id.startsWith('free:')
        ? { label: id.slice(5), impacted: false }
        : { key: id, impacted: false })

  const put = (next: ImpactItem) => {
    const rest = impacts.filter((i) => isLegacy(i) || idOf(i) !== idOf(next))
    // Untouched rows carry no weight: only answered ones are worth sending.
    const kept = [...rest, next].filter(
      (i) => isLegacy(i) || i.impacted || (i.remark ?? '').trim() !== '')
    onChange({ ...value, impacts: kept })
  }

  const rfqs = attachments.filter((a) => a.kind === 'rfq')

  const row = (id: string, label: string, def?: ChecklistItemDef) => {
    const item = answerFor(id)
    const wantsRfq = id === RFQ_ITEM && item.impacted
    return (
      <li key={id} className="py-1">
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input type="checkbox" data-testid={`check-${id}`}
            checked={item.impacted}
            onChange={(e) => put({ ...item, impacted: e.target.checked })} />
          <span className={item.impacted ? 'text-slate-100' : 'text-slate-400'}>{label}</span>
        </label>
        {item.impacted && (
          <div className="mt-1 ml-6 space-y-1">
            {/* Some questions are only answered once you say which kind it is. */}
            {def?.choices && def.choices.length > 0 && (
              <div className="flex items-center gap-3 text-xs" role="group"
                aria-label={t('check.choice')}>
                {def.choices.map((choice) => (
                  <label key={choice} className="flex items-center gap-1.5 cursor-pointer">
                    <input type="radio" name={`choice-${id}`}
                      data-testid={`check-choice-${id}-${choice}`}
                      checked={item.choice === choice}
                      onChange={() => put({ ...item, choice })} />
                    <span className="text-slate-300">
                      {t(`check.choice.${choice}`) === `check.choice.${choice}`
                        ? choice : t(`check.choice.${choice}`, lang)}
                    </span>
                  </label>
                ))}
              </div>
            )}
            <input type="text" data-testid={`check-remark-${id}`}
              value={item.remark ?? ''}
              onChange={(e) => put({ ...item, remark: e.target.value })}
              placeholder={t('check.remarkPlaceholder', lang)} aria-label={t('check.remark', lang)}
              className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
            {/* Supplier work needs a price and a date: the RFQ is asked for
                right here, where the box was ticked — never gated, only asked. */}
            {wantsRfq && changeId != null && assessmentId != null && (
              <div className="space-y-1" data-testid={`check-rfq-${id}`}>
                {rfqs.length > 0 ? (
                  <ul className="text-sm rounded border border-slate-700/60 bg-slate-900/30 px-2 py-1">
                    {rfqs.map((a) => (
                      <AttachmentRow key={a.id} changeId={changeId} attachment={a} />
                    ))}
                  </ul>
                ) : (
                  <p className="text-[11px] text-amber-300/80" data-testid="check-rfq-missing">
                    {t('attach.rfqMissing', lang)}
                  </p>
                )}
                <AttachmentDropzone changeId={changeId} assessmentId={assessmentId}
                  kind="rfq" compact label={t('attach.rfqSlot', lang)}
                  onUploaded={() => onUploaded?.()} />
              </div>
            )}
          </div>
        )}
      </li>
    )
  }

  const common = items.filter((i) => !i.extra)
  const extras = items.filter((i) => i.extra)
  const labelOf = (i: ChecklistItemDef) => (lang === 'de' ? i.label_de : i.label_en)

  return (
    <div className="space-y-1">
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{t('check.title', lang)}</p>
      <p className="text-[11px] text-slate-500">{t('check.hint', lang)}</p>
      {items.length === 0 && freeLines.length === 0 && legacy.length === 0 ? (
        <p className="text-xs text-slate-600">{t('check.empty', lang)}</p>
      ) : (
        <ul className="divide-y divide-slate-700/40 rounded border border-slate-700/60 bg-slate-900/30 px-2">
          {common.map((i) => row(i.key, labelOf(i), i))}
          {extras.map((i) => row(i.key, labelOf(i), i))}
          {freeLines.map((label, idx) => (
            label.trim() === '' ? (
              <li key={`free-new-${idx}`} className="py-1">
                <input type="text" autoFocus data-testid={`check-free-input-${idx}`}
                  aria-label={t('check.itemLabel', lang)}
                  placeholder={t('check.itemPlaceholder', lang)}
                  onBlur={(e) => {
                    const v = e.target.value.trim()
                    if (!v) return
                    setFreeLines((f) => f.map((x, j) => (j === idx ? v : x)))
                    put({ label: v, impacted: true })
                  }}
                  className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
              </li>
            ) : row(`free:${label}`, label)
          ))}
          {/* Answers from before the keyed checklist: kept visible, not edited. */}
          {legacy.map((i) => (
            <li key={`legacy-${i.activity_id}-${i.label}`} className="py-1 text-xs text-slate-500">
              <span data-testid={`check-legacy-${i.activity_id ?? 'free'}`}>
                {i.impacted ? '✓' : '·'} {i.label}
                {i.remark ? ` — ${i.remark}` : ''}
              </span>
              <span className="ml-2 opacity-70">({t('check.legacy', lang)})</span>
            </li>
          ))}
        </ul>
      )}
      <button type="button" data-testid="check-add-item"
        onClick={() => setFreeLines((f) => [...f, ''])}
        className="text-xs text-sky-300 hover:text-sky-200">
        {t('check.addItem', lang)}
      </button>
    </div>
  )
}
