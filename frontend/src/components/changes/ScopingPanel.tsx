import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { useAuth } from '../../contexts/AuthContext'
import { contactsApi } from '../../api/contacts'
import { useDepartments } from '../../hooks/queries/useWorkflows'
import ReasonDialog from './ReasonDialog'
import AttachmentDropzone from './AttachmentDropzone'
import { AttachmentRow } from './AttachmentRow'
import NeedsInfoCard from './NeedsInfoCard'
import ConcernStrip from './ConcernStrip'
import { getActsAsDepartmentId } from '../../lib/actsAs'
import { t } from '../../i18n/cmLabels'
import type { Attachment, ChangeConcern, ChangeMeeting, ChangeRequest } from '../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const DECISION_LABEL: Record<string, string> = {
  proceed: t('meeting.proceed'), reject: t('meeting.reject'),
  needs_info: t('meeting.needsInfo'),
}

export default function ScopingPanel(
  { change, canSendRejection = true, canAnswerConcerns = false, isPm = false }: {
    change: ChangeRequest & { attachments?: Attachment[] }
    /** Sales membership: Sales writes the answer of record. */
    canAnswerConcerns?: boolean
    /** Project Management may close a question the asking side left hanging. */
    isPm?: boolean
    /** Sales membership — only Sales confirms the rejection letter went out.
     *  Defaults true until memberships load so the control doesn't flash-grey. */
    canSendRejection?: boolean
  },
) {
  const changeId = change.id
  const status = change.status
  const qc = useQueryClient()
  const { userId } = useAuth()
  const { data: concerns = [] } = useQuery({
    queryKey: ['change', changeId, 'concerns'],
    queryFn: () => changesApi.listConcerns(changeId),
  })
  const { data: meetings = [] } = useQuery({
    queryKey: ['change-meetings', changeId],
    queryFn: () => changesApi.listMeetings(changeId),
  })
  const { data: departments = [] } = useDepartments()

  const [date, setDate] = useState('')
  const [channel, setChannel] = useState<'meeting' | 'chat' | 'email'>('meeting')
  const [participants, setParticipants] = useState('')
  const [addName, setAddName] = useState('')
  const [deptIds, setDeptIds] = useState<number[]>([])
  const [deptTouched, setDeptTouched] = useState(false)

  // Recommended assessors for this change type (stage-1 Responsible depts): the
  // technical disciplines who each assess their part. Pre-marked in the picker;
  // the lead can narrow the fan-out to those relevant for this change.
  const { data: recommended = [] } = useQuery({
    queryKey: ['recommended-departments', changeId],
    queryFn: () => changesApi.recommendedDepartments(changeId),
    enabled: status === 'captured' || status === 'scoping',
  })
  const recommendedIds = recommended.map((d) => d.id)
  useEffect(() => {
    // Seed the selection from the recommendation once, until the user edits it.
    if (!deptTouched && recommendedIds.length > 0 && deptIds.length === 0) {
      setDeptIds(recommendedIds)
    }
  }, [recommended]) // eslint-disable-line react-hooks/exhaustive-deps

  // Attendee autofill: the signed-in user's Entra "relevant people" via the hub,
  // or local PLM2 users in dev. Free-text still allowed for external attendees.
  const { data: contacts = [] } = useQuery({
    queryKey: ['contacts'], queryFn: () => contactsApi.list(),
    enabled: status === 'captured' || status === 'scoping',
    staleTime: 60 * 60 * 1000,
  })
  const appendParticipant = (name: string) => {
    const n = name.trim()
    if (!n) return
    const cur = participants.split(',').map((s) => s.trim()).filter(Boolean)
    if (!cur.includes(n)) setParticipants([...cur, n].join(', '))
    setAddName('')
  }
  const removeParticipant = (name: string) => {
    const cur = participants.split(',').map((s) => s.trim()).filter(Boolean)
    setParticipants(cur.filter((n) => n !== name).join(', '))
  }
  const participantList = participants.split(',').map((s) => s.trim()).filter(Boolean)

  // Resolve the typed text to the best contact match so Enter/Tab confirms the
  // suggestion (exact > prefix > contains); falls back to the raw text for
  // external attendees not in the directory.
  const bestMatch = (q: string): string => {
    const s = q.trim().toLowerCase()
    if (!s) return ''
    const exact = contacts.find((c) => c.name.toLowerCase() === s)
    const prefix = contacts.find((c) => c.name.toLowerCase().startsWith(s))
    const contains = contacts.find((c) => c.name.toLowerCase().includes(s))
    return (exact ?? prefix ?? contains)?.name ?? q.trim()
  }
  const confirmTyped = () => appendParticipant(bestMatch(addName))

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['change-meetings', changeId] })
    qc.invalidateQueries({ queryKey: ['change', changeId, 'concerns'] })
    qc.invalidateQueries({ queryKey: ['change', changeId] })
  }
  const create = useMutation({
    mutationFn: () => changesApi.createMeeting(changeId, {
      meeting_date: date ? `${date}T12:00:00Z` : undefined,
      channel,
      participants: participants.split(',').map((n) => n.trim())
        .filter(Boolean).map((name) => ({ name })),
      selected_department_ids: deptIds,
    }),
    onSuccess: () => {
      setParticipants(''); setAddName('')
      setDeptTouched(false); setDeptIds(recommendedIds); invalidate()
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not record the meeting'),
  })
  // A refused decision names the open concerns that blocked it — that detail is
  // the whole answer, so it is shown in place and not only as a toast.
  const [decideError, setDecideError] = useState<string | null>(null)
  // Closing a rejected customer change is an act with a record: the letter is
  // attached, then Sales confirms it went out and the backend closes the ECR.
  const markSent = useMutation({
    mutationFn: () => changesApi.markRejectionSent(changeId),
    onSuccess: () => {
      toast.success(t('reject.sent'))
      invalidate()
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not close the change'),
  })
  const decide = useMutation({
    mutationFn: (vars: {
      meetingId: number; decision: 'proceed' | 'reject' | 'needs_info'; reason?: string
    }) => changesApi.decideMeeting(changeId, vars.meetingId, vars.decision, vars.reason),
    onSuccess: () => { setDecideError(null); invalidate() },
    onError: (e: unknown) => {
      const detail = errDetail(e) ?? 'Decision failed'
      setDecideError(detail)
      toast.error(detail)
    },
  })
  // Reject and needs-info both owe the originator an answer, so both collect
  // one before the call goes out rather than letting the server 400.
  const [pending, setPending] = useState<
    { meetingId: number; decision: 'reject' | 'needs_info' } | null>(null)
  // Which older meeting record the user asked to see in full.
  const [showMeeting, setShowMeeting] = useState<number | null>(null)

  const open = status === 'captured' || status === 'scoping'
  // Meetings belong to scoping: the backend refuses to create one while the
  // change is still being captured, so the recording UI stays hidden there.
  const meetingOpen = status === 'scoping'
  // The most recent decision that leaves a ball in our court: a rejection the
  // customer has to be told about, or missing information somebody has to go
  // and get. Cleared once a later meeting reaches 'proceed'.
  // The change already carries its attachments; the loop reads them in place
  // rather than fetching again.
  const attachments = change.attachments ?? []
  const rejectionLetters = attachments.filter((a) => a.kind === 'rejection_letter')
  // Question documents from before the cards existed (and any filed outside one)
  // belong to no card. They are still evidence, so the questions section shows
  // them rather than leaving them findable only in the attachments list.
  const unassignedQuestionDocs = attachments.filter(
    (a) => (a.kind === 'info_request' || a.kind === 'info_response') && a.concern_id == null)
  // Team needs-info flags are the customer questions; they get their own cards,
  // in the order the questions were asked. A flag raised by a meeting's decision
  // belongs under that meeting's record; a hand-raised one stands on its own.
  // Every needs-info flag is a question, whoever raised it and however it is
  // attributed: auto-raised by a decision, hand-raised in the strip, or filed
  // against a department. One flow, one card — the strip keeps the objections.
  const needsInfo = [...concerns]
    .filter((c) => c.kind === 'needs_info')
    .sort((a, b) => a.raised_at.localeCompare(b.raised_at))
  const openQuestions = needsInfo.filter((c) => c.is_open)
  const solvedQuestions = needsInfo.filter((c) => !c.is_open)
  const settledQuestionsOf = (meetingId: number) =>
    solvedQuestions.filter((c) => c.raised_by_meeting_id === meetingId)
  // A question raised by a decision keeps its origin on the card, so nesting
  // survives even though open work is hoisted out of the history.
  const meetingOf = (id?: number | null) =>
    id == null ? undefined : meetings.find((m: ChangeMeeting) => m.id === id)
  const originOf = (c: ChangeConcern) => {
    const m = meetingOf(c.raised_by_meeting_id)
    return m ? `${t('concern.fromMeeting')} ${new Date(m.meeting_date).toLocaleDateString()}` : undefined
  }
  const latestMeeting: ChangeMeeting | null =
    meetings.length > 0 ? meetings[meetings.length - 1] : null
  const olderMeetings: ChangeMeeting[] = meetings.slice(0, Math.max(0, meetings.length - 1))
  // Both paths — meeting-raised and hand-raised — render the same card with the
  // same gates. Closing belongs to the asker (or PM); answering to Sales.
  // While an admin acts as a department, their personal asker right steps
  // aside with their real memberships — the card shows that department's view.
  const actingAs = getActsAsDepartmentId() != null
  const questionCard = (c: ChangeConcern) => (
    <NeedsInfoCard key={c.id} changeId={changeId} concern={c}
      attachments={attachments} editable={open}
      canAnswer={canAnswerConcerns}
      canSettle={(!actingAs && c.raised_by === userId) || isPm}
      origin={originOf(c)} onChanged={invalidate} />
  )
  const outstanding = [...meetings].reverse().find(
    (m: ChangeMeeting) => m.decision === 'reject' || m.decision === 'needs_info')
    ?? null
  const toggleDept = (id: number) => {
    setDeptTouched(true)
    setDeptIds((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id])
  }

  const meetingRow = (m: ChangeMeeting) => (
    <li key={m.id} className="p-3 space-y-1">
      <div className="flex justify-between items-center">
        <span className="text-slate-200 flex items-center gap-2">
          <span className="text-xs px-1.5 py-0.5 rounded bg-slate-700 text-slate-300">
            {t(`channel.${m.channel ?? 'meeting'}`)}
          </span>
          {new Date(m.meeting_date).toLocaleDateString()} — {' '}
          {m.participants.map((p) => p.name).join(', ') || '—'}
        </span>
        {m.decision ? (
          <span className="text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-200">
            {DECISION_LABEL[m.decision] ?? m.decision}
          </span>
        ) : meetingOpen && (
          <span className="flex gap-2">
            <button className="bg-emerald-700 hover:bg-emerald-600 text-white px-2.5 py-1 rounded text-xs"
              disabled={decide.isPending}
              onClick={() => decide.mutate({ meetingId: m.id, decision: 'proceed' })}>
              {t('meeting.proceed')}
            </button>
            <button className="bg-amber-700 hover:bg-amber-600 text-white px-2.5 py-1 rounded text-xs"
              disabled={decide.isPending}
              onClick={() => setPending({ meetingId: m.id, decision: 'needs_info' })}>
              {t('meeting.needsInfo')}
            </button>
            <button className="bg-red-800 hover:bg-red-700 text-white px-2.5 py-1 rounded text-xs"
              disabled={decide.isPending}
              onClick={() => setPending({ meetingId: m.id, decision: 'reject' })}>
              {t('meeting.reject')}
            </button>
          </span>
        )}
      </div>
      {m.decision_reason && (
        <p className={`whitespace-pre-wrap ${
          m.decision === 'reject' ? 'text-red-300' : 'text-amber-300'}`}>
          {m.decision === 'needs_info' ? t('meeting.missingInfo') : t('meeting.rejectedBecause')}
          {' '}{m.decision_reason}
        </p>
      )}
      {/* Questions this decision raised that are already settled stay with their
          meeting; the open ones are hoisted into "Now" above. */}
      {settledQuestionsOf(m.id).length > 0 && (
        <div data-testid={`meeting-questions-${m.id}`}
          className="mt-2 ml-4 border-l-2 border-slate-700 pl-3 space-y-2">
          {settledQuestionsOf(m.id).map(questionCard)}
        </div>
      )}
      {m.selected_department_ids.length > 0 && (
        <p className="text-xs text-slate-500">
          {t('meeting.departments')}: {m.selected_department_ids.map((id) =>
            departments.find((d) => d.id === id)?.name ?? `#${id}`).join(', ')}
        </p>
      )}
    </li>
  )

  return (
    <div className="space-y-4 text-sm">
      <ReasonDialog
        open={pending !== null}
        title={pending?.decision === 'reject' ? t('meeting.rejectTitle') : t('meeting.needsInfoTitle')}
        warning={pending?.decision === 'reject' ? t('meeting.rejectWarning') : t('meeting.needsInfoWarning')}
        label={pending?.decision === 'reject' ? t('meeting.rejectLabel') : t('meeting.needsInfoLabel')}
        submitLabel={pending?.decision === 'reject' ? t('meeting.reject') : t('meeting.needsInfo')}
        danger={pending?.decision === 'reject'}
        onSubmit={(reason) => {
          if (pending) decide.mutate({ ...pending, reason })
          setPending(null)
        }}
        onClose={() => setPending(null)}
      />

      {/* NOW — what the change is waiting on, always open, always first. */}
      <section className="space-y-3" data-testid="scoping-now">
        <h3 className="text-xs uppercase tracking-wide text-slate-500">{t('scoping.now')}</h3>

        {outstanding?.decision === 'reject' && change.customer_relevant && (
          <div className="rounded-lg border border-red-800/60 bg-red-950/30 p-3 space-y-2">
            <p className="font-medium text-slate-100">{t('meeting.shareRejection')}</p>
            <p className="text-xs text-slate-400">{t('meeting.shareHint')}</p>
            {/* Rejection closure: the letter, then the confirmed send that closes it. */}
            <div className="space-y-2" data-testid="rejection-closure">
              {rejectionLetters.length > 0 && (
                <ul className="text-sm divide-y divide-slate-700/60">
                  {rejectionLetters.map((l) => (
                    <AttachmentRow key={l.id} changeId={changeId} attachment={l} />
                  ))}
                </ul>
              )}
              <AttachmentDropzone changeId={changeId} kind="rejection_letter"
                label={t('attach.rejectionSlot')} onUploaded={invalidate} />
              {change.rejection_sent_at ? (
                <p className="text-xs text-emerald-300">
                  ✓ {t('reject.sent')} · {new Date(change.rejection_sent_at).toLocaleDateString()}
                </p>
              ) : (
                <button type="button" data-testid="rejection-sent"
                  disabled={rejectionLetters.length === 0 || !canSendRejection || markSent.isPending}
                  title={!canSendRejection ? t('reject.salesOnly')
                    : rejectionLetters.length === 0 ? t('reject.needLetter') : undefined}
                  onClick={() => markSent.mutate()}
                  className="bg-red-800 hover:bg-red-700 text-white px-3 py-1.5 rounded text-xs font-semibold disabled:opacity-50 disabled:cursor-not-allowed">
                  {t('reject.markSent')}
                </button>
              )}
            </div>
          </div>
        )}

        {openQuestions.length > 0 ? (
          <div className="space-y-3" data-testid="needs-info-cards">
            <p className="text-xs text-slate-400">{t('concern.openRequests')}</p>
            {openQuestions.map(questionCard)}
          </div>
        ) : (
          !outstanding && <p className="text-xs text-slate-500">{t('concern.none')}</p>
        )}

        {unassignedQuestionDocs.length > 0 && (
          <div data-testid="unassigned-question-docs"
            className="rounded-lg border border-slate-700 bg-slate-800/40 p-3 space-y-1">
            <p className="text-[11px] uppercase tracking-wide text-slate-500">
              {t('concern.unassignedDocs')}
            </p>
            <ul className="text-sm">
              {unassignedQuestionDocs.map((a) => (
                <AttachmentRow key={a.id} changeId={changeId} attachment={a} />
              ))}
            </ul>
            <p className="text-[11px] text-slate-500">{t('concern.unassignedHint')}</p>
          </div>
        )}

        {/* Everything else the team flagged, in one strip. */}
        <ConcernStrip changeId={changeId} editable={open} departments={departments}
          isPm={isPm} hideConcernIds={needsInfo.map((c) => c.id)} />
      </section>

      {decideError && (
        <p role="alert" data-testid="decide-error"
          className="rounded border border-red-800/60 bg-red-950/40 px-2 py-1 text-xs text-red-200">
          {decideError}
        </p>
      )}

      {/* HISTORY — quiet by default: the latest record open, everything older
          one line away. */}
      <section className="space-y-2" data-testid="scoping-history">
        <h3 className="text-xs uppercase tracking-wide text-slate-500">{t('scoping.history')}</h3>

        {solvedQuestions.filter((c) => c.raised_by_meeting_id == null).length > 0 && (
          <div className="space-y-1" data-testid="settled-questions">
            <p className="text-xs text-slate-500">{t('concern.solvedQuestions')}</p>
            {solvedQuestions
              .filter((c) => c.raised_by_meeting_id == null)
              .map(questionCard)}
          </div>
        )}

        {olderMeetings.length > 0 && (
          <ul className="divide-y divide-slate-700 border border-slate-700 rounded-lg"
            data-testid="older-meetings">
            {olderMeetings.map((m: ChangeMeeting) => (
              showMeeting === m.id ? meetingRow(m) : (
                <li key={m.id}>
                  <button type="button" data-testid={`meeting-summary-${m.id}`}
                    onClick={() => setShowMeeting(m.id)}
                    className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-slate-800">
                    <span className="px-1.5 py-0 rounded bg-slate-700 text-slate-300">
                      {t(`channel.${m.channel ?? 'meeting'}`)}
                    </span>
                    <span className="text-slate-400">
                      {new Date(m.meeting_date).toLocaleDateString()}
                    </span>
                    {m.decision && (
                      <span className="px-1.5 py-0 rounded-full bg-slate-700 text-slate-300">
                        {DECISION_LABEL[m.decision] ?? m.decision}
                      </span>
                    )}
                    <span className="ml-auto text-slate-600">{t('scoping.showDetails')}</span>
                  </button>
                </li>
              )
            ))}
          </ul>
        )}

        <ul className="divide-y divide-slate-700 border border-slate-700 rounded-lg">
          {latestMeeting ? meetingRow(latestMeeting) : (
            <li className="p-3 text-slate-400">{t('meeting.none')}</li>
          )}
        </ul>
      </section>

      {meetingOpen && (
        <div className="border border-slate-700 rounded-lg p-4 space-y-3">
          <h3 className="text-xs uppercase tracking-wide text-slate-500">{t('scoping.newMeeting')}</h3>
          {/* No minutes field: the discussion itself lives in the mail thread,
              which belongs on the change as a document. */}
          <p className="text-xs text-slate-500">{t('scoping.discussionByEmail')}</p>
          <div className="flex flex-wrap gap-3">
            <div>
              <label className="block text-xs text-slate-500 mb-1">{t('channel.label')}</label>
              <select value={channel} onChange={(e) => setChannel(e.target.value as typeof channel)}
                className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100">
                <option value="meeting">{t('channel.meeting')}</option>
                <option value="chat">{t('channel.chat')}</option>
                <option value="email">{t('channel.email')}</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">{t('meeting.date')}</label>
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
                className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
            </div>
            <div className="flex-1 min-w-[14rem]">
              <label className="block text-xs text-slate-500 mb-1">
                {t('meeting.participants')}
              </label>
              {/* Picked names live as removable chips — grouped, contained, not
                  free-editable text that can be accidentally mangled. */}
              <div className="flex flex-wrap items-center gap-1.5 rounded-lg bg-slate-800 border border-slate-600 px-2 py-1.5 min-h-[2.25rem]">
                {participantList.map((name) => (
                  <span key={name}
                    className="inline-flex items-center gap-1 rounded-md bg-slate-700 text-slate-100 text-xs px-2 py-0.5">
                    {name}
                    <button type="button" aria-label={`Remove ${name}`}
                      className="text-slate-400 hover:text-red-300"
                      onClick={() => removeParticipant(name)}>×</button>
                  </span>
                ))}
                <input
                  type="text" list="sc-contacts" value={addName}
                  placeholder={participantList.length ? '' : t('meeting.addAttendee')}
                  onChange={(e) => {
                    const v = e.target.value
                    setAddName(v)
                    // Picking a suggestion sets the full name in one change event.
                    if (contacts.some((c) => c.name === v)) appendParticipant(v)
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') { e.preventDefault(); confirmTyped() }
                    // Tab confirms the suggestion when text is typed; an empty
                    // field lets Tab move focus normally.
                    else if (e.key === 'Tab' && addName.trim()) { e.preventDefault(); confirmTyped() }
                    else if (e.key === 'Backspace' && !addName && participantList.length) {
                      removeParticipant(participantList[participantList.length - 1])
                    }
                  }}
                  className="flex-1 min-w-[8rem] bg-transparent text-sm text-slate-100 outline-none" />
              </div>
              <datalist id="sc-contacts">
                {contacts.map((c) => (
                  <option key={c.email ?? c.name} value={c.name}>
                    {c.email ?? ''}
                  </option>
                ))}
              </datalist>
            </div>
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">
              {t('meeting.departments')}
              {recommendedIds.length > 0 && (
                <span className="ml-2 opacity-70">{t('meeting.recommendedHint')}</span>
              )}
            </label>
            <div className="flex flex-wrap gap-2">
              {/* Retired departments stay resolvable by name on old records but
                  are never offered for new work. */}
              {departments.filter((d) => d.is_active).map((d) => {
                const isRec = recommendedIds.includes(d.id)
                return (
                  <button key={d.id} type="button" onClick={() => toggleDept(d.id)}
                    title={isRec ? t('meeting.recommended') : undefined}
                    className={`px-2.5 py-1 rounded-full text-xs border ${deptIds.includes(d.id)
                      ? 'bg-sky-600 text-white border-sky-500'
                      : 'bg-slate-900 text-slate-300 border-slate-600'}`}>
                    {d.name}
                  </button>
                )
              })}
            </div>
          </div>
          <button
            className="bg-sky-600 hover:bg-sky-500 text-white font-semibold px-4 py-1.5 rounded-lg text-sm disabled:opacity-50"
            disabled={create.isPending}
            onClick={() => create.mutate()}>
            {t('meeting.save')}
          </button>
        </div>
      )}
    </div>
  )
}
