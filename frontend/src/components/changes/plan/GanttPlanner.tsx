/**
 * The change plan as an MS-Project-like Gantt (spec 2026-09-25 §4, §9).
 *
 * Left: tasks grouped by swimlane. Right: the timeline. Bars move and resize
 * by drag (snapped to days), links are drawn from the dot at a bar's end onto
 * another bar, a selection moves as a block. Every change is rendered locally
 * first and then replaced by the server's PlanOut, which owns validation, the
 * summary and the critical path. After "Timing validated" a date change asks
 * for a reason and becomes a deviation.
 *
 * The component fetches its own plan (`['change', id, 'plan', plan]`) and owns
 * every plan mutation.
 */
import {
  useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState,
  type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { planApi } from '../../../api/changePlan'
import { useDepartments } from '../../../hooks/queries/useWorkflows'
import type { BulkDateUpdate, PlanOut, TaskCreate, TaskKind, TaskOut, TaskPatch } from '../../../types/changePlan'
import ReasonDialog from '../ReasonDialog'
import ConfirmDialog from './ConfirmDialog'
import { GridBody, GridHeader } from './GanttGrid'
import GanttToolbar, { btn, btnPrimary, type AddPreset, type AlignAction } from './GanttToolbar'
import { TimelineBody, TimelineHeader, type LinkPreview } from './GanttTimeline'
import TaskEditor from './TaskEditor'
import ValidationList from './ValidationList'
import {
  HEADER_H, PX_PER_DAY, ROW_H, applyDrag, deadlineColor, buildRows, createsCycle, diffUpdates, endOf,
  fmtDay, gridWidth, groupByLane, inclusiveEnd, laneOf, matchTo, rowNumbers, runParallel, snapDays,
  snapToPredecessors, taskGeo, timelineRange, toDay, toIso, todayDay, xOf, zoomStep,
  type Geo, type Zoom,
} from './ganttMath'

export interface GanttPlannerProps {
  changeId: number
  plan: 'quote' | 'detailed'
  /** track: baseline ghosts + progress editing */
  mode?: 'plan' | 'track'
  /** read-only small view (offer preview) */
  compact?: boolean
  onPlanChange?: (p: PlanOut) => void
}

const errDetail = (e: unknown): string | undefined => {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map((x) => (x as { msg?: string })?.msg ?? String(x)).join('; ')
  if (d && typeof d === 'object' && 'message' in d) return String((d as { message: unknown }).message)
  return undefined
}

interface DragState {
  mode: 'move' | 'resize'
  ids: number[]
  delta: number
}

interface PointerStart {
  kind: 'bar' | 'link'
  task: TaskOut
  mode: 'move' | 'resize'
  x0: number
  y0: number
  additive: boolean
  moved: boolean
  ids: number[]
}

interface ConfirmState { title: string; body?: string; label: string; danger?: boolean; run: () => void }
interface ReasonState { updates: BulkDateUpdate[]; links?: { id: number; predecessors: number[] }[]; patch?: { id: number; body: TaskPatch } }

export default function GanttPlanner({ changeId, plan, mode = 'plan', compact = false, onPlanChange }: GanttPlannerProps) {
  const qc = useQueryClient()
  const queryKey = useMemo(() => ['change', changeId, 'plan', plan], [changeId, plan])
  const { data, isLoading, isError } = useQuery({
    queryKey, queryFn: () => planApi.get(changeId, plan),
  })
  const { data: deptData } = useDepartments()
  const departments = useMemo(
    () => (deptData ?? []).filter((d) => d.is_active !== false).map((d) => ({ id: d.id, name: d.name })),
    [deptData])

  const onPlanChangeRef = useRef(onPlanChange)
  onPlanChangeRef.current = onPlanChange
  useEffect(() => { if (data) onPlanChangeRef.current?.(data) }, [data])

  const uid = useId().replace(/[^a-zA-Z0-9]/g, '')
  const track = mode === 'track'
  const [zoom, setZoom] = useState<Zoom>(compact ? 'week' : 'day')
  const [critical, setCritical] = useState(false)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [selection, setSelection] = useState<number[]>([])
  const [editorId, setEditorId] = useState<number | null>(null)
  const [overrides, setOverrides] = useState<Map<number, Geo>>(new Map())
  const [drag, setDrag] = useState<DragState | null>(null)
  const [nudge, setNudge] = useState<{ ids: number[]; delta: number } | null>(null)
  const [linkPreview, setLinkPreview] = useState<LinkPreview | null>(null)
  const [confirm, setConfirm] = useState<ConfirmState | null>(null)
  const [reasonFor, setReasonFor] = useState<ReasonState | null>(null)
  const [flashId, setFlashId] = useState<number | null>(null)
  const [showIssues, setShowIssues] = useState(false)

  const scrollerRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  const tasks = useMemo(() => data?.tasks ?? [], [data])
  const baselineSet = !!data?.baseline_set
  const canEdit = !compact && !!data?.can_edit
  const canDates = !compact && !!data?.can_edit_dates
  const canStructure = canEdit && !baselineSet
  const progressDepts = data?.progress_department_ids
  const canProgressOn = useCallback((t: TaskOut) => !compact && track
    && (canEdit || (t.department_id != null && (progressDepts ?? []).includes(t.department_id))),
  [compact, track, canEdit, progressDepts])

  // ---------------------------------------------------------------- geometry
  const groups = useMemo(() => groupByLane(tasks), [tasks])
  const rowNo = useMemo(() => rowNumbers(groups), [groups])
  const rows = useMemo(() => buildRows(groups, collapsed), [groups, collapsed])
  const baseGeos = useMemo(() => {
    const m = new Map(tasks.map((t) => [t.id, taskGeo(t)]))
    overrides.forEach((g, id) => { if (m.has(id)) m.set(id, g) })
    return m
  }, [tasks, overrides])
  const geos = useMemo(() => {
    let g = baseGeos
    if (drag && drag.delta !== 0) g = applyDrag(g, drag.mode, drag.ids, drag.delta)
    if (nudge && nudge.delta !== 0) g = applyDrag(g, 'move', nudge.ids, nudge.delta)
    return g
  }, [baseGeos, drag, nudge])

  const today = todayDay()
  const ppd = PX_PER_DAY[zoom]
  const deadlines = useMemo(() => data?.deadlines ?? [], [data])
  const range = useMemo(
    () => timelineRange(tasks, deadlines.map((d) => toDay(d.date)), today, zoom),
    // The range follows server data, not live drags, so the canvas does not jump.
    [tasks, deadlines, today, zoom])
  const gw = gridWidth({ compact, track })
  const timelineW = (range.to - range.from) * ppd

  const issueIds = useMemo(() => new Set(
    (data?.validation.errors ?? []).map((i) => i.task_id).filter((x): x is number => x != null)), [data])

  // ---------------------------------------------------------------- mutations
  const mut = useMutation({
    mutationFn: (fn: () => Promise<PlanOut>) => fn(),
    onSuccess: (p) => {
      qc.setQueryData(queryKey, p)
      setOverrides(new Map())
      qc.invalidateQueries({ queryKey: ['change', changeId, 'plan-feedback'] })
      qc.invalidateQueries({ queryKey: ['change', changeId, 'plan-deviations'] })
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
    },
    onError: (e: unknown) => {
      toast.error(errDetail(e) ?? 'Could not save the plan')
      setOverrides(new Map())
    },
  })
  const run = (fn: () => Promise<PlanOut>, after?: (p: PlanOut) => void) =>
    mut.mutate(fn, after ? { onSuccess: after } : undefined)

  const sendDates = (s: ReasonState, reason?: string) => run(async () => {
    let out: PlanOut | undefined
    for (const l of s.links ?? []) out = await planApi.patchTask(changeId, l.id, { predecessors: l.predecessors })
    if (s.updates.length) out = await planApi.bulkPatch(changeId, plan, s.updates, reason)
    if (s.patch) out = await planApi.patchTask(changeId, s.patch.id, { ...s.patch.body, ...(reason ? { reason } : {}) })
    return out ?? planApi.get(changeId, plan)
  })

  /** Render the new dates now, then save (asking for a reason after baseline). */
  const commitDates = (updates: BulkDateUpdate[], links?: ReasonState['links']) => {
    if (updates.length === 0 && !links?.length) return
    setOverrides((prev) => {
      const next = new Map(prev)
      for (const u of updates) {
        const t = tasks.find((x) => x.id === u.id)
        if (!t) continue
        const g = prev.get(u.id) ?? taskGeo(t)
        next.set(u.id, {
          start: u.start_date ? toDay(u.start_date) : g.start,
          dur: u.duration_days ?? g.dur,
        })
      }
      return next
    })
    const s: ReasonState = { updates, links }
    if (baselineSet && updates.length > 0) setReasonFor(s)
    else sendDates(s)
  }

  // ---------------------------------------------------------------- selection
  const selectedSet = useMemo(() => new Set(selection), [selection])
  const select = (t: TaskOut, additive: boolean, openEditor: boolean) => {
    if (additive) {
      setSelection((s) => (s.includes(t.id) ? s.filter((x) => x !== t.id) : [...s, t.id]))
      return
    }
    setSelection([t.id])
    if (openEditor) setEditorId(t.id)
  }
  const clearSelection = () => { setSelection([]); setEditorId(null) }

  // Drop selection entries whose task disappeared.
  useEffect(() => {
    const ids = new Set(tasks.map((t) => t.id))
    setSelection((s) => (s.every((x) => ids.has(x)) ? s : s.filter((x) => ids.has(x))))
    setEditorId((e) => (e != null && !ids.has(e) ? null : e))
  }, [tasks])

  // ---------------------------------------------------------------- pointer
  const latest = useRef({ geos: baseGeos, tasks, ppd, canDates, canEdit, selection })
  latest.current = { geos: baseGeos, tasks, ppd, canDates, canEdit, selection }
  const commitRef = useRef(commitDates)
  commitRef.current = commitDates
  const selectRef = useRef(select)
  selectRef.current = select
  const runRef = useRef(run)
  runRef.current = run

  const svgPoint = (clientX: number, clientY: number) => {
    const r = svgRef.current?.getBoundingClientRect()
    return { x: clientX - (r?.left ?? 0), y: clientY - (r?.top ?? 0) }
  }

  const beginPointer = (start: PointerStart) => {
    const onMove = (e: PointerEvent) => {
      const dx = e.clientX - start.x0
      if (!start.moved && Math.abs(dx) < 3 && Math.abs(e.clientY - start.y0) < 3) return
      start.moved = true
      if (start.kind === 'link') {
        const g = latest.current.geos.get(start.task.id)
        const idx = rowsRef.current.findIndex((r) => r.type === 'task' && r.task.id === start.task.id)
        if (!g || idx < 0) return
        const pt = svgPoint(e.clientX, e.clientY)
        setLinkPreview({
          x1: xOf(endOf(g), rangeRef.current, latest.current.ppd) + 6, y1: idx * ROW_H + ROW_H / 2,
          x2: pt.x, y2: pt.y,
        })
        return
      }
      if (!latest.current.canDates) return
      setDrag({ mode: start.mode, ids: start.ids, delta: snapDays(dx, latest.current.ppd) })
    }
    const onUp = (e: PointerEvent) => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
      if (start.kind === 'link') {
        setLinkPreview(null)
        if (!start.moved) return
        const el = typeof document.elementFromPoint === 'function'
          ? document.elementFromPoint(e.clientX, e.clientY) : null
        const hit = el?.closest?.('[data-task-id]')
        const toId = hit ? Number(hit.getAttribute('data-task-id')) : NaN
        addLink(start.task.id, toId)
        return
      }
      setDrag(null)
      const delta = snapDays(e.clientX - start.x0, latest.current.ppd)
      if (!start.moved || delta === 0 || !latest.current.canDates) {
        if (!start.moved) selectRef.current(start.task, start.additive, !start.additive)
        return
      }
      const next = applyDrag(latest.current.geos, start.mode, start.ids, delta)
      const only = new Map([...next].filter(([id]) => start.ids.includes(id)))
      commitRef.current(diffUpdates(latest.current.tasks, only))
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
  }

  const onBarPointerDown = (e: ReactPointerEvent, task: TaskOut, m: 'move' | 'resize') => {
    if (e.button !== 0) return
    e.stopPropagation()
    e.preventDefault()
    scrollerRef.current?.focus({ preventScroll: true })
    const additive = e.shiftKey || e.ctrlKey || e.metaKey
    const sel = latest.current.selection
    const ids = m === 'resize' ? [task.id] : (sel.includes(task.id) && sel.length > 1 ? sel : [task.id])
    beginPointer({ kind: 'bar', task, mode: m, x0: e.clientX, y0: e.clientY, additive, moved: false, ids })
  }

  const onLinkStart = (e: ReactPointerEvent, task: TaskOut) => {
    if (e.button !== 0) return
    e.stopPropagation()
    e.preventDefault()
    beginPointer({ kind: 'link', task, mode: 'move', x0: e.clientX, y0: e.clientY, additive: false, moved: false, ids: [] })
  }

  const addLink = (fromId: number, toId: number) => {
    const target = latest.current.tasks.find((t) => t.id === toId)
    if (!target || toId === fromId) return
    if (target.predecessors.includes(fromId)) { toast.info?.('These tasks are already linked'); return }
    if (createsCycle(latest.current.tasks, fromId, toId)) {
      toast.error('That link would create a loop')
      return
    }
    runRef.current(() => planApi.patchTask(changeId, toId, { predecessors: [...target.predecessors, fromId] }))
  }

  const onLinkClick = (fromId: number, toId: number) => {
    const from = tasks.find((t) => t.id === fromId)
    const to = tasks.find((t) => t.id === toId)
    if (!from || !to) return
    setConfirm({
      title: 'Remove this link?',
      body: `#${rowNo.get(toId)} ${to.name} will no longer wait for #${rowNo.get(fromId)} ${from.name}. Dates do not move.`,
      label: 'Remove link', danger: true,
      run: () => run(() => planApi.patchTask(changeId, toId, { predecessors: to.predecessors.filter((p) => p !== fromId) })),
    })
  }

  const rowsRef = useRef(rows)
  rowsRef.current = rows
  const rangeRef = useRef(range)
  rangeRef.current = range

  const onRowClick = (e: ReactMouseEvent, t: TaskOut) => {
    const additive = e.shiftKey || e.ctrlKey || e.metaKey
    select(t, additive, !additive)
  }

  // ---------------------------------------------------------------- keyboard
  const nudgeRef = useRef<{ ids: number[]; delta: number } | null>(null)
  const nudgeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const flushNudge = () => {
    const n = nudgeRef.current
    nudgeRef.current = null
    setNudge(null)
    if (!n || n.delta === 0) return
    const next = applyDrag(latest.current.geos, 'move', n.ids, n.delta)
    const only = new Map([...next].filter(([id]) => n.ids.includes(id)))
    commitRef.current(diffUpdates(latest.current.tasks, only))
  }
  const flushRef = useRef(flushNudge)
  flushRef.current = flushNudge
  useEffect(() => () => { if (nudgeTimer.current) clearTimeout(nudgeTimer.current) }, [])

  const onKeyDown = (e: ReactKeyboardEvent) => {
    if (compact) return
    const target = e.target as HTMLElement
    if (target !== scrollerRef.current && /INPUT|TEXTAREA|SELECT/.test(target.tagName)) return
    if (e.key === 'Escape') { clearSelection(); return }
    if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && selection.length > 0 && canDates) {
      e.preventDefault()
      const step = (e.key === 'ArrowLeft' ? -1 : 1) * (e.shiftKey ? 7 : 1)
      const cur = nudgeRef.current ?? { ids: selection, delta: 0 }
      nudgeRef.current = { ids: cur.ids, delta: cur.delta + step }
      setNudge({ ...nudgeRef.current })
      if (nudgeTimer.current) clearTimeout(nudgeTimer.current)
      nudgeTimer.current = setTimeout(() => flushRef.current(), 450)
      return
    }
    if ((e.key === 'Delete' || e.key === 'Backspace') && selection.length > 0 && canStructure) {
      e.preventDefault()
      askDelete(selection)
    }
  }

  // ---------------------------------------------------------------- zoom
  const pendingCenter = useRef<number | null>(null)
  const changeZoom = useCallback((z: Zoom) => {
    const el = scrollerRef.current
    if (el) {
      const visible = Math.max(el.clientWidth - gw, 100)
      pendingCenter.current = rangeRef.current.from + (el.scrollLeft + visible / 2) / PX_PER_DAY[zoomRef.current]
    }
    setZoom(z)
  }, [gw])
  const zoomRef = useRef(zoom)
  zoomRef.current = zoom
  useLayoutEffect(() => {
    const el = scrollerRef.current
    if (!el || pendingCenter.current == null) return
    const visible = Math.max(el.clientWidth - gw, 100)
    el.scrollLeft = Math.max(0, (pendingCenter.current - range.from) * ppd - visible / 2)
    pendingCenter.current = null
  }, [zoom, range.from, ppd, gw])

  useEffect(() => {
    const el = scrollerRef.current
    if (!el || compact) return
    let last = 0
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      const now = Date.now()
      if (now - last < 180) return
      last = now
      changeZoom(zoomStep(zoomRef.current, e.deltaY < 0 ? 1 : -1))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [changeZoom, compact, data])

  // First view: scroll to the plan start.
  const didInitScroll = useRef(false)
  useLayoutEffect(() => {
    const el = scrollerRef.current
    if (!el || didInitScroll.current || !data) return
    didInitScroll.current = true
    const first = data.summary.start ? toDay(data.summary.start) : today
    el.scrollLeft = Math.max(0, xOf(first, range, ppd) - 3 * ppd - 16)
  }, [data, range, ppd, today])

  // ---------------------------------------------------------------- actions
  const focusTask = (id: number) => {
    const t = tasks.find((x) => x.id === id)
    if (!t) return
    const lane = laneOf(t)
    if (collapsed.has(lane)) setCollapsed((c) => { const n = new Set(c); n.delete(lane); return n })
    setSelection([id])
    setFlashId(id)
    setTimeout(() => setFlashId((f) => (f === id ? null : f)), 1600)
    requestAnimationFrame(() => {
      const el = scrollerRef.current
      if (!el) return
      const idx = buildRows(groups, new Set([...collapsed].filter((l) => l !== lane)))
        .findIndex((r) => r.type === 'task' && r.task.id === id)
      if (idx >= 0) el.scrollTop = Math.max(0, idx * ROW_H - 2 * ROW_H)
      el.scrollLeft = Math.max(0, xOf(toDay(t.start_date), range, ppd) - 60)
    })
  }

  const newTask = (kind: TaskKind, preset?: AddPreset) => {
    const anchor = selection.length === 1 ? tasks.find((t) => t.id === selection[0]) : undefined
    const start = anchor ? toIso(endOf(taskGeo(anchor)))
      : data?.summary.finish ?? toIso(today)
    const body: TaskCreate = {
      plan, kind, start_date: start,
      name: preset === 'buffer' ? 'Safety buffer' : preset === 'bank_build' ? 'Bank build (idea)'
        : preset === 'milestone' ? 'Milestone' : 'New task',
      duration_days: kind === 'milestone' ? 0 : preset === 'bank_build' ? 10 : 5,
      lane: preset === 'bank_build' ? 'Scheduling' : anchor?.lane ?? null,
      department_id: preset === 'bank_build' ? null : anchor?.department_id ?? null,
      predecessors: anchor && preset !== 'bank_build' ? [anchor.id] : [],
      is_idea: preset === 'bank_build',
    }
    if (preset === 'bank_build') {
      const sched = departments.find((d) => d.name === 'Scheduling')
      if (sched) body.department_id = sched.id
    }
    const before = new Set(tasks.map((t) => t.id))
    run(() => planApi.createTask(changeId, body), (p) => {
      const created = p.tasks.find((t) => !before.has(t.id))
      if (created) { setSelection([created.id]); setEditorId(created.id) }
    })
  }

  const align = (a: AlignAction) => {
    if (a === 'snap') {
      const u = snapToPredecessors(tasks, selection)
      if (!u.length) { toast.info?.('Already aligned to their predecessors'); return }
      commitDates(u)
    } else if (a === 'match_start' || a === 'match_end') {
      commitDates(matchTo(tasks, selection, a === 'match_start' ? 'start' : 'end'))
    } else {
      const { links, updates } = runParallel(tasks, selection)
      commitDates(updates, links)
    }
  }

  const askDelete = (ids: number[]) => {
    const names = ids.map((id) => tasks.find((t) => t.id === id)?.name).filter(Boolean)
    setConfirm({
      title: ids.length === 1 ? `Delete "${names[0]}"?` : `Delete ${ids.length} tasks?`,
      body: 'Links to the deleted tasks are removed too.',
      label: 'Delete', danger: true,
      run: () => run(async () => {
        let out: PlanOut | undefined
        for (const id of ids) out = await planApi.deleteTask(changeId, id)
        return out!
      }, () => { setSelection([]); setEditorId(null) }),
    })
  }

  const seed = (replace: boolean) => {
    const go = () => run(() => planApi.seed(changeId, plan, replace))
    if (!replace) { go(); return }
    setConfirm({
      title: 'Replace the plan?',
      body: plan === 'quote'
        ? 'Every task is replaced by a new plan generated from the costing lead times.'
        : 'Every task is replaced by a copy of the quote plan. Team confirmations go stale.',
      label: 'Replace plan', danger: true, run: go,
    })
  }

  const exportPlan = (fmt: 'xml' | 'csv') => {
    const p = fmt === 'xml' ? planApi.exportXml(changeId, plan) : planApi.exportCsv(changeId, plan)
    p.catch((e: unknown) => toast.error(errDetail(e) ?? 'Export failed'))
  }

  const saveTask = (t: TaskOut, patch: TaskPatch) => {
    const dateChange = patch.start_date !== undefined || patch.duration_days !== undefined
    if (baselineSet && dateChange) {
      setOverrides((prev) => new Map(prev).set(t.id, {
        start: patch.start_date ? toDay(patch.start_date) : toDay(t.start_date),
        dur: patch.duration_days ?? t.duration_days,
      }))
      setReasonFor({ updates: [], patch: { id: t.id, body: patch } })
      return
    }
    run(() => planApi.patchTask(changeId, t.id, patch))
  }

  // ---------------------------------------------------------------- render
  if (isLoading) {
    return <div className="rounded-lg border border-slate-700 bg-slate-900 p-4 text-sm text-slate-400">Loading plan...</div>
  }
  if (isError || !data) {
    return <div className="rounded-lg border border-red-900/60 bg-red-950/30 p-4 text-sm text-red-300">Could not load the plan. Reload the page to try again.</div>
  }

  const seedLabel = plan === 'quote' ? 'Seed from costing' : 'Seed from quote plan'
  const empty = tasks.length === 0
  const s = data.summary
  const nErr = data.validation.errors.length
  const nWarn = data.validation.warnings.length
  const editorTask = editorId != null ? tasks.find((t) => t.id === editorId) : undefined

  if (empty) {
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
              <button type="button" className={btnPrimary} onClick={() => seed(false)} disabled={mut.isPending}
                data-testid="gantt-seed">{seedLabel}</button>
              <button type="button" className={btn} onClick={() => newTask('work')} disabled={mut.isPending}>+ Add a task</button>
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

  const stat = (label: string, value: string, tone = 'text-slate-100') => (
    <div className="min-w-0">
      <p className="text-[10px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`truncate text-sm font-medium tabular-nums ${tone}`}>{value}</p>
    </div>
  )

  // Shown inclusive, from the committed plan (ideas do not count).
  const real = tasks.filter((t) => !t.is_idea).map(taskGeo)
  const firstDay = real.length ? Math.min(...real.map((g) => g.start)) : (s.start ? toDay(s.start) : null)
  const lastDay = real.length ? Math.max(...real.map(inclusiveEnd)) : null
  const chartHeight = HEADER_H + Math.max(rows.length, 1) * ROW_H

  return (
    <div className="space-y-2" data-testid="gantt-planner">
      {!compact && (
        <GanttToolbar
          canStructure={canStructure} canDates={canDates} canSchedule={canEdit && !baselineSet}
          empty={empty} seedLabel={seedLabel}
          zoom={zoom} onZoom={changeZoom} critical={critical} onCritical={setCritical}
          onAddTask={(k) => newTask(k)}
          onAddPreset={(p) => newTask(p === 'milestone' ? 'milestone' : p === 'buffer' ? 'buffer' : 'bank_build', p)}
          onSchedule={() => run(() => planApi.schedule(changeId, plan))}
          onExport={exportPlan}
          onSeed={canStructure ? () => seed(true) : undefined}
          saving={mut.isPending}
          selectionCount={selection.length}
          onAlign={align}
          onDeleteSelection={canStructure ? () => askDelete(selection) : undefined}
          onClearSelection={clearSelection}
        />
      )}

      {!compact && (
        <div className="rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2" data-testid="gantt-summary">
          <div className="grid grid-cols-3 gap-3 sm:grid-cols-7 items-center">
            {stat('Start', fmtDay(firstDay))}
            {stat('Finish', fmtDay(lastDay))}
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
                {nErr + nWarn === 0 ? 'No issues'
                  : `${nErr} error${nErr === 1 ? '' : 's'}, ${nWarn} warning${nWarn === 1 ? '' : 's'}`}
              </button>
            </div>
          </div>
          {showIssues && (
            <div className="mt-2 border-t border-slate-700 pt-2">
              <ValidationList errors={data.validation.errors} warnings={data.validation.warnings}
                rowNo={rowNo} onFocusTask={focusTask} />
            </div>
          )}
        </div>
      )}

      <div ref={scrollerRef} tabIndex={0} onKeyDown={onKeyDown}
        aria-label="Plan chart. Select tasks, then use arrow keys to move them."
        data-testid="gantt-scroller"
        className={`relative overflow-auto rounded-lg border border-slate-700 bg-slate-900 outline-none focus-visible:border-sky-700 ${compact ? 'max-h-[320px]' : 'max-h-[70vh]'}`}
        style={{ minHeight: Math.min(chartHeight + 2, compact ? 320 : 240) }}>
        <div style={{ width: gw + timelineW }}>
          <div className="sticky top-0 z-20 flex" style={{ height: HEADER_H }}>
            <div className="sticky left-0 z-30 border-r border-slate-700 bg-slate-900">
              <GridHeader compact={compact} track={track} />
            </div>
            <TimelineHeader range={range} ppd={ppd} zoom={zoom} today={today} deadlines={deadlines}
              scrollerRef={scrollerRef} />
          </div>
          <div className="flex">
            <div className="sticky left-0 z-10 border-r border-slate-700 bg-slate-900">
              <GridBody rows={rows} geos={geos} rowNo={rowNo} selected={selectedSet} flashId={flashId}
                issueIds={issueIds} compact={compact} track={track}
                onToggleLane={(l) => setCollapsed((c) => {
                  const n = new Set(c)
                  if (n.has(l)) n.delete(l); else n.add(l)
                  return n
                })}
                onRowClick={compact ? undefined : onRowClick} />
            </div>
            <TimelineBody rows={rows} geos={geos} range={range} ppd={ppd} zoom={zoom} today={today}
              deadlines={deadlines} track={track} critical={critical} criticalIds={s.critical_ids}
              selected={selectedSet} flashId={flashId} rowNo={rowNo}
              canDrag={canDates} canLink={canEdit} linkPreview={linkPreview} svgRef={svgRef} uid={uid}
              onBarPointerDown={compact ? undefined : onBarPointerDown}
              onLinkStart={onLinkStart} onLinkClick={onLinkClick}
              onBackgroundPointerDown={compact ? undefined : (e) => {
                if (!(e.shiftKey || e.ctrlKey || e.metaKey)) clearSelection()
              }} />
          </div>
        </div>
      </div>

      {!compact && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-[11px] text-slate-500" aria-label="Legend">
          {deadlines.map((d) => (
            <span key={d.key} className="flex items-center gap-1.5">
              <span className="inline-block h-3 w-0 border-l-2 border-dashed" style={{ borderColor: deadlineColor(d.key) }} />
              {d.label}
            </span>
          ))}
          <span className="flex items-center gap-1.5"><span className="inline-block h-3 w-0 border-l-2 border-sky-400" />Today</span>
          {track && <span className="flex items-center gap-1.5"><span className="inline-block h-1 w-4 rounded bg-slate-400/60" />Baseline</span>}
          {track && <span className="flex items-center gap-1.5"><span className="inline-block h-2 w-3 rounded-sm bg-red-500" />Slip</span>}
          {canDates && <span>Drag bars to move, drag the right edge to resize, drag the dot at the end onto another bar to link. Ctrl+scroll zooms.</span>}
        </div>
      )}

      {editorTask && !compact && (
        <TaskEditor task={editorTask} tasks={tasks} rowNo={rowNo} departments={departments}
          canEdit={canEdit} canDates={canDates} canProgress={canProgressOn(editorTask)}
          track={track} baselineSet={baselineSet} saving={mut.isPending}
          onSave={(patch) => saveTask(editorTask, patch)}
          onDelete={canStructure ? () => askDelete([editorTask.id]) : undefined}
          onClose={() => setEditorId(null)} />
      )}

      <ConfirmDialog open={!!confirm} title={confirm?.title ?? ''} body={confirm?.body}
        confirmLabel={confirm?.label} danger={confirm?.danger}
        onConfirm={() => confirm?.run()} onClose={() => setConfirm(null)} />

      <ReasonDialog open={!!reasonFor} title="Record a deviation" label="Why does this move?"
        warning="This is recorded as a deviation and PM/Sales decide to lock or escalate it."
        submitLabel="Save move"
        onSubmit={(reason) => { const r = reasonFor; setReasonFor(null); if (r) sendDates(r, reason) }}
        onClose={() => { setReasonFor(null); setOverrides(new Map()) }} />
    </div>
  )
}
