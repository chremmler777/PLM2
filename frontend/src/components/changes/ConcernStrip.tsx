import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { useAuth } from '../../contexts/AuthContext'
import { t } from '../../i18n/cmLabels'
import { preferredDepartmentId } from '../../lib/departments'
import AttachmentDropzone from './AttachmentDropzone'
import { AttachmentRow } from './AttachmentRow'
import type { Attachment, ChangeConcern, ConcernKind } from '../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const KIND_STYLE: Record<ConcernKind, string> = {
  reject_proposal: 'bg-red-900/60 text-red-200 border-red-800',
  needs_info: 'bg-amber-900/50 text-amber-200 border-amber-800',
}

/**
 * Concerns let the team work the decision in parallel: anyone can flag that
 * they'd reject the change or that something is missing, without waiting for
 * the meeting. Open flags block 'proceed', so the meeting cannot quietly run
 * over an objection — it has to be withdrawn by its author, or answered by a
 * reject / needs-info decision, which closes it.
 *
 * Deliberately no "clear all": only the person who raised a flag may drop it.
 */
export default function ConcernStrip({
  changeId, editable, scoped = false, departments = [], myDepartmentIds = [],
  hideConcernIds = [], onlyDepartmentId, isPm = false, attachments = [],
}: {
  changeId: number
  editable: boolean
  /** Concerns shown as their own containers elsewhere on the page. */
  hideConcernIds?: number[]
  /** Inside a department bucket: only that department's flags, raised for it. */
  onlyDepartmentId?: number
  /** Project Management may settle any objection. */
  isPm?: boolean
  /** The change's documents, so a proposal can show and require its own. */
  attachments?: Attachment[]
  /** Assessment phase: every flag belongs to a department, and dropping one
   *  needs a written resolution. */
  scoped?: boolean
  departments?: { id: number; name: string; is_active?: boolean }[]
  myDepartmentIds?: number[]
}) {
  const qc = useQueryClient()
  const { userId, isAdmin } = useAuth()
  const [kind, setKind] = useState<ConcernKind>('needs_info')
  const [note, setNote] = useState('')
  const [adding, setAdding] = useState(false)
  // Which concern is being withdrawn, and the note explaining how it was met.
  const [withdrawing, setWithdrawing] = useState<number | null>(null)
  const [resolution, setResolution] = useState('')
  // A refused flag must say why in place: a toast is missed, and the typed note
  // has to survive so the user can fix the problem and send it again.
  const [failure, setFailure] = useState<string | null>(null)
  // A proposal is text plus its documentation, and the author confirming that
  // the documentation is really there — the explicit tick the business asked for.
  const [proposing, setProposing] = useState<number | null>(null)
  const [proposal, setProposal] = useState('')
  const [docConfirmed, setDocConfirmed] = useState(false)

  // In assessment you flag for your own department (admins for any). In scoping
  // the department is mere attribution — anyone may say "this concerns Packaging"
  // — and "Team" (no department) is the default.
  const selectable = departments.filter((d) => d.is_active !== false)
  const options = !scoped ? selectable
    : isAdmin ? selectable
    : selectable.filter((d) => myDepartmentIds.includes(d.id))
  const [deptId, setDeptId] = useState<number | undefined>(onlyDepartmentId)
  // Scoping starts on "Team". Assessment starts on the master department when
  // the user holds it, and otherwise on nothing at all — they pick.
  const effectiveDept = onlyDepartmentId ?? deptId ?? (scoped
    ? preferredDepartmentId(myDepartmentIds, options)
    : undefined)
  const deptName = (id?: number | null) =>
    id == null ? null : departments.find((d) => d.id === id)?.name ?? `#${id}`

  const { data: concerns = [] } = useQuery({
    queryKey: ['change', changeId, 'concerns'],
    queryFn: () => changesApi.listConcerns(changeId),
  })
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['change', changeId, 'concerns'] })
    qc.invalidateQueries({ queryKey: ['change', changeId] })
  }

  const raise = useMutation({
    mutationFn: () => changesApi.raiseConcern(changeId, kind, note.trim(), effectiveDept),
    onSuccess: () => { setNote(''); setAdding(false); setFailure(null); invalidate() },
    onError: (e: unknown) => {
      const detail = errDetail(e) ?? 'Could not raise the flag'
      setFailure(detail)
      toast.error(detail)
    },
  })
  const withdraw = useMutation({
    mutationFn: (vars: { concernId: number; note: string }) =>
      changesApi.withdrawConcern(changeId, vars.concernId, vars.note.trim() || undefined),
    onSuccess: () => { setWithdrawing(null); setResolution(''); setFailure(null); invalidate() },
    onError: (e: unknown) => {
      const detail = errDetail(e) ?? 'Could not withdraw'
      setFailure(detail)
      toast.error(detail)
    },
  })

  // A team needs-info flag is the customer question in flag form: Sales closes it
  // by writing the answer. Everything else is the author's own to withdraw.
  // Who may settle a row, mirroring the backend: the author always, PM always,
  // and for a department-attributed flag its own members.
  //
  // `userId != null` matters: without it an unloaded session (userId null) and a
  // payload with a null raiser compare equal, and the control unlocks for
  // everyone. That is exactly how it went wrong in the field.
  const isAuthor = (c: ChangeConcern) => userId != null && c.raised_by === userId
  const isRaisingDept = (c: ChangeConcern) =>
    c.department_id != null && myDepartmentIds.includes(c.department_id)
  const mayClose = (c: ChangeConcern) => isAuthor(c) || isPm || isRaisingDept(c)
  const closerRule = (c: ChangeConcern) =>
    c.department_id != null ? t('concern.authorDeptOrPm') : t('concern.authorOrPm')

  // One vocabulary switch: assessment talks risks, scoping talks concerns.
  const w = {
    title: scoped ? t('risk.title') : t('concern.title'),
    hint: t('risk.hint'),
    raise: scoped ? t('risk.raise') : t('concern.raise'),
    proposal: scoped ? t('risk.proposal') : t('concern.proposal'),
    settle: scoped ? t('risk.resolved') : t('concern.markSolved'),
    kindOf: (k: ConcernKind) => scoped
      ? (k === 'needs_info' ? t('risk.question') : t('risk.kind'))
      : (k === 'reject_proposal' ? t('concern.wouldReject') : t('concern.wantsInfo')),
  }

  const docsOf = (concernId: number) =>
    attachments.filter((a) => a.concern_id === concernId)

  const propose = useMutation({
    mutationFn: (vars: { concernId: number; note: string }) =>
      changesApi.answerConcern(changeId, vars.concernId, vars.note.trim()),
    onSuccess: () => {
      setProposing(null); setProposal(''); setDocConfirmed(false)
      setFailure(null); invalidate()
    },
    onError: (e: unknown) => {
      const detail = errDetail(e) ?? 'Could not submit the proposal'
      setFailure(detail)
      toast.error(detail)
    },
  })

  const listed = concerns
    .filter((c: ChangeConcern) => !hideConcernIds.includes(c.id))
    .filter((c: ChangeConcern) =>
      onlyDepartmentId === undefined || c.department_id === onlyDepartmentId)
  const open = listed.filter((c: ChangeConcern) => c.is_open)
  const settled = listed.filter((c: ChangeConcern) => !c.is_open)

  return (
    <div className={`rounded-lg border p-3 space-y-2 ${
      open.length > 0 ? 'border-amber-700/60 bg-amber-950/20' : 'border-slate-700 bg-slate-800'}`}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-medium text-slate-100">{w.title}</span>
        {open.length > 0 && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-amber-900 text-amber-100">
            {t('concern.blocking').replace('{n}', String(open.length))}
          </span>
        )}
        {editable && !adding && (
          <button className="ml-auto text-xs text-sky-300 hover:text-sky-200"
            onClick={() => { setFailure(null); setAdding(true) }}>+ {w.raise}</button>
        )}
      </div>

      {scoped && <p className="text-[11px] text-slate-500">{w.hint}</p>}

      {open.length === 0 && settled.length === 0 && (
        <p className="text-xs text-slate-500">{t('concern.none')}</p>
      )}

      <ul className="space-y-1">
        {[...open, ...settled].map((c: ChangeConcern) => (
          <li key={c.id}
            className={`flex items-start gap-2 text-sm rounded border px-2 py-1.5 ${
              c.is_open ? KIND_STYLE[c.kind] : 'border-slate-700 bg-slate-900/40 text-slate-500'}`}>
            <span className="text-xs font-semibold flex-shrink-0 mt-0.5">
              {w.kindOf(c.kind)}
            </span>
            <span className="min-w-0 flex-1">
              {c.department_id != null && (
                <span className="mr-1.5 rounded bg-slate-800/80 px-1 py-0 text-[10px] leading-tight align-middle">
                  {deptName(c.department_id)}
                </span>
              )}
              <span className={c.is_open ? '' : 'line-through'}>{c.note}</span>
              <span className="block text-xs opacity-70">
                {c.raised_by_name ?? `#${c.raised_by}`}
                {!c.is_open && ` — ${c.withdrawn_at ? t('concern.withdrawn') : t('concern.answered')}`}
              </span>
              {!c.is_open && c.resolution_note && (
                <span className="block text-xs opacity-70">
                  {t('concern.resolved')}: {c.resolution_note}
                </span>
              )}
              {/* A department point is solved by whoever can solve it: anyone may
                  put a proposal on it, and the raising side then settles it. */}
              {scoped && c.is_open && (
                <span className="block mt-1 space-y-1">
                  {c.answer_note && (
                    <>
                      <span data-testid={`concern-proposal-state-${c.id}`}
                        className="inline-flex items-center rounded bg-sky-900/70 text-sky-200 px-1.5 py-0 text-[10px] leading-tight font-medium">
                        {t('concern.proposalReceived').replace('{x}',
                          deptName(c.department_id) ?? t('concern.deptTitle'))}
                      </span>
                      <span className="block text-xs" data-testid={`concern-proposal-${c.id}`}>
                        {w.proposal}: {c.answer_note}
                        <span className="block opacity-70">
                          {t('concern.proposalBy')}{' '}
                          {c.answered_by_name ?? (c.answered_by != null ? `#${c.answered_by}` : '—')}
                        </span>
                      </span>
                    </>
                  )}
                  {docsOf(c.id).length > 0 && (
                    <ul className="text-sm rounded border border-slate-700/60 bg-slate-900/30 px-2 py-0.5">
                      {docsOf(c.id).map((a) => (
                        <AttachmentRow key={a.id} changeId={changeId} attachment={a} />
                      ))}
                    </ul>
                  )}
                  {editable && (proposing === c.id ? (
                    <span className="block space-y-1">
                      <textarea value={proposal} rows={2}
                        data-testid={`concern-proposal-note-${c.id}`}
                        onChange={(e) => setProposal(e.target.value)}
                        placeholder={t('concern.proposalPlaceholder')}
                        aria-label={w.proposal}
                        className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
                      <AttachmentDropzone changeId={changeId} concernId={c.id} compact
                        label={t('concern.proposalDocSlot')} onUploaded={invalidate} />
                      <label className="flex items-center gap-2 text-xs cursor-pointer">
                        <input type="checkbox" data-testid={`concern-proposal-confirm-${c.id}`}
                          checked={docConfirmed}
                          onChange={(e) => setDocConfirmed(e.target.checked)} />
                        <span className="text-slate-300">{t('concern.proposalConfirm')}</span>
                      </label>
                      {docsOf(c.id).length === 0 && (
                        <span className="block text-[11px] text-amber-300/80"
                          data-testid={`concern-proposal-needsdoc-${c.id}`}>
                          {t('concern.proposalNeedsDoc')}
                        </span>
                      )}
                      <span className="flex flex-wrap gap-2">
                        <button data-testid={`concern-proposal-submit-${c.id}`}
                          className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50 disabled:cursor-not-allowed"
                          disabled={!proposal.trim() || !docConfirmed
                            || docsOf(c.id).length === 0 || propose.isPending}
                          onClick={() => propose.mutate({ concernId: c.id, note: proposal })}>
                          {t('concern.proposalSubmit')}
                        </button>
                        <button className="text-xs text-slate-400 hover:text-slate-200 px-1"
                          onClick={() => {
                            setProposing(null); setProposal(''); setDocConfirmed(false)
                          }}>
                          {t('common.cancel')}
                        </button>
                      </span>
                    </span>
                  ) : (
                    <button data-testid={`concern-propose-${c.id}`}
                      className="text-xs text-sky-300 hover:text-sky-200"
                      onClick={() => {
                        setProposing(c.id); setProposal(c.answer_note ?? '')
                        setDocConfirmed(false)
                      }}>
                      + {w.proposal}
                    </button>
                  ))}
                </span>
              )}
              {withdrawing === c.id && (() => {
                // Sales answering owes the answer itself; a department flag owes
                // its resolution; a plain team withdrawal may go unexplained.
                const answering = !isAuthor(c)
                const noteRequired = answering || c.department_id != null
                return (
                  <span className="mt-1 flex flex-wrap items-center gap-2">
                    <textarea value={resolution} rows={2}
                      onChange={(e) => setResolution(e.target.value)}
                      data-testid="concern-withdraw-note"
                      placeholder={answering ? t('concern.answerPlaceholder') : t('concern.resolution')}
                      aria-label={answering ? t('concern.answer') : t('concern.resolution')}
                      className="flex-1 min-w-[14rem] bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
                    <button data-testid="concern-withdraw-confirm"
                      className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50"
                      disabled={withdraw.isPending || (noteRequired && !resolution.trim())}
                      onClick={() => withdraw.mutate({ concernId: c.id, note: resolution })}>
                      {scoped ? w.settle : (answering ? t('concern.markSolved') : t('concern.withdraw'))}
                    </button>
                    <button className="text-xs text-slate-400 hover:text-slate-200 px-1"
                      onClick={() => { setWithdrawing(null); setResolution('') }}>
                      {t('common.cancel')}
                    </button>
                    {answering && (
                      <span className="block w-full text-[11px] text-slate-500">
                        {t('concern.answerHint')}
                      </span>
                    )}
                  </span>
                )
              })()}
            </span>
            {/* Its author may drop it; Sales may settle a team needs-info flag.
                Anyone else sees the control greyed with the rule, never a
                vanished button or a late 403. Admin is no exception. */}
            {c.is_open && editable && withdrawing !== c.id && (
              <button data-testid={`concern-close-${c.id}`}
                className="text-xs underline decoration-dotted flex-shrink-0 disabled:no-underline disabled:opacity-50 disabled:cursor-not-allowed disabled:text-slate-500"
                disabled={!mayClose(c) || withdraw.isPending}
                title={mayClose(c) ? undefined : closerRule(c)}
                onClick={() => { setWithdrawing(c.id); setResolution('') }}>
                {scoped ? w.settle : (isAuthor(c) ? t('concern.withdraw') : t('concern.markSolved'))}
              </button>
            )}
          </li>
        ))}
      </ul>

      {failure && (
        <p role="alert" data-testid="concern-error"
          className="rounded border border-red-800/60 bg-red-950/40 px-2 py-1 text-xs text-red-200">
          {failure}
        </p>
      )}

      {adding && (
        <div className="flex gap-2 items-start flex-wrap">
          <select value={kind} onChange={(e) => setKind(e.target.value as ConcernKind)}
            aria-label={t('concern.kind')}
            className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100">
            <option value="needs_info">{t('concern.wantsInfo')}</option>
            <option value="reject_proposal">{t('concern.wouldReject')}</option>
          </select>
          {onlyDepartmentId === undefined && (scoped || options.length > 0) && (
            <select value={effectiveDept ?? ''} aria-label={t('concern.department')}
              onChange={(e) => setDeptId(e.target.value ? Number(e.target.value) : undefined)}
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100">
              {scoped
                ? effectiveDept === undefined
                  && <option value="">{t('concern.pickDepartment')}</option>
                : <option value="">{t('concern.team')}</option>}
              {options.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          )}
          <input value={note} onChange={(e) => setNote(e.target.value)}
            placeholder={t('concern.notePlaceholder')} aria-label={t('concern.note')}
            className="flex-1 min-w-[12rem] bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
          <button className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50"
            disabled={!note.trim() || raise.isPending || (scoped && effectiveDept === undefined)}
            onClick={() => raise.mutate()}>{w.raise}</button>
          <button className="text-xs text-slate-400 hover:text-slate-200 px-1"
            onClick={() => { setAdding(false); setNote(''); setFailure(null) }}>
            {t('common.cancel')}
          </button>
        </div>
      )}
    </div>
  )
}
