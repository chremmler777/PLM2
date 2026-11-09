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
import { Check, Flag, Info, Minus } from 'lucide-react'
import { useAuth } from '../../../contexts/AuthContext'
import { toastError } from '../../../lib/apiError'
import { changesApi } from '../../../api/changes'
import { AttachmentRow } from '../AttachmentRow'
import { t } from '../../../i18n/cmLabels'
import type {
  Attachment, ChangeConcern, ChecklistChoice, ChecklistItemDef, ChecklistRequiredDocument,
} from '../../../types/change'
import AttachmentDropzone from '../AttachmentDropzone'
import ChecklistRiskForm from './ChecklistRiskForm'
import type { DepartmentFieldsProps } from './types'

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
  /** Internal / External modification: one line per case (2026-11-08); each
   *  becomes its own costing line on submit. `remark` mirrors them. */
  cases?: (string | CaseEntry)[]
  /** Spec §4: with no Yes, the reference that shows this No. */
  ref?: string
  choice?: string
  /** Legacy shape: answers stored against the activity catalog. */
  activity_id?: number | null
}

/** Rows that take several cases, each a costing line (backend CASE_KEYS). */
export const CASE_KEYS = new Set(['modification_internal', 'modification_external'])
export interface CaseEntry { id: string; text: string }
const newCaseId = () => `c${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`
/** A row's cases as {id, text}; the first falls back to the remark. */
export const casesOf = (i: ImpactItem): CaseEntry[] => {
  const raw = i.cases ?? []
  const out = raw.map((c) => (typeof c === 'string' ? { id: '', text: c } : c))
    .map((c, n) => (c.id ? c : { ...c, id: `legacy${n}` }))
  return out.length ? out : [{ id: '', text: i.remark ?? '' }]
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

/** A document a Yes row still owes: the row's item and the document. */
export interface MissingDocument {
  key: string
  item: ChecklistItemDef
  doc: ChecklistRequiredDocument
  /** "Case 2 · Re-cut insert LH" when the document is owed per case */
  caseLabel?: string
}

/** The file types each document slot takes, mirroring REQUIRED_DOCUMENTS in
 *  the backend (assessment_checklist.py), which refuses any other file. A
 *  checklist row reads the list from its served definition; the slots
 *  outside a row (the not-feasible deck, the bucket's RFQ slot) read it here
 *  so the wrong file is turned away before the upload, not by a server 400. */
export const DOCUMENT_EXTENSIONS: Record<'change_ppt' | 'rfq', string[]> = {
  change_ppt: ['.ppt', '.pptx', '.pdf'],
  rfq: ['.pdf', '.xlsx', '.xls', '.doc', '.docx', '.msg', '.eml'],
}

/** A slot's file types: from the served definitions when an item declares
 *  the kind, else the mirrored constant. */
export function documentExtensions(
  kind: keyof typeof DOCUMENT_EXTENSIONS, defs: ChecklistItemDef[] = [],
): string[] {
  for (const item of defs) {
    const doc = item.requires_documents?.find((d) => d.kind === kind)
    if (doc?.extensions?.length) return doc.extensions
  }
  return DOCUMENT_EXTENSIONS[kind]
}

/** The name of a required document, in the sentence it appears in. */
export const docLabel = (d: ChecklistRequiredDocument, lang: 'de' | 'en' = 'en') =>
  lang === 'de' ? d.label_de : d.label_en

/**
 * Documents the answered checklist still owes: every Yes row whose item
 * declares `requires_documents`, minus the kinds already filed against the
 * assessment. The same rule the backend refuses the submit on; a draft is
 * never held by it.
 */
export function missingDocuments(
  defs: ChecklistItemDef[], value: Record<string, unknown> | null | undefined,
  attachments: Pick<Attachment, 'kind' | 'case_ref'>[],
): MissingDocument[] {
  const filed = new Set(attachments.map((a) => a.kind))
  const rows = impactsOf(value).filter((i) => i.key && i.answer === 'yes')
  const yes = new Set(rows.map((i) => i.key!))
  return defs.flatMap((item) => {
    if (!yes.has(item.key)) return []
    const row = rows.find((i) => i.key === item.key)!
    const cases = item.case_documents?.length
      ? casesOf(row).filter((c) => c.id && !c.id.startsWith('legacy') && c.text.trim()) : []
    if (cases.length) {
      // 2026-11-08: each case owes its own documents
      return cases.flatMap((c, n) => item.case_documents!
        .filter((doc) => !(attachments as Pick<Attachment, 'kind' | 'case_ref'>[])
          .some((a) => a.kind === doc.kind && a.case_ref === c.id))
        .map((doc) => ({ key: item.key, item, doc, caseLabel: `Case ${n + 1} · ${c.text.slice(0, 40)}` })))
    }
    return (item.requires_documents ?? [])
      .filter((doc) => !filed.has(doc.kind))
      .map((doc) => ({ key: item.key, item, doc }))
  })
}

const EMPTY_EVIDENCE = new Set(['ok', 'okay', 'tbd', 'na', 'n/a', 'done', 'checked', 'yes', 'no', 'none', '-'])

/** Evidence in words, mirroring the backend (spec §4 verdict): a reference
 *  that names something (5+ characters with a number, or two words), or a
 *  number with its unit ("+0.4 s"). "ok", "checked" say nothing. */
export function saysWhat(text: string | null | undefined): boolean {
  const v = (text ?? '').trim()
  if (!v || EMPTY_EVIDENCE.has(v.toLowerCase())) return false
  const digit = /\d/.test(v)
  if (digit && /[A-Za-zÄÖÜäöüß]/.test(v)) return true
  const words = v.match(/[A-Za-z0-9ÄÖÜäöüß]+/g) ?? []
  const empty = words.every((w) => EMPTY_EVIDENCE.has(w.toLowerCase()) || w.length <= 2)
  return v.length >= 5 && !empty && (digit || words.length >= 2)
}

/** Spec §4 verdict: with a Yes, every Yes says what changes and its evidence
 *  (remark); with none, every No of the served checklist carries its
 *  reference. Returns the impact and the rows still owing it. */
export function verdictEvidence(
  defs: ChecklistItemDef[], value: Record<string, unknown> | null | undefined,
): { impact: 'yes' | 'no'; missing: string[] } {
  const rows = impactsOf(value).filter((i) => i.answer === 'yes' || i.answer === 'no')
  const label = (i: ImpactItem) => defs.find((d) => d.key === i.key)?.label_en ?? i.label ?? i.key ?? ''
  const yes = rows.filter((i) => i.answer === 'yes')
  if (yes.length) {
    // R4: a Yes names a drawing/document number or a value with its unit;
    // a row that owes filed documents has them as its evidence
    const evidenced = (i: ImpactItem) => {
      const v = i.key ? (i.remark ?? '') : `${i.label ?? ''} ${i.remark ?? ''}`
      const filed = !!defs.find((d) => d.key === i.key)?.requires_documents?.length
      return saysWhat(v) && (/\d/.test(v) || filed)
    }
    return { impact: 'yes', missing: yes.filter((i) => !evidenced(i)).map(label) }
  }
  const served = new Set(defs.map((d) => d.key))
  const shown = new Set(rows.filter((i) => i.key && saysWhat(i.ref)).map((i) => i.key))
  return { impact: 'no', missing: [...new Set(rows.filter((i) => i.key && served.has(i.key)
    && !shown.has(i.key)).map(label))] }
}

/** Impact no: one reference for every No row that has none yet. */
export function refToNos(value: Record<string, unknown>, ref: string): Record<string, unknown> {
  return { ...value, impacts: impactsOf(value).map((i) => (
    i.key && i.answer === 'no' && !saysWhat(i.ref) ? { ...i, ref } : i)) }
}

/** "Rest → No": every keyed row still unanswered becomes a marked No. */
export function restToNo(
  defs: ChecklistItemDef[], value: Record<string, unknown>,
): Record<string, unknown> {
  const impacts = impactsOf(value)
  const served = new Set(defs.map((d) => d.key))
  const answered = new Set(impacts.filter((i) => i.key && i.answer).map((i) => i.key!))
  // An earlier item (key no longer served) is kept exactly as stored.
  const rest = impacts.filter((i) => !(i.key && !i.answer && served.has(i.key)))
  const filled = defs.filter((d) => !answered.has(d.key))
    .map((d) => ({ key: d.key, answer: 'no' as const, impacted: false, bulk: true }))
  return { ...value, impacts: [...rest, ...filled] }
}

/**
 * Labels for checklist keys the served list may no longer carry (backend
 * LEGACY_ITEMS: the 13-item common list before 2026-09-25). A stored answer
 * keeps its key forever, so it still needs a name after the list changed.
 */
const EARLIER_ITEM_LABELS: Record<string, { de: string; en: string }> = {
  cycle_time_change: { de: 'Zykluszeitänderung', en: 'Cycle time change' },
  scrap_increase: { de: 'Ausschusserhöhung', en: 'Scrap increase' },
  maintenance_increase: { de: 'Erhöhter Wartungsaufwand', en: 'Increased maintenance' },
  threed_change: { de: '3D-Änderung erforderlich', en: '3D change necessary' },
  dimensional_risk: { de: 'Maßliches Risiko', en: 'Dimensional risk' },
  visual_risk: { de: 'Optisches Risiko', en: 'Visual risk' },
  work_instruction_update: { de: 'Arbeitsanweisung aktualisieren', en: 'Work instruction update' },
  new_process: { de: 'Neuer Prozess', en: 'New process' },
  sparepart_required: { de: 'Ersatzteil erforderlich', en: 'Spare part required' },
  modification_internal: { de: 'Interne Änderung/Umbau', en: 'Internal modification' },
  modification_external: { de: 'Externe Änderung/Umbau (Lieferant)', en: 'External modification (supplier)' },
  prototyping_required: { de: 'Prototypen/Musterbau erforderlich', en: 'Prototyping required' },
  matching_required: { de: 'Abmusterung/Matching erforderlich', en: 'Matching/sampling required' },
}

/** A stored answer's name: its free label, the served checklist's label,
 *  else the earlier checklist's, else the key made readable. */
export function checklistItemLabel(
  i: { key?: string; label?: string }, defs: ChecklistItemDef[], lang: 'de' | 'en' = 'en',
): string {
  if (i.label) return i.label
  if (!i.key) return ''
  const def = defs.find((d) => d.key === i.key)
  if (def) return lang === 'de' ? def.label_de : def.label_en
  const earlier = EARLIER_ITEM_LABELS[i.key]
  if (earlier) return earlier[lang]
  const words = i.key.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** Keyed answers to items the served checklist no longer lists: kept as
 *  given (never re-asked, never dropped) and sent back unchanged. */
export function earlierAnswers(
  defs: ChecklistItemDef[], value: Record<string, unknown> | null | undefined,
): ImpactItem[] {
  const served = new Set(defs.map((d) => d.key))
  return impactsOf(value).filter((i) => i.key !== undefined && !served.has(i.key))
}

/** Keys are capped where the backend caps them (change_concerns.checklist_key). */
export const riskKeyOf = (id: string) => id.slice(0, 120)

/** A choice as the backend serves it ({value, label_de, label_en}) or as an
 *  older payload did (a bare string). */
export const choiceValue = (c: ChecklistChoice | string): string =>
  typeof c === 'string' ? c : String(c?.value ?? '')

export function choiceLabel(c: ChecklistChoice | string, lang: 'de' | 'en' = 'en'): string {
  if (typeof c !== 'string') {
    const own = lang === 'de' ? c?.label_de : c?.label_en
    if (own) return own
  }
  const v = choiceValue(c)
  const key = `check.choice.${v}`
  return t(key, lang) === key ? v : t(key, lang)
}

/** Rows written under the old activity-catalog shape — read-only history. */
const isLegacy = (i: ImpactItem) => i.key === undefined && i.activity_id !== undefined

const idOf = (i: ImpactItem) => i.key ?? `free:${i.label ?? ''}`

export default function ActivityChecklist({
  departmentId, value, onChange, lang = 'en',
  changeId, assessmentId, attachments = [], onUploaded, highlightOpen = false, ownerIds = [],
}: DepartmentFieldsProps & {
  /** Who owns the assessment (owner, responsible): they and admins delete its documents. */
  ownerIds?: number[]
  departmentId: number
  lang?: 'de' | 'en'
  /** Present when the checklist can collect the documents a Yes owes
   *  (external modification: the change presentation and the change RFQ). */
  changeId?: number
  assessmentId?: number
  attachments?: Attachment[]
  onUploaded?: () => void
  /** Mark the rows still unanswered (after the submit form's "jump to open"). */
  highlightOpen?: boolean
}) {
  const { userId, isAdmin } = useAuth()
  const { data: items = [], isSuccess: itemsLoaded } = useQuery({
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
  // Christoph 2026-11-08: a row (or case) going away with documents filed on
  // it asks first, then deletes them: {row id, case index or null}
  const [askDrop, setAskDrop] = useState<{ id: string; n: number | null } | null>(null)
  const dropDocs = async (ids: number[]) => {
    if (changeId == null) return
    for (const x of ids) {
      try { await changesApi.deleteAttachment(changeId, x) } catch (e) { toastError(e, t('attach.deleteFailed')) }
    }
    onUploaded?.()
  }
  // The department's risk vocabulary, for naming the row's risks (shared
  // cache with the risk form).
  const hasRowRisks = (concerns as ChangeConcern[]).some((c) =>
    c.kind === 'risk' && c.department_id === departmentId && !!c.checklist_key)
  const { data: riskTypeData } = useQuery({
    queryKey: ['risk-types', departmentId],
    queryFn: () => changesApi.riskTypes(departmentId),
    enabled: changeId != null && hasRowRisks,
    retry: false,
  })
  const riskTypeName = (k?: string | null) =>
    (k && riskTypeData?.items?.find((i) => i.key === k)?.label_en) ?? k ?? ''
  const openRisksFor = (id: string) => (concerns as ChangeConcern[]).filter((c) =>
    c.kind === 'risk' && c.is_open && c.department_id === departmentId
    && c.checklist_key === riskKeyOf(id))
  const impacts = impactsOf(value)
  const legacy = impacts.filter(isLegacy)
  // Answers to items the served checklist no longer lists: shown read-only
  // under "Earlier checklist items" and carried back unchanged. Only once
  // the list is loaded, or every answer would look earlier while it loads.
  const servedKeys = new Set(items.map((i) => i.key))
  const isEarlier = (i: ImpactItem) =>
    itemsLoaded && i.key !== undefined && !servedKeys.has(i.key)
  const earlier = impacts.filter(isEarlier)

  const answerFor = (id: string): ImpactItem =>
    impacts.find((i) => !isLegacy(i) && idOf(i) === id)
      ?? (id.startsWith('free:')
        ? { label: id.slice(5), impacted: false }
        : { key: id, impacted: false })

  const put = (next: ImpactItem) => {
    const rest = impacts.filter((i) => isLegacy(i) || idOf(i) !== idOf(next))
    // Untouched rows carry no weight; a No is an answer and is kept. Earlier
    // items are never edited here, so they stay exactly as stored.
    const kept = [...rest, next].filter(
      (i) => isLegacy(i) || isEarlier(i) || i.answer !== undefined || i.impacted
        || (i.remark ?? '').trim() !== '')
    onChange({ ...value, impacts: kept })
  }

  const row = (id: string, label: string, def?: ChecklistItemDef) => {
    const item = answerFor(id)
    // The documents this Yes owes, each in its own slot on the row.
    // a row whose cases carry their own documents has no row-level slots
    const docs = item.answer === 'yes' && !def?.case_documents?.length
      ? def?.requires_documents ?? [] : []
    // Answering by hand drops the Rest → No mark: the row was now considered.
    const { bulk: _bulk, ...own } = item
    void _bulk
    const setAnswer = (answer: 'yes' | 'no') => put(answer === 'yes'
      ? { ...own, answer, impacted: true }
      : { ...(item.key ? { key: item.key } : { label: item.label }), answer, impacted: false })
    const caseIds = new Set(casesOf(item).map((c) => c.id).filter(Boolean))
    const rowDocs = attachments.filter((x) => x.case_ref && caseIds.has(x.case_ref))
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
                onClick={() => (ans === 'no' && item.answer === 'yes' && rowDocs.length
                  ? setAskDrop({ id, n: null }) : setAnswer(ans))}
                className={`px-2 py-0.5 text-xs ${item.answer === ans
                  ? (ans === 'yes' ? 'bg-sky-700 text-white' : 'bg-slate-600 text-slate-100')
                  : 'bg-slate-900 text-slate-400 hover:text-slate-200'}`}>
                {t(`check.${ans}`, lang)}
              </button>
            ))}
          </span>
          <span className={item.answer === 'yes' ? 'text-slate-100'
            : item.answer === 'no' ? 'text-slate-500' : 'text-slate-300'}>{label}</span>
          {/* A risk hangs off work that happens: only a Yes row flags one
              (more than one is fine). A worry about a No row is a free risk
              in the department's risk panel. */}
          {changeId != null && item.answer === 'yes' && (
            <button type="button" data-testid={`check-flag-${id}`}
              onClick={() => setFlagging(id)}
              className="ml-auto text-[11px] text-amber-300/80 hover:text-amber-200">
              {t('check.flagRisk', lang)}
            </button>
          )}
        </div>
        {askDrop?.id === id && askDrop.n === null && (
          <div data-testid={`check-dropdocs-${id}`}
            className="mt-1 ml-6 flex flex-wrap items-center gap-2 rounded border border-red-700/70 bg-red-950/30 px-2 py-1 text-xs text-red-100">
            {t('check.dropDocs', lang).replace('{n}', String(rowDocs.length))}
            <button type="button" data-testid={`check-dropdocs-yes-${id}`}
              className="rounded bg-red-800 px-1.5 text-white hover:bg-red-700"
              onClick={() => { const ids = rowDocs.map((x) => x.id); setAskDrop(null); setAnswer('no'); void dropDocs(ids) }}>
              {t('risk.yes')}</button>
            <button type="button" className="rounded border border-slate-600 px-1.5 text-slate-200"
              onClick={() => setAskDrop(null)}>{t('risk.no')}</button>
          </div>
        )}
        {/* The row's risks, compact: the full card (proposal, resolve,
            delete) lives in the department's risk panel — click to go there. */}
        {openRisksFor(id).length > 0 && (
          <ul className="mt-0.5 ml-6 space-y-0.5">
            {openRisksFor(id).map((r) => (
              <li key={r.id}>
                <button type="button" data-testid={`check-risk-${r.id}`}
                  onClick={() => document.getElementById(`concern-card-${r.id}`)
                    ?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
                  className="inline-flex items-baseline gap-1 text-left text-[11px] text-amber-300 hover:underline decoration-dotted underline-offset-2">
                  <Flag aria-hidden="true" size={11} className="self-center flex-shrink-0" />
                  <span>
                    <span className="sr-only">Risk, </span>
                    {r.severity != null ? `Severity ${r.severity}` : 'Severity not set'} · {riskTypeName(r.risk_type)} · {r.note}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {flagging === id && changeId != null && (
          <ChecklistRiskForm changeId={changeId} departmentId={departmentId}
            checklistKey={riskKeyOf(id)}
            defaultNote={item.remark?.trim() ? `${label}: ${item.remark.trim()}` : label}
            onDone={() => setFlagging(null)} />
        )}
        {item.impacted && (
          <div className="mt-1 ml-6 space-y-1">
            {/* Some questions are only answered once you say which kind it is. */}
            {def?.choices && def.choices.length > 0 && (
              <div className="flex items-center gap-3 text-xs" role="group"
                aria-label={t('check.choice')}>
                {def.choices.map((c) => {
                  const choice = choiceValue(c)
                  return (
                    <label key={choice} className="flex items-center gap-1.5 cursor-pointer">
                      <input type="radio" name={`choice-${id}`}
                        data-testid={`check-choice-${id}-${choice}`}
                        checked={item.choice === choice}
                        onChange={() => put({ ...item, choice })} />
                      <span className="text-slate-300">{choiceLabel(c, lang)}</span>
                    </label>
                  )
                })}
              </div>
            )}
            {item.key && CASE_KEYS.has(item.key) ? (() => {
              const cases = casesOf(item)
              const putCases = (next: CaseEntry[]) => put({ ...item,
                cases: next.map((c) => (c.id && !c.id.startsWith('legacy') ? c : { ...c, id: newCaseId() })),
                remark: next.map((c) => c.text.trim()).filter(Boolean).join('; ') })
              const caseDocs = def?.case_documents ?? []
              return (
                <div className="space-y-1.5" data-testid={`check-cases-${id}`}>
                  {cases.map((c, n) => (
                    <div key={n} className="rounded border border-slate-700 border-l-4 border-l-amber-600 bg-slate-900/40 p-1.5 space-y-1"
                      data-testid={`check-case-box-${id}-${n}`}>
                      <div className="flex items-center gap-1">
                        <span className="rounded bg-amber-900/60 px-1.5 text-[11px] font-semibold text-amber-100 flex-shrink-0">{t('check.case', lang)} {n + 1}</span>
                        <input type="text" data-testid={n === 0 ? `check-remark-${id}` : `check-case-${id}-${n}`}
                          value={c.text}
                          onChange={(e) => putCases(cases.map((x, m) => (m === n ? { ...x, text: e.target.value } : x)))}
                          placeholder={t('check.casePlaceholder', lang)}
                          aria-label={`${t('check.case', lang)} ${n + 1}`}
                          className="flex-1 bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
                        {cases.length > 1 && (
                          <button type="button" className="text-xs text-slate-400 hover:text-red-300 px-1"
                            aria-label={t('check.caseRemove', lang)}
                            onClick={() => (attachments.some((x) => x.case_ref && x.case_ref === c.id)
                              ? setAskDrop({ id, n }) : putCases(cases.filter((_, m) => m !== n)))}>×</button>
                        )}
                      </div>
                      {askDrop?.id === id && askDrop.n === n && (() => {
                        const docsOfCase = attachments.filter((x) => x.case_ref && x.case_ref === c.id)
                        return (
                          <div data-testid={`check-dropcase-${id}-${n}`}
                            className="flex flex-wrap items-center gap-2 rounded border border-red-700/70 bg-red-950/30 px-2 py-1 text-xs text-red-100">
                            {t('check.dropCase', lang).replace('{n}', String(docsOfCase.length))}
                            <button type="button" className="rounded bg-red-800 px-1.5 text-white hover:bg-red-700"
                              onClick={() => { setAskDrop(null); putCases(cases.filter((_, m) => m !== n)); void dropDocs(docsOfCase.map((x) => x.id)) }}>
                              {t('risk.yes')}</button>
                            <button type="button" className="rounded border border-slate-600 px-1.5 text-slate-200"
                              onClick={() => setAskDrop(null)}>{t('risk.no')}</button>
                          </div>
                        )
                      })()}
                      {/* each case files its own documents (2026-11-08) */}
                      {c.id && !c.id.startsWith('legacy') && c.text.trim() && caseDocs.map((doc) => {
                        const filed = attachments.filter((x) => x.kind === doc.kind && x.case_ref === c.id)
                        const name = docLabel(doc, lang)
                        return (
                          <div key={doc.kind} data-testid={`check-casedoc-${id}-${n}-${doc.kind}`}
                            data-state={filed.length > 0 ? 'filed' : 'required'}
                            className={`ml-12 rounded border px-2 py-1 ${filed.length > 0
                              ? 'border-slate-700/60' : 'border-amber-700/60 bg-amber-950/20'}`}>
                            <p className={`text-[11px] font-medium ${filed.length > 0 ? 'text-emerald-300' : 'text-amber-300'}`}>
                              {t(filed.length > 0 ? 'check.docFiled' : 'check.docRequired', lang).replace('{d}', name)}
                            </p>
                            {filed.length > 0 && changeId != null && (
                              <ul className="text-sm">
                                {filed.map((x) => <AttachmentRow key={x.id} changeId={changeId} attachment={x} confirm
                                  tag={`${t('check.case', lang)} ${n + 1} · ${c.text.slice(0, 40)}`}
                                  onDelete={!(isAdmin || (userId != null && ownerIds.includes(userId)) || (!ownerIds.length && x.uploaded_by === userId)) ? undefined : (att) => { changesApi.deleteAttachment(changeId, att.id)
                                    .then(() => onUploaded?.()).catch((e: unknown) => toastError(e, t('attach.deleteFailed'))) }} />)}
                              </ul>
                            )}
                            {changeId != null && assessmentId != null && (
                              <AttachmentDropzone changeId={changeId} assessmentId={assessmentId} caseRef={c.id} compact
                                kind={doc.kind} extensions={doc.extensions}
                                label={t('check.docSlot', lang).replace('{d}', lang === 'en' ? name.charAt(0).toLowerCase() + name.slice(1) : name)
                                  .replace('{x}', doc.extensions.join(', '))}
                                onUploaded={() => onUploaded?.()} />
                            )}
                          </div>
                        )
                      })}
                    </div>
                  ))}
                  <div className="flex items-center gap-3">
                    <button type="button" data-testid={`check-case-add-${id}`}
                      className="text-[11px] text-sky-300 hover:text-sky-200"
                      onClick={() => putCases([...cases, { id: newCaseId(), text: '' }])}>{t('check.caseAdd', lang)}</button>
                    <span className="text-[11px] text-slate-500">{t('check.caseHint', lang)}</span>
                  </div>
                </div>
              )
            })() : (
            <input type="text" data-testid={`check-remark-${id}`}
              value={item.remark ?? ''}
              onChange={(e) => put({ ...item, remark: e.target.value })}
              placeholder={t('check.remarkPlaceholder', lang)} aria-label={t('check.remark', lang)}
              className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
            )}
            {/* Supplier work is presented (the change presentation) and
                priced (the change RFQ): each document has its own slot here,
                where the Yes was given. Submit waits for both. */}
            {docs.map((doc) => {
              const filed = attachments.filter((a) => a.kind === doc.kind)
              const name = docLabel(doc, lang)
              const inSentence = lang === 'en' ? name.charAt(0).toLowerCase() + name.slice(1) : name
              return (
                <div key={doc.kind} data-testid={`check-doc-${id}-${doc.kind}`}
                  data-state={filed.length > 0 ? 'filed' : 'required'}
                  className={`space-y-1 rounded border px-2 py-1 ${filed.length > 0
                    ? 'border-slate-700/60 bg-slate-900/30'
                    : 'border-amber-700/60 bg-amber-950/20'}`}>
                  <p className={`text-[11px] font-medium ${filed.length > 0 ? 'text-emerald-300' : 'text-amber-300'}`}
                    data-testid={`check-doc-state-${id}-${doc.kind}`}>
                    {t(filed.length > 0 ? 'check.docFiled' : 'check.docRequired', lang).replace('{d}', name)}
                  </p>
                  {filed.length > 0 && changeId != null && (
                    <ul className="text-sm">
                      {filed.map((a) => (
                        <AttachmentRow key={a.id} changeId={changeId} attachment={a} />
                      ))}
                    </ul>
                  )}
                  {changeId != null && assessmentId != null && (
                    <AttachmentDropzone changeId={changeId} assessmentId={assessmentId} compact
                      kind={doc.kind} extensions={doc.extensions}
                      label={t('check.docSlot', lang).replace('{d}', inSentence)
                        .replace('{x}', doc.extensions.join(', '))}
                      onUploaded={() => onUploaded?.()} />
                  )}
                </div>
              )
            })}
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
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{t('check.title', lang)}
        {' '}<span className="normal-case cursor-help" title={t('check.hint', lang)}><Info aria-hidden="true" size={12} className="inline align-[-2px]" /></span></p>
      {items.length === 0 && freeLines.length === 0 && legacy.length === 0 && earlier.length === 0 ? (
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
                {i.impacted
                  ? <Check role="img" aria-label="Impacted" size={12} className="mr-1 inline align-[-2px]" />
                  : <Minus role="img" aria-label="Not impacted" size={12} className="mr-1 inline align-[-2px]" />}
                {i.label}
                {i.remark ? `: ${i.remark}` : ''}
              </span>
              <span className="ml-2 opacity-70">({t('check.legacy', lang)})</span>
            </li>
          ))}
        </ul>
      )}
      {earlier.length > 0 && (
        <div data-testid="check-earlier" className="pt-1">
          <p className="text-[11px] uppercase tracking-wide text-slate-500">{t('check.earlier', lang)}</p>
          <p className="text-[11px] text-slate-500">{t('check.earlierHint', lang)}</p>
          <ul className="mt-1 divide-y divide-slate-700/40 rounded border border-slate-700/60 bg-slate-900/20 px-2">
            {earlier.map((i) => {
              const yes = i.answer ? i.answer === 'yes' : i.impacted
              return (
                <li key={`earlier-${i.key}`} data-testid={`check-earlier-${i.key}`}
                  className="py-1 text-xs text-slate-400">
                  {yes
                    ? <Check role="img" aria-label={t('check.yes', lang)} size={12} className="mr-1 inline align-[-2px]" />
                    : <Minus role="img" aria-label={t('check.no', lang)} size={12} className="mr-1 inline align-[-2px]" />}
                  <span className={yes ? 'text-slate-200' : ''}>{checklistItemLabel(i, items, lang)}</span>
                  <span className="ml-1 text-slate-500">({t(yes ? 'check.yes' : 'check.no', lang)})</span>
                  {i.choice ? ` · ${choiceLabel(i.choice, lang)}` : ''}
                  {i.remark ? `: ${i.remark}` : ''}
                </li>
              )
            })}
          </ul>
        </div>
      )}
      <button type="button" data-testid="check-add-item"
        onClick={() => setFreeLines((f) => [...f, ''])}
        className="text-xs text-sky-300 hover:text-sky-200">
        {t('check.addItem', lang)}
      </button>
    </div>
  )
}
