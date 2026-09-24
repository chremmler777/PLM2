/**
 * The department's assessment checklist: the questions the business asks of
 * every department, plus the ones only that department is asked. Every row is
 * answered No or Yes — nothing is pre-selected, because an unanswered row and a
 * considered No must not look the same. Yes asks what has to be done, and a row
 * that offers choices asks which applies. Anything the list does not cover goes in as a free line,
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
import type { Attachment, ChangeConcern, ChecklistItemDef } from '../../../types/change'
import ChecklistRiskForm from './ChecklistRiskForm'
import type { DepartmentFieldsProps } from './types'

/** Ticking this asks a supplier for money and dates — so it asks for the RFQ. */
const RFQ_ITEM = 'modification_external'

/** A keyed answer, or a free line the department wrote itself. */
export interface ImpactItem {
  key?: string
  label?: string
  /** The department's answer. `impacted` mirrors it (yes) for costing. */
  answer?: 'yes' | 'no'
  /** Answered by "Rest → No" rather than row by row — shown to reviewers. */
  bulk?: boolean
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

/** How far the department has got: keyed rows only (free lines are always Yes). */
export function checklistProgress(
  defs: ChecklistItemDef[], value: Record<string, unknown> | null | undefined,
): { answered: number; total: number; firstOpen: string | null } {
  const byKey = new Map(impactsOf(value).filter((i) => i.key).map((i) => [i.key!, i]))
  const open = defs.filter((d) => !byKey.get(d.key)?.answer)
  return { answered: defs.length - open.length, total: defs.length,
           firstOpen: open[0]?.key ?? null }
}

/** "Rest → No": every keyed row still unanswered becomes a marked No. */
export function restToNo(
  defs: ChecklistItemDef[], value: Record<string, unknown>,
): Record<string, unknown> {
  const impacts = impactsOf(value)
  const answered = new Set(impacts.filter((i) => i.key && i.answer).map((i) => i.key!))
  const rest = impacts.filter((i) => !(i.key && !i.answer))
  const filled = defs.filter((d) => !answered.has(d.key))
    .map((d) => ({ key: d.key, answer: 'no' as const, impacted: false, bulk: true }))
  return { ...value, impacts: [...rest, ...filled] }
}

/** Keys are capped where the backend caps them (change_concerns.checklist_key). */
export const riskKeyOf = (id: string) => id.slice(0, 120)

/** Rows written under the old activity-catalog shape — read-only history. */
const isLegacy = (i: ImpactItem) => i.key === undefined && i.activity_id !== undefined

const idOf = (i: ImpactItem) => i.key ?? `free:${i.label ?? ''}`

export default function ActivityChecklist({
  departmentId, value, onChange, lang = 'en',
  changeId, assessmentId, attachments = [], onUploaded, highlightOpen = false,
}: DepartmentFieldsProps & {
  departmentId: number
  lang?: 'de' | 'en'
  /** Present when the checklist can collect documents of its own (the RFQ). */
  changeId?: number
  assessmentId?: number
  attachments?: Attachment[]
  onUploaded?: () => void
  /** Mark the rows still unanswered (after the submit form's "jump to open"). */
  highlightOpen?: boolean
}) {
  const { data: items = [] } = useQuery({
    queryKey: ['assessment-checklist', departmentId],
    queryFn: () => changesApi.assessmentChecklist(departmentId),
  })
  const [freeLines, setFreeLines] = useState<string[]>([])
  // Same cache entry as the department's risk strip, so a risk raised or
  // withdrawn in either place shows in both.
  const { data: concerns = [] } = useQuery({
    queryKey: ['change', changeId, 'concerns'],
    queryFn: () => changesApi.listConcerns(changeId!),
    enabled: changeId != null,
  })
  const [flagging, setFlagging] = useState<string | null>(null)
  const openRisksFor = (id: string) => (concerns as ChangeConcern[]).filter((c) =>
    c.kind === 'risk' && c.is_open && c.department_id === departmentId
    && c.checklist_key === riskKeyOf(id))
  const impacts = impactsOf(value)
  const legacy = impacts.filter(isLegacy)

  const answerFor = (id: string): ImpactItem =>
    impacts.find((i) => !isLegacy(i) && idOf(i) === id)
      ?? (id.startsWith('free:')
        ? { label: id.slice(5), impacted: false }
        : { key: id, impacted: false })

  const put = (next: ImpactItem) => {
    const rest = impacts.filter((i) => isLegacy(i) || idOf(i) !== idOf(next))
    // Untouched rows carry no weight; a No is an answer and is kept.
    const kept = [...rest, next].filter(
      (i) => isLegacy(i) || i.answer !== undefined || i.impacted
        || (i.remark ?? '').trim() !== '')
    onChange({ ...value, impacts: kept })
  }

  const rfqs = attachments.filter((a) => a.kind === 'rfq')

  const row = (id: string, label: string, def?: ChecklistItemDef) => {
    const item = answerFor(id)
    const wantsRfq = id === RFQ_ITEM && item.impacted
    // Answering by hand drops the Rest → No mark: the row was now considered.
    const { bulk: _bulk, ...own } = item
    void _bulk
    const setAnswer = (answer: 'yes' | 'no') => put(answer === 'yes'
      ? { ...own, answer, impacted: true }
      : { ...(item.key ? { key: item.key } : { label: item.label }), answer, impacted: false })
    const open = !item.answer && !id.startsWith('free:')
    return (
      <li key={id} id={`check-row-${id}`} data-open={String(open)}
        className={`py-1 ${highlightOpen && open ? 'border-l-2 border-amber-500 pl-2' : ''}`}>
        <div className="flex items-center gap-2 text-sm">
          <span role="group" aria-label={label}
            className="flex rounded border border-slate-600 overflow-hidden flex-shrink-0">
            {(['no', 'yes'] as const).map((ans) => (
              <button key={ans} type="button" data-testid={`check-${ans}-${id}`}
                aria-pressed={item.answer === ans}
                onClick={() => setAnswer(ans)}
                className={`px-2 py-0.5 text-xs ${item.answer === ans
                  ? (ans === 'yes' ? 'bg-sky-700 text-white' : 'bg-slate-600 text-slate-100')
                  : 'bg-slate-900 text-slate-400 hover:text-slate-200'}`}>
                {t(`check.${ans}`, lang)}
              </button>
            ))}
          </span>
          <span className={item.answer === 'yes' ? 'text-slate-100'
            : item.answer === 'no' ? 'text-slate-500' : 'text-slate-300'}>{label}</span>
          {/* A No can still carry a risk ("no 3D change, but the stack is
              tight"), so any answered row may flag one — and more than one. */}
          {changeId != null && item.answer && (
            <button type="button" data-testid={`check-flag-${id}`}
              onClick={() => setFlagging(id)}
              className="ml-auto text-[11px] text-amber-300/80 hover:text-amber-200">
              {t('check.flagRisk', lang)}
            </button>
          )}
        </div>
        {/* The row's risks, compact: the full card (proposal, resolve,
            delete) lives in the department's risk panel — click to go there. */}
        {openRisksFor(id).length > 0 && (
          <ul className="mt-0.5 ml-6 space-y-0.5">
            {openRisksFor(id).map((r) => (
              <li key={r.id}>
                <button type="button" data-testid={`check-risk-${r.id}`}
                  onClick={() => document.getElementById(`concern-card-${r.id}`)
                    ?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
                  className="text-left text-[11px] text-amber-300 hover:underline decoration-dotted underline-offset-2">
                  ⚑ {r.severity ?? '?'} · {r.risk_type ?? ''} · {r.note}
                </button>
              </li>
            ))}
          </ul>
        )}
        {flagging === id && changeId != null && (
          <ChecklistRiskForm changeId={changeId} departmentId={departmentId}
            checklistKey={riskKeyOf(id)}
            defaultNote={item.remark?.trim() ? `${label} — ${item.remark.trim()}` : label}
            onDone={() => setFlagging(null)} />
        )}
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
                    put({ label: v, answer: 'yes', impacted: true })
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
