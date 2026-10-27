/**
 * Scoping is triage (C33, spec §3): "which parts, who assesses, go/no-go".
 *
 * Quick add (< 15 s): one line, the department it is raised for (last used,
 * else the viewer's own), what to check, the part or the whole change. The
 * default is a CHECK item: the department checks it in its own assessment
 * ("Unsure? Leave it."). "Make it a question" asks the one test that matters:
 * can we decide parts, assessors and go/no-go without this? Only a "no"
 * becomes a question, with who can answer and what the answer changes; a
 * question holds proceed (HARD #2).
 *
 * Beside the line, the open items on the same pick: "same as #n" (the
 * department co-owns it) or "add to #n" instead of a second one.
 *
 * Below: check items grouped by their owning department, each with its due
 * (= that department's assessment due) and, for the asker or Project
 * Management, "Make it a question". Questions are cards (NeedsInfoCard).
 */
import { useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { btnSm } from '../../common/buttonStyles'
import { toastError } from '../../../lib/apiError'
import { changesApi } from '../../../api/changes'
import { t } from '../../../i18n/cmLabels'
import { formatCalendarDate } from '../../../lib/format'
import { defaultFlagDepartment } from '../../../lib/scopingRules'
import { isRoutable } from '../../../lib/departments'
import { getActsAsDepartmentId } from '../../../lib/actsAs'
import { useAuth } from '../../../contexts/AuthContext'
import {
  CHECK_WHAT, isCheckItem,
  type AnswerFrom, type ChangeConcern, type CheckWhat, type ImpactedItem,
} from '../../../types/change'

const input = 'bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100'
const LAST_DEPT_KEY = 'plm2.scoping.lastRaisedFor'

function lastDept(): number | undefined {
  try {
    const v = window.localStorage.getItem(LAST_DEPT_KEY)
    return v ? Number(v) : undefined
  } catch { return undefined }
}
function rememberDept(id: number) {
  try { window.localStorage.setItem(LAST_DEPT_KEY, String(id)) } catch { /* private mode */ }
}

/** "Make it a question": who answers, what the answer changes in the scope. */
export function QuestionFields({ from, setFrom, effect, setEffect, idPrefix }: {
  from: AnswerFrom | ''; setFrom: (v: AnswerFrom) => void
  effect: string; setEffect: (v: string) => void; idPrefix: string
}) {
  return (
    <div className="space-y-1.5 rounded border border-amber-800/50 bg-amber-950/20 p-2"
      data-testid={`${idPrefix}-question-fields`}>
      <fieldset className="flex flex-wrap items-center gap-3 text-xs">
        <legend className="sr-only">{t('flag.answerFrom')}</legend>
        <span className="text-slate-400">{t('flag.answerFrom')}</span>
        {(['customer', 'our_team', 'supplier'] as AnswerFrom[]).map((k) => (
          <label key={k} className="flex items-center gap-1.5 cursor-pointer">
            <input type="radio" name={`${idPrefix}-from`} checked={from === k}
              data-testid={`${idPrefix}-from-${k}`} onChange={() => setFrom(k)} />
            <span className="text-slate-200">{t(`flag.from.${k}`)}</span>
          </label>
        ))}
      </fieldset>
      <input value={effect} onChange={(e) => setEffect(e.target.value)}
        aria-label={t('flag.scopeEffect')}
        placeholder={`${t('flag.scopeEffect')} ${t('flag.scopeEffectPlaceholder')}`}
        data-testid={`${idPrefix}-effect`} className={`${input} w-full`} />
    </div>
  )
}

export default function ScopingFlags({
  changeId, concerns, impactedItems, departments, myDepartmentIds,
  changeDepartmentIds, editable, canRaise = true, onChanged,
}: {
  changeId: number
  concerns: ChangeConcern[]
  impactedItems: ImpactedItem[]
  departments: { id: number; name: string; is_active?: boolean }[]
  myDepartmentIds: number[]
  /** Departments on this change (recommended / picked): preselect among them. */
  changeDepartmentIds: number[]
  editable: boolean
  /** Christoph 2026-10-27: questions and check items are raised in the
   *  meeting by the PM or the lead; everyone else reads them and brings
   *  their points to the meeting. */
  canRaise?: boolean
  onChanged: () => void
}) {
  const [note, setNote] = useState('')
  const [deptPicked, setDeptPicked] = useState<number | undefined>(undefined)
  const [asQuestion, setAsQuestion] = useState(false)
  // A2-03: proceed routes a check item's owner as C, so a check item is
  // raised only for a department that can be routed (not Management, not
  // retired); a question may be asked of any active department.
  const options = departments.filter((d) => (asQuestion ? d.is_active !== false : isRoutable(d)))
  const remembered = lastDept()
  const deptId = (deptPicked != null && options.some((d) => d.id === deptPicked) ? deptPicked : undefined)
    ?? (remembered != null && options.some((d) => d.id === remembered) ? remembered : undefined)
    ?? defaultFlagDepartment(myDepartmentIds, options, changeDepartmentIds)
    ?? changeDepartmentIds.find((id) => options.some((d) => d.id === id))
  const [what, setWhat] = useState<CheckWhat | ''>('')
  const [partId, setPartId] = useState<number | ''>('')
  const [from, setFrom] = useState<AnswerFrom | ''>('')
  const [effect, setEffect] = useState('')
  const [failure, setFailure] = useState<string | null>(null)
  const deptName = (id?: number | null) =>
    id == null ? '' : departments.find((d) => d.id === id)?.name ?? `#${id}`

  const reset = () => {
    setNote(''); setWhat(''); setPartId(''); setAsQuestion(false); setFrom(''); setEffect('')
    setFailure(null)
  }
  const raise = useMutation({
    mutationFn: () => changesApi.raiseConcern(changeId, {
      kind: 'needs_info', note: note.trim(), department_id: deptId,
      flag_type: asQuestion ? 'question' : 'check', check_what: what as CheckWhat,
      ...(partId !== '' ? { part_id: partId } : {}),
      ...(asQuestion ? { answer_from: from as AnswerFrom, scope_effect: effect.trim() } : {}),
    }),
    onSuccess: () => {
      if (deptId != null) rememberDept(deptId)
      reset(); toast.success(t('flag.added')); onChanged()
    },
    onError: (e: unknown) => setFailure(toastError(e, 'Could not add it')),
  })
  const join = useMutation({
    mutationFn: (vars: { id: number; sameAs: boolean; addTo: boolean }) => changesApi.joinConcern(changeId, vars.id, {
      ...(vars.sameAs && deptId != null ? { department_id: deptId } : {}),
      // the line goes along only where the backend lets the caller add it
      ...(note.trim() && vars.addTo ? { note: note.trim() } : {}),
    }),
    onSuccess: () => { reset(); onChanged() },
    onError: (e: unknown) => setFailure(toastError(e, 'Could not add it')),
  })

  // The open items on the same pick (what + part), beside the line.
  const open = concerns.filter((c) => c.is_open && c.kind === 'needs_info')
  const twins = what === '' ? [] : open.filter((c) => c.check_what === what
    && (c.part_id ?? '') === partId).slice(0, 3)
  // 'same as' is a department act: members only (an admin acts as the
  // department), as the backend's join_flag
  const mayCoOwn = deptId != null && myDepartmentIds.includes(deptId)
  // ...and a check item is co-owned only by a department that can be routed
  const deptRoutable = (id?: number) => {
    const d = departments.find((x) => x.id === id)
    return !!d && isRoutable(d)
  }

  const missing = [
    ...(note.trim() ? [] : [t('flag.missingNote')]),
    ...(deptId != null ? [] : [t('flag.missingDept')]),
    ...(what ? [] : [t('flag.missingWhat')]),
    ...(asQuestion && !from ? [t('flag.missingFrom')] : []),
    ...(asQuestion && effect.trim().length < 5 ? [t('flag.missingEffect')] : []),
  ]

  // Check items by owning department (the raised-for one), in raise order.
  const checks = open.filter(isCheckItem).sort((a, b) => a.id - b.id)
  const groups = useMemo(() => {
    const out = new Map<string, ChangeConcern[]>()
    for (const c of checks) {
      const key = c.owner_department_names?.[0] ?? deptName(c.department_id)
      out.set(key, [...(out.get(key) ?? []), c])
    }
    return [...out.entries()]
  }, [checks]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-3" data-testid="scoping-flags">
      {editable && !canRaise && (
        <p className="text-xs text-slate-400" data-testid="quick-add-pm-only">{t('flag.pmOnlyHint')}</p>
      )}
      {editable && canRaise && (
        <div className="rounded-lg border border-slate-700 bg-slate-800/60 p-3 space-y-2"
          data-testid="quick-add">
          <p className="text-[11px] uppercase tracking-wide text-slate-500">{t('flag.meetingTitle')}</p>
          <div className="flex flex-wrap items-center gap-2">
            <input value={note} onChange={(e) => setNote(e.target.value)}
              aria-label={t('flag.placeholder')} placeholder={t('flag.placeholder')}
              data-testid="quick-add-note"
              onKeyDown={(e) => { if (e.key === 'Enter' && missing.length === 0) raise.mutate() }}
              className={`${input} flex-1 min-w-[14rem]`} />
            <select value={deptId ?? ''} aria-label={t('flag.raisedFor')} data-testid="quick-add-dept"
              onChange={(e) => setDeptPicked(e.target.value ? Number(e.target.value) : undefined)}
              className={input}>
              {deptId == null && <option value="">{t('flag.raisedFor')}…</option>}
              {options.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
            <select value={what} aria-label={t('flag.checkWhat')} data-testid="quick-add-what"
              onChange={(e) => setWhat(e.target.value as CheckWhat | '')} className={input}>
              <option value="">{t('flag.checkWhat')}…</option>
              {CHECK_WHAT.map((k) => <option key={k} value={k}>{t(`flag.what.${k}`)}</option>)}
            </select>
            <select value={partId} aria-label={t('flag.part')} data-testid="quick-add-part"
              onChange={(e) => setPartId(e.target.value ? Number(e.target.value) : '')}
              className={`${input} max-w-[12rem]`}>
              <option value="">{t('flag.wholeChange')}</option>
              {impactedItems.map((i) => (
                <option key={i.part_id} value={i.part_id}>{i.part_number ?? `#${i.part_id}`}</option>
              ))}
            </select>
            <button type="button" className={asQuestion ? btnSm.secondary : btnSm.primary}
              data-testid="quick-add-submit"
              disabled={missing.length > 0 || raise.isPending}
              title={missing.length ? t('flag.missing').replace('{x}', missing.join(', ')) : undefined}
              onClick={() => raise.mutate()}>
              {asQuestion ? t('flag.addQuestion') : t('flag.addCheck')}
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
            <label className="flex items-center gap-1.5 cursor-pointer text-slate-300">
              <input type="checkbox" checked={asQuestion} data-testid="quick-add-question"
                onChange={(e) => setAsQuestion(e.target.checked)} />
              {t('flag.makeQuestion')}
            </label>
            {!asQuestion && <span className="text-slate-500">{t('flag.defaultHint')}</span>}
            {asQuestion && (
              <span className="text-amber-300/90" data-testid="quick-add-scope-test">
                {t('flag.scopeTest')} {t('flag.scopeTestNo')}
              </span>
            )}
          </div>
          {asQuestion && (
            <QuestionFields from={from} setFrom={setFrom} effect={effect}
              setEffect={setEffect} idPrefix="quick-add" />
          )}
          {twins.length > 0 && (
            <div className="text-[11px] space-y-1" data-testid="quick-add-twins">
              <span className="text-slate-400">{t('flag.existing')}</span>
              {twins.map((c) => (
                <div key={c.id} className="flex flex-wrap items-center gap-2">
                  <span className="text-slate-300">#{c.id} {c.note.split('\n')[0]}</span>
                  <span className="text-slate-500">({(c.owner_department_names ?? []).join(', ')})</span>
                  {mayCoOwn && (!isCheckItem(c) || deptRoutable(deptId))
                    && !(c.owner_department_names ?? []).includes(deptName(deptId)) && (
                    <button type="button" className="text-sky-300 hover:text-sky-200"
                      data-testid={`quick-add-same-${c.id}`} disabled={join.isPending}
                      onClick={() => join.mutate({ id: c.id, sameAs: true, addTo: !!c.can_add_to })}>
                      {t('flag.sameAs').replace('{n}', String(c.id))}
                    </button>
                  )}
                  {note.trim() && c.can_add_to && c.answered_at == null && (
                    <button type="button" className="text-sky-300 hover:text-sky-200"
                      data-testid={`quick-add-addto-${c.id}`} disabled={join.isPending}
                      onClick={() => join.mutate({ id: c.id, sameAs: false, addTo: true })}>
                      {t('flag.addTo').replace('{n}', String(c.id))}
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
          {failure && (
            <p role="alert" data-testid="quick-add-error"
              className="rounded border border-red-800/60 bg-red-950/40 px-2 py-1 text-xs text-red-200">
              {failure}
            </p>
          )}
        </div>
      )}

      <section className="space-y-1.5" data-testid="check-items">
        <h4 className="text-[11px] uppercase tracking-wide text-slate-500">
          {t('flag.checks')} ({checks.length})
        </h4>
        {checks.length === 0 ? (
          <p className="text-xs text-slate-500">{t('flag.noChecks')}</p>
        ) : groups.map(([owner, rows]) => (
          <details key={owner} className="rounded border border-slate-700 bg-slate-800/40"
            data-testid={`check-group-${owner}`}>
            <summary className="cursor-pointer px-2 py-1 text-xs text-slate-200">
              {owner} <span className="text-slate-500">({rows.length})</span>
            </summary>
            <ul className="divide-y divide-slate-700/60">
              {rows.map((c) => (
                <CheckRow key={c.id} changeId={changeId} c={c} editable={editable}
                  onChanged={onChanged} />
              ))}
            </ul>
          </details>
        ))}
      </section>
    </div>
  )
}

/** One check item: what, part, the line, who raised it, its due; the asker
 *  or Project Management may make it a question, or withdraw it. */
export function CheckRow({ changeId, c, editable, onChanged }: {
  changeId: number; c: ChangeConcern; editable: boolean; onChanged: () => void
}) {
  const { userId } = useAuth()
  const [promoting, setPromoting] = useState(false)
  const [from, setFrom] = useState<AnswerFrom | ''>('')
  const [effect, setEffect] = useState('')
  const promote = useMutation({
    mutationFn: () => changesApi.setConcernType(changeId, c.id, {
      flag_type: 'question', answer_from: from as AnswerFrom, scope_effect: effect.trim() }),
    onSuccess: () => { setPromoting(false); onChanged() },
    onError: (e: unknown) => { toastError(e, 'Could not make it a question') },
  })
  // Withdrawing an item raised for a department says why (backend rule).
  const [withdrawing, setWithdrawing] = useState(false)
  const [why, setWhy] = useState('')
  const withdraw = useMutation({
    mutationFn: () => changesApi.withdrawConcern(changeId, c.id, why.trim()),
    onSuccess: () => { setWithdrawing(false); setWhy(''); onChanged() },
    onError: (e: unknown) => { toastError(e, 'Could not withdraw it') },
  })
  const isAuthor = getActsAsDepartmentId() == null && userId != null && c.raised_by === userId
  const co = (c.owner_department_names ?? []).slice(1)
  return (
    <li className="px-2 py-1.5 text-xs space-y-1" data-testid={`check-row-${c.id}`}>
      <div className="flex flex-wrap items-baseline gap-2">
        {c.check_what && (
          <span className="rounded bg-slate-700 px-1.5 text-[11px] text-slate-200">
            {t(`flag.what.${c.check_what}`)}
          </span>
        )}
        <span className="text-slate-400">{c.part_number ?? t('flag.wholeChange')}</span>
        <span className="text-slate-100 whitespace-pre-wrap">{c.note}</span>
        <span className="text-slate-500">
          {t('flag.byRaiser').replace('{x}', c.raised_by_name ?? `#${c.raised_by}`)}
          {co.length > 0 && ` · ${t('flag.coOwner')} ${co.join(', ')}`}
        </span>
        <span className="ml-auto text-slate-400" data-testid={`check-due-${c.id}`}>
          {c.owner_due ? t('flag.due').replace('{d}', formatCalendarDate(c.owner_due)) : t('flag.dueAtAssessment')}
        </span>
      </div>
      {withdrawing && (
        <div className="flex flex-wrap items-center gap-2">
          <input value={why} onChange={(e) => setWhy(e.target.value)} autoFocus
            aria-label={t('concern.resolution')} placeholder={t('concern.resolution')}
            data-testid={`check-withdraw-note-${c.id}`} className={`${input} flex-1 min-w-[12rem]`} />
          <button type="button" className={btnSm.secondary} data-testid={`check-withdraw-confirm-${c.id}`}
            disabled={!why.trim() || withdraw.isPending} onClick={() => withdraw.mutate()}>
            {t('concern.withdraw')}
          </button>
          <button type="button" className="text-slate-400 hover:text-slate-200"
            onClick={() => setWithdrawing(false)}>{t('common.cancel')}</button>
        </div>
      )}
      {editable && (c.can_switch || isAuthor) && !promoting && !withdrawing && (
        <div className="flex flex-wrap gap-3">
          {c.can_switch && (
            <button type="button" className="text-sky-300 hover:text-sky-200"
              data-testid={`check-promote-${c.id}`} onClick={() => setPromoting(true)}>
              {t('proceed.promote')}
            </button>
          )}
          {isAuthor && (
            <button type="button" className="text-slate-400 hover:text-slate-200"
              data-testid={`check-withdraw-${c.id}`} onClick={() => setWithdrawing(true)}>
              {t('concern.withdraw')}
            </button>
          )}
        </div>
      )}
      {promoting && (
        <div className="space-y-1.5">
          <p className="text-[11px] text-amber-300/90">{t('flag.scopeTest')} {t('flag.scopeTestNo')}</p>
          <QuestionFields from={from} setFrom={setFrom} effect={effect} setEffect={setEffect}
            idPrefix={`promote-${c.id}`} />
          <div className="flex gap-2">
            <button type="button" className={btnSm.primary} data-testid={`check-promote-save-${c.id}`}
              disabled={!from || effect.trim().length < 5 || promote.isPending}
              onClick={() => promote.mutate()}>{t('proceed.promote')}</button>
            <button type="button" className="text-slate-400 hover:text-slate-200"
              onClick={() => setPromoting(false)}>{t('common.cancel')}</button>
          </div>
        </div>
      )}
    </li>
  )
}
