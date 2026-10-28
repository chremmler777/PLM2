import { useState, useEffect, useId } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Check, UserRound, X } from 'lucide-react'
import Button from '../common/Button'
import { btnSm } from '../common/buttonStyles'
import { apiErrorMessage, toastError } from '../../lib/apiError'
import { changesApi } from '../../api/changes'
import { useAuth } from '../../contexts/AuthContext'
import { contactsApi, type Contact } from '../../api/contacts'
import { useDepartments } from '../../hooks/queries/useWorkflows'
import ReasonDialog from './ReasonDialog'
import AttachmentDropzone from './AttachmentDropzone'
import { AttachmentRow } from './AttachmentRow'
import NeedsInfoCard from './NeedsInfoCard'
import ConcernStrip from './ConcernStrip'
import TransitionConfirmDialog from './TransitionConfirmDialog'
import ScopingFlags from './scoping/ScopingFlags'
import ProceedFixList from './scoping/ProceedFixList'
import { CustomerFlipCard, PpapDecisionCard } from './scoping/PpapFlipCards'
import { NeedByCheck, isUrgentV2, needByHold, okRef, type NeedByAnswer } from './CaptureV2'
import DateInput from '../gantt/DateInput'
import { getActsAsDepartmentId } from '../../lib/actsAs'
import { t } from '../../i18n/cmLabels'
import { formatDate } from '../../lib/format'
import {
  isCheckItem,
  type Attachment, type ChangeConcern, type ChangeMeeting, type ChangeRequest, type CostCarrier,
  type ImpactedItem, type MeetingParticipant, type NextStep, type RasicLetter,
} from '../../types/change'
import {
  askingSide, canAnswerQuestion, carrierOf, flipHolds, unroutedCheckOwners, splitUnroutedOwners, ownerUnroutableLine, isPersonContact, openFlagLines, ppapApplies,
} from '../../lib/scopingRules'
import { departmentLabel, isRoutable, pickableDepartments } from '../../lib/departments'
import { plantText } from '../../lib/plantName'

/** The room's letters, in the order the picker shows them. I (informed) is an
 *  FYI: no assessment, nothing blocks on it. */
const RASIC_PICK: RasicLetter[] = ['R', 'A', 'S', 'C', 'I']

/** An attendee as picked. A directory person is a colleague (and carries
 *  their user id and email as the contacts API sends them); a typed name
 *  that matched nobody is an external guest. `guest` is UI-only and never
 *  sent. */
type Attendee = MeetingParticipant & { guest?: boolean }
/** What the backend gets: the name plus whatever identifies the PLM2 user
 *  (user_id, checked against the email; else the email to resolve). A
 *  guest is a name. */
const toParticipant = ({ name, user_id, email }: Attendee): MeetingParticipant => ({
  name,
  ...(user_id != null ? { user_id } : {}),
  ...(email ? { email } : {}),
})
/** The picker text for each contact: the name, and for a name two people
 *  share, the name with their email (else department) so the right one is
 *  picked and its user id sent. */
function contactLabels(people: Contact[]): Map<Contact, string> {
  const count = new Map<string, number>()
  for (const c of people) {
    const k = c.name.trim().toLowerCase()
    count.set(k, (count.get(k) ?? 0) + 1)
  }
  const out = new Map<Contact, string>()
  for (const c of people) {
    const shared = (count.get(c.name.trim().toLowerCase()) ?? 0) > 1
    const tag = c.email || c.department
    out.set(c, shared && tag ? `${c.name} (${tag})` : c.name)
  }
  return out
}
const attendeeKey = (a: Attendee) => (a.user_id != null ? `u${a.user_id}` : `n${a.name.toLowerCase()}`)

const DECISION_LABEL: Record<string, string> = {
  proceed: t('meeting.proceed'), reject: t('meeting.reject'),
  needs_info: t('meeting.needsInfo'),
}

