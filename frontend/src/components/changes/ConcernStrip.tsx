import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { useAuth } from '../../contexts/AuthContext'
import { t } from '../../i18n/cmLabels'
import { getActsAsDepartmentId } from '../../lib/actsAs'
import { preferredDepartmentId } from '../../lib/departments'
import AttachmentDropzone from './AttachmentDropzone'
import { AttachmentRow } from './AttachmentRow'
import type {
  Attachment, ChangeConcern, ConcernKind, RiskSeverity, RiskType, RiskTemplateIn,
} from '../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const KIND_STYLE: Record<ConcernKind, string> = {
  reject_proposal: 'bg-red-900/60 text-red-200 border-red-800',
  needs_info: 'bg-amber-900/50 text-amber-200 border-amber-800',
  // A risk holds nothing up, so it is not painted as an obstruction. Its weight
  // is carried by the severity badge, where it belongs.
  risk: 'bg-slate-900/50 text-slate-200 border-slate-700',
}

/** The vocabulary the backend serves; kept here as the offline fallback so the
 *  form still works when /reference/risk-types is unreachable. */
const RISK_TYPES: RiskType[] = [
  'fill_issue', 'dimensional_issue', 'visual_surface', 'process_capability', 'other',
]

const SEVERITIES: RiskSeverity[] = [1, 2, 3]

/** 1 is noted, 2 wants watching, 3 is the one that gets someone out of bed. */
const SEVERITY_STYLE: Record<RiskSeverity, string> = {
  1: 'bg-slate-700 text-slate-200 border-slate-600',
  2: 'bg-amber-900/70 text-amber-100 border-amber-700',
  3: 'bg-red-900/80 text-red-100 border-red-700',
}

function SeverityBadge({ value, testId }: { value?: number | null; testId: string }) {
  if (value == null) return null
  const style = SEVERITY_STYLE[value as RiskSeverity] ?? SEVERITY_STYLE[1]
  return (
    <span data-testid={testId} title={t('risk.severity')}
      className={`inline-flex items-center rounded border px-1.5 py-0 text-[10px] leading-tight font-semibold ${style}`}>
      {value}
    </span>
  )
}

