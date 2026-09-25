import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'
import type { Attachment } from '../../types/change'
import { DEPARTMENT_FIELDS } from './departmentForms'
import ActivityChecklist, { checklistProgress, impactsOf, restToNo } from './departmentForms/ActivityChecklist'
import AttachmentDropzone from './AttachmentDropzone'
import TransitionConfirmDialog from './TransitionConfirmDialog'
import { verdictLabel, plural } from '../../lib/humanLabels'
import { readStored, writeStored } from '../../lib/safeStorage'

/** Where an unfinished assessment is kept in this browser. */
export const draftKey = (changeId: number, departmentId: number) =>
  `cm-assessment-draft:${changeId}:${departmentId}`

/** What the form keeps while the department is still answering. */
export interface AssessmentDraft {
  details: Record<string, unknown>
  verdict?: string
  conditions?: string
  notes?: string
}

/** The local draft, else the server's (details.draft or unsubmitted details). */
export function loadDraft(changeId: number, departmentId: number,
  serverDetails?: Record<string, unknown> | null): AssessmentDraft | null {
  const raw = readStored(draftKey(changeId, departmentId))
  if (raw) {
    try {
      const d = JSON.parse(raw) as AssessmentDraft
      if (d && typeof d === 'object' && d.details && typeof d.details === 'object') return d
    } catch {
      // A broken draft is no draft.
    }
  }
  if (serverDetails && typeof serverDetails === 'object') {
    // details.draft = {data, saved_at, saved_by}; data is what the form saved.
    const inner = (serverDetails as { draft?: { data?: unknown } }).draft?.data
    if (inner && typeof inner === 'object') {
      const d = inner as Partial<AssessmentDraft> & Record<string, unknown>
      return d.details && typeof d.details === 'object'
        ? { details: d.details, verdict: d.verdict, conditions: d.conditions, notes: d.notes }
        : { details: d }
    }
    if (impactsOf(serverDetails).length > 0 || 'impacted' in serverDetails) {
      return { details: serverDetails }
    }
  }
  return null
}

export const clearDraft = (changeId: number, departmentId: number) => {
  try { window.localStorage.removeItem(draftKey(changeId, departmentId)) } catch { /* storage off */ }
}

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const VERDICTS = ['feasible', 'feasible_with_conditions', 'not_feasible'] as const