export default function ScopingPanel(
  { change, canSendRejection = true, canAnswerConcerns = false, isPm = false, myDepartmentIds = [],
    canRecordMeeting = true, onInformTeam, readOnly = false, canMoveCarrier = true }: {
    change: ChangeRequest & { attachments?: Attachment[]; next_step?: NextStep | null }
    /** A read-only viewer (no active department) or a closed record: the
     *  backend refuses every write, so no control is offered (R24). */
    readOnly?: boolean
    /** A change from KTX Weissenburg / Solingen: opens the tab where the
     *  information goes out to the team (its scoping ends there, never in
     *  an assessment). */
    onInformTeam?: () => void
    /** May the viewer move the cost carrier away from what was captured
     *  (lib/transitionRights mayMoveCarrier, the backend's PATCH and room
     *  rule): an engineering lead may not make an internal change a
     *  customer one, nor take the customer off one. */
    canMoveCarrier?: boolean
    /** Lead, Project Management or admin (stage-state `can_record_meeting`):
     *  records the meeting and decides it. Everyone else reads the record. */
    canRecordMeeting?: boolean
    /** The viewer's departments: a new flag is filed under their own. */
    myDepartmentIds?: number[]
    /** Sales membership: Sales may answer any question (so may PM and the
     *  asking department; the backend serves the verdict per question). */
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
  // Mother plant (spec §14): no assessment, costing or offer. The scoping
  // record says which departments are informed; the backend refuses
  // "proceed" (it would enter assessment) and there is no cost carrier.
  const motherPlant = change.origin === 'mother_plant'
  // HARD #7: a held flip goes back to internal only by Sales' answer
  const flipLocked = flipHolds(change)
  // P3 / [R4]: a carrier the viewer may not move to is not offered
  const capturedCarrier = carrierOf(change.customer_relevant)
  const carrierBarred = (c: CostCarrier) => (c === 'internal' && flipLocked)
    || (!canMoveCarrier && capturedCarrier !== '' && c !== capturedCarrier)
  const carrierNotYours = !canMoveCarrier && capturedCarrier !== '' && !flipLocked
  // R37 same words everywhere: with SCOPING_V2 the meeting's needs_info is
  // "Not yet" on the button, its dialog and the record
  const decisionLabel = (d: string) =>
    (d === 'needs_info' && change.scoping_v2 === true && !motherPlant
      ? t('meeting.notYet') : DECISION_LABEL[d]) ?? d
  // C33 (served switch SCOPING_V2): questions and check items, 'Not yet'.
  const v2 = change.scoping_v2 === true && !motherPlant
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
  const [participants, setParticipants] = useState<Attendee[]>([])
  const [addName, setAddName] = useState('')
  const channelId = useId()
  const attendeeId = useId()
  const attendeeHintId = useId()
  // The room's RASIC call per department. A department in the map is on the
  // hook with that letter; one outside it is not involved. Seeded from the
  // standard routing's letters, overruled by the people in the room.
  const [deptRasic, setDeptRasic] = useState<Record<number, RasicLetter>>({})
  const deptIds = Object.keys(deptRasic).map(Number)
  const [deptTouched, setDeptTouched] = useState(false)
  // Who pays, as the room confirms it: required next to RASIC (spec §16).
  // Not asked twice: the form starts from what is already known (the last
  // meeting's call, else what capture said), shown checked and changeable;
  // only an unset carrier waits for a pick.
  const [carrierPick, setCarrier] = useState<CostCarrier | ''>('')
  // Where only one carrier is open to the viewer (a Process lead on an internal
  // change may not make it a customer change), there is no call to make: that
  // one counts as picked, instead of a click on the only option.
  const openCarriers = (['customer', 'internal'] as CostCarrier[]).filter((c) => !carrierBarred(c))
  const knownCarrier: CostCarrier | '' =
    [...meetings].reverse().find((m: ChangeMeeting) => m.cost_carrier)?.cost_carrier
      ?? capturedCarrier
  const carrier: CostCarrier | '' = carrierPick
    || (knownCarrier && !carrierBarred(knownCarrier) ? knownCarrier : '')
    || (openCarriers.length === 1 ? openCarriers[0] : '')
  // The form is a record of one meeting: open while there is none, then one
  // click away. After a save it resets and folds up.
  const [formOpen, setFormOpen] = useState<boolean | null>(null)
  const [carried, setCarried] = useState(false)
  // Proceeding (and closing a rejected change) is asked once more.
  const [confirmProceed, setConfirmProceed] = useState<ChangeMeeting | null>(null)
  // §3 urgent: "Need-by realistic?" in the proceed dialog, nothing preselected
  const [needBy, setNeedBy] = useState<NeedByAnswer>({ check: '', proposed: '' })
  const [confirmSent, setConfirmSent] = useState(false)

  // Recommended assessors for this change type (stage-1 Responsible depts): the
  // technical disciplines who each assess their part. Pre-marked in the picker;
  // the lead can narrow the fan-out to those relevant for this change.
  const { data: recommended = [] } = useQuery({
    queryKey: ['recommended-departments', changeId],
    queryFn: () => changesApi.recommendedDepartments(changeId),
    enabled: status === 'captured' || status === 'scoping',
  })
  // Christoph 2026-10-28: the room starts from the standard (Tool Engineer,
  // APQP, Development, Manufacturing Engineer); "optional" ones (Packaging)
  // are offered as "sometimes", not pre-marked.
  const recommendedIds = recommended.filter((d) => !d.optional).map((d) => d.id)
  const sometimesIds = recommended.filter((d) => d.optional).map((d) => d.id)
  const recommendedRasic = (): Record<number, RasicLetter> =>
    Object.fromEntries(recommended.filter((d) => !d.optional).map((d) => [d.id, d.rasic_letter ?? 'R']))
  const recommendedLetter = (id: number): RasicLetter =>
    recommended.find((d) => d.id === id)?.rasic_letter ?? 'R'
  // §3 internal: the raiser's department is auto-R (served by the backend);
  // leaving it out, or below R/A, needs a reason, logged
  const raiserDept = recommended.find((d) => d.raiser)
  const raiserOut = !motherPlant && !!raiserDept && !['R', 'A'].includes(deptRasic[raiserDept.id] ?? '')
  const [waiveReason, setWaiveReason] = useState('')
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
  const people = contacts.filter((c) => isPersonContact(c, departments.map((d) => d.name)))
  const labels = contactLabels(people)
  const labelOf = (c: Contact) => labels.get(c) ?? c.name
  const fromContact = (c: Contact): Attendee =>
    ({ name: c.name, user_id: c.user_id ?? null, email: c.email ?? null, guest: false })
  const appendParticipant = (a: Attendee | null) => {
    if (!a || !a.name.trim()) return
    const next = { ...a, name: a.name.trim() }
    // Same user id, or the same name where one side is a bare name: two
    // colleagues who share a name are two attendees.
    if (!participants.some((p) => attendeeKey(p) === attendeeKey(next)
      || ((p.user_id == null || next.user_id == null)
        && p.name.toLowerCase() === next.name.toLowerCase()))) {
      setParticipants([...participants, next])
    }
    setAddName('')
  }
  const removeParticipant = (a: Attendee) =>
    setParticipants(participants.filter((p) => attendeeKey(p) !== attendeeKey(a)))
  const participantList = participants

  // Resolve the typed text to the best contact match so Enter/Tab confirms the
  // suggestion (exact > prefix > contains, on label, name or mail); falls
  // back to the raw text for external attendees not in the directory.
  const bestMatch = (q: string): Attendee | null => {
    const s = q.trim().toLowerCase()
    if (!s) return null
    const keys = (c: Contact) => [labelOf(c), c.name, (c.email ?? '').split('@')[0], c.email ?? '']
      .map((k) => k.toLowerCase()).filter(Boolean)
    const exact = people.find((c) => keys(c).some((k) => k === s))
    const prefix = people.find((c) => keys(c).some((k) => k.startsWith(s)))
    const contains = people.find((c) => c.name.toLowerCase().includes(s))
    const hit = exact ?? prefix ?? contains
    return hit ? fromContact(hit) : { name: q.trim(), user_id: null, guest: true }
  }
  const confirmTyped = () => appendParticipant(bestMatch(addName))

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['change-meetings', changeId] })
    qc.invalidateQueries({ queryKey: ['change', changeId, 'concerns'] })
    qc.invalidateQueries({ queryKey: ['change', changeId] })
    qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
  }
  const create = useMutation({
    mutationFn: () => changesApi.createMeeting(changeId, {
      meeting_date: date ? `${date}T12:00:00Z` : undefined,
      channel,
      participants: participants.map(toParticipant),
      selected_department_ids: deptIds,
      // Mother plant: every department on the record is informed, nobody
      // assesses.
      department_rasic: motherPlant
        ? Object.fromEntries(deptIds.map((id) => [id, 'I' as RasicLetter])) : deptRasic,
      ...(carrier && !motherPlant ? { cost_carrier: carrier } : {}),
      ...(raiserOut && waiveReason.trim() ? { raiser_waive_reason: waiveReason.trim() } : {}),
    }),
    onSuccess: () => {
      // A fresh form for the next record, folded away; the letters of this
      // meeting are what the next one starts from (seeded on reopen).
      setParticipants([]); setAddName(''); setDate(''); setChannel('meeting'); setCarrier('')
      setWaiveReason('')
      setDeptTouched(false); setCarried(false); setFormOpen(false)
      toast.success(t('meeting.saved'))
      invalidate()
    },
    onError: (e: unknown) => toastError(e, 'Could not record the meeting'),
  })
  // A refused decision names the open concerns that blocked it — that detail is
  // the whole answer, so it is shown in place and not only as a toast.
  const [decideError, setDecideError] = useState<string | null>(null)
  const [refusal, setRefusal] = useState<string | null>(null)
  // Closing a rejected customer change is an act with a record: the letter is
  // attached, then Sales confirms it went out and the backend closes the ECR.
  const markSent = useMutation({
    mutationFn: () => changesApi.markRejectionSent(changeId),
    onSuccess: () => {
      toast.success(t('reject.sent'))
      invalidate()
    },
    onError: (e: unknown) => toastError(e, 'Could not close the change'),
  })
  const setMeetingCarrier = useMutation({
    mutationFn: (vars: { meetingId: number; carrier: CostCarrier }) =>
      changesApi.updateMeeting(changeId, vars.meetingId, { cost_carrier: vars.carrier }),
    onSuccess: invalidate,
    onError: (e: unknown) => toastError(e, 'Could not set the cost carrier'),
  })
  const decide = useMutation({
    mutationFn: (vars: {
      meetingId: number; decision: 'proceed' | 'reject' | 'needs_info'; reason?: string
      needBy?: NeedByAnswer
    }) => (vars.needBy && vars.needBy.check
      ? changesApi.decideMeeting(changeId, vars.meetingId, vars.decision, vars.reason, {
        need_by_check: vars.needBy.check,
        ...(vars.needBy.check === 'no' ? { need_by_proposed: `${vars.needBy.proposed}T12:00:00` } : {}),
      })
      : changesApi.decideMeeting(changeId, vars.meetingId, vars.decision, vars.reason)),
    onSuccess: () => { setDecideError(null); invalidate() },
    onError: (e: unknown, vars) => {
      const msg = apiErrorMessage(e, 'Could not record the decision')
      setDecideError(msg)
      // A refused 'proceed' is shown as the warning dialog, not only a toast:
      // the server's message names the open flags (or the missing parts).
      if (vars.decision === 'proceed') setRefusal(msg)
      else toastError(e, 'Could not record the decision')
      invalidate()
    },
  })
  // Reject and needs-info both owe the originator an answer, so both collect
  // one before the call goes out rather than letting the server 400.
  const [pending, setPending] = useState<
    { meetingId: number; decision: 'reject' | 'needs_info' } | null>(null)
  // Which older meeting record the user asked to see in full.
  const [showMeeting, setShowMeeting] = useState<number | null>(null)

  const open = status === 'captured' || status === 'scoping'
  // What may be written here: open, and not by a read-only viewer (R24).
  const writable = open && !readOnly
  // Meetings belong to scoping: the backend refuses to create one while the
  // change is still being captured, so the recording UI stays hidden there.
  const meetingOpen = status === 'scoping'
  // Recording and deciding are the lead's, PM's or an admin's (the backend
  // answers anyone else 403): others see the record, not the controls.
  const recordOpen = meetingOpen && canRecordMeeting && !readOnly
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
  // C33: check items are not questions; they have their own list.
  const needsInfo = [...concerns]
    .filter((c) => c.kind === 'needs_info' && !isCheckItem(c))
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
  // Both paths, meeting-raised and hand-raised, render the same card with the
  // same gates. Closing belongs to the asker (or PM); answering to the asking
  // department (or the author), Sales or PM (2026-10-14, served per question).
  // While an admin acts as a department, their personal asker right steps
  // aside with their real memberships: the card shows that department's view.
  const actingAs = getActsAsDepartmentId() != null
  const deptName = (id: number) => departments.find((d) => d.id === id)?.name
  const questionCard = (c: ChangeConcern) => (
    <NeedsInfoCard key={c.id} changeId={changeId} concern={c}
      attachments={attachments} editable={writable}
      canAnswer={canAnswerQuestion(c, {
        userId, actingAs, isSales: canAnswerConcerns, isPm, myDepartmentIds,
      })}
      askingSide={askingSide(c, deptName)}
      canSettle={(!actingAs && c.raised_by === userId) || isPm}
      origin={originOf(c)} onChanged={invalidate}
      structured={v2} confirmerName={change.sales_owner_name ?? change.lead_name} />
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
    ...(carrier || motherPlant ? [] : [t('meeting.costCarrier')]),
    ...(raiserOut && !okRef(waiveReason) ? [t('meeting.raiserWaive').replace('{d}', raiserDept?.name ?? '')] : []),
  ]
  // The backend refuses to start the assessment on an unlocked impacted
  // set: the step says so instead of answering 400. With Development's
  // confirm switched off (served `impact_confirm_step`), 'proceed' locks the
  // set itself, so only an empty set holds it.
  const confirmStep = change.impact_confirm_step !== false
  const impactedCount = (change as { impacted_items?: unknown[] }).impacted_items?.length
  const impactUnlocked = confirmStep && !change.impact_confirmed_at
  const noImpactedParts = !confirmStep && impactedCount === 0
  // Open flags block 'proceed' (risks never do): the decision says so in a
  // dialog that lists them rather than failing on the server.
  const openFlags = openFlagLines(concerns, (id) => departments.find((d) => d.id === id)?.name)
  // C33: check items never hold proceed; they go along as its conditions.
  const openChecks = concerns.filter((c) => c.is_open && isCheckItem(c))
  // HARD #7: a change that goes on as internal (internal now, or a customer
  // change the open meeting set to internal) waits for Quality's PPAP
  // decision; a flipped one for the Sales contact's "notification or offer"
  // answer (mirrors ppap_decision_service.applies / flip_open).
  const ppapOwed = v2 && ppapApplies(change, meetings)
  // Every hold names its owner and due ("Quality's PPAP decision (Quality, due
  // Tue)"), as the header and the dialog's own sentence promise (R5).
  const holdWho = (key: string) => {
    const who = change.next_step?.items?.find((i) => i.kind === 'hard' && i.key === key)?.who
    return who ? ` (${who})` : ''
  }
  const hard7 = v2 ? [
    ...(ppapOwed && change.ppap_decision == null
      ? [t('next.item.ppap_decision') + holdWho('ppap_decision')] : []),
    ...(change.customer_flip_at && change.flip_answer == null
      ? [t('next.item.customer_flip') + holdWho('customer_flip')] : []),
  ] : []
  // R25: the letters a department may take. Management gives OKs and books
  // no hours (Informed only); a retired department carried on an old record
  // takes nothing new, it can only be taken off.
  const lettersFor = (id: number): RasicLetter[] => {
    const d = departments.find((x) => x.id === id)
    if (!d || isRoutable(d)) return RASIC_PICK
    return d.is_active === false ? [] : ['I']
  }
  const toggleDept = (id: number) => {
    setDeptTouched(true)
    setDeptRasic((prev) => {
      if (id in prev) { const next = { ...prev }; delete next[id]; return next }
      const allowed = lettersFor(id)
      if (!allowed.length) return prev
      const rec = recommendedLetter(id)
      return { ...prev, [id]: allowed.includes(rec) ? rec : allowed[0] }
    })
  }
  const setLetter = (id: number, letter: RasicLetter) => {
    setDeptTouched(true)
    setDeptRasic((prev) => ({ ...prev, [id]: letter }))
  }
  const letterOf = (m: ChangeMeeting, id: number): string | null =>
    m.department_rasic?.[String(id)] ?? null

  // Why "Proceed & start assessment" cannot be pressed yet, in words.
  // Christoph 2026-10-28: Proceed stays off until every question is
  // answered and closed (the backend refuses it too: HARD #2)
  // ... and so does an open proposal to cancel: the PM settles it first
  const openCancelVotes = concerns.filter((c) => c.is_open && c.kind === 'reject_proposal')
  const questionsHold = v2 && (openQuestions.length > 0 || openCancelVotes.length > 0)
  const proceedBlockedWhy = (m: ChangeMeeting): string | undefined =>
    v2 && openQuestions.length > 0
      ? t(openQuestions.length === 1 ? 'meeting.questionsHold1' : 'meeting.questionsHoldN')
        .replace('{n}', String(openQuestions.length))
      : v2 && openCancelVotes.length > 0 ? t('meeting.cancelVoteHold')
      : carrierOfMeeting(m) === '' ? t('meeting.costCarrierMissing')
        : impactUnlocked ? t('meeting.impactNotLocked')
          : noImpactedParts ? t('meeting.noImpactedParts') : undefined

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
            {decisionLabel(m.decision)}
          </span>
        ) : recordOpen && motherPlant ? (
          <span className="flex flex-wrap items-center justify-end gap-2">
            {onInformTeam && (
              <button type="button" className={btnSm.primary}
                data-testid={`meeting-inform-${m.id}`} onClick={onInformTeam}>
                {t('mp.sendInfo')}
              </button>
            )}
            <button type="button" className={btnSm.secondary}
              disabled={decide.isPending}
              onClick={() => setPending({ meetingId: m.id, decision: 'needs_info' })}>
              {t('meeting.needsInfo')}
            </button>
            <button type="button"
              className={`${btnSm.secondary} text-red-300 hover:text-red-200 hover:border-red-700`}
              disabled={decide.isPending}
              onClick={() => setPending({ meetingId: m.id, decision: 'reject' })}>
              {t('meeting.reject')}
            </button>
          </span>
        ) : recordOpen ? (
          <span className="flex flex-wrap items-center justify-end gap-2">
            {carrierOfMeeting(m) === '' && (
              <select aria-label={t('meeting.costCarrier')} data-testid={`meeting-carrier-${m.id}`}
                value="" onChange={(e) => e.target.value
                  && setMeetingCarrier.mutate({ meetingId: m.id, carrier: e.target.value as CostCarrier })}
                className="h-7 bg-slate-800 border border-amber-600 rounded-lg px-2 text-xs text-slate-100">
                <option value="">{t('meeting.costCarrierPick')}</option>
                <option value="customer" disabled={carrierBarred('customer')}>{t('meeting.costCarrier.customer')}</option>
                <option value="internal" disabled={carrierBarred('internal')}>{t('meeting.costCarrier.internal')}</option>
              </select>
            )}
            <button type="button" className={btnSm.primary}
              data-testid={`meeting-proceed-${m.id}`}
              disabled={decide.isPending || questionsHold || carrierOfMeeting(m) === ''
                || impactUnlocked || noImpactedParts}
              title={proceedBlockedWhy(m)}
              aria-describedby={proceedBlockedWhy(m) ? `meeting-proceed-why-${m.id}` : undefined}
              onClick={() => setConfirmProceed(m)}>
              {t('meeting.proceed')}
            </button>
            <button type="button" className={btnSm.secondary}
              disabled={decide.isPending} data-testid={`meeting-not-yet-${m.id}`}
              title={v2 && openQuestions.length > 0 ? t('tasks.hint.scopingWaiting')
                .replace('{n}', String(openQuestions.length))
                .replace('{x}', [...new Set(openQuestions.map((q) => askingSide(q, deptName)))].join(', '))
                : undefined}
              onClick={() => (v2 && openQuestions.length > 0
                // C33: the open questions are the reason; nothing new is asked
                ? decide.mutate({ meetingId: m.id, decision: 'needs_info' })
                : setPending({ meetingId: m.id, decision: 'needs_info' }))}>
              {v2 ? t('meeting.notYet') : t('meeting.needsInfo')}
            </button>
            <button type="button"
              className={`${btnSm.secondary} text-red-300 hover:text-red-200 hover:border-red-700`}
              disabled={decide.isPending}
              onClick={() => setPending({ meetingId: m.id, decision: 'reject' })}>
              {t('meeting.reject')}
            </button>
          </span>
        ) : meetingOpen && !motherPlant && (
          <span className="text-xs text-slate-500" data-testid={`meeting-undecided-${m.id}`}>
            {t('meeting.undecided')}
          </span>
        )}
      </div>
      {!m.decision && recordOpen && !motherPlant && proceedBlockedWhy(m) && (
        <p id={`meeting-proceed-why-${m.id}`} data-testid={`meeting-proceed-why-${m.id}`}
          className="text-right text-[11px] text-slate-400">
          {proceedBlockedWhy(m)}
        </p>
      )}
      {!m.decision && recordOpen && motherPlant && (
        <p data-testid={`meeting-inform-hint-${m.id}`} className="text-[11px] text-slate-400">
          {plantText('mp.sendInfoHint', change.mother_plant_name)}
        </p>
      )}
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
          {t(motherPlant ? 'mp.informDepartments' : 'meeting.departments')}: {m.selected_department_ids.map((id) => {
            const name = departments.find((d) => d.id === id)?.name ?? `#${id}`
            const letter = letterOf(m, id)
            return letter ? `${name} (${letter})` : name
          }).join(', ')}
        </p>
      )}
      {(m.go_conditions?.length ?? 0) > 0 && (
        <details className="text-xs text-slate-400" data-testid={`meeting-conditions-${m.id}`}>
          <summary className="cursor-pointer">
            {t('meeting.goConditions').replace('{n}', String(m.go_conditions!.length))}
          </summary>
          <ul className="ml-4 list-disc">
            {m.go_conditions!.map((g) => (
              <li key={g.id}>
                {g.department_id != null ? `${departments.find((d) => d.id === g.department_id)?.name ?? `#${g.department_id}`}: ` : ''}
                {g.note.split('\n')[0]}
              </li>
            ))}
          </ul>
        </details>
      )}
      {carrierOfMeeting(m) && !motherPlant && (
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
    // §3 "Not routed" (SOFT, A2-03): check items whose owner this meeting
    // skips do not hold proceed; proceed routes that department as C (the
    // fix list's Route buttons pick R or C first), unless it takes no letter
    const live = meetings.find((x: ChangeMeeting) => x.id === m.id) ?? m
    // The backend's outcome per owner: a routable one is routed C; one that
    // takes no letter (Management, retired) holds proceed, no override
    const split = v2 ? splitUnroutedOwners(unroutedCheckOwners(live, concerns), departments)
      : { routesC: [], blocked: [] }
    const ownerHolds = split.blocked.map(([id, n]) => ownerUnroutableLine(id, n, departments))
    const unrouted = split.routesC.map(([id, n]) =>
      t('proceed.routesC').replace('{d}', departments.find((d) => d.id === id)?.name ?? `#${id}`)
        .replace('{n}', String(n)))
    // Open flags hold the step: the same dialog becomes the warning, listing
    // each flag and how it is cleared, and its confirm stays disabled.
    if (openFlags.length > 0 || hard7.length > 0 || ownerHolds.length > 0) {
      return {
        to: 'in_assessment',
        title: t('meeting.proceedBlockedTitle'),
        consequence: !v2 ? t('meeting.proceedBlocked')
          : openFlags.length > 0 ? t('proceed.questionsOpen') : t('proceed.heldBelow'),
        open: [...openFlags, ...hard7, ...ownerHolds],
        holdWhileOpen: true,
        confirmLabel: v2 && openChecks.length > 0
          ? t('proceed.go').replace('{n}', String(openChecks.length))
          : t('meeting.proceedConfirm'),
      }
    }
    return {
      to: 'in_assessment',
      title: t('meeting.proceedTitle'),
      consequence: t('meeting.proceedConsequence'),
      // §3 urgent: the need-by question is answered before the step
      holdNote: needByHold(change, needBy),
      open: [
        ...(assessors === 0 && m.department_rasic ? [t('meeting.proceedNoAssessor')] : []),
        ...(flipped ? [t('meeting.costCarrierFlip')
          .replace('{from}', carrierName(carrierOf(change.customer_relevant))).replace('{to}', carrierName(c))] : []),
        ...unrouted,
      ],
      allClear: undefined,
      info: [t('meeting.proceedCarrier').replace('{x}', carrierName(c)),
        ...(!confirmStep && !change.impact_confirmed_at && impactedCount
          ? [t('meeting.proceedLocksImpact').replace('{n}', String(impactedCount))] : []),
        ...lines],
      // C33 Go with conditions: the open check items go to their departments
      confirmLabel: v2 && openChecks.length > 0
        ? t('proceed.go').replace('{n}', String(openChecks.length))
        : t('meeting.proceedConfirm'),
    }
  })()

  return (
    <div className="space-y-4 text-sm">
      <TransitionConfirmDialog confirm={proceedConfirm} busy={decide.isPending}
        onClose={() => { setConfirmProceed(null); setNeedBy({ check: '', proposed: '' }) }}
        onConfirm={() => {
          const m = confirmProceed!
          setConfirmProceed(null)
          decide.mutate({ meetingId: m.id, decision: 'proceed', needBy })
          setNeedBy({ check: '', proposed: '' })
        }}>
        {v2 && confirmProceed && isUrgentV2(change) && openFlags.length === 0 && hard7.length === 0 && (
          <NeedByCheck change={change} value={needBy} onChange={setNeedBy}
            customer={!ppapApplies(change, meetings)} />
        )}
        {v2 && confirmProceed && (
          <ProceedFixList changeId={changeId}
            meeting={meetings.find((m: ChangeMeeting) => m.id === confirmProceed.id) ?? confirmProceed}
            concerns={concerns} attachments={attachments} departments={departments}
            confirmerName={change.sales_owner_name ?? change.lead_name} onChanged={invalidate} />
        )}
      </TransitionConfirmDialog>
      <TransitionConfirmDialog busy={false}
        confirm={refusal ? {
          to: 'in_assessment', title: t('meeting.proceedBlockedTitle'),
          consequence: t('meeting.proceedBlockedServer'),
          open: [refusal], holdWhileOpen: true, confirmLabel: t('meeting.proceedConfirm'),
        } : null}
        onClose={() => setRefusal(null)}
        onConfirm={() => setRefusal(null)} />
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
        title={pending?.decision === 'reject' ? t('meeting.rejectTitle')
          : v2 ? t('meeting.notYetTitle') : t('meeting.needsInfoTitle')}
        warning={pending?.decision === 'reject' ? t('meeting.rejectWarning') : t('meeting.needsInfoWarning')}
        label={pending?.decision === 'reject' ? t('meeting.rejectLabel') : t('meeting.needsInfoLabel')}
        submitLabel={pending?.decision === 'reject' ? t('meeting.reject')
          : v2 ? t('meeting.notYet') : t('meeting.needsInfo')}
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
                <p className="inline-flex items-center gap-1.5 text-xs text-emerald-300">
                  <Check aria-hidden="true" size={14} />
                  {t('reject.sent')} · {formatDate(change.rejection_sent_at)}
                </p>
              ) : (
                <Button variant="primary" data-testid="rejection-sent"
                  disabled={rejectionLetters.length === 0 || !canSendRejection}
                  loading={markSent.isPending}
                  title={!canSendRejection ? t('reject.salesOnly')
                    : rejectionLetters.length === 0 ? t('reject.needLetter') : undefined}
                  aria-describedby={!canSendRejection || rejectionLetters.length === 0
                    ? 'rejection-sent-why' : undefined}
                  onClick={() => setConfirmSent(true)}>
                  {t('reject.markSent')}
                </Button>
              )}
              {!change.rejection_sent_at && (!canSendRejection || rejectionLetters.length === 0) && (
                <p id="rejection-sent-why" className="text-[11px] text-slate-400" data-testid="rejection-sent-why">
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

        {/* HARD #7: Quality's ppap_decision on an internal change, and the
            Sales answer once it became a customer change. */}
        {v2 && (ppapOwed || change.ppap_decision != null) && (
          <PpapDecisionCard change={change} editable={writable} onChanged={invalidate}
            isQuality={departments.some((d) => d.name === 'Quality' && myDepartmentIds.includes(d.id))} />
        )}
        {v2 && change.customer_flip_at && (
          <CustomerFlipCard change={change}
            editable={!['closed', 'cancelled', 'rejected'].includes(change.status) && !readOnly}
            isSales={canAnswerConcerns} attachments={attachments} onChanged={invalidate} />
        )}

        {/* C33: the quick add and the check items, grouped by owner. */}
        {v2 && open && (
          <ScopingFlags changeId={changeId} concerns={concerns}
            impactedItems={(change as { impacted_items?: ImpactedItem[] }).impacted_items ?? []}
            departments={departments} myDepartmentIds={myDepartmentIds}
            changeDepartmentIds={[...new Set([...recommendedIds, ...(latestMeeting?.selected_department_ids ?? [])])]}
            editable={writable} canRaise={change.can_raise_question ?? canRecordMeeting} onChanged={invalidate} />
        )}

        {/* Everything else the team flagged, in one strip. */}
        <ConcernStrip changeId={changeId} editable={writable} departments={departments}
          voteOnly={v2}
          isPm={isPm} hideConcernIds={concerns.filter((c) => c.kind === 'needs_info').map((c) => c.id)}
          myDepartmentIds={myDepartmentIds}
          changeDepartmentIds={[...new Set([...recommendedIds, ...(latestMeeting?.selected_department_ids ?? [])])]} />
      </section>

      {/* A refused proceed is shown in its warning dialog; the line here
          stays as the record once that dialog is closed, never both at once. */}
      {decideError && !refusal && (
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
                    className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-sky-400">
                    <span className="px-1.5 py-0 rounded bg-slate-700 text-slate-300">
                      {t(`channel.${m.channel ?? 'meeting'}`)}
                    </span>
                    <span className="text-slate-400">
                      {formatDate(m.meeting_date)}
                    </span>
                    {m.decision && (
                      <span className="px-1.5 py-0 rounded-full bg-slate-700 text-slate-300">
                        {decisionLabel(m.decision)}
                      </span>
                    )}
                    <span className="ml-auto text-slate-500">{t('scoping.showDetails')}</span>
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

      {meetingOpen && (!canRecordMeeting || readOnly) && (
        <p className="text-xs text-slate-500" data-testid="meeting-record-rights">{t('meeting.recordRights')}</p>
      )}
      {recordOpen && !formShown && (
        <div className="flex items-center gap-3">
          <button type="button" data-testid="meeting-form-open" onClick={openForm}
            className="text-sm text-sky-300 hover:text-sky-200">
            {meetings.length > 0 ? t('meeting.recordAnother') : t('meeting.recordFirst')}
          </button>
          {latestMeeting && !latestMeeting.decision && !motherPlant && (
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
          {channel === 'email' && (
            <p className="text-xs text-slate-500" data-testid="meeting-email-hint">{t('scoping.discussionByEmail')}</p>
          )}
          {motherPlant && (
            <p className="text-xs text-slate-400 max-w-[65ch]" data-testid="meeting-mother-plant-hint">
              {plantText('mp.scopingHint', change.mother_plant_name)}
            </p>
          )}
          <div className="flex flex-wrap gap-3">
            <div>
              <label htmlFor={channelId} className="block text-xs text-slate-400 mb-1">{t('channel.label')}</label>
              <select id={channelId} data-testid="meeting-channel"
                value={channel} onChange={(e) => setChannel(e.target.value as typeof channel)}
                className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100">
                <option value="meeting">{t('channel.meeting')}</option>
                <option value="chat">{t('channel.chat')}</option>
                <option value="email">{t('channel.email')}</option>
              </select>
            </div>
            <div>
              <span className="block text-xs text-slate-400 mb-1" aria-hidden="true">{t('meeting.dateLabel')}</span>
              <DateInput value={date} onChange={setDate} aria-label={t('meeting.dateLabel')}
                className="w-36 bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
            </div>
            <div className="flex-1 min-w-[14rem]">
              <label htmlFor={attendeeId} className="block text-xs text-slate-400 mb-1">
                {t('meeting.participants')}
                <span id={attendeeHintId} className="ml-2 text-slate-500">{t('meeting.attendanceHint')}</span>
              </label>
              {/* Picked people live as removable chips: grouped, contained, not
                  free-editable text that can be accidentally mangled. A person
                  from the directory is the user (person icon); a typed name
                  is an external guest. */}
              <div className="flex flex-wrap items-center gap-1.5 rounded-lg bg-slate-800 border border-slate-600 px-2 py-1.5 min-h-[2.25rem] focus-within:border-sky-500">
                {participantList.map((a) => (
                  <span key={attendeeKey(a)} data-testid="meeting-attendee"
                    data-user-id={a.user_id ?? undefined} data-guest={a.guest || undefined}
                    title={a.guest ? 'Guest, not a PLM user' : (a.email ?? undefined)}
                    className={`inline-flex items-center gap-1 rounded-md text-xs pl-2 pr-0.5 py-0.5 ${
                      a.guest ? 'bg-slate-800 text-slate-300 ring-1 ring-inset ring-slate-600' : 'bg-slate-700 text-slate-100'}`}>
                    {!a.guest && <UserRound aria-hidden="true" size={12} className="text-sky-300" />}
                    {a.name}
                    <button type="button" aria-label={`Remove ${a.name}`}
                      className="inline-flex h-5 w-5 items-center justify-center rounded text-slate-400 hover:bg-slate-600 hover:text-red-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
                      onClick={() => removeParticipant(a)}>
                      <X aria-hidden="true" size={12} />
                    </button>
                  </span>
                ))}
                <input
                  id={attendeeId} aria-describedby={attendeeHintId}
                  type="text" list="sc-contacts" value={addName} autoComplete="off"
                  placeholder={participantList.length ? '' : t('meeting.addAttendee')}
                  onChange={(e) => {
                    const v = e.target.value
                    setAddName(v)
                    // Picking a suggestion sets the full name in one change event.
                    const picked = people.find((c) => labelOf(c) === v)
                    if (picked) appendParticipant(fromContact(picked))
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
                  className="flex-1 min-w-[8rem] bg-transparent text-sm text-slate-100 placeholder:text-slate-500 outline-none" />
              </div>
              <datalist id="sc-contacts">
                {people.map((c) => (
                  <option key={c.user_id != null ? `u${c.user_id}` : (c.email ?? c.name)}
                    value={labelOf(c)}>
                    {[c.email, c.department].filter(Boolean).join(' · ')}
                  </option>
                ))}
              </datalist>
            </div>
          </div>
          <div>
            <div className="flex items-baseline justify-between gap-4 mb-1">
              <span className="text-xs text-slate-400">
                {t(motherPlant ? 'mp.informDepartments' : 'meeting.departments')}
                {recommendedIds.length > 0 && (
                  <span className="ml-2 text-slate-500">{t('meeting.recommendedHint')}</span>
                )}
              </span>
              <span className="text-[11px] text-slate-500 tabular-nums" data-testid="rasic-summary">
                {motherPlant ? t('mp.informSummary').replace('{n}', String(deptIds.length))
                  : t('meeting.rasicSummary')
                    .replace('{a}', String(Object.values(deptRasic).filter((l) => l === 'R' || l === 'A').length))
                    .replace('{n}', String(deptIds.length))}
              </span>
            </div>
            {!motherPlant && (
              <p className="text-[11px] text-slate-500 mb-2 max-w-[65ch]">{t('meeting.rasicHint')}</p>
            )}
            {/* One row per department: name left, its letter right. A row
                without a letter is not involved and reads muted. Retired
                departments stay resolvable by name on old records but are
                never offered for new work; one a carried-over call still
                holds shows "(retired)" so it can be taken off. */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 border-t border-slate-700/70">
              {pickableDepartments(departments, deptIds).map((d) => {
                const isRec = recommendedIds.includes(d.id)
                const sometimes = sometimesIds.includes(d.id)
                const letter = deptRasic[d.id]
                // Assessing now beyond the standard: most departments join
                // at implementation with their own task, not here
                const extra = !motherPlant && recommended.length > 0 && !isRec && !sometimes
                  && (letter === 'R' || letter === 'A')
                return (
                  <div key={d.id} data-testid={`rasic-row-${d.id}`}
                    className={`flex items-center justify-between gap-3 py-1.5 border-b border-slate-700/70 ${
                      letter ? '' : 'opacity-60'}`}>
                    <div className="min-w-0">
                    <button type="button" onClick={() => toggleDept(d.id)}
                      aria-pressed={!!letter}
                      title={isRec ? t('meeting.recommended') : undefined}
                      className={`max-w-full truncate text-left text-sm rounded px-1 -mx-1 transition-colors ${
                        letter ? 'text-slate-100' : 'text-slate-400 hover:text-slate-200'}`}>
                      {departmentLabel(d)}
                      {sometimes && !letter && (
                        <span className="ml-1.5 text-[11px] text-slate-500">{t('rasic.sometimes')}</span>
                      )}
                    </button>
                    {extra && (
                      <p className="text-[11px] leading-snug text-amber-300/90" data-testid={`rasic-extra-${d.id}`}>
                        {t('rasic.extraWarn')}
                      </p>
                    )}
                    </div>
                    {motherPlant ? (
                      <input type="checkbox" checked={!!letter} data-testid={`inform-${d.id}`}
                        aria-label={`${t('mp.informDepartments')}: ${d.name}`}
                        onChange={() => toggleDept(d.id)} />
                    ) : (
                    <span className="inline-flex flex-shrink-0 rounded-md border border-slate-600 overflow-hidden divide-x divide-slate-600"
                      role="group" aria-label={`${d.name} RASIC`}>
                      {lettersFor(d.id).map((l) => (
                        <button key={l} type="button" data-testid={`rasic-${d.id}-${l}`}
                          aria-pressed={letter === l} title={t(`rasic.${l}`)}
                          aria-label={`${l}, ${t(`rasic.${l}`)}`}
                          onClick={() => setLetter(d.id, l)}
                          className={`w-7 h-6 text-[11px] font-semibold transition-colors active:scale-[0.97] ${
                            letter === l
                              ? (l === 'R' || l === 'A'
                                ? 'bg-sky-700 text-white'
                                : 'bg-slate-600 text-slate-100')
                              : 'bg-slate-900 text-slate-500 hover:text-slate-200 hover:bg-slate-800'}`}>
                          {l}
                        </button>
                      ))}
                      <button type="button" data-testid={`rasic-${d.id}-none`}
                        aria-pressed={!letter} title={t('rasic.none')} aria-label={t('rasic.none')}
                        onClick={() => { if (letter) toggleDept(d.id) }}
                        className={`w-7 h-6 text-[11px] transition-colors ${
                          letter ? 'bg-slate-900 text-slate-500 hover:text-slate-200 hover:bg-slate-800'
                            : 'bg-slate-800 text-slate-300'}`}>
                        &ndash;
                      </button>
                    </span>
                    )}
                  </div>
                )
              })}
            </div>
            {!motherPlant && (
              <p className="mt-1.5 text-[11px] text-slate-500">
                <span className="text-slate-400">R/A</span> {t('rasic.assessNote')}
              </p>
            )}
            {!motherPlant && raiserOut && (
              <label className="mt-2 block text-xs text-amber-200" data-testid="meeting-raiser-waive">
                {t('meeting.raiserWaive').replace('{d}', raiserDept?.name ?? '')}{' '}
                <span className="text-amber-300">(required)</span>
                <input value={waiveReason} onChange={(e) => setWaiveReason(e.target.value)}
                  data-testid="meeting-raiser-waive-reason" placeholder={t('meeting.raiserWaiveHint')}
                  className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 placeholder:text-slate-500 focus:border-sky-500 focus:outline-none" />
              </label>
            )}
          </div>
          {/* Who pays, confirmed by the room next to who works. A change from
              KTX Weissenburg / Solingen has no cost carrier to confirm. */}
          {!motherPlant && (
          <fieldset data-testid="meeting-carrier">
            <legend className="text-xs text-slate-400 mb-1">
              {t('meeting.costCarrier')}
              <span className="ml-2 text-slate-500">{t('meeting.costCarrierHint')}</span>
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
                    disabled={carrierBarred(c)}
                    checked={carrier === c} onChange={() => setCarrier(c)} />
                  <span className="text-slate-200">{t(`meeting.costCarrier.${c}`)}</span>
                </label>
              ))}
            </div>
            {flipLocked && (
              <p data-testid="meeting-carrier-flip-lock" className="mt-1 text-xs text-slate-400">
                {t('flip.holdsCustomer')}
              </p>
            )}
            {carrierNotYours && (
              <p data-testid="meeting-carrier-not-yours" className="mt-1 text-xs text-slate-400">
                {t(capturedCarrier === 'internal' ? 'meeting.costCarrierNotYours.customer'
                  : 'meeting.costCarrierNotYours.internal')}
              </p>
            )}
            {carrier && carrierOf(change.customer_relevant) && carrier !== carrierOf(change.customer_relevant) && (
              <p data-testid="meeting-carrier-flip" className="mt-1 text-xs text-amber-300">
                {t('meeting.costCarrierFlip')
                  .replace('{from}', carrierName(carrierOf(change.customer_relevant))).replace('{to}', carrierName(carrier))}
              </p>
            )}
          </fieldset>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" data-testid="meeting-save"
              disabled={saveMissing.length > 0} loading={create.isPending}
              aria-describedby={saveMissing.length > 0 ? 'meeting-save-missing' : undefined}
              onClick={() => create.mutate()}>
              {t('meeting.save')}
            </Button>
            {saveMissing.length > 0 && (
              <span id="meeting-save-missing" className="text-xs text-slate-400" data-testid="meeting-save-missing">
                {t('meeting.saveMissing').replace('{x}', saveMissing.join(', '))}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
