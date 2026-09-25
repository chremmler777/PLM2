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
import TransitionConfirmDialog from './TransitionConfirmDialog'
import DateInput from '../gantt/DateInput'
import { getActsAsDepartmentId } from '../../lib/actsAs'
import { t } from '../../i18n/cmLabels'
import { formatDate } from '../../lib/format'
import type {
  Attachment, ChangeConcern, ChangeMeeting, ChangeRequest, CostCarrier, RasicLetter,
} from '../../types/change'
import { carrierOf, isPersonContact } from '../../lib/scopingRules'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const DECISION_LABEL: Record<string, string> = {
  proceed: t('meeting.proceed'), reject: t('meeting.reject'),
  needs_info: t('meeting.needsInfo'),
}

export default function ScopingPanel(
  { change, canSendRejection = true, canAnswerConcerns = false, isPm = false, myDepartmentIds = [],
    canRecordMeeting = true }: {
    change: ChangeRequest & { attachments?: Attachment[] }
    /** Lead, Project Management or admin (stage-state `can_record_meeting`):
     *  records the meeting and decides it. Everyone else reads the record. */
    canRecordMeeting?: boolean
    /** The viewer's departments: a new flag is filed under their own. */
    myDepartmentIds?: number[]
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
  // The room's RASIC call per department. A department in the map is on the
  // hook with that letter; one outside it is not involved. Seeded from the
  // standard routing's letters, overruled by the people in the room.
  const [deptRasic, setDeptRasic] = useState<Record<number, RasicLetter>>({})
  const deptIds = Object.keys(deptRasic).map(Number)
  const [deptTouched, setDeptTouched] = useState(false)
  // Who pays, as the room confirms it: required next to RASIC (spec §16).
  // Never preselected: the room makes the call consciously; what capture
  // said (and the last meeting's call) is shown beside it as a hint.
  const [carrier, setCarrier] = useState<CostCarrier | ''>('')
  // The form is a record of one meeting: open while there is none, then one
  // click away. After a save it resets and folds up.
  const [formOpen, setFormOpen] = useState<boolean | null>(null)
  const [carried, setCarried] = useState(false)
  // Proceeding (and closing a rejected change) is asked once more.
  const [confirmProceed, setConfirmProceed] = useState<ChangeMeeting | null>(null)
  const [confirmSent, setConfirmSent] = useState(false)

  // Recommended assessors for this change type (stage-1 Responsible depts): the
  // technical disciplines who each assess their part. Pre-marked in the picker;
  // the lead can narrow the fan-out to those relevant for this change.
  const { data: recommended = [] } = useQuery({
    queryKey: ['recommended-departments', changeId],
    queryFn: () => changesApi.recommendedDepartments(changeId),
    enabled: status === 'captured' || status === 'scoping',
  })
  const recommendedIds = recommended.map((d) => d.id)
  const recommendedRasic = (): Record<number, RasicLetter> =>
    Object.fromEntries(recommended.map((d) => [d.id, d.rasic_letter ?? 'R']))
  const recommendedLetter = (id: number): RasicLetter =>
    recommended.find((d) => d.id === id)?.rasic_letter ?? 'R'
  useEffect(() => {
    // Seed the selection from the recommendation once, until the user edits it.
    if (!deptTouched && recommendedIds.length > 0 && deptIds.length === 0) {
      setDeptRasic(recommendedRasic())
    }
  }, [recommended]) // eslint-disable-line react-hooks/exhaustive-deps
  // A later meeting starts from the last one's RASIC call and cost carrier:
  // the room edits the difference (spec §16).
  const lastLetters = meetings[meetings.length - 1]?.department_rasic
  useEffect(() => {
    if (deptTouched || !lastLetters || Object.keys(lastLetters).length === 0) return
    setDeptRasic(Object.fromEntries(Object.entries(lastLetters).map(([k, v]) => [Number(k), v])) as Record<number, RasicLetter>)
    setCarried(true)
  }, [lastLetters]) // eslint-disable-line react-hooks/exhaustive-deps

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
  const people = contacts.filter((c) => isPersonContact(c, departments.map((d) => d.name)))

  // Resolve the typed text to the best contact match so Enter/Tab confirms the
  // suggestion (exact > prefix > contains); falls back to the raw text for
  // external attendees not in the directory.
  const bestMatch = (q: string): string => {
    const s = q.trim().toLowerCase()
    if (!s) return ''
    const exact = people.find((c) => c.name.toLowerCase() === s)
    const prefix = people.find((c) => c.name.toLowerCase().startsWith(s))
    const contains = people.find((c) => c.name.toLowerCase().includes(s))
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
      department_rasic: deptRasic,
      ...(carrier ? { cost_carrier: carrier } : {}),
    }),
    onSuccess: () => {
      // A fresh form for the next record, folded away; the letters of this
      // meeting are what the next one starts from (seeded on reopen).
      setParticipants(''); setAddName(''); setDate(''); setChannel('meeting'); setCarrier('')
      setDeptTouched(false); setCarried(false); setFormOpen(false)
      toast.success(t('meeting.saved'))
      invalidate()
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
  const setMeetingCarrier = useMutation({
    mutationFn: (vars: { meetingId: number; carrier: CostCarrier }) =>
      changesApi.updateMeeting(changeId, vars.meetingId, { cost_carrier: vars.carrier }),
    onSuccess: invalidate,
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not set the cost carrier'),
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
  // Recording and deciding are the lead's, PM's or an admin's (the backend
  // answers anyone else 403): others see the record, not the controls.
  const recordOpen = meetingOpen && canRecordMeeting
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
    return m ? `${t('concern.fromMeeting')} ${formatDate(m.meeting_date)}` : undefined
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
  // The carrier a meeting confirmed: its own record, or (older backend that
  // keeps no carrier on the meeting) the change's flag.
  const carrierOfMeeting = (m: ChangeMeeting): CostCarrier | '' =>
    m.cost_carrier !== undefined ? (m.cost_carrier ?? '') : carrierOf(change.customer_relevant)
  const carrierName = (c: CostCarrier | '') =>
    c ? t(`meeting.costCarrier.${c}`) : '-'
  const openForm = () => {
    // A reopened form starts from the last meeting's call: its letters and
    // its cost carrier, so the room edits the difference, not the whole list.
    const last = latestMeeting
    const letters = last?.department_rasic
      ? Object.fromEntries(Object.entries(last.department_rasic).map(([k, v]) => [Number(k), v]))
      : null
    if (letters && Object.keys(letters).length > 0) {
      setDeptRasic(letters as Record<number, RasicLetter>); setDeptTouched(true); setCarried(true)
    } else if (!deptTouched) {
      setDeptRasic(recommendedRasic())
    }
    setFormOpen(true)
  }
  // Open by default, except while the last record still waits for its
  // decision: then the next record is one click away, not in the way.
  const formShown = formOpen ?? !(latestMeeting && !latestMeeting.decision)
  const saveMissing = [
    ...(carrier ? [] : [t('meeting.costCarrier')]),
  ]
  const toggleDept = (id: number) => {
    setDeptTouched(true)
    setDeptRasic((prev) => {
      if (id in prev) { const next = { ...prev }; delete next[id]; return next }
      return { ...prev, [id]: recommendedLetter(id) }
    })
  }
  const setLetter = (id: number, letter: RasicLetter) => {
    setDeptTouched(true)
    setDeptRasic((prev) => ({ ...prev, [id]: letter }))
  }
  const letterOf = (m: ChangeMeeting, id: number): string | null =>
    m.department_rasic?.[String(id)] ?? null

  // "25.09.2026 · Anna, Ben", or what is known when the record is thin.
  const meetingHeadline = (m: ChangeMeeting): string => {
    const names = m.participants.map((p) => p.name).filter(Boolean).join(', ')
    const date = m.meeting_date ? formatDate(m.meeting_date) : ''
    const who = names || t('meeting.noAttendees')
    return date ? `${date} · ${who}` : (names || t('meeting.undated'))
  }
  const meetingRow = (m: ChangeMeeting) => (
    <li key={m.id} className="p-3 space-y-1">
      <div className="flex justify-between items-center">
        <span className="text-slate-200 flex items-center gap-2">
          <span className="text-xs px-1.5 py-0.5 rounded bg-slate-700 text-slate-300">
            {t(`channel.${m.channel ?? 'meeting'}`)}
          </span>
          {meetingHeadline(m)}
        </span>
        {m.decision ? (
          <span className="text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-200">
            {DECISION_LABEL[m.decision] ?? m.decision}
          </span>
        ) : recordOpen ? (
          <span className="flex gap-2">
            {carrierOfMeeting(m) === '' && (
              <select aria-label={t('meeting.costCarrier')} data-testid={`meeting-carrier-${m.id}`}
                value="" onChange={(e) => e.target.value
                  && setMeetingCarrier.mutate({ meetingId: m.id, carrier: e.target.value as CostCarrier })}
                className="bg-slate-800 border border-amber-600 rounded px-2 py-0.5 text-xs text-slate-100">
                <option value="">{t('meeting.costCarrierPick')}</option>
                <option value="customer">{t('meeting.costCarrier.customer')}</option>
                <option value="internal">{t('meeting.costCarrier.internal')}</option>
              </select>
            )}
            <button className="bg-emerald-700 hover:bg-emerald-600 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50 disabled:cursor-not-allowed"
              data-testid={`meeting-proceed-${m.id}`}
              disabled={decide.isPending || carrierOfMeeting(m) === ''}
              title={carrierOfMeeting(m) === '' ? t('meeting.costCarrierMissing') : undefined}
              onClick={() => setConfirmProceed(m)}>
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
        ) : meetingOpen && (
          <span className="text-xs text-slate-500" data-testid={`meeting-undecided-${m.id}`}>
            {t('meeting.undecided')}
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
        <p className="text-xs text-slate-500" data-testid={`meeting-depts-${m.id}`}>
          {t('meeting.departments')}: {m.selected_department_ids.map((id) => {
            const name = departments.find((d) => d.id === id)?.name ?? `#${id}`
            const letter = letterOf(m, id)
            return letter ? `${name} (${letter})` : name
          }).join(', ')}
        </p>
      )}
      {carrierOfMeeting(m) && (
        <p className="text-xs text-slate-500" data-testid={`meeting-carrier-line-${m.id}`}>
          {t('meeting.costCarrier')}: {carrierName(carrierOfMeeting(m))}
        </p>
      )}
    </li>
  )

  // What proceeding sets in motion, read before it happens.
  const proceedConfirm = (() => {
    const m = confirmProceed
    if (!m) return null
    const rasic = m.department_rasic ?? {}
    const lines = m.selected_department_ids.map((id) => {
      const name = departments.find((d) => d.id === id)?.name ?? `#${id}`
      const letter = rasic[String(id)]
      return letter ? `${name}: ${letter}` : name
    })
    const assessors = Object.values(rasic).filter((l) => l === 'R' || l === 'A').length
    const c = carrierOfMeeting(m)
    const flipped = c !== '' && carrierOf(change.customer_relevant) !== '' && c !== carrierOf(change.customer_relevant)
    return {
      to: 'in_assessment',
      title: t('meeting.proceedTitle'),
      consequence: t('meeting.proceedConsequence'),
      open: [
        ...(assessors === 0 && m.department_rasic ? [t('meeting.proceedNoAssessor')] : []),
        ...(flipped ? [t('meeting.costCarrierFlip')
          .replace('{from}', carrierName(carrierOf(change.customer_relevant))).replace('{to}', carrierName(c))] : []),
      ],
      allClear: undefined,
      info: [t('meeting.proceedCarrier').replace('{x}', carrierName(c)), ...lines],
      confirmLabel: t('meeting.proceedConfirm'),
    }
  })()

  return (
    <div className="space-y-4 text-sm">
      <TransitionConfirmDialog confirm={proceedConfirm} busy={decide.isPending}
        onClose={() => setConfirmProceed(null)}
        onConfirm={() => {
          const m = confirmProceed!
          setConfirmProceed(null)
          decide.mutate({ meetingId: m.id, decision: 'proceed' })
        }} />
      <TransitionConfirmDialog busy={markSent.isPending}
        confirm={confirmSent ? {
          to: 'closed', title: t('reject.closeTitle'),
          consequence: t('reject.closeConsequence'), open: [],
          info: rejectionLetters.map((l) => l.filename),
          confirmLabel: t('reject.closeConfirm'), final: true,
        } : null}
        onClose={() => setConfirmSent(false)}
        onConfirm={() => { setConfirmSent(false); markSent.mutate() }} />
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

        {(outstanding?.decision === 'reject' || change.status === 'rejected'
          || (change.status === 'closed' && !!change.rejected_at)) && change.customer_relevant && (
          <div className="rounded-lg border border-red-800/60 bg-red-950/30 p-3 space-y-2">
            <p className="font-medium text-slate-100" data-testid="rejection-title">{t('reject.sendTitle')}</p>
            <p className="text-xs text-slate-400">{t('meeting.shareHint')}</p>
            {/* Rejection closure: the letter, then the confirmed send that closes it. */}
            <div className="space-y-2" data-testid="rejection-closure">
              <p className="text-[11px] uppercase tracking-wide text-slate-500">{t('reject.step1')}</p>
              {rejectionLetters.length > 0 && (
                <ul className="text-sm divide-y divide-slate-700/60">
                  {rejectionLetters.map((l) => (
                    <AttachmentRow key={l.id} changeId={changeId} attachment={l} />
                  ))}
                </ul>
              )}
              {!change.rejection_sent_at && (
                <AttachmentDropzone changeId={changeId} kind="rejection_letter"
                  label={t('attach.rejectionSlot')} onUploaded={invalidate} />
              )}
              {!change.rejection_sent_at && (
                <p className="text-[11px] uppercase tracking-wide text-slate-500">{t('reject.step2')}</p>
              )}
              {change.rejection_sent_at ? (
                <p className="text-xs text-emerald-300">
                  ✓ {t('reject.sent')} · {formatDate(change.rejection_sent_at)}
                </p>
              ) : (
                <button type="button" data-testid="rejection-sent"
                  disabled={rejectionLetters.length === 0 || !canSendRejection || markSent.isPending}
                  title={!canSendRejection ? t('reject.salesOnly')
                    : rejectionLetters.length === 0 ? t('reject.needLetter') : undefined}
                  onClick={() => setConfirmSent(true)}
                  className="bg-sky-600 hover:bg-sky-500 text-white px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed">
                  {t('reject.markSent')}
                </button>
              )}
              {!change.rejection_sent_at && (!canSendRejection || rejectionLetters.length === 0) && (
                <p className="text-[11px] text-slate-400" data-testid="rejection-sent-why">
                  {!canSendRejection ? t('reject.salesOnly') : t('reject.needLetter')}
                </p>
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
          !outstanding && <p className="text-xs text-slate-500" data-testid="scoping-now-empty">{t('scoping.noOpenQuestions')}</p>
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
          isPm={isPm} hideConcernIds={needsInfo.map((c) => c.id)}
          myDepartmentIds={myDepartmentIds}
          changeDepartmentIds={[...new Set([...recommendedIds, ...(latestMeeting?.selected_department_ids ?? [])])]} />
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
                      {formatDate(m.meeting_date)}
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

      {meetingOpen && !canRecordMeeting && (
        <p className="text-xs text-slate-500" data-testid="meeting-record-rights">{t('meeting.recordRights')}</p>
      )}
      {recordOpen && !formShown && (
        <div className="flex items-center gap-3">
          <button type="button" data-testid="meeting-form-open" onClick={openForm}
            className="text-sm text-sky-300 hover:text-sky-200">
            {meetings.length > 0 ? t('meeting.recordAnother') : t('meeting.recordFirst')}
          </button>
          {latestMeeting && !latestMeeting.decision && (
            <span className="text-xs text-slate-500">{t('meeting.awaitingDecision')}</span>
          )}
        </div>
      )}
      {recordOpen && formShown && (
        <div className="border border-slate-700 rounded-lg p-4 space-y-3" data-testid="meeting-form">
          <div className="flex items-center justify-between">
            <h3 className="text-xs uppercase tracking-wide text-slate-500">{t('scoping.newMeeting')}</h3>
            {meetings.length > 0 && (
              <button type="button" onClick={() => setFormOpen(false)}
                className="text-xs text-slate-500 hover:text-slate-300">{t('meeting.collapse')}</button>
            )}
          </div>
          {carried && (
            <p className="text-[11px] text-slate-400" data-testid="meeting-carried">{t('meeting.carriedLetters')}</p>
          )}
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
              <label className="block text-xs text-slate-500 mb-1">{t('meeting.dateLabel')}</label>
              <DateInput value={date} onChange={setDate} aria-label={t('meeting.dateLabel')}
                className="w-36 bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
            </div>
            <div className="flex-1 min-w-[14rem]">
              <label className="block text-xs text-slate-500 mb-1">
                {t('meeting.participants')}
                <span className="ml-2 opacity-70">{t('meeting.attendanceHint')}</span>
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
                    if (people.some((c) => c.name === v)) appendParticipant(v)
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
                {people.map((c) => (
                  <option key={c.email ?? c.name} value={c.name}>
                    {c.email ?? ''}
                  </option>
                ))}
              </datalist>
            </div>
          </div>
          <div>
            <div className="flex items-baseline justify-between gap-4 mb-1">
              <label className="text-xs text-slate-500">
                {t('meeting.departments')}
                {recommendedIds.length > 0 && (
                  <span className="ml-2 opacity-70">{t('meeting.recommendedHint')}</span>
                )}
              </label>
              <span className="text-[11px] text-slate-500 tabular-nums" data-testid="rasic-summary">
                {t('meeting.rasicSummary')
                  .replace('{a}', String(Object.values(deptRasic).filter((l) => l === 'R' || l === 'A').length))
                  .replace('{n}', String(deptIds.length))}
              </span>
            </div>
            <p className="text-[11px] text-slate-500 mb-2 max-w-[65ch]">{t('meeting.rasicHint')}</p>
            {/* One row per department: name left, its letter right. A row
                without a letter is not involved and reads muted. Retired
                departments stay resolvable by name on old records but are
                never offered for new work. */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 border-t border-slate-700/70">
              {departments.filter((d) => d.is_active).map((d) => {
                const isRec = recommendedIds.includes(d.id)
                const letter = deptRasic[d.id]
                return (
                  <div key={d.id} data-testid={`rasic-row-${d.id}`}
                    className={`flex items-center justify-between gap-3 py-1.5 border-b border-slate-700/70 ${
                      letter ? '' : 'opacity-60'}`}>
                    <button type="button" onClick={() => toggleDept(d.id)}
                      aria-pressed={!!letter}
                      title={isRec ? t('meeting.recommended') : undefined}
                      className={`min-w-0 truncate text-left text-sm rounded px-1 -mx-1 transition-colors ${
                        letter ? 'text-slate-100' : 'text-slate-400 hover:text-slate-200'}`}>
                      {d.name}
                    </button>
                    <span className="inline-flex flex-shrink-0 rounded-md border border-slate-600 overflow-hidden divide-x divide-slate-600"
                      role="group" aria-label={`${d.name} RASIC`}>
                      {(['R', 'A', 'S', 'C'] as RasicLetter[]).map((l) => (
                        <button key={l} type="button" data-testid={`rasic-${d.id}-${l}`}
                          aria-pressed={letter === l} title={t(`rasic.${l}`)}
                          onClick={() => setLetter(d.id, l)}
                          className={`w-7 h-6 text-[11px] font-semibold transition-colors active:scale-[0.97] ${
                            letter === l
                              ? (l === 'R' || l === 'A'
                                ? 'bg-sky-600 text-white'
                                : 'bg-slate-600 text-slate-100')
                              : 'bg-slate-900 text-slate-500 hover:text-slate-200 hover:bg-slate-800'}`}>
                          {l}
                        </button>
                      ))}
                      <button type="button" data-testid={`rasic-${d.id}-none`}
                        aria-pressed={!letter} title={t('rasic.none')}
                        onClick={() => { if (letter) toggleDept(d.id) }}
                        className={`w-7 h-6 text-[11px] transition-colors ${
                          letter ? 'bg-slate-900 text-slate-500 hover:text-slate-200 hover:bg-slate-800'
                            : 'bg-slate-800 text-slate-300'}`}>
                        &ndash;
                      </button>
                    </span>
                  </div>
                )
              })}
            </div>
            <p className="mt-1.5 text-[11px] text-slate-500">
              <span className="text-slate-400">R/A</span> {t('rasic.assessNote')}
            </p>
          </div>
          {/* Who pays, confirmed by the room next to who works. */}
          <fieldset data-testid="meeting-carrier">
            <legend className="text-xs text-slate-500 mb-1">
              {t('meeting.costCarrier')}
              <span className="ml-2 opacity-70">{t('meeting.costCarrierHint')}</span>
            </legend>
            {carrierOf(change.customer_relevant) && (
              <p className="text-[11px] text-slate-400 mb-1" data-testid="meeting-carrier-captured">
                {t('meeting.costCarrierCaptured').replace('{x}', t(change.customer_relevant ? 'start.customerChange' : 'start.internalChange'))}
                {latestMeeting && carrierOfMeeting(latestMeeting)
                  ? ` · ${t('meeting.costCarrierLast').replace('{x}', carrierName(carrierOfMeeting(latestMeeting)))}` : ''}
              </p>
            )}
            <div className="flex flex-wrap gap-4 text-sm">
              {(['customer', 'internal'] as CostCarrier[]).map((c) => (
                <label key={c} className="flex items-center gap-1.5 cursor-pointer">
                  <input type="radio" name="meeting-carrier" data-testid={`meeting-carrier-${c}`}
                    checked={carrier === c} onChange={() => setCarrier(c)} />
                  <span className="text-slate-200">{t(`meeting.costCarrier.${c}`)}</span>
                </label>
              ))}
            </div>
            {carrier && carrierOf(change.customer_relevant) && carrier !== carrierOf(change.customer_relevant) && (
              <p data-testid="meeting-carrier-flip" className="mt-1 text-xs text-amber-300">
                {t('meeting.costCarrierFlip')
                  .replace('{from}', carrierName(carrierOf(change.customer_relevant))).replace('{to}', carrierName(carrier))}
              </p>
            )}
          </fieldset>
          <div className="flex flex-wrap items-center gap-3">
            <button data-testid="meeting-save"
              className="bg-sky-600 hover:bg-sky-500 text-white font-semibold px-4 py-1.5 rounded-lg text-sm disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={create.isPending || saveMissing.length > 0}
              title={saveMissing.length ? t('meeting.saveMissing').replace('{x}', saveMissing.join(', ')) : undefined}
              onClick={() => create.mutate()}>
              {t('meeting.save')}
            </button>
            {saveMissing.length > 0 && (
              <span className="text-xs text-slate-400" data-testid="meeting-save-missing">
                {t('meeting.saveMissing').replace('{x}', saveMissing.join(', '))}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
