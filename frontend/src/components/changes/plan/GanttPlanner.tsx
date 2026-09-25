/**
 * The change plan (spec 2026-09-25 §4, §9, §11): the ECR adapter around the
 * generic Gantt in `components/gantt`.
 *
 * It fetches `['change', id, 'plan', plan]`, maps PlanOut to the generic
 * model, and persists every ChangeSet the Gantt emits: through the atomic
 * `POST /plan/changes` when the server has migration 088 (detected by `links`
 * in PlanOut), else as the older REST calls (finish-to-start links only).
 * Saves of one plan run one at a time, also across components; a failed save
 * refetches the plan (the Gantt rolls its optimistic view back).
 *
 * ECR rules kept here: after "Timing validated" only dates (with a reason,
 * successors carried along) and notes change; the seed, buffer and bank build
 * presets; the validation strip; exports and import via the backend.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { planApi } from '../../../api/changePlan'
import { useDepartments } from '../../../hooks/queries/useWorkflows'
import type { PlanOut, TaskOut, TaskPatch } from '../../../types/changePlan'
import { Gantt, type GanttHandle } from '../../gantt/Gantt'
import type { GanttMarker } from '../../gantt/GanttChart'
import type { ColumnKey, GanttColumn } from '../../gantt/columns'
import { autoSchedulePatches } from '../../gantt/engine/schedule'
import { endOf, fmtShort, makeCal, normStart, toDay } from '../../gantt/engine/calendar'
import { buildTree, key, rowNumbers } from '../../gantt/engine/tree'
import type { ApplyResult, ChangeSet, GanttId, GanttModel, GanttTask } from '../../gantt/engine/types'
import ConfirmDialog from './ConfirmDialog'
import DeviationDialog, { type MovedTask } from './DeviationDialog'
import PlanToolbar, { btn, btnPrimary, type AlignAction } from './GanttToolbar'
import TaskEditor from './TaskEditor'
import ValidationList from './ValidationList'
import {
  bankBuildChangeSet, bufferChangeSet, matchSelection, runParallel, snapToLinks, withSuccessorMoves,
} from './ecrActions'
import {
  ECR_KINDS, SERVER_SLACK, hasDateChanges, persistLegacy, planToModel, serialized, toLegacyCalls, toPlanChangeSet,
  translateIdMap,
} from './ecrAdapter'
import { deadlineColor } from './ganttMath'

export interface GanttPlannerProps {
  changeId: number
  plan: 'quote' | 'detailed'
  /** track: baseline ghosts + progress editing */
  mode?: 'plan' | 'track'
  /** read-only small view (offer preview) */
  compact?: boolean
  onPlanChange?: (p: PlanOut) => void
  /** Hide the seed buttons (the host offers its own). */
  hideSeed?: boolean
  /** CSS height of the chart area. */
  height?: number | string
}

const errDetail = (e: unknown): string | undefined => {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map((x) => (x as { msg?: string })?.msg ?? String(x)).join('; ')
  if (d && typeof d === 'object' && 'message' in d) return String((d as { message: unknown }).message)
  if (e instanceof Error && e.message) return e.message
  return undefined
}

interface ReasonAsk { cs: ChangeSet; changed: MovedTask[]; moved: MovedTask[]; resolve: (cs: ChangeSet | null) => void }
interface ConfirmState { title: string; body?: string; label: string; danger?: boolean; run: () => void }

