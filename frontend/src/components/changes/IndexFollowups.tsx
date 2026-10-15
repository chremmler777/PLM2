/**
 * A new customer index on a part this change carried (ECR-solid spec §1).
 *
 * One card per new index: what changed, then the follow-ups, each with its
 * owner:
 * - Recheck per routed department that had submitted: per changed area
 *   "No effect" (drawing ref / checklist row) or "Effect" (what + evidence),
 *   plus "Something else changed". Nothing preselected.
 * - The lead: "Index D adds parts or departments?" (shown on the recheck
 *   cards while open).
 * - Sales (an open quote): "D replaces C; does the quote deadline hold?"
 * Departments that had not submitted see a banner: assess on D.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { btnSm } from '../common/buttonStyles'
import { toastError } from '../../lib/apiError'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'
import { formatDate } from '../../lib/format'
import DateInput from '../gantt/DateInput'
import type {
  Assessment, Attachment, ChangeRecheck, IndexFollowup, RecheckAreaAnswer,
} from '../../types/change'

const input = 'bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100'
const areaLabel = (a: string) => t(`intake.area.${a}`)

export interface IndexFollowupsProps {
  changeId: number
  assessments: Pick<Assessment, 'department_id' | 'submitted_at' | 'status'>[]
  departments: { id: number; name: string }[]
  myDepartmentIds: number[]
  mayLead: boolean
  isSales: boolean
  leadName?: string | null
  salesOwnerName?: string | null
  attachments: Attachment[]
  readOnly?: boolean
}

export default function IndexFollowups(props: IndexFollowupsProps) {
  const { changeId } = props
  const { data: rows = [] } = useQuery({
    queryKey: ['change', changeId, 'index-followups'],
    queryFn: () => changesApi.indexFollowups(changeId),
  })
  if (rows.length === 0) return null
  return (
    <div className="space-y-3" data-testid="index-followups">
      {rows.map((f) => <FollowupCard key={f.intake_id} f={f} {...props} />)}
    </div>
  )
}

function FollowupCard({ f, changeId, assessments, departments, myDepartmentIds, mayLead,
  isSales, leadName, salesOwnerName, attachments, readOnly }: IndexFollowupsProps & { f: IndexFollowup }) {
  const qc = useQueryClient()
  const onDone = (data: IndexFollowup[]) => {
    qc.setQueryData(['change', changeId, 'index-followups'], data)
    qc.invalidateQueries({ queryKey: ['change', changeId] })
    qc.invalidateQueries({ queryKey: ['change-my-tasks'] })
  }
  // Routed departments that had not submitted: they assess on the new index.
  const recheckDepts = new Set(f.rechecks.map((r) => r.department_id))
  const unsubmitted = [...new Set(assessments
    .filter((a) => a.status !== 'waived' && !a.submitted_at && !recheckDepts.has(a.department_id))
    .map((a) => a.department_id))]
  const mineUnsubmitted = unsubmitted.filter((d) => myDepartmentIds.includes(d))
  const open = f.lead_open || f.deadline_open || f.rechecks.some((r) => r.status === 'open')
  return (
    <section data-testid={`followup-${f.intake_id}`}
      className={`rounded-lg border p-3 space-y-2 ${open ? 'border-amber-700/60 bg-amber-950/20'
        : 'border-slate-700 bg-slate-800/40'}`}>
      <p className="text-sm font-medium text-slate-100">
        {t('followup.title').replace('{to}', f.to_revision ?? '?')
          .replace('{from}', f.from_revision ?? '?').replace('{p}', f.part_number ?? '')}
      </p>
      <p className="text-xs text-slate-300">
        {f.what_changed.includes('none')
          ? t('followup.noVisible').replace('{x}', f.no_change_reason ?? '')
          : t('followup.areas').replace('{x}', f.what_changed.map(areaLabel).join(', '))}
        {f.what_changed_ref ? ` · ${f.what_changed_ref}` : ''}
      </p>
      {mineUnsubmitted.length > 0 && (
        <p data-testid="assess-on-new" role="note"
          className="rounded border border-sky-700/60 bg-sky-950/30 px-2 py-1 text-xs text-sky-100">
          {t('followup.assessOnNew').split('{to}').join(f.to_revision ?? '?')
            .replace('{from}', f.from_revision ?? '?')}
        </p>
      )}
      {f.lead_open || f.scope_answer ? (
        <LeadQuestion f={f} changeId={changeId} mayAnswer={mayLead && !readOnly}
          leadName={leadName} onDone={onDone} />
      ) : null}
      {f.rechecks.map((r) => (
        <RecheckCard key={r.id} r={r} f={f} changeId={changeId} onDone={onDone}
          deptName={r.department_name ?? departments.find((d) => d.id === r.department_id)?.name ?? ''}
          mayAnswer={!readOnly && myDepartmentIds.includes(r.department_id)} />
      ))}
      {(f.deadline_open || f.deadline_answer) && (
        <DeadlineQuestion f={f} changeId={changeId} mayAnswer={isSales && !readOnly}
          salesOwnerName={salesOwnerName} attachments={attachments} onDone={onDone} />
      )}
    </section>
  )
}

function LeadQuestion({ f, changeId, mayAnswer, leadName, onDone }: {
  f: IndexFollowup; changeId: number; mayAnswer: boolean; leadName?: string | null
  onDone: (d: IndexFollowup[]) => void
}) {
  const [answer, setAnswer] = useState<'' | 'no' | 'yes'>('')
  const [note, setNote] = useState('')
  const save = useMutation({
    mutationFn: () => changesApi.answerIndexScope(changeId, f.intake_id, {
      answer: answer as 'no' | 'yes', ...(answer === 'yes' ? { note: note.trim() } : {}) }),
    onSuccess: onDone,
    onError: (e: unknown) => { toastError(e, 'Could not record the answer') },
  })
  const q = t('followup.lead').replace('{to}', f.to_revision ?? '?')
  if (!f.lead_open) {
    return (
      <p className="text-xs text-slate-400" data-testid="lead-answered">
        {q} {t('followup.leadAnswered').replace('{x}', f.scope_answer === 'yes'
          ? `${t('followup.leadYes')} ${f.scope_note ?? ''}` : t('followup.leadNo'))}
        {f.scope_by_name ? ` · ${f.scope_by_name}` : ''}
      </p>
    )
  }
  const ready = answer === 'no' || (answer === 'yes' && note.trim().length >= 5)
  return (
    <div className="rounded border border-slate-700 p-2 space-y-1" data-testid="lead-question">
      <p className="text-xs font-medium text-slate-200">{q}</p>
      {!mayAnswer ? (
        <p className="text-[11px] text-slate-500">
          {t('followup.leadOwes').replace('{x}', leadName ?? 'The lead')}
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-3 text-xs">
          {(['no', 'yes'] as const).map((v) => (
            <label key={v} className="flex items-center gap-1.5 cursor-pointer text-slate-200">
              <input type="radio" name={`lead-${f.intake_id}`} checked={answer === v}
                data-testid={`lead-${v}`} onChange={() => setAnswer(v)} />
              {t(v === 'no' ? 'followup.leadNo' : 'followup.leadYes')}
            </label>
          ))}
          {answer === 'yes' && (
            <input value={note} onChange={(e) => setNote(e.target.value)} data-testid="lead-note"
              aria-label={t('followup.leadNotePlaceholder')}
              placeholder={t('followup.leadNotePlaceholder')} className={`${input} flex-1 min-w-[12rem]`} />
          )}
          {answer !== '' && (
            <button type="button" className={btnSm.primary} data-testid="lead-save"
              disabled={!ready || save.isPending} onClick={() => save.mutate()}>
              {t('followup.save')}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

type AreaDraft = { effect: '' | 'no' | 'yes'; ref: string; what: string; evidence: string }
const blank: AreaDraft = { effect: '', ref: '', what: '', evidence: '' }
const okRef = (v: string) => v.trim().length >= 5

function RecheckCard({ r, f, changeId, deptName, mayAnswer, onDone }: {
  r: ChangeRecheck; f: IndexFollowup; changeId: number; deptName: string; mayAnswer: boolean
  onDone: (d: IndexFollowup[]) => void
}) {
  const [draft, setDraft] = useState<Record<string, AreaDraft>>({})
  const [elseOn, setElseOn] = useState(false)
  const [elseWhat, setElseWhat] = useState('')
  const [elseEvidence, setElseEvidence] = useState('')
  const set = (a: string, patch: Partial<AreaDraft>) =>
    setDraft((d) => ({ ...d, [a]: { ...(d[a] ?? blank), ...patch } }))
  const answers: RecheckAreaAnswer[] = r.areas.map((a) => {
    const d = draft[a] ?? blank
    return d.effect === 'yes'
      ? { area: a, effect: true, what: d.what.trim(), evidence: d.evidence.trim() }
      : { area: a, effect: false, ref: d.ref.trim() }
  })
  const ready = r.areas.every((a) => {
    const d = draft[a] ?? blank
    return d.effect === 'no' ? okRef(d.ref)
      : d.effect === 'yes' ? d.what.trim().length >= 5 && okRef(d.evidence) : false
  }) && (!elseOn || (elseWhat.trim().length >= 5 && okRef(elseEvidence)))
  const save = useMutation({
    mutationFn: () => changesApi.answerRecheck(changeId, r.id, {
      answers, something_else: elseOn ? { what: elseWhat.trim(), evidence: elseEvidence.trim() } : null }),
    onSuccess: onDone,
    onError: (e: unknown) => { toastError(e, 'Could not save the recheck') },
  })
  return (
    <div className="rounded border border-slate-700 p-2 space-y-1" data-testid={`recheck-${r.id}`}>
      <p className="text-xs font-medium text-slate-200">
        {t('followup.recheckFor').replace('{d}', deptName)}
        {r.status === 'answered' && ` · ${r.effect ? t('followup.answeredEffect') : t('followup.answeredNoEffect')}`}
        {r.answered_by_name ? ` · ${r.answered_by_name} ${formatDate(r.answered_at)}` : ''}
      </p>
      {f.lead_open && r.status === 'open' && (
        <p className="text-[11px] text-amber-300/90">{t('followup.lead').replace('{to}', f.to_revision ?? '?')}</p>
      )}
      {r.status === 'answered' ? (
        <ul className="text-[11px] text-slate-400 space-y-0.5">
          {r.answers.map((a) => (
            <li key={a.area}>{areaLabel(a.area)}: {a.effect ? `${a.what} (${a.evidence})` : `${t('followup.noEffect')} (${a.ref})`}</li>
          ))}
          {r.something_else && <li>{t('followup.somethingElse')}: {r.something_else}</li>}
        </ul>
      ) : !mayAnswer ? (
        <p className="text-[11px] text-slate-500">{t('followup.recheckOwes').replace('{d}', deptName)}</p>
      ) : (
        <div className="space-y-1.5">
          {r.areas.map((a) => {
            const d = draft[a] ?? blank
            return (
              <div key={a} className="flex flex-wrap items-center gap-2 text-xs">
                <span className="w-28 text-slate-300">{areaLabel(a)}</span>
                {(['no', 'yes'] as const).map((v) => (
                  <label key={v} className="flex items-center gap-1 cursor-pointer text-slate-200">
                    <input type="radio" name={`rc-${r.id}-${a}`} checked={d.effect === v}
                      data-testid={`rc-${a}-${v}`} onChange={() => set(a, { effect: v })} />
                    {t(v === 'no' ? 'followup.noEffect' : 'followup.effect')}
                  </label>
                ))}
                {d.effect === 'no' && (
                  <input value={d.ref} onChange={(e) => set(a, { ref: e.target.value })}
                    data-testid={`rc-${a}-ref`} aria-label={t('followup.refPlaceholder')}
                    placeholder={t('followup.refPlaceholder')} className={`${input} flex-1 min-w-[10rem]`} />
                )}
                {d.effect === 'yes' && (
                  <>
                    <input value={d.what} onChange={(e) => set(a, { what: e.target.value })}
                      data-testid={`rc-${a}-what`} aria-label={t('followup.whatPlaceholder')}
                      placeholder={t('followup.whatPlaceholder')} className={`${input} flex-1 min-w-[10rem]`} />
                    <input value={d.evidence} onChange={(e) => set(a, { evidence: e.target.value })}
                      data-testid={`rc-${a}-evidence`} aria-label={t('followup.evidencePlaceholder')}
                      placeholder={t('followup.evidencePlaceholder')} className={`${input} flex-1 min-w-[10rem]`} />
                  </>
                )}
              </div>
            )
          })}
          <label className="flex items-center gap-1.5 text-xs text-slate-300 cursor-pointer">
            <input type="checkbox" checked={elseOn} data-testid="rc-else"
              onChange={(e) => setElseOn(e.target.checked)} />
            {t('followup.somethingElse')}
          </label>
          {elseOn && (
            <div className="flex flex-wrap gap-2">
              <input value={elseWhat} onChange={(e) => setElseWhat(e.target.value)}
                aria-label={t('followup.whatPlaceholder')} placeholder={t('followup.whatPlaceholder')}
                className={`${input} flex-1 min-w-[10rem]`} />
              <input value={elseEvidence} onChange={(e) => setElseEvidence(e.target.value)}
                aria-label={t('followup.evidencePlaceholder')} placeholder={t('followup.evidencePlaceholder')}
                className={`${input} flex-1 min-w-[10rem]`} />
            </div>
          )}
          <p className="text-[11px] text-slate-500">{t('followup.effectBeforeQuote')}</p>
          <button type="button" className={btnSm.primary} data-testid="rc-save"
            disabled={!ready || save.isPending} onClick={() => save.mutate()}>
            {t('followup.saveRecheck')}
          </button>
        </div>
      )}
    </div>
  )
}

function DeadlineQuestion({ f, changeId, mayAnswer, salesOwnerName, attachments, onDone }: {
  f: IndexFollowup; changeId: number; mayAnswer: boolean; salesOwnerName?: string | null
  attachments: Attachment[]; onDone: (d: IndexFollowup[]) => void
}) {
  const [answer, setAnswer] = useState<'' | 'holds' | 'new_date' | 'not_asked'>('')
  const [ref, setRef] = useState('')
  const [mailId, setMailId] = useState<number | ''>('')
  const [date, setDate] = useState('')
  const mails = attachments.filter((a) => a.kind === 'customer_email')
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
  const save = useMutation({
    mutationFn: () => changesApi.answerIndexDeadline(changeId, f.intake_id, {
      answer: answer as 'holds' | 'new_date' | 'not_asked',
      ...(answer === 'not_asked' ? {} : mailId !== '' ? { mail_id: mailId } : { ref: ref.trim() }),
      ...(answer === 'new_date' ? { new_date: `${date}T12:00:00` } : {}),
    }),
    onSuccess: onDone,
    onError: (e: unknown) => { toastError(e, 'Could not record the answer') },
  })
  const q = t('followup.deadline').replace('{to}', f.to_revision ?? '?').replace('{from}', f.from_revision ?? '?')
  const evidenceOk = mailId !== '' || okRef(ref)
  const ready = answer === 'not_asked' || (answer === 'holds' && evidenceOk)
    || (answer === 'new_date' && evidenceOk && !!date)
  // once "not asked yet" was given, only holds / new date close it
  const options = (f.deadline_answer === 'not_asked' ? ['holds', 'new_date'] : ['holds', 'new_date', 'not_asked']) as
    ('holds' | 'new_date' | 'not_asked')[]
  return (
    <div className="rounded border border-slate-700 p-2 space-y-1" data-testid="deadline-question">
      <p className="text-xs font-medium text-slate-200">{q}</p>
      {f.deadline_answer && (
        <p className="text-[11px] text-slate-400" data-testid="deadline-answered">
          {f.deadline_answer === 'not_asked'
            ? t('followup.deadlineAssumed').replace('{d}', formatDate(f.deadline_confirm_by))
            : t('followup.deadlineAnswered').replace('{x}',
              `${t(`followup.deadline.${f.deadline_answer}`)}${f.deadline_ref ? ` (${f.deadline_ref})` : ''}`)}
        </p>
      )}
      {f.deadline_open && (!mayAnswer ? (
        <p className="text-[11px] text-slate-500">
          {t('followup.deadlineOwes').replace('{x}', salesOwnerName ?? 'Sales')}
        </p>
      ) : (
        <div className="space-y-1.5 text-xs">
          <div className="flex flex-wrap gap-3">
            {options.map((v) => (
              <label key={v} className="flex items-center gap-1.5 cursor-pointer text-slate-200">
                <input type="radio" name={`dl-${f.intake_id}`} checked={answer === v}
                  data-testid={`dl-${v}`} onChange={() => setAnswer(v)} />
                {t(`followup.deadline.${v}`)}
              </label>
            ))}
          </div>
          {(answer === 'holds' || answer === 'new_date') && (
            <div className="flex flex-wrap gap-2">
              {mails.length > 0 && (
                <select value={mailId} aria-label={t('answer.mail')}
                  onChange={(e) => setMailId(e.target.value ? Number(e.target.value) : '')}
                  className={`${input} max-w-[18rem]`}>
                  <option value="">{t('answer.mailPick')}</option>
                  {mails.map((m) => <option key={m.id} value={m.id}>{m.filename}</option>)}
                </select>
              )}
              {mailId === '' && (
                <input value={ref} onChange={(e) => setRef(e.target.value)} data-testid="dl-ref"
                  aria-label={t('answer.ref')} placeholder={t('answer.refPlaceholder')}
                  className={`${input} flex-1 min-w-[12rem]`} />
              )}
              {answer === 'new_date' && (
                <DateInput value={date} onChange={setDate} aria-label={t('deadline.quote')}
                  className={`${input} w-36`} />
              )}
            </div>
          )}
          {answer !== '' && (
            <button type="button" className={btnSm.primary} data-testid="dl-save"
              disabled={!ready || save.isPending} onClick={() => save.mutate()}>
              {t('followup.save')}
            </button>
          )}
        </div>
      ))}
    </div>
  )
}
