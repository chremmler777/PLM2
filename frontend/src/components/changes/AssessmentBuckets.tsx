/**
 * The assessment tab: one bucket per routed department.
 *
 * Collapsed, a row is the status board — everyone sees who is on the hook, where
 * they stand and when it is due. Expanded, it is that department's workplace:
 * what they have to look at, their own flags, and the form that answers it.
 * A department's work never appears outside its own row, so there is exactly one
 * place to look for it.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { changesApi } from '../../api/changes'
import AssessmentSubmitForm from './AssessmentSubmitForm'
import ConcernStrip from './ConcernStrip'
import AttachmentDropzone from './AttachmentDropzone'
import { AttachmentRow } from './AttachmentRow'
import { impactedCount, impactsOf } from './departmentForms/ActivityChecklist'
import { t } from '../../i18n/cmLabels'
import type {
  Assessment, AssessmentObject, ChangeDetail, DepartmentObjects,
} from '../../types/change'

const OBJECT_ICON: Record<string, string> = {
  tool: '🛠', equipment: '⚙️', gauge: '📐', document: '📄', part: '🔩',
}

const VERDICT_ICON: Record<string, string> = {
  feasible: '✓', feasible_with_conditions: '≈', not_feasible: '✗',
}

const VERDICT_TONE: Record<string, string> = {
  feasible: 'text-emerald-300',
  feasible_with_conditions: 'text-amber-300',
  not_feasible: 'text-red-300',
}

type State = 'waiting' | 'in_work' | 'submitted' | 'waived' | 'on_hold'

const STATE_STYLE: Record<State, string> = {
  waiting: 'bg-slate-700 text-slate-300',
  in_work: 'bg-sky-900/70 text-sky-200',
  submitted: 'bg-emerald-900/70 text-emerald-200',
  waived: 'bg-slate-800 text-slate-500',
  on_hold: 'bg-amber-900/70 text-amber-200',
}

const STATE_LABEL: Record<State, string> = {
  waiting: 'bucket.waiting', in_work: 'bucket.inWork', submitted: 'bucket.submitted',
  waived: 'bucket.waived', on_hold: 'concern.onHold',
}

/**
 * A department can carry more than one assessment row — a change re-routed onto
 * a new template keeps the old template's rows alongside the new ones. The
 * bucket must bind to the row that can actually be worked: the active one, else
 * the earliest still-pending one, else the latest answer. Binding to a stale
 * row is how a department ends up staring at a bucket with no entry mask.
 */
export function pickAssessment(list: Assessment[]): Assessment | undefined {
  if (list.length <= 1) return list[0]
  const byStage = [...list].sort((a, b) => a.stage_order - b.stage_order)
  return byStage.find((a) => a.status === 'active')
    ?? byStage.find((a) => a.status !== 'waived' && (!a.verdict || a.verdict === 'pending'))
    ?? [...byStage].reverse().find((a) => a.submitted_at || (a.verdict && a.verdict !== 'pending'))
    ?? byStage[0]
}

function stateOf(a: Assessment | undefined, onHold: boolean): State {
  if (a?.status === 'waived') return 'waived'
  if (a?.submitted_at || (a?.verdict && a.verdict !== 'pending')) return 'submitted'
  if (onHold) return 'on_hold'
  if (a?.owner_id != null || a?.accepted_at) return 'in_work'
  return 'waiting'
}