/**
 * Two phases, two vocabularies. In scoping (scoped=false) the strip is the
 * team working the decision in parallel: anyone may flag that they'd reject
 * the change or that information is missing, open flags block 'proceed', and
 * the meeting cannot quietly run over an objection. In assessment
 * (scoped=true) the strip is the per-change risk register: a risk blocks
 * nothing — it is worked with a mitigation proposal and closed by the raising
 * side.
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
  // The scoping form: a question or a cancel vote, in the raiser's words.
  const [kind, setKind] = useState<Exclude<ConcernKind, 'risk'>>('needs_info')
  // The risk form (assessment): nothing is guessed — the type is picked, the
  // severity is a deliberate choice (2 = the honest middle), the note says
  // what it is.
  const [riskType, setRiskType] = useState<RiskType | ''>('')
  const [severity, setSeverity] = useState<RiskSeverity>(2)
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

  // Fetched only once the risk form is open — an unopened strip asks for
  // nothing, and the scoping form never needs the vocabulary.
  // The vocabulary is the department's own (backend: risk_types.py), so it is
  // re-fetched when the department changes.
  const { data: riskTypeData } = useQuery({
    queryKey: ['risk-types', effectiveDept ?? null],
    queryFn: () => changesApi.riskTypes(effectiveDept),
    enabled: adding && scoped,
    retry: false,
  })
  const riskTypeOptions: string[] = riskTypeData?.items?.length
    ? riskTypeData.items.map((i) => i.key)
    : RISK_TYPES
  // Served labels first (they cover every department's keys); the local table
  // only for the legacy keys when the reference is unreachable.
  const servedLabel = (k: string) => riskTypeData?.items?.find((i) => i.key === k)?.label_en
  const riskTypeLabel = (k?: string | null) =>
    k ? (servedLabel(k) ?? (t(`risktype.${k}`) !== `risktype.${k}` ? t(`risktype.${k}`) : k))
      : t('risk.kind')

  // The department's own additions to the dropdown: "+ Add own risk type…"
  // opens a one-line input; the new type is created, selected, and can be
  // removed again from the same spot.
  const ADD_TYPE = '__add_type__'
  const [newType, setNewType] = useState<string | null>(null)
  const invalidateTypes = () =>
    qc.invalidateQueries({ queryKey: ['risk-types', effectiveDept ?? null] })
  const createType = useMutation({
    mutationFn: (label: string) => changesApi.createRiskType(effectiveDept as number, label),
    onSuccess: (row) => { invalidateTypes(); setRiskType(row.key); setNewType(null); toast.success(t('risk.typeAdded')) },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not add the risk type'),
  })
  const deleteType = useMutation({
    mutationFn: (id: number) => changesApi.deleteRiskType(id),
    onSuccess: () => { invalidateTypes(); setRiskType(''); toast.success(t('risk.typeDeleted')) },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not remove the risk type'),
  })
  const customIdOf = (k: string) => riskTypeData?.items?.find((i) => i.key === k)?.custom_id

  // The department's pre-written risks. Picking one fills the form; the user
  // may still edit before raising. Saving writes the current form to the list.
  const { data: templates = [] } = useQuery({
    queryKey: ['risk-templates', effectiveDept ?? null],
    queryFn: () => changesApi.riskTemplates(effectiveDept as number),
    enabled: adding && scoped && effectiveDept !== undefined,
    retry: false,
  })
  const [templateId, setTemplateId] = useState<number | ''>('')
  const [saveTemplate, setSaveTemplate] = useState(false)
  const applyTemplate = (id: number | '') => {
    setTemplateId(id)
    const tpl = templates.find((x) => x.id === id)
    if (!tpl) return
    setRiskType(tpl.risk_type); setSeverity(tpl.severity); setNote(tpl.note)
  }
  const invalidateTemplates = () =>
    qc.invalidateQueries({ queryKey: ['risk-templates', effectiveDept ?? null] })
  const deleteTemplate = useMutation({
    mutationFn: (id: number) => changesApi.deleteRiskTemplate(id),
    onSuccess: () => { setTemplateId(''); invalidateTemplates(); toast.success(t('risk.templateDeleted')) },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not delete the template'),
  })
  const saveTemplateNow = useMutation({
    // The payload is handed over, not read from state: the form is cleared in
    // the same tick the raise succeeds.
    mutationFn: (body: RiskTemplateIn) => changesApi.createRiskTemplate(body),
    onSuccess: () => { invalidateTemplates(); toast.success(t('risk.templateSaved')) },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not save the template'),
  })

  // Scoping raises a concern (question / cancel vote); assessment raises a
  // risk. The backend enforces the same split.
  const raise = useMutation({
    mutationFn: () => changesApi.raiseConcern(changeId, {
      note: note.trim(),
      ...(scoped
        ? { kind: 'risk' as const, severity,
            ...(riskType ? { risk_type: riskType } : {}) }
        : { kind }),
      ...(effectiveDept !== undefined ? { department_id: effectiveDept } : {}),
    }),
    onSuccess: () => {
      // The tick means "keep this wording for next time": saved after the
      // raise went through, so a refused risk never becomes a template.
      if (scoped && saveTemplate && riskType && effectiveDept !== undefined) {
        saveTemplateNow.mutate({ department_id: effectiveDept, risk_type: riskType,
          severity, note: note.trim() })
      }
      setNote(''); setAdding(false); setFailure(null); setSaveTemplate(false); setTemplateId('')
      invalidate()
    },
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

  // Who may settle a row, mirroring the backend: the author always, PM always.
  // The raising department's members only where the department really owns
  // the flag — the assessment strip (holds and risks). A scoping question's
  // attribution is a label anyone may pick; it hands the named department
  // (Sales, typically) no right to declare the point settled.
  //
  // `userId != null` matters: without it an unloaded session (userId null) and a
  // payload with a null raiser compare equal, and the control unlocks for
  // everyone. That is exactly how it went wrong in the field.
  //
  // Acting-as means being exactly that department: personal authorship steps
  // aside with the real memberships, so the simulated view never keeps the
  // admin's own requester rights.
  const actingAs = getActsAsDepartmentId() != null
  const isAuthor = (c: ChangeConcern) =>
    !actingAs && userId != null && c.raised_by === userId
  const isRaisingDept = (c: ChangeConcern) =>
    c.department_id != null && myDepartmentIds.includes(c.department_id)
  const mayClose = (c: ChangeConcern) =>
    isAuthor(c) || isPm || (scoped && isRaisingDept(c))
  const closerRule = (c: ChangeConcern) =>
    scoped && c.department_id != null
      ? t('concern.authorDeptOrPm') : t('concern.authorOrPm')

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

  // A risk raised from a checklist row says which row: the checklist is the
  // department's own list, served per department.
  const originDept = onlyDepartmentId ?? effectiveDept
  const { data: checklistDefs = [] } = useQuery({
    queryKey: ['assessment-checklist', originDept],
    queryFn: () => changesApi.assessmentChecklist(originDept as number),
    enabled: scoped && originDept != null
      && concerns.some((c: ChangeConcern) => !!c.checklist_key),
  })
  const originLabel = (key: string) => key.startsWith('free:') ? key.slice(5)
    : checklistDefs.find((d) => d.key === key)?.label_en ?? key

  // A risk raised by mistake: its raiser may delete it while nothing hangs off
  // it yet. Acting-as does not matter here — the raise carried their own id.
  const [retracting, setRetracting] = useState<number | null>(null)
  const mayRetract = (c: ChangeConcern) =>
    c.kind === 'risk' && c.is_open && userId != null && c.raised_by === userId
    && !c.answered_at && docsOf(c.id).length === 0
  const retract = useMutation({
    mutationFn: (concernId: number) => changesApi.retractConcern(changeId, concernId),
    onSuccess: () => { setRetracting(null); setFailure(null); invalidate() },
    onError: (e: unknown) => {
      const detail = errDetail(e) ?? 'Could not delete the risk'
      setFailure(detail)
      toast.error(detail)
    },
  })

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
  // Only the legacy flags obstruct anything. Risks are counted and shown, but the
  // card must not dress them up as a blockade — they never were one.
  const blocking = open.filter((c: ChangeConcern) => c.kind !== 'risk')
  const openRisks = open.filter((c: ChangeConcern) => c.kind === 'risk')

  return (
    <div className={`rounded-lg border p-3 space-y-2 ${
      blocking.length > 0 ? 'border-amber-700/60 bg-amber-950/20' : 'border-slate-700 bg-slate-800'}`}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-medium text-slate-100">{w.title}</span>
        {blocking.length > 0 && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-amber-900 text-amber-100">
            {t('concern.blocking').replace('{n}', String(blocking.length))}
          </span>
        )}
        {openRisks.length > 0 && (
          <span data-testid="risk-open-count" title={t('risk.open')}
            className="text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-200">
            {t('risk.openCount').replace('{n}', String(openRisks.length))}
          </span>
        )}
        {editable && !adding && (
          <button className="ml-auto text-xs text-sky-300 hover:text-sky-200"
            onClick={() => { setFailure(null); setAdding(true) }}>
            + {scoped ? t('risk.raiseOffChecklist') : w.raise}</button>
        )}
      </div>

      {scoped && <p className="text-[11px] text-slate-500">{w.hint}</p>}

      {open.length === 0 && settled.length === 0 && (
        <p className="text-xs text-slate-500">{t('concern.none')}</p>
      )}

      <ul className="space-y-1">
        {[...open, ...settled].map((c: ChangeConcern) => (
          <li key={c.id} id={`concern-card-${c.id}`}
            className={`flex items-start gap-2 text-sm rounded border px-2 py-1.5 ${
              c.is_open ? KIND_STYLE[c.kind] : 'border-slate-700 bg-slate-900/40 text-slate-500'}`}>
            {/* A risk reads as "how bad / what kind"; a legacy flag keeps the
                wording it was raised under. */}
            {c.kind === 'risk' ? (
              <span className="flex items-center gap-1.5 flex-shrink-0 mt-0.5">
                <SeverityBadge value={c.severity} testId={`risk-severity-${c.id}`} />
                <span className="text-xs font-semibold" data-testid={`risk-type-${c.id}`}>
                  {riskTypeLabel(c.risk_type)}
                </span>
              </span>
            ) : (
              <span className="text-xs font-semibold flex-shrink-0 mt-0.5">
                {w.kindOf(c.kind)}
              </span>
            )}
            <span className="min-w-0 flex-1">
              {c.department_id != null && (
                <span className="mr-1.5 rounded bg-slate-800/80 px-1 py-0 text-[10px] leading-tight align-middle">
                  {deptName(c.department_id)}
                </span>
              )}
              {c.checklist_key && (
                <span data-testid={`risk-origin-${c.id}`}
                  className="mr-1.5 rounded border border-slate-600 px-1 py-0 text-[10px] leading-tight align-middle">
                  {t('risk.from')}: {originLabel(c.checklist_key)}
                </span>
              )}
              <span className={c.is_open ? '' : 'line-through'}>{c.note}</span>
              <span className="block text-xs opacity-70">
                {c.raised_by_name ?? `#${c.raised_by}`}
                {/* The raiser's role next to their name — who objects is read
                    with the hat they wear. */}
                {(c.raised_by_departments?.length ?? 0) > 0
                  && ` (${c.raised_by_departments!.join(', ')})`}
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
                      placeholder={c.kind === 'risk' ? t('risk.resolutionPlaceholder')
                        : answering ? t('concern.answerPlaceholder') : t('concern.resolution')}
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
            {/* Its author may drop it; PM or the raising department may settle
                it. Anyone else sees the control greyed with the rule, never a
                vanished button or a late 403. Admin is no exception. */}
            {editable && mayRetract(c) && withdrawing !== c.id && (retracting === c.id ? (
              <span className="flex items-center gap-2 flex-shrink-0 text-xs">
                <span className="text-slate-300">{t('risk.retractConfirm')}</span>
                <button data-testid={`concern-retract-confirm-${c.id}`}
                  className="bg-red-700 hover:bg-red-600 text-white px-2 py-0.5 rounded disabled:opacity-50"
                  disabled={retract.isPending}
                  onClick={() => retract.mutate(c.id)}>{t('risk.retractYes')}</button>
                <button className="text-slate-400 hover:text-slate-200"
                  onClick={() => setRetracting(null)}>{t('common.cancel')}</button>
              </span>
            ) : (
              <button data-testid={`concern-retract-${c.id}`}
                className="text-xs text-red-300/80 hover:text-red-200 flex-shrink-0"
                onClick={() => setRetracting(c.id)}>
                {t('risk.retract')}
              </button>
            ))}
            {c.is_open && editable && withdrawing !== c.id && retracting !== c.id && (
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

      {/* Two forms for two phases. Scoping: a question or a cancel vote, with
          the department as optional attribution. Assessment: a typed, rated
          risk for the raiser's own department. */}
      {adding && !scoped && (
        <div className="flex gap-2 items-start flex-wrap" data-testid="concern-form">
          <select value={kind} aria-label={t('concern.kind')}
            onChange={(e) => setKind(e.target.value as Exclude<ConcernKind, 'risk'>)}
            className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100">
            <option value="needs_info">{t('concern.wantsInfo')}</option>
            <option value="reject_proposal">{t('concern.wouldReject')}</option>
          </select>
          {onlyDepartmentId === undefined && options.length > 0 && (
            <select value={effectiveDept ?? ''} aria-label={t('concern.department')}
              onChange={(e) => setDeptId(e.target.value ? Number(e.target.value) : undefined)}
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100">
              <option value="">{t('concern.team')}</option>
              {options.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          )}
          <input value={note} onChange={(e) => setNote(e.target.value)}
            placeholder={t('concern.notePlaceholder')} aria-label={t('concern.note')}
            className="flex-1 min-w-[12rem] bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
          <button className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50"
            disabled={!note.trim() || raise.isPending}
            onClick={() => raise.mutate()}>{w.raise}</button>
          <button className="text-xs text-slate-400 hover:text-slate-200 px-1"
            onClick={() => { setAdding(false); setNote(''); setFailure(null) }}>
            {t('common.cancel')}
          </button>
        </div>
      )}
      {adding && scoped && (
        <div className="space-y-2" data-testid="risk-form">
          {effectiveDept !== undefined && templates.length > 0 && (
            <div className="flex gap-2 items-center flex-wrap">
              <select value={templateId} aria-label={t('risk.template')} data-testid="risk-template-select"
                onChange={(e) => applyTemplate(e.target.value === '' ? '' : Number(e.target.value))}
                className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100 max-w-[24rem]">
                <option value="">{t('risk.pickTemplate')}</option>
                {templates.map((x) => (
                  <option key={x.id} value={x.id}>
                    {`[${x.severity}] ${riskTypeLabel(x.risk_type)} — ${x.note}`}
                  </option>
                ))}
              </select>
              {templateId !== '' && (
                <button type="button" data-testid="risk-template-delete"
                  className="text-xs text-red-300 hover:text-red-200 underline decoration-dotted disabled:opacity-50"
                  title={t('risk.templateHint')}
                  disabled={deleteTemplate.isPending}
                  onClick={() => deleteTemplate.mutate(templateId as number)}>
                  {t('risk.deleteTemplate')}
                </button>
              )}
            </div>
          )}
          <div className="flex gap-2 items-center flex-wrap">
            <select value={newType !== null ? ADD_TYPE : riskType}
              aria-label={t('risk.type')} data-testid="risk-type-select"
              onChange={(e) => {
                // While the name field is open the dropdown reads "add own
                // type"; choosing anything else closes the field again.
                if (e.target.value === ADD_TYPE) { setNewType(''); return }
                setNewType(null)
                setRiskType(e.target.value as RiskType | '')
              }}
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100">
              <option value="">{t('risk.pickType')}</option>
              {riskTypeOptions.map((k) => (
                <option key={k} value={k}>{riskTypeLabel(k)}</option>
              ))}
              {effectiveDept !== undefined && (
                <option value={ADD_TYPE}>{t('risk.addType')}</option>
              )}
            </select>
            {riskType && customIdOf(riskType) != null && (
              <button type="button" data-testid="risk-type-delete"
                className="text-[11px] text-red-300 hover:text-red-200 underline decoration-dotted disabled:opacity-50"
                title={t('risk.templateHint')} disabled={deleteType.isPending}
                onClick={() => deleteType.mutate(customIdOf(riskType) as number)}>
                {t('risk.deleteType')}
              </button>
            )}
            {newType !== null && (
              <span className="flex items-center gap-1">
                <input value={newType} autoFocus data-testid="risk-new-type"
                  aria-label={t('risk.newTypeLabel')} placeholder={t('risk.newTypeLabel')}
                  onChange={(e) => setNewType(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && newType.trim()) createType.mutate(newType.trim())
                    if (e.key === 'Escape') setNewType(null)
                  }}
                  className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100 w-44" />
                <button type="button" data-testid="risk-new-type-save"
                  className="bg-sky-600 hover:bg-sky-500 text-white px-2 py-1 rounded text-xs disabled:opacity-50"
                  disabled={!newType.trim() || createType.isPending}
                  onClick={() => createType.mutate(newType.trim())}>{t('risk.saveType')}</button>
                <button type="button" className="text-xs text-slate-400 hover:text-slate-200 px-1"
                  onClick={() => setNewType(null)}>{t('common.cancel')}</button>
              </span>
            )}
            {onlyDepartmentId === undefined && (
              <select value={effectiveDept ?? ''} aria-label={t('concern.department')}
                onChange={(e) => setDeptId(e.target.value ? Number(e.target.value) : undefined)}
                className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100">
                {effectiveDept === undefined
                  && <option value="">{t('concern.pickDepartment')}</option>}
                {options.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            )}
            {/* Three buttons, not a dropdown: the weight of the choice should be
                visible on the card without opening anything. */}
            <span className="flex items-center gap-1" role="group" aria-label={t('risk.severity')}>
              <span className="text-[11px] text-slate-500 mr-0.5">{t('risk.severity')}</span>
              {SEVERITIES.map((s) => (
                <button key={s} type="button" data-testid={`risk-severity-pick-${s}`}
                  aria-pressed={severity === s} title={t('risk.severityHint')}
                  onClick={() => setSeverity(s)}
                  className={`w-7 h-6 rounded border text-xs font-semibold ${
                    severity === s ? SEVERITY_STYLE[s]
                      : 'border-slate-600 bg-slate-900 text-slate-400 hover:text-slate-200'}`}>
                  {s}
                </button>
              ))}
            </span>
          </div>
          <textarea value={note} rows={2} onChange={(e) => setNote(e.target.value)}
            placeholder={t('risk.notePlaceholder')} aria-label={t('risk.note')}
            data-testid="risk-note"
            className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
          <div className="flex gap-2 items-center">
            <button data-testid="risk-submit"
              className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={!note.trim() || !riskType || raise.isPending
                || effectiveDept === undefined}
              onClick={() => raise.mutate()}>{w.raise}</button>
            <button className="text-xs text-slate-400 hover:text-slate-200 px-1"
              onClick={() => { setAdding(false); setNote(''); setFailure(null); setSaveTemplate(false); setTemplateId('') }}>
              {t('common.cancel')}
            </button>
            {effectiveDept !== undefined && (
              <label className="flex items-center gap-1.5 text-[11px] text-slate-400 cursor-pointer ml-auto"
                title={t('risk.templateHint')}>
                <input type="checkbox" data-testid="risk-save-template"
                  checked={saveTemplate} onChange={(e) => setSaveTemplate(e.target.checked)} />
                {t('risk.saveAsTemplate')}
              </label>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