export default function GanttPlanner({
  changeId, plan, mode = 'plan', compact = false, onPlanChange, hideSeed = false, height,
}: GanttPlannerProps) {
  const qc = useQueryClient()
  const queryKey = useMemo(() => ['change', changeId, 'plan', plan], [changeId, plan])
  // Each save bumps this. A GET that started before a save answered carries
  // the old plan: the cache (the save's answer) wins over it.
  const saveGen = useRef(0)
  const { data, isLoading, isError } = useQuery({
    queryKey,
    queryFn: async () => {
      const gen = saveGen.current
      const out = await planApi.get(changeId, plan)
      const cached = qc.getQueryData<PlanOut>(queryKey)
      return gen !== saveGen.current && cached ? cached : out
    },
  })
  const { data: deptData } = useDepartments()
  const departments = useMemo(
    () => (deptData ?? []).filter((d) => d.is_active !== false).map((d) => ({ id: d.id, name: d.name })),
    [deptData])
  const onPlanChangeRef = useRef(onPlanChange)
  onPlanChangeRef.current = onPlanChange
  useEffect(() => { if (data) onPlanChangeRef.current?.(data) }, [data])

  const ganttRef = useRef<GanttHandle>(null)
  const track = mode === 'track'
  const [groupByLane, setGroupByLane] = useState(true)
  const [selection, setSelection] = useState<GanttId[]>([])
  const [editorId, setEditorId] = useState<number | null>(null)
  const [showIssues, setShowIssues] = useState(false)
  const [confirm, setConfirm] = useState<ConfirmState | null>(null)
  const [reasonAsk, setReasonAsk] = useState<ReasonAsk | null>(null)
  const [busy, setBusy] = useState(false)
  const [blank, setBlank] = useState(false)
  const [importWarnings, setImportWarnings] = useState<string[]>([])

  const model = useMemo(() => (data ? planToModel(data) : null), [data])
  const modern = !!model?.support.modern
  const baselineSet = !!data?.baseline_set
  const canEdit = !compact && !!data?.can_edit
  const canStructure = canEdit && !baselineSet
  const canDates = !compact && !!data?.can_edit_dates
  const progressDepts = data?.progress_department_ids
  const summaryIds = useMemo(() => new Set((data?.tasks ?? []).filter((t) => t.is_summary).map((t) => t.id)), [data])
  const byId = useMemo(() => new Map((data?.tasks ?? []).map((t) => [t.id, t])), [data])

  // Progress (backend `_may_progress`): detailed plan, in implementation (the
  // server fills progress_department_ids only then), a date editor or a member
  // of the task's department.
  const canProgressOn = useCallback((deptId: number | null | undefined) => !compact && track && plan === 'detailed'
    // An editor may report once the baseline is set (the server checks the status too);
    // a department member while the server lists the department.
    && ((canDates && baselineSet) || (deptId != null && (progressDepts ?? []).includes(deptId))),
  [compact, track, plan, canDates, baselineSet, progressDepts])

  const rights = useMemo(() => ({
    structure: canStructure,
    dates: canDates,
    links: canStructure,
    field: (t: GanttTask, f: string) => {
      if (compact) return false
      switch (f) {
        case 'start': case 'duration': return canDates
        case 'notes': return canEdit || canDates
        case 'progress': return canProgressOn(t.meta?.department_id as number | null | undefined)
        default: return canStructure // name, lane, kind, isIdea, constraint, links
      }
    },
  }), [compact, canStructure, canDates, canEdit, canProgressOn])

  // ---------------------------------------------------------------- persistence
  // The server's plan as of the last answer: the "before" of the next save (saves are serialized).
  const serverRef = useRef<PlanOut | null>(null)
  useEffect(() => { if (data) serverRef.current = data }, [data])
  const afterSave = useCallback((out: PlanOut | null) => {
    saveGen.current += 1
    if (out) { serverRef.current = out; qc.setQueryData(queryKey, out) }
    qc.invalidateQueries({ queryKey: ['change', changeId, 'plan-feedback'] })
    qc.invalidateQueries({ queryKey: ['change', changeId, 'plan-deviations'] })
    qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
    if (plan === 'quote') qc.invalidateQueries({ queryKey: ['change', changeId, 'offers'] })
  }, [qc, queryKey, changeId, plan])

  const onChange = useCallback((cs: ChangeSet): Promise<ApplyResult> => serialized(`${changeId}:${plan}`, async () => {
    const reason = typeof cs.meta?.reason === 'string' ? cs.meta.reason : undefined
    // A refetch in flight would answer with the plan before this save.
    await qc.cancelQueries({ queryKey })
    // Not the Gantt's view: that already shows this ChangeSet (optimistic).
    const server = serverRef.current ? planToModel(serverRef.current) : model
    const before: GanttModel = { tasks: server?.tasks ?? [], links: server?.links ?? [] }
    try {
      if (modern) {
        const body = toPlanChangeSet(cs, before)
        // Nothing the server knows is left (e.g. it only touched a task whose create was refused).
        if (!body.tasks_upsert.length && !body.tasks_delete.length && !body.links_upsert.length && !body.links_delete.length) return {}
        const out = await planApi.applyChanges(changeId, plan, body, reason)
        afterSave(out)
        // Task and link ids are separate spaces: never merge the two maps.
        return { idMap: translateIdMap(out.id_map), linkIdMap: translateIdMap(out.link_id_map) }
      }
      const calls = toLegacyCalls(cs, plan, before.tasks, before.links, reason)
      const { plan: out, idMap } = await persistLegacy(calls, {
        createTask: (b) => planApi.createTask(changeId, b),
        patchTask: (id, b) => planApi.patchTask(changeId, id, b),
        bulkPatch: (u, r) => planApi.bulkPatch(changeId, plan, u, r),
        deleteTask: (id) => planApi.deleteTask(changeId, id),
      }, before.tasks.map((t) => t.id).filter((x): x is number => typeof x === 'number'))
      afterSave(out)
      return { idMap }
    } catch (e) {
      // Part of a multi-call save may have landed: the server copy is the truth.
      qc.invalidateQueries({ queryKey })
      throw e
    }
  }), [changeId, plan, modern, model, afterSave, qc, queryKey])

  /** After the baseline, a date change needs a reason and carries its successors. */
  const beforeChange = useCallback((cs: ChangeSet, m: GanttModel): Promise<ChangeSet | null> | ChangeSet => {
    if (!baselineSet || !hasDateChanges(cs)) return cs
    const { cs: full, moved } = withSuccessorMoves({ tasks: m.tasks, links: m.links, calendar: model?.calendar }, cs)
    const cal = makeCal(model?.calendar)
    const byKey = new Map(m.tasks.map((t) => [key(t.id), t]))
    const changed: MovedTask[] = (cs.updateTasks ?? []).filter((u) => 'start' in u.patch || 'duration' in u.patch).map((u) => {
      const t = byKey.get(key(u.id))!
      const s0 = normStart(cal, toDay(t.start))
      const e0 = endOf(cal, s0, t.duration)
      const s1 = normStart(cal, toDay(u.patch.start ?? t.start))
      const e1 = endOf(cal, s1, u.patch.duration ?? t.duration)
      // Slip in the plan calendar's units (working days in working mode).
      return { id: t.id, name: t.name, from: t.start, to: u.patch.start ?? t.start, days: cal.idx(e1) - cal.idx(e0) }
    })
    return new Promise((resolve) => setReasonAsk({ cs: full, changed, moved, resolve }))
  }, [baselineSet, model])

  const apply = (cs: ChangeSet | null) => {
    if (!cs) { toast.info?.('Nothing to change'); return }
    void ganttRef.current?.apply(cs)
  }

  // ---------------------------------------------------------------- selection + editor
  const onSelectionChange = useCallback((ids: GanttId[]) => {
    setSelection(ids)
    setEditorId((cur) => {
      if (cur == null) return cur
      if (ids.length > 1) return null
      if (ids.length === 1 && typeof ids[0] === 'number' && ids[0] !== cur) return ids[0]
      return cur
    })
  }, [])
  useEffect(() => { if (editorId != null && !byId.has(editorId)) setEditorId(null) }, [byId, editorId])

  const saveFromEditor = (t: TaskOut, patch: TaskPatch) => {
    const g: Partial<GanttTask> = {}
    if (patch.name !== undefined) g.name = patch.name
    if (patch.kind !== undefined) g.kind = patch.kind
    if (patch.lane !== undefined) g.lane = patch.lane
    if (patch.start_date !== undefined) g.start = patch.start_date
    if (patch.duration_days !== undefined) g.duration = patch.duration_days
    if (patch.is_idea !== undefined) g.isIdea = patch.is_idea
    if (patch.notes !== undefined) g.notes = patch.notes
    if (patch.progress_pct !== undefined) g.progress = patch.progress_pct
    if (patch.actual_start !== undefined) g.actualStart = patch.actual_start
    if (patch.actual_finish !== undefined) g.actualEnd = patch.actual_finish
    if (patch.department_id !== undefined) g.meta = { ...(model?.tasks.find((x) => x.id === t.id)?.meta ?? {}), department_id: patch.department_id }
    const cs: ChangeSet = { label: 'Edit task', updateTasks: Object.keys(g).length ? [{ id: t.id, patch: g }] : [] }
    if (patch.predecessors) {
      const links = ganttRef.current?.getModel().links ?? model?.links ?? []
      const into = links.filter((l) => l.to === t.id)
      const want = new Set(patch.predecessors)
      cs.removeLinks = into.filter((l) => typeof l.from === 'number' && !want.has(l.from)).map((l) => l.id)
      cs.addLinks = [...want].filter((pid) => !into.some((l) => l.from === pid))
        .map((pid) => ({ id: `link-${t.id}-${pid}-${Date.now()}`, from: pid, to: t.id, type: 'FS' as const, lagDays: 0 }))
    }
    apply(cs)
  }

  // ---------------------------------------------------------------- server actions
  const runServer = async (fn: () => Promise<PlanOut & { import_warnings?: string[] }>, done?: string) => {
    setBusy(true)
    try {
      await qc.cancelQueries({ queryKey })
      const out = await serialized(`${changeId}:${plan}`, fn)
      afterSave(out)
      const warnings = out.import_warnings ?? []
      if (warnings.length) {
        setImportWarnings(warnings)
        toast.warning?.(`${done ?? 'Done'}, ${warnings.length} note${warnings.length === 1 ? '' : 's'}: see the list under the chart`)
      } else if (done) toast.success?.(done)
    } catch (e) {
      toast.error(errDetail(e) ?? 'Could not save the plan')
      qc.invalidateQueries({ queryKey })
    } finally { setBusy(false) }
  }
  const seed = (replace: boolean) => {
    const go = () => void runServer(() => planApi.seed(changeId, plan, replace))
    if (!replace) { go(); return }
    setConfirm({
      title: 'Replace the plan?',
      body: plan === 'quote'
        ? 'Every task is replaced by a new plan generated from the costing lead times.'
        : 'Every task is replaced by a copy of the quote plan. Team confirmations go stale.',
      label: 'Replace plan', danger: true, run: go,
    })
  }
  const importFile = (file: File) => {
    const hasTasks = (data?.tasks.length ?? 0) > 0
    const go = (replace: boolean) => void runServer(() => planApi.importXml(changeId, plan, file, replace), 'Plan imported')
    if (!hasTasks) { go(false); return }
    setConfirm({
      title: 'Import and replace the plan?',
      body: `Every task of this plan is replaced by the tasks in ${file.name}.`,
      label: 'Import and replace', danger: true, run: () => go(true),
    })
  }
  /** After the baseline the server's forward pass records deviations: preview and ask why first. */
  const scheduleWithReason = () => {
    const m = ganttRef.current?.getModel() ?? { tasks: model?.tasks ?? [], links: model?.links ?? [] }
    const cal = makeCal(model?.calendar)
    const moves = autoSchedulePatches(m.tasks, m.links, model?.calendar)
    if (!moves.length) { toast.info?.('Every task already starts after its predecessors'); return }
    const byK = new Map(m.tasks.map((t) => [key(t.id), t]))
    const changed: MovedTask[] = moves.map((mv) => {
      const t = byK.get(key(mv.id))!
      return { id: t.id, name: t.name, from: t.start, to: mv.patch.start, days: cal.idx(toDay(mv.patch.start)) - cal.idx(normStart(cal, toDay(t.start))) }
    })
    setReasonAsk({
      cs: { label: 'Auto-schedule' }, changed, moved: [],
      resolve: (r) => {
        const reason = typeof r?.meta?.reason === 'string' ? r.meta.reason : null
        if (reason) void runServer(() => planApi.schedule(changeId, plan, reason))
      },
    })
  }
  const exportPlan = (fmt: 'mspdi' | 'csv') => {
    const p = fmt === 'mspdi' ? planApi.exportXml(changeId, plan) : planApi.exportCsv(changeId, plan)
    p.catch((e: unknown) => toast.error(errDetail(e) ?? 'Export failed'))
  }

  const ctx = () => {
    const m = ganttRef.current?.getModel() ?? { tasks: model?.tasks ?? [], links: model?.links ?? [] }
    return { tasks: buildTree(m.tasks).order, links: m.links, calendar: model?.calendar }
  }
  const align = (a: AlignAction) => {
    const c = ctx()
    apply(a === 'snap' ? snapToLinks(c, selection) : a === 'parallel' ? runParallel(c, selection)
      : matchSelection(c, selection, a === 'match_start' ? 'start' : 'end'))
  }
  const addBuffer = () => apply(bufferChangeSet(ctx(), selection, 5))
  const addBankBuild = () => {
    const sched = departments.find((d) => d.name === 'Scheduling')
    apply(bankBuildChangeSet(ctx(), selection, { lane: 'Scheduling', departmentId: sched?.id ?? null }))
  }

  const newTask = useCallback(({ after, milestone }: { after?: GanttTask; milestone: boolean }): Partial<GanttTask> => ({
    kind: milestone ? 'milestone' : 'work',
    meta: { department_id: (after?.meta?.department_id as number | null | undefined) ?? null },
  }), [])

  // ---------------------------------------------------------------- derived view
  const markers = useMemo<GanttMarker[]>(() => (data?.deadlines ?? []).map((d) => ({
    id: d.key, date: d.date, label: d.label, color: deadlineColor(d.key),
  })), [data])
  // Row numbers follow the stored order (like the Gantt's # column), not the lane view.
  const rowNo = useMemo(() => {
    if (!model) return new Map<number, number>()
    const m = new Map<number, number>()
    rowNumbers(buildTree(model.tasks)).forEach((n, k) => m.set(Number(k), n))
    return m
  }, [model])
  const columns = useMemo<(ColumnKey | GanttColumn)[]>(() => (track
    ? ['row', 'name', 'start', 'end', 'duration', 'predecessors', 'progress']
    : modern ? ['row', 'wbs', 'name', 'start', 'end', 'duration', 'predecessors', SERVER_SLACK] : ['row', 'name', 'start', 'end', 'duration', 'predecessors']), [track, modern])
  const issues = useMemo(() => (data ? [...data.validation.errors, ...data.validation.warnings.map((w) => ({ ...w, warn: true }))]
    .map((i) => ({ code: i.code, message: i.message, taskId: i.task_id, level: ('warn' in i ? 'warning' : 'error') as 'warning' | 'error' })) : []), [data])

  // Keep the "Add a task" path of the empty state: once the Gantt shows, start a draft row.
  useEffect(() => {
    if (blank && ganttRef.current) { ganttRef.current.insertTask(false); setBlank(false) }
  }, [blank])

  // ---------------------------------------------------------------- render
  if (isLoading) {
    return <div className="rounded-lg border border-slate-700 bg-slate-900 p-4 text-sm text-slate-400">Loading plan...</div>
  }
  if (isError || !data || !model) {
    return <div className="rounded-lg border border-red-900/60 bg-red-950/30 p-4 text-sm text-red-300">Could not load the plan. Reload the page to try again.</div>
  }

  const seedLabel = plan === 'quote' ? 'Seed from costing' : 'Seed from quote plan'
  const empty = data.tasks.length === 0
  if (empty && !blank) {
    return (
      <div className="rounded-lg border border-dashed border-slate-600 bg-slate-900 p-6 text-center" data-testid="gantt-empty">
        {compact ? (
          <p className="text-sm text-slate-400">No timing plan yet.</p>
        ) : canStructure ? (
          <>
            <p className="text-sm font-medium text-slate-200">No tasks in this plan yet</p>
            <p className="mx-auto mt-1 max-w-md text-xs text-slate-400">
              {plan === 'quote'
                ? 'Start from the costing: every department effort and supplier lead time becomes a block, followed by sampling, validation, customer approval and a buffer. Or add the first task yourself.'
                : 'Start from the quote plan the customer saw, then refine it with every team. Or add the first task yourself.'}
            </p>
            <div className="mt-4 flex justify-center gap-2">
              {!hideSeed && (
                <button type="button" className={btnPrimary} onClick={() => seed(false)} disabled={busy} data-testid="gantt-seed">{seedLabel}</button>
              )}
              <button type="button" className={btn} onClick={() => setBlank(true)} disabled={busy} data-testid="gantt-add-first">+ Add a task</button>
            </div>
          </>
        ) : (
          <>
            <p className="text-sm font-medium text-slate-200">No plan yet</p>
            <p className="mt-1 text-xs text-slate-400">Plan editors (PM, Sales, Scheduling, change lead) build it here. You see it as soon as it exists.</p>
          </>
        )}
      </div>
    )
  }

  const s = data.summary
  const nErr = data.validation.errors.length
  const nWarn = data.validation.warnings.length
  const cal = makeCal(model.calendar)
  // Shown from the tasks (non-idea leaves), inclusive last day; summary.finish is exclusive like end_date.
  const real = data.tasks.filter((t) => !t.is_idea && !summaryIds.has(t.id))
  const spans = real.map((t) => { const st = normStart(cal, toDay(t.start_date)); return { s: st, e: endOf(cal, st, t.duration_days), ms: t.duration_days === 0 } })
  const firstDay = spans.length ? Math.min(...spans.map((x) => x.s)) : (s.start ? toDay(s.start) : null)
  const lastDay = spans.length ? Math.max(...spans.map((x) => (x.ms ? x.s : x.e - 1))) : (s.finish ? toDay(s.finish) - 1 : null)
  const editorTask = editorId != null ? byId.get(editorId) : undefined
  const stat = (label: string, value: string, tone = 'text-slate-100') => (
    <div className="min-w-0">
      <p className="text-[10px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`truncate text-sm font-medium tabular-nums ${tone}`}>{value}</p>
    </div>
  )

  return (
    <div className="space-y-2" data-testid="gantt-planner">
      {!compact && (
        <div className="rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2" data-testid="gantt-summary">
          <div className="grid grid-cols-3 items-center gap-3 sm:grid-cols-7">
            {stat('Start', fmtShort(firstDay))}
            {stat('Finish', fmtShort(lastDay))}
            {stat('Duration', `${s.duration_days} d, ${Math.round((s.duration_days / 7) * 10) / 10} wk`)}
            {stat('Buffer', `${s.buffer_days} d`, s.buffer_days === 0 ? 'text-amber-300' : 'text-slate-100')}
            {stat('Ideas', String(s.ideas), s.ideas > 0 ? 'text-amber-300' : 'text-slate-100')}
            {stat('Critical path', `${s.critical_ids.length} task${s.critical_ids.length === 1 ? '' : 's'}`)}
            <div className="col-span-3 sm:col-span-1 sm:justify-self-end">
              <button type="button" onClick={() => setShowIssues((v) => !v)} aria-expanded={showIssues}
                data-testid="gantt-validation-pill"
                className={`whitespace-nowrap rounded-full border px-2.5 py-1 text-xs ${nErr > 0
                  ? 'border-red-700 bg-red-950/50 text-red-200'
                  : nWarn > 0 ? 'border-amber-700 bg-amber-950/40 text-amber-200'
                    : 'border-emerald-800 bg-emerald-950/40 text-emerald-200'}`}>
                {nErr + nWarn === 0 ? 'No issues' : `${nErr} error${nErr === 1 ? '' : 's'}, ${nWarn} warning${nWarn === 1 ? '' : 's'}`}
              </button>
            </div>
          </div>
          {showIssues && (
            <div className="mt-2 border-t border-slate-700 pt-2">
              <ValidationList errors={data.validation.errors} warnings={data.validation.warnings}
                rowNo={rowNo} onFocusTask={(id) => ganttRef.current?.focusTask(id)} />
            </div>
          )}
        </div>
      )}

      <Gantt ref={ganttRef} tasks={model.tasks} links={model.links} calendar={model.calendar}
        rights={rights} readOnly={compact} compact={compact}
        onChange={onChange} beforeChange={beforeChange}
        onError={(m) => toast.error(m)} onNotify={(m) => toast.info?.(m)}
        kinds={ECR_KINDS} columns={columns} markers={markers}
        showBaselines={track} showProgress={track} criticalIds={s.critical_ids}
        groupByLane={groupByLane}
        linkTypes={modern ? ['FS', 'SS', 'FF', 'SF'] : ['FS']} allowLag={modern} hierarchy={modern} constraints={modern}
        defaultZoom={compact ? 'week' : 'day'} height={height ?? (compact ? 300 : '62vh')}
        issues={issues}
        newTask={newTask}
        onTaskOpen={(t) => { if (typeof t.id === 'number') setEditorId(t.id) }}
        onSelectionChange={onSelectionChange}
        exportName={`change-${changeId}-${plan}`}
        onExport={exportPlan}
        toolbarStart={!compact ? (
          <PlanToolbar canStructure={canStructure} canDates={canDates} empty={empty}
            seedLabel={seedLabel} onSeed={canStructure && !hideSeed ? () => seed(true) : undefined}
            onBuffer={addBuffer} onBankBuild={addBankBuild}
            onSchedule={canStructure ? () => void runServer(() => planApi.schedule(changeId, plan))
              : baselineSet && canDates && modern ? scheduleWithReason : undefined}
            selectionCount={selection.length} onAlign={align}
            groupByLane={groupByLane} onGroupByLane={setGroupByLane}
            onImport={canStructure && modern ? importFile : undefined} />
        ) : undefined}
        ariaLabel={`${plan === 'quote' ? 'Quote' : 'Detailed'} plan`} />

      {!compact && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-[11px] text-slate-500" aria-label="Legend">
          {track && <span className="flex items-center gap-1.5"><span className="inline-block h-1 w-4 rounded bg-slate-400/60" />Baseline</span>}
          {track && <span className="flex items-center gap-1.5"><span className="inline-block h-1 w-3 rounded-sm bg-red-500" />Slip</span>}
          {canDates && <span>Drag bars to move, their edges to resize, the dots at the ends onto another bar to link. Double-click or Enter opens a task. Ctrl+scroll zooms, Ctrl+Z undoes.</span>}
        </div>
      )}

      {importWarnings.length > 0 && !compact && (
        <div className="rounded-lg border border-amber-800/60 bg-amber-950/30 px-3 py-2 text-xs text-amber-200" data-testid="gantt-import-warnings" role="status">
          <div className="mb-1 flex items-center">
            <span className="font-medium">The import skipped or changed {importWarnings.length} item{importWarnings.length === 1 ? '' : 's'}:</span>
            <button type="button" className="ml-auto text-amber-300 hover:text-amber-100" onClick={() => setImportWarnings([])}
              aria-label="Dismiss import notes">Dismiss</button>
          </div>
          <ul className="list-disc space-y-0.5 pl-4">{importWarnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </div>
      )}

      {editorTask && !compact && (
        <TaskEditor task={editorTask} tasks={data.tasks} rowNo={rowNo} departments={departments}
          canEdit={canStructure} canDates={canDates && !summaryIds.has(editorTask.id)}
          canProgress={canProgressOn(editorTask.department_id)}
          track={track} baselineSet={baselineSet} saving={busy}
          onSave={(patch) => saveFromEditor(editorTask, patch)}
          onDelete={canStructure ? () => setConfirm({
            title: `Delete "${editorTask.name}"?`, body: 'Links to the deleted task are removed too.', label: 'Delete', danger: true,
            run: () => { apply({ label: 'Delete task', removeTasks: [editorTask.id], removeLinks: model.links.filter((l) => l.from === editorTask.id || l.to === editorTask.id).map((l) => l.id) }); setEditorId(null) },
          }) : undefined}
          onClose={() => setEditorId(null)} />
      )}

      <ConfirmDialog open={!!confirm} title={confirm?.title ?? ''} body={confirm?.body}
        confirmLabel={confirm?.label} danger={confirm?.danger}
        onConfirm={() => confirm?.run()} onClose={() => setConfirm(null)} />

      <DeviationDialog open={!!reasonAsk} changed={reasonAsk?.changed ?? []} moved={reasonAsk?.moved ?? []}
        onSubmit={(reason) => { const r = reasonAsk; setReasonAsk(null); r?.resolve({ ...r.cs, meta: { ...(r.cs.meta ?? {}), reason } }) }}
        onClose={() => { const r = reasonAsk; setReasonAsk(null); r?.resolve(null) }} />
    </div>
  )
}