export default function AssessmentSubmitForm({
  changeId, departmentId, departmentName, onDone, showEffort = true,
  changePptCount = 0, onVerdictChange, assessmentId, evidence = [], onUploaded,
  serverDraft = null,
}: {
  changeId: number; departmentId: number; departmentName: string; onDone: () => void
  /** Internal change decks already filed against this assessment. A not-feasible
   *  verdict owes an explanation, so it cannot be sent without one — the same
   *  rule the backend enforces. */
  changePptCount?: number
  onVerdictChange?: (verdict: string) => void
  /** Lets the checklist collect its own documents (the RFQ) against this row. */
  assessmentId?: number
  evidence?: Attachment[]
  onUploaded?: () => void
  /** Effort is money's business: the assessment bucket asks feasibility only and
   *  leaves hours to costing. The API still accepts them from other callers. */
  showEffort?: boolean
  /** The unsubmitted answers the server kept (the row's details), restored on
   *  load when this browser has no newer draft of its own. */
  serverDraft?: Record<string, unknown> | null
}) {
  const qc = useQueryClient()
  // A half-answered checklist survives a reload, a crash or a colleague's
  // browser: restored from this browser first, else from the server's draft.
  const [initial] = useState(() => loadDraft(changeId, departmentId, serverDraft))
  const [verdict, setVerdict] = useState(initial?.verdict ?? '')
  const [failure, setFailure] = useState<string | null>(null)
  const needsChangePpt = verdict === 'not_feasible' && changePptCount === 0
  const [effort, setEffort] = useState('')
  const [conditions, setConditions] = useState(initial?.conditions ?? '')
  const [notes, setNotes] = useState(initial?.notes ?? '')
  // Whatever this department's own questionnaire collects, verbatim.
  const [details, setDetails] = useState<Record<string, unknown>>(initial?.details ?? {})
  const [confirming, setConfirming] = useState(false)
  const [savedAt, setSavedAt] = useState<'local' | 'server' | null>(initial ? 'local' : null)
  // Autosave: every change lands locally at once and on the server after a
  // pause. A backend without the draft endpoint is simply not asked again.
  const serverDraftOff = useRef(false)
  const lastSaved = useRef(JSON.stringify({
    details: initial?.details ?? {}, verdict: initial?.verdict ?? '',
    conditions: initial?.conditions ?? '', notes: initial?.notes ?? '',
  }))
  useEffect(() => {
    const snapshot = JSON.stringify({ details, verdict, conditions, notes } satisfies AssessmentDraft)
    if (snapshot === lastSaved.current) return
    lastSaved.current = snapshot
    writeStored(draftKey(changeId, departmentId), snapshot)
    setSavedAt('local')
    if (serverDraftOff.current) return
    if (assessmentId == null) return
    const timer = window.setTimeout(() => {
      changesApi.saveAssessmentDraft?.(changeId, assessmentId, { details, verdict, conditions, notes })
        ?.then(() => setSavedAt('server'))
        .catch((e: unknown) => {
          const code = (e as { response?: { status?: number } })?.response?.status
          if (code === 404 || code === 405 || code === 403) serverDraftOff.current = true
        })
    }, 800)
    return () => window.clearTimeout(timer)
  }, [changeId, departmentId, assessmentId, details, verdict, conditions, notes])
  useEffect(() => { if (initial?.verdict) onVerdictChange?.(initial.verdict) }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const Fields = DEPARTMENT_FIELDS[departmentName]
  // A questionnaire that answers "not impacted" is a complete assessment on its
  // own: nothing is affected, so there is nothing further to ask.
  const notImpacted = !!Fields && details.impacted === false
  // A department with its own first question answers it before anything
  // else: the general checklist only matters once it says "impacted".
  const questionnaireOpen = !!Fields && details.impacted === undefined
  // Same query the checklist renders from (shared cache): the form needs the
  // count to hold the submit until every row is answered.
  const { data: defs = [], isSuccess: defsLoaded } = useQuery({
    queryKey: ['assessment-checklist', departmentId],
    queryFn: () => changesApi.assessmentChecklist(departmentId),
  })
  const progress = checklistProgress(defs, details)
  const [showOpen, setShowOpen] = useState(false)
  // An unloaded (or failed) checklist is not "0 of 0 done": every department
  // has rows, so without them there is nothing to submit against.
  const checklistDone = notImpacted
    || (defsLoaded && defs.length > 0 && progress.answered === progress.total)
  const submit = useMutation({
    mutationFn: () => changesApi.submitAssessment(changeId, {
      department_id: departmentId,
      // "Not impacted" is feasible by definition — nothing changes for us.
      verdict: notImpacted ? 'feasible' : verdict,
      ...(showEffort ? { effort_hours: parseFloat(effort) } : {}),
      conditions: conditions || undefined, notes: notes || undefined,
      // One envelope for everything the department answered: the checklist and,
      // where it has one, its own questionnaire.
      details,
    }),
    onSuccess: () => {
      toast.success(`${departmentName}: ${notImpacted ? t('pkg.notImpacted') : verdictLabel(verdict)}`)
      clearDraft(changeId, departmentId)
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      qc.invalidateQueries({ queryKey: ['change-routing', changeId] })
      // "Your actions" and My Tasks drop the submitted task straight away.
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
      qc.invalidateQueries({ queryKey: ['change-my-tasks'] })
      onDone()
    },
    onError: (e: unknown) => {
      // The backend enforces the same rule; say what it said, in place.
      const detail = errDetail(e) ?? 'Submit failed'
      setFailure(detail)
      toast.error(detail)
    },
  })
  const ready = !needsChangePpt && checklistDone && (notImpacted || (verdict !== ''
    && (!showEffort || (effort !== '' && parseFloat(effort) >= 0))
    && (!Fields || details.impacted !== undefined)))
  return (
    <div className="border border-slate-700 rounded-lg p-3 space-y-2 text-sm">
      {Fields && <Fields value={details} onChange={setDetails} />}
      {/* The workbook's checklist: their catalog, off by default. Skipped once a
          questionnaire has said the department is not impacted at all. */}
      {questionnaireOpen && (
        <p data-testid="questionnaire-first" className="text-[11px] text-slate-500">
          {t('pkg.answerFirst')}
        </p>
      )}
      {!notImpacted && !questionnaireOpen && progress.total > 0 && (
        <p data-testid="check-progress"
          className={`text-[11px] ${progress.answered === progress.total ? 'text-emerald-400' : 'text-slate-400'}`}>
          {t('check.progress').replace('{n}', String(progress.answered))
            .replace('{m}', String(progress.total))}
          {progress.answered < progress.total && (
            <button type="button" data-testid="check-rest-no" title={t('check.restNoHint')}
              onClick={() => setDetails((d) => restToNo(defs, d))}
              className="ml-2 rounded border border-slate-600 px-1.5 py-0 text-[11px] text-slate-300 hover:bg-slate-700">
              {t('check.restNo')}
            </button>
          )}
        </p>
      )}
      {!notImpacted && !questionnaireOpen && (
        <ActivityChecklist departmentId={departmentId} value={details} onChange={setDetails}
          changeId={changeId} assessmentId={assessmentId}
          attachments={evidence} onUploaded={onUploaded} highlightOpen={showOpen} />
      )}
      {/* Not impacted answers everything: the rest of the form would only ask
          about work that does not exist. */}
      {!notImpacted && (
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor={`verdict-${departmentId}`} className="block text-xs text-slate-500 mb-1">
            {t('assessment.verdict')}
          </label>
          <select id={`verdict-${departmentId}`} value={verdict}
            onChange={(e) => { setVerdict(e.target.value); onVerdictChange?.(e.target.value) }}
            className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100">
            <option value="">{t('assessment.pickVerdict')}</option>
            {VERDICTS.map((v) => <option key={v} value={v}>{verdictLabel(v)}</option>)}
          </select>
        </div>
        {showEffort && (
          <div>
            <label htmlFor={`effort-${departmentId}`} className="block text-xs text-slate-500 mb-1">
              {t('effort.hours')}
            </label>
            <input id={`effort-${departmentId}`} type="number" min="0" step="0.25"
              value={effort} onChange={(e) => setEffort(e.target.value)}
              className="w-28 bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
          </div>
        )}
      </div>
      )}
      {!notImpacted && verdict === 'feasible_with_conditions' && (
        <div>
          <label htmlFor={`conditions-${departmentId}`} className="block text-xs text-slate-500 mb-1">
            {t('conditions')}
          </label>
          <input id={`conditions-${departmentId}`} type="text"
            value={conditions} onChange={(e) => setConditions(e.target.value)}
            className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
        </div>
      )}
      {!notImpacted && (
        <textarea rows={2} placeholder="Notes" value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
      )}
      {needsChangePpt && (
        <div data-testid="assessment-evidence-required"
          className="space-y-1 rounded border border-amber-700/60 bg-amber-950/30 px-2 py-1.5 text-xs text-amber-200">
          <p>{t('check.changePptRequired')}</p>
          {/* Right above Submit: the one thing still between the department
              and sending its answer. */}
          {assessmentId != null && (
            <AttachmentDropzone changeId={changeId} assessmentId={assessmentId} compact
              kind="change_ppt" label={t('bucket.changePptSlot')}
              onUploaded={() => onUploaded?.()} />
          )}
        </div>
      )}
      {failure && (
        <p role="alert" data-testid="assessment-error"
          className="rounded border border-red-800/60 bg-red-950/40 px-2 py-1 text-xs text-red-200">
          {failure}
        </p>
      )}
      <button data-testid="assessment-submit"
        disabled={!ready || submit.isPending} onClick={() => setConfirming(true)}
        className="bg-sky-600 hover:bg-sky-500 text-white font-semibold px-4 py-1.5 rounded-lg text-sm disabled:opacity-50">
        {notImpacted ? t('pkg.submitNotImpacted') : t('assessment.submit')}
      </button>
      {!checklistDone && progress.firstOpen && (
        <button type="button" data-testid="check-open-jump"
          className="ml-2 text-xs text-amber-300 underline decoration-dotted underline-offset-2"
          onClick={() => {
            setShowOpen(true)
            document.getElementById(`check-row-${progress.firstOpen}`)
              ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
          }}>
          {progress.total - progress.answered === 1 ? t('check.openRowsOne')
            : t('check.openRows').replace('{n}', String(progress.total - progress.answered))}
        </button>
      )}
      {savedAt && (
        <span data-testid="assessment-draft-state" className="ml-2 text-[11px] text-slate-500">
          {savedAt === 'server' ? t('assessment.draftSaved') : t('assessment.draftLocal')}
        </span>
      )}
      <TransitionConfirmDialog busy={submit.isPending}
        confirm={confirming ? {
          to: 'submit-assessment',
          title: t('assessment.confirmTitle').replace('{d}', departmentName),
          consequence: t('assessment.confirmBody'),
          open: [],
          info: [
            `${t('assessment.verdict')}: ${notImpacted ? t('pkg.notImpacted') : verdictLabel(verdict)}`,
            ...(notImpacted ? [] : [
              `${plural(impactsOf(details).filter((i) => i.impacted).length, 'area')} ${t('assessment.confirmImpacted')}`,
            ]),
            ...(conditions.trim() ? [`${t('conditions')}: ${conditions.trim()}`] : []),
          ],
          confirmLabel: notImpacted ? t('pkg.submitNotImpacted') : t('assessment.submit'),
        } : null}
        onClose={() => setConfirming(false)}
        onConfirm={() => { setConfirming(false); submit.mutate() }} />
    </div>
  )
}