function ObjectList({ objects }: { objects: AssessmentObject[] }) {
  if (objects.length === 0) {
    return <p className="text-xs text-slate-500">{t('bucket.noObjects')}</p>
  }
  // Grouped by kind: a gauge reads differently from a document, and a mixed
  // list hides that difference.
  const groups = [...new Set(objects.map((o) => o.type))]
  return (
    <div className="space-y-2">
      {groups.map((type) => (
        <div key={type}>
          <p className="text-[11px] uppercase tracking-wide text-slate-500 mb-0.5">
            {t(`objtype.${type}`)}
          </p>
          <ul className="space-y-0.5">
            {objects.filter((o) => o.type === type).map((o) => (
              <li key={`${o.type}-${o.id}`}
                className="flex items-baseline gap-2 text-sm min-w-0">
                <span aria-hidden className="flex-shrink-0">{OBJECT_ICON[o.type] ?? '•'}</span>
                <span className="font-mono text-slate-200 flex-shrink-0">{o.number}</span>
                <span className="text-slate-400 truncate">{o.name}</span>
                {o.via_part_id != null && (
                  <span className="text-[11px] text-slate-600 flex-shrink-0">
                    {t('bucket.via')} #{o.via_part_id}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

export default function AssessmentBuckets({
  change, departments, myDepartmentIds, editable, isPm = false, canSeeAll = false,
}: {
  change: ChangeDetail
  departments: { id: number; name: string; is_active?: boolean }[]
  myDepartmentIds: number[]
  /** Assessment phase: only then is there anything to submit. */
  editable: boolean
  /** Project Management may settle any department's flag. */
  isPm?: boolean
  /** PM, Sales, the change lead and admins may read any department's work. */
  canSeeAll?: boolean
}) {
  const changeId = change.id
  const [openDept, setOpenDept] = useState<number | null>(null)
  // What each open form currently says, so the evidence block can shout when the
  // verdict turns the explanation into a requirement.
  const [verdictOf, setVerdictOf] = useState<Record<number, string>>({})
  const qc = useQueryClient()
  const evidenceOf = (assessmentId?: number) =>
    assessmentId == null ? []
      : (change.attachments ?? []).filter((a) => a.assessment_id === assessmentId)

  const { data: routing } = useQuery({
    queryKey: ['change-routing', changeId],
    queryFn: () => changesApi.getRouting(changeId),
  })
  const { data: objectData } = useQuery({
    queryKey: ['change-assessment-objects', changeId],
    queryFn: () => changesApi.assessmentObjects(changeId),
  })

  const deptName = (id: number) =>
    departments.find((d) => d.id === id)?.name ?? `#${id}`
  const objectsOf = (id: number): AssessmentObject[] =>
    (objectData?.departments ?? []).find((d: DepartmentObjects) => d.department_id === id)
      ?.objects ?? []

  // Routing says who is on the hook; the assessment rows carry their answers.
  // Either source alone can name a department, so both feed the list.
  const routed = (routing?.stages ?? []).flatMap((s) =>
    s.departments.map((d) => ({
      department_id: d.department_id, rasic: d.rasic_letter, stage: s.stage_order,
    })))
  const ids = [...new Set([
    ...routed.map((r) => r.department_id),
    ...change.assessments.map((a) => a.department_id),
  ])]
  // One bucket per department, whatever the routing history left behind.
  const rows = ids.map((id) => {
    const mine = change.assessments.filter((x) => x.department_id === id)
    const a = pickAssessment(mine)
    const r = routed.find((x) => x.department_id === id)
    return {
      id,
      assessment: a,
      rasic: a?.rasic_letter ?? r?.rasic ?? null,
      stage: a?.stage_order ?? r?.stage ?? 0,
      stale: Math.max(0, mine.length - 1),
      onHold: change.blocked_department_ids?.includes(id) ?? false,
    }
  }).sort((x, y) => x.stage - y.stage || deptName(x.id).localeCompare(deptName(y.id)))

  if (rows.length === 0) {
    return <p className="text-sm text-slate-400">{t('bucket.none')}</p>
  }

  return (
    <div className="space-y-2">
      {rows.map((row) => {
        const a = row.assessment
        const state = stateOf(a, row.onHold)
        const isMine = myDepartmentIds.includes(row.id)
        // Another department's answers are theirs; ordinary members see the
        // status board only. The overview belongs to PM/Sales/lead/admin.
        const mayOpen = isMine || canSeeAll
        const expanded = mayOpen && openDept === row.id
        const areas = impactedCount(a?.details)
        const canSubmit = isMine && editable && a?.status === 'active'
        return (
          <section key={row.id} data-testid={`bucket-${row.id}`}
            className={`rounded-lg border ${
              expanded ? 'border-slate-600 bg-slate-800' : 'border-slate-700 bg-slate-800/50'}`}>
            <button type="button" data-testid={`bucket-toggle-${row.id}`}
              aria-expanded={expanded}
              disabled={!mayOpen}
              title={mayOpen ? (expanded ? t('bucket.collapse') : t('bucket.expand'))
                : t('bucket.othersHidden')}
              onClick={() => { if (mayOpen) setOpenDept(expanded ? null : row.id) }}
              className="w-full flex items-center gap-3 px-3 py-2 text-left disabled:cursor-default">
              <span aria-hidden className="text-slate-500 text-xs w-3 flex-shrink-0">
                {mayOpen ? (expanded ? '▾' : '▸') : ''}
              </span>
              {row.rasic && (
                <span className="rounded border border-slate-600 px-1.5 py-0 text-[10px] leading-tight text-slate-300 flex-shrink-0">
                  {row.rasic}
                </span>
              )}
              <span className="text-slate-100 font-medium truncate">{deptName(row.id)}</span>
              <span data-testid={`bucket-state-${row.id}`}
                className={`rounded px-1.5 py-0 text-[10px] leading-tight font-medium flex-shrink-0 ${STATE_STYLE[state]}`}>
                {t(STATE_LABEL[state])}
              </span>
              {a?.verdict && a.verdict !== 'pending' && (
                <span data-testid={`bucket-verdict-${row.id}`}
                  className={`text-sm flex-shrink-0 ${VERDICT_TONE[a.verdict] ?? ''}`}
                  title={a.verdict}>
                  {VERDICT_ICON[a.verdict] ?? ''}
                </span>
              )}
              {evidenceOf(a?.id).length > 0 && (
                <span data-testid={`bucket-evidence-count-${row.id}`}
                  title={t('bucket.evidence')}
                  className="text-[10px] text-slate-400 flex-shrink-0">
                  📎 {evidenceOf(a?.id).length}
                </span>
              )}
              {row.stale > 0 && (
                <span data-testid={`bucket-stale-${row.id}`}
                  title={t('bucket.staleRowsHint')}
                  className="rounded bg-slate-700/70 text-slate-400 px-1.5 py-0 text-[10px] leading-tight flex-shrink-0">
                  +{row.stale}
                </span>
              )}
              {areas > 0 && (
                <span data-testid={`bucket-areas-${row.id}`}
                  className="rounded bg-slate-700 text-slate-300 px-1.5 py-0 text-[10px] leading-tight flex-shrink-0">
                  {areas === 1 ? t('check.impactedOne')
                    : t('check.impactedCount').replace('{n}', String(areas))}
                </span>
              )}
              <span className="ml-auto flex items-center gap-3 flex-shrink-0 text-xs">
                <span className="text-slate-400">{a?.owner_name ?? t('tasks.unclaimed')}</span>
                {a?.due_date && (
                  <span className={a.overdue ? 'text-red-400 font-semibold' : 'text-slate-400'}>
                    {new Date(a.due_date).toLocaleDateString()}
                    {a.overdue && ` ⚠ ${t('tasks.overdue')}`}
                  </span>
                )}
              </span>
            </button>

            {expanded && (
              <div className="border-t border-slate-700 px-3 py-3 space-y-3">
                <div>
                  <p className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">
                    {t('bucket.objects')}
                  </p>
                  <ObjectList objects={objectsOf(row.id)} />
                </div>

                {/* This department's own holds, in the room where the work happens. */}
                <ConcernStrip changeId={changeId} editable={isMine && editable}
                  scoped departments={departments} myDepartmentIds={myDepartmentIds}
                  onlyDepartmentId={row.id} isPm={isPm} />

                {a?.submitted_at || (a?.verdict && a.verdict !== 'pending') ? (
                  <div className="text-sm space-y-0.5" data-testid={`bucket-answer-${row.id}`}>
                    <p className="text-[11px] uppercase tracking-wide text-slate-500">
                      {t('bucket.answer')}
                    </p>
                    <p className={VERDICT_TONE[a!.verdict] ?? 'text-slate-200'}>{a!.verdict}</p>
                    {a!.conditions && <p className="text-slate-300">{a!.conditions}</p>}
                    {a!.notes && <p className="text-slate-400 whitespace-pre-wrap">{a!.notes}</p>}
                  </div>
                ) : canSubmit ? (
                  <AssessmentSubmitForm changeId={changeId} departmentId={row.id}
                    departmentName={deptName(row.id)} showEffort={false}
                    evidenceCount={evidenceOf(a?.id).length}
                    assessmentId={a?.id} evidence={evidenceOf(a?.id)}
                    onUploaded={() => qc.invalidateQueries({ queryKey: ['change', changeId] })}
                    onVerdictChange={(v) => setVerdictOf((m) => ({ ...m, [row.id]: v }))}
                    onDone={() => setOpenDept(null)} />
                ) : (
                  <p className="text-xs text-slate-500" data-testid={`bucket-readonly-${row.id}`}>
                    {t('bucket.readOnly')}
                  </p>
                )}
                {/* Evidence: reports and results behind the answer. Optional —
                    nothing here gates the submit. */}
                {a && (() => {
                  const required = verdictOf[row.id] === 'not_feasible'
                    && evidenceOf(a.id).length === 0
                  return (
                  <div data-testid={`bucket-evidence-${row.id}`}
                    className={`space-y-1 ${required
                      ? 'rounded border border-amber-700/60 bg-amber-950/20 p-2' : ''}`}>
                    <p className={`text-[11px] uppercase tracking-wide ${
                      required ? 'text-amber-300' : 'text-slate-500'}`}>
                      {t('bucket.evidence')}
                    </p>
                    {required && (
                      <p className="text-xs text-amber-200" data-testid={`bucket-evidence-required-${row.id}`}>
                        {t('check.evidenceRequired')}
                      </p>
                    )}
                    {evidenceOf(a.id).length > 0 && (
                      <ul className="text-sm rounded border border-slate-700/60 bg-slate-900/30 px-2 py-1">
                        {evidenceOf(a.id).map((att) => (
                          <AttachmentRow key={att.id} changeId={changeId} attachment={att} />
                        ))}
                      </ul>
                    )}
                    {isMine && editable ? (
                      <AttachmentDropzone changeId={changeId} assessmentId={a.id} compact
                        label={t('bucket.evidenceSlot')}
                        onUploaded={() => qc.invalidateQueries({ queryKey: ['change', changeId] })} />
                    ) : evidenceOf(a.id).length === 0 && (
                      <p className="text-xs text-slate-600">{t('bucket.evidenceHint')}</p>
                    )}
                  </div>
                  )
                })()}

                {/* What they ticked, for whoever may read the bucket. */}
                {impactsOf(a?.details).filter((i) => i.impacted).length > 0 && (
                  <ul className="text-xs text-slate-400 space-y-0.5"
                    data-testid={`bucket-impacts-${row.id}`}>
                    {impactsOf(a?.details).filter((i) => i.impacted).map((i) => (
                      <li key={`${i.activity_id ?? 'free'}-${i.label}`}>
                        ✓ {i.label}{i.remark ? ` — ${i.remark}` : ''}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </section>
        )
      })}
    </div>
  )
}
