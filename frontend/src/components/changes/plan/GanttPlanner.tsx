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
import type { PlanCalendar, PlanOut, TaskOut, TaskPatch } from '../../../types/changePlan'
import { Gantt, type GanttHandle } from '../../gantt/Gantt'
import type { GanttMarker } from '../../gantt/GanttChart'
import type { ColumnKey, GanttColumn } from '../../gantt/columns'
import { autoSchedulePatches } from '../../gantt/engine/schedule'
import { endOf, fmtShort, makeCal, normStart, toDay } from '../../gantt/engine/calendar'
import { buildTree, key, rowNumbers } from '../../gantt/engine/tree'
import type { ApplyResult, ChangeSet, GanttId, GanttModel, GanttTask } from '../../gantt/engine/types'
import CalendarDialog, { type CalendarSave } from '../../gantt/CalendarDialog'
import ConfirmDialog from './ConfirmDialog'
import DeviationDialog, { type MovedTask } from './DeviationDialog'
import PlanToolbar, { btn, btnPrimary, type AlignAction } from './GanttToolbar'
import TaskEditor from './TaskEditor'
import ValidationList from './ValidationList'
import {
  bankBuildChangeSet, bufferChangeSet, ideasFollow, matchSelection, runParallel, snapToLinks, withSuccessorMoves,
} from './ecrActions'
import {
  ECR_KINDS, SERVER_SLACK, planChannelName, hasDateChanges, persistLegacy, planToModel, serialized, toLegacyCalls, toPlanChangeSet,
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
  /**
   * Hide the seed button of the empty state (the host offers its own). The
   * "copy again" entry stays in the More menu on purpose (G12).
   */
  hideSeed?: boolean
  /** The change status: progress is reported only in `in_implementation` (server rule). */
  status?: string
  /** Change number for export file names (`<change_number>-<plan>.png`) and the title. */
  changeNumber?: string
  /** Rendered in its own browser window (no "Open in new window" then). */
  inWindow?: boolean
  /** Deep link: scroll to, expand the parents of, select and highlight this task once the plan is loaded. */
  focusTaskId?: number
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
  changeId, plan, mode = 'plan', compact = false, onPlanChange, hideSeed = false, height, status, changeNumber, inWindow = false, focusTaskId,
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
  // Lane grouping: remembered per plan; by default off when the plan has
  // summary tasks (grouping and an outline do not mix).
  const laneKey = `gantt-lanes-${changeId}-${plan}`
  const [lanePref, setLanePref] = useState<boolean | null>(() => {
    try { const v = localStorage.getItem(laneKey); return v == null ? null : v === '1' } catch { return null }
  })
  const setGroupByLane = (v: boolean) => {
    setLanePref(v)
    try { localStorage.setItem(laneKey, v ? '1' : '0') } catch { /* private mode: not remembered */ }
  }
  const [calendarOpen, setCalendarOpen] = useState(false)
  const [selection, setSelection] = useState<GanttId[]>([])
  const [editorId, setEditorId] = useState<number | null>(null)
  const [showIssues, setShowIssues] = useState(false)
  const [confirm, setConfirm] = useState<ConfirmState | null>(null)
  const [reasonAsk, setReasonAsk] = useState<ReasonAsk | null>(null)
  const [busy, setBusy] = useState(false)
  const [blank, setBlank] = useState(false)
  const [importWarnings, setImportWarnings] = useState<string[]>([])
  const emptyFile = useRef<HTMLInputElement>(null)

  const model = useMemo(() => (data ? planToModel(data) : null), [data])
  const modern = !!model?.support.modern
  const baselineSet = !!data?.baseline_set
  const canEdit = !compact && !!data?.can_edit
  const canStructure = canEdit && !baselineSet
  const canDates = !compact && !!data?.can_edit_dates
  const progressDepts = data?.progress_department_ids
  const summaryIds = useMemo(() => new Set((data?.tasks ?? []).filter((t) => t.is_summary).map((t) => t.id)), [data])
  const byId = useMemo(() => new Map((data?.tasks ?? []).map((t) => [t.id, t])), [data])
  const groupByLane = lanePref ?? summaryIds.size === 0
  // Automatic scheduling: successors move with every change (one undo step).
  // After the baseline the server always carries successors along.
  const autoSchedule = modern && (baselineSet || !!model?.auto)

  // Progress (backend `_may_progress`): the detailed plan while the change is in
  // implementation, by a date editor or a member of the task's department.
  // Without a status from the host, the baseline stands in for it.
  const inImplementation = status != null ? status === 'in_implementation' : baselineSet
  const canProgressOn = useCallback((deptId: number | null | undefined) => !compact && track && plan === 'detailed'
    && inImplementation
    && (canDates || (deptId != null && (progressDepts ?? []).includes(deptId))),
  [compact, track, plan, canDates, inImplementation, progressDepts])

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
  // Other windows showing this plan (the pop-out, the change page) hear about
  // every save and refetch; each window also refetches on focus.
  const channelRef = useRef<BroadcastChannel | null>(null)
  useEffect(() => {
    let ch: BroadcastChannel | null = null
    try {
      if (typeof BroadcastChannel === 'undefined') return
      ch = new BroadcastChannel(planChannelName(changeId, plan))
      ch.onmessage = (e: MessageEvent) => {
        if (e.data !== 'changed') return
        qc.invalidateQueries({ queryKey })
        qc.invalidateQueries({ queryKey: ['change', changeId, 'plan-deviations'] })
        qc.invalidateQueries({ queryKey: ['change', changeId, 'plan-feedback'] })
      }
      channelRef.current = ch
    } catch { /* no BroadcastChannel: focus refetch still keeps windows current */ }
    return () => { try { ch?.close() } catch { /* closed already */ } channelRef.current = null }
  }, [changeId, plan, qc, queryKey])
  const afterSave = useCallback((out: PlanOut | null) => {
    try { channelRef.current?.postMessage('changed') } catch { /* channel closed */ }
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
        // The server pushes successors itself (auto scheduling, or after the
        // baseline): send only the user's own changes (G3, P6).
        const body = toPlanChangeSet(cs, before, { stripDerived: autoSchedule })
        // Nothing the server knows is left (e.g. it only touched a task whose create was refused).
        if (!body.tasks_upsert.length && !body.tasks_delete.length && !body.links_upsert.length && !body.links_delete.length) return {}
        const out = await planApi.applyChanges(changeId, plan, body, reason)
        afterSave(out)
        // Task and link ids are separate spaces: never merge the two maps. The
        // server's answer is the truth: shown at once, its own pushes undoable.
        const answered = planToModel(out)
        return {
          idMap: translateIdMap(out.id_map), linkIdMap: translateIdMap(out.link_id_map),
          server: { tasks: answered.tasks, links: answered.links },
        }
      }
      const calls = toLegacyCalls(cs, plan, before.tasks, before.links, reason)
      const { plan: out, idMap } = await persistLegacy(calls, {
        createTask: (b) => planApi.createTask(changeId, b),
        patchTask: (id, b) => planApi.patchTask(changeId, id, b),
        bulkPatch: (u, r) => planApi.bulkPatch(changeId, plan, u, r),
        deleteTask: (id) => planApi.deleteTask(changeId, id),
      }, before.tasks.map((t) => t.id).filter((x): x is number => typeof x === 'number'))
      afterSave(out)
      if (!out) return { idMap }
      const answered = planToModel(out)
      return { idMap, server: { tasks: answered.tasks, links: answered.links } }
    } catch (e) {
      // Part of a multi-call save may have landed: the server copy is the truth.
      qc.invalidateQueries({ queryKey })
      throw e
    }
  }), [changeId, plan, modern, model, afterSave, qc, queryKey, autoSchedule])

  /**
   * Linked bank build ideas follow their anchor. After the baseline a date
   * change needs a reason; the preview lists the successors the move pushes
   * (already in the ChangeSet as `meta.derived`, the server makes the same moves).
   */
  const beforeChange = useCallback((cs0: ChangeSet, m: GanttModel): Promise<ChangeSet | null> | ChangeSet => {
    let cs = ideasFollow({ tasks: m.tasks, links: m.links, calendar: model?.calendar }, cs0)
    if (!baselineSet || !hasDateChanges(cs)) return cs
    let derived = new Set(Array.isArray(cs.meta?.derived) ? (cs.meta!.derived as GanttId[]).map(key) : [])
    if (!modern) {
      // An older server (no typed links) does not push: the successors move
      // here and each is recorded as a deviation with the same reason.
      const r = withSuccessorMoves({ tasks: m.tasks, links: m.links, calendar: model?.calendar }, cs)
      cs = r.cs
      derived = new Set(r.moved.map((x) => key(x.id)))
    }
    const full = cs
    const cal = makeCal(model?.calendar)
    const byKey = new Map(m.tasks.map((t) => [key(t.id), t]))
    const moved: MovedTask[] = (cs.updateTasks ?? []).filter((u) => derived.has(key(u.id)) && u.patch.start).map((u) => {
      const t = byKey.get(key(u.id))!
      return { id: t.id, name: t.name, from: t.start, to: u.patch.start!, days: cal.idx(toDay(u.patch.start!)) - cal.idx(normStart(cal, toDay(t.start))) }
    })
    const changed: MovedTask[] = (cs.updateTasks ?? []).filter((u) => !derived.has(key(u.id)) && ('start' in u.patch || 'duration' in u.patch)).map((u) => {
      const t = byKey.get(key(u.id))!
      const s0 = normStart(cal, toDay(t.start))
      const e0 = endOf(cal, s0, t.duration)
      const s1 = normStart(cal, toDay(u.patch.start ?? t.start))
      const e1 = endOf(cal, s1, u.patch.duration ?? t.duration)
      // Slip in the plan calendar's units (working days in working mode).
      return { id: t.id, name: t.name, from: t.start, to: u.patch.start ?? t.start, days: cal.idx(e1) - cal.idx(e0) }
    })
    return new Promise((resolve) => setReasonAsk({ cs: full, changed, moved, resolve }))
  }, [baselineSet, model, modern])

  const apply = (cs: ChangeSet | null) => {
    if (!cs) { toast.info?.('Nothing to change'); return }
    void ganttRef.current?.apply(cs)
  }

  // Deep link to a task: once per id, when the plan holding it is on screen.
  const plannerRef = useRef<HTMLDivElement>(null)
  const focusedRef = useRef<number | null>(null)
  useEffect(() => {
    if (focusTaskId == null || !data || focusedRef.current === focusTaskId) return
    focusedRef.current = focusTaskId
    if (!data.tasks.some((t) => t.id === focusTaskId)) { toast.info?.('The linked task is no longer in this plan'); return }
    requestAnimationFrame(() => {
      plannerRef.current?.scrollIntoView?.({ block: 'start', behavior: 'smooth' })
      ganttRef.current?.focusTask(focusTaskId)
    })
  }, [focusTaskId, data])

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
    if (patch.constraint_type !== undefined) {
      g.constraint = patch.constraint_type ? { type: patch.constraint_type, date: patch.constraint_date ?? null } : { type: 'asap', date: null }
    }
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
  const runServer = async (fn: () => Promise<PlanOut & { import_warnings?: string[] }>, done?: string): Promise<boolean> => {
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
      return true
    } catch (e) {
      toast.error(errDetail(e) ?? 'Could not save the plan')
      qc.invalidateQueries({ queryKey })
      return false
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
  /** The plan alone in its own browser window (/changes/:id/plan/:plan). */
  const openWindow = () => {
    const url = `${import.meta.env.BASE_URL ?? '/'}changes/${changeId}/plan/${plan}`.replace(/\/{2,}/g, '/')
    const w = Math.min(1600, Math.max(900, window.screen?.availWidth ? window.screen.availWidth - 80 : 1400))
    const h = Math.min(1000, Math.max(640, window.screen?.availHeight ? window.screen.availHeight - 80 : 900))
    const win = window.open(url, `plm2-plan-${changeId}-${plan}`, `popup,width=${w},height=${h}`)
    if (!win) toast.error('The browser blocked the new window: allow pop-ups for this site')
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
    const cs = bankBuildChangeSet(ctx(), selection, { lane: 'Scheduling', departmentId: sched?.id ?? null })
    if (typeof cs.meta?.warning === 'string') toast.warning?.(cs.meta.warning)
    apply(cs)
  }

  /** Plan calendar (G7, G11): mode (keep or convert durations), working days, holidays, auto scheduling. */
  const saveCalendar = (c: CalendarSave) => {
    setCalendarOpen(false)
    // Only what changed: the server keeps the other fields (a lone {auto} flips only that).
    const cur = model?.calendar
    const body: Partial<PlanCalendar> = {}
    if (c.calendar.mode !== cur?.mode) body.mode = c.calendar.mode
    if (c.calendar.workdays.join() !== [...(cur?.workdays ?? [])].sort((a, b) => a - b).join()) body.workdays = c.calendar.workdays
    if (c.calendar.holidays.join() !== [...(cur?.holidays ?? [])].sort().join()) body.holidays = c.calendar.holidays
    if (c.auto !== undefined && c.auto !== model?.auto) body.auto = c.auto
    if (!Object.keys(body).length) return
    const moves = 'mode' in body || 'workdays' in body || 'holidays' in body
    void runServer(() => planApi.setCalendar(changeId, plan, body, c.convert), 'Calendar saved').then((ok) => {
      // Old steps would replay in the old unit: start the history over on the new plan.
      if (ok && moves) { ganttRef.current?.clearHistory(); toast.info?.('Undo history cleared: calendar changed') }
    })
  }

  // `after` is the nearest leaf above the new row: its lane is kept, and its department with it.
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
  // Tracking preset (G17): planned vs baseline vs actual.
  const columns = useMemo<(ColumnKey | GanttColumn)[]>(() => (track
    // Listed by importance: narrow screens drop columns from the end.
    ? ['row', 'name', 'start', 'end', 'progress', 'variance', 'baselineEnd', 'actualStart', 'actualEnd', 'baselineStart', 'predecessors']
    : modern ? ['row', 'wbs', 'name', 'start', 'end', 'duration', 'predecessors', SERVER_SLACK] : ['row', 'name', 'start', 'end', 'duration', 'predecessors']), [track, modern])
  const issues = useMemo(() => (data ? [...data.validation.errors, ...data.validation.warnings.map((w) => ({ ...w, warn: true }))]
    .map((i) => ({ code: i.code, message: i.message, taskId: i.task_id, level: ('warn' in i ? 'warning' : 'error') as 'warning' | 'error' })) : []), [data])

  // "+ Add a task" on an empty plan: show the (empty) Gantt with a draft row and
  // stay there until tasks exist (G4); the draft is started once.
  const draftStarted = useRef(false)
  useEffect(() => {
    if (blank && ganttRef.current && !draftStarted.current) { draftStarted.current = true; ganttRef.current.insertTask(false) }
    if (!blank) draftStarted.current = false
  })
  useEffect(() => { if ((data?.tasks.length ?? 0) > 0) setBlank(false) }, [data])

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
              {modern && (
                <>
                  <button type="button" className={btn} onClick={() => emptyFile.current?.click()} disabled={busy} data-testid="gantt-import-empty">
                    Import MS Project</button>
                  <input ref={emptyFile} type="file" accept=".xml,application/xml,text/xml" className="hidden" data-testid="gantt-import-empty-file"
                    onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) importFile(f) }} />
                </>
              )}
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
  // summary.finish is the inclusive last day (backend plan_finish).
  const lastDay = spans.length ? Math.max(...spans.map((x) => (x.ms ? x.s : x.e - 1))) : (s.finish ? toDay(s.finish) : null)
  const spanWeeks = firstDay != null && lastDay != null ? Math.ceil((lastDay - firstDay + 1) / 7) : 0
  const unitLabel = cal.mode === 'working' ? 'wd' : 'd'
  const editorTask = editorId != null ? byId.get(editorId) : undefined
  const stat = (label: string, value: string, tone = 'text-slate-100') => (
    <div className="shrink-0">
      <p className="text-[10px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`whitespace-nowrap text-sm font-medium tabular-nums ${tone}`}>{value}</p>
    </div>
  )

  return (
    <div ref={plannerRef} className="space-y-2" data-testid="gantt-planner">
      {!compact && (
        <div className="rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2" data-testid="gantt-summary">
          {/* Wraps instead of squeezing: the issue pill never covers a figure on a narrow screen. */}
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            {stat('Start', fmtShort(firstDay))}
            {stat('Finish', fmtShort(lastDay))}
            {stat('Duration', `${s.duration_days} ${unitLabel} (${spanWeeks} wk)`)}
            {stat('Buffer', `${s.buffer_days} d`, s.buffer_days === 0 ? 'text-amber-300' : 'text-slate-100')}
            {stat('Ideas', String(s.ideas), s.ideas > 0 ? 'text-amber-300' : 'text-slate-100')}
            {stat('Critical path', `${s.critical_ids.length} task${s.critical_ids.length === 1 ? '' : 's'}`)}
            <div className="ml-auto">
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
        kinds={ECR_KINDS} columns={columns} markers={markers} maxGridFraction={track ? 0.6 : undefined}
        showBaselines={track} showProgress={track} criticalIds={s.critical_ids}
        groupByLane={groupByLane} autoSchedule={autoSchedule}
        linkTypes={modern ? ['FS', 'SS', 'FF', 'SF'] : ['FS']} allowLag={modern} hierarchy={modern} constraints={modern}
        defaultZoom={compact ? 'week' : 'day'} height={height ?? (compact ? 300 : '62vh')}
        issues={issues}
        newTask={newTask}
        onTaskOpen={(t) => { if (typeof t.id === 'number') setEditorId(t.id) }}
        onSelectionChange={onSelectionChange}
        exportName={`${changeNumber ?? `change-${changeId}`}-${plan}`}
        onExport={exportPlan}
        toolbarStart={!compact ? (
          <PlanToolbar canStructure={canStructure} canDates={canDates} empty={empty}
            seedLabel={plan === 'quote' ? 'Seed again from costing' : 'Copy quote plan again'}
            onSeed={canStructure ? () => seed(true) : undefined}
            onCalendar={modern ? () => setCalendarOpen(true) : undefined}
            calendarLabel={`Calendar: ${model.calendar.mode === 'working' ? 'working days' : 'calendar days'}${autoSchedule && !baselineSet ? ', auto' : ''}`}
            onBuffer={addBuffer} onBankBuild={addBankBuild}
            onSchedule={canStructure ? () => void runServer(() => planApi.schedule(changeId, plan))
              : baselineSet && canDates && modern ? scheduleWithReason : undefined}
            selectionCount={selection.length} onAlign={align}
            groupByLane={groupByLane} onGroupByLane={setGroupByLane}
            onImport={canStructure && modern ? importFile : undefined}
            onOpenWindow={inWindow ? undefined : openWindow} />
        ) : undefined}
        ariaLabel={`${plan === 'quote' ? 'Quote' : 'Detailed'} plan`}
        title={`${changeNumber ?? `Change ${changeId}`} - ${plan === 'quote' ? 'Quote plan' : 'Detailed plan'}`}
        fullScreen={!compact}
        below={compact ? undefined : (
          <>
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
              track={track} baselineSet={baselineSet} saving={busy} calendar={model.calendar}
              links={modern ? model.links : undefined} linkTypes={modern ? ['FS', 'SS', 'FF', 'SF'] : ['FS']} allowLag={modern}
              constraints={modern} isSummary={summaryIds.has(editorTask.id)} summaryIds={summaryIds}
              onLinks={(cs) => apply(cs)}
              onSave={(patch) => saveFromEditor(editorTask, patch)}
              onDelete={canStructure ? () => setConfirm({
                title: `Delete "${editorTask.name}"?`, body: 'Links to the deleted task are removed too.', label: 'Delete', danger: true,
                run: () => { apply({ label: 'Delete task', removeTasks: [editorTask.id], removeLinks: model.links.filter((l) => l.from === editorTask.id || l.to === editorTask.id).map((l) => l.id) }); setEditorId(null) },
              }) : undefined}
              onClose={() => setEditorId(null)} />
          )}

          </>
        )} />


      {calendarOpen && (
        <CalendarDialog calendar={model.calendar} tasks={model.tasks} links={model.links}
          scheduleAuto={autoSchedule} auto={modern && !baselineSet ? model.auto : undefined}
          canEdit={canStructure} saving={busy} onSave={saveCalendar} onClose={() => setCalendarOpen(false)} />
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

