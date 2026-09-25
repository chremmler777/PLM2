/**
 * Generic, MS-Project-like Gantt (spec 2026-09-25 §11). No module imports:
 * hosts pass tasks, links, a calendar and rights, and receive every user
 * action as one ChangeSet through `onChange` (their adapter persists it).
 *
 * Every action is applied locally at once (optimistic), queued (one save in
 * flight), and reconciled with the host's next model; on an error the queue
 * is dropped, the view falls back to the host model and `onError` is told.
 */
import {
  forwardRef, useCallback, useEffect, useId, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState,
  type ReactNode, type PointerEvent as ReactPointerEvent, type KeyboardEvent as ReactKeyboardEvent,
} from 'react'
import {
  diff, durationFromLastDay, endOf, isIsoDay, makeCal, nextWork, normStart, todayDay, toDay, toIso,
} from './engine/calendar'
import {
  applyChangeSet, chainLinksChangeSet, duplicateChangeSet, isEmptyChangeSet, removeTasksChangeSet, unlinkChangeSet,
} from './engine/changes'
import { History } from './engine/history'
import { formatPredecessors, predecessorChangeSet, tempId } from './engine/notation'
import { exportCsv } from './engine/csv'
import { exportMspdi } from './engine/mspdi'
import { autoPushChangeSet, schedule, wouldCycle } from './engine/schedule'
import { buildTree, descendants, indent, key, leaves, moveRows, outdent, rowNumbers, type Tree } from './engine/tree'
import type {
  ChangeSet, GanttCalendar, GanttId, GanttLink, GanttModel, GanttTask, Issue, LinkType,
} from './engine/types'
import { LIMITS, LINK_TYPES, inYearRange } from './engine/types'
import { linkViolated, validate } from './engine/validate'
import { ChartBody, ChartHeader, HEADER_H, MARKER_STRIP, type GanttMarker, type LinkDraft, type TaskGeo } from './GanttChart'
import { ColumnPicker, GridBody, GridHeader } from './GanttGrid'
import { BUILTIN_COLUMNS, gridWidth, type CellContext, type ColumnKey, type GanttColumn } from './columns'
import { ContextMenu, LinkPopover, TaskDialog, type MenuEntry } from './GanttPopups'
import { buildChartSvg, downloadBlob, openPrint, svgToPng } from './exportImage'
import {
  PX_PER_DAY, ZOOMS, buildRows, snapDays, textWidth, timelineRange, typeFromSides, unitFor, visibleWindow, xOf, zoomStep,
  anchorX, barGeo, type Zoom,
} from './layout'
import { THEMES, resolveTheme, themeVars, v, type GanttKindStyle, type GanttThemeName } from './theme'
import { useSaveQueue, type SaveQueueOptions } from './useSaveQueue'
import { readDateInput } from './dateText'

export interface GanttRights {
  /** Add, delete, indent, reorder, duplicate, rename. Default true. */
  structure?: boolean
  /** Move and resize. Default true. */
  dates?: boolean
  /** Draw, edit and remove links. Default true. */
  links?: boolean
  /** Progress editing (per task possible). Default: same as dates. */
  progress?: boolean | ((t: GanttTask) => boolean)
  /** Fine grained override per field: name, lane, kind, isIdea, constraint, notes, start, duration, links, progress. */
  field?: (t: GanttTask, field: string) => boolean
}

/** Why this ChangeSet would leave an idea task with subtasks, or null. */
function ideaHolding(m: GanttModel, cs: ChangeSet): string | null {
  const touches = (cs.updateTasks ?? []).some((u) => 'parentId' in u.patch || 'isIdea' in u.patch)
    || (cs.addTasks ?? []).some((t) => t.parentId != null || t.isIdea) || !!cs.order
  if (!touches) return null
  const after = applyChangeSet(m, cs)
  const parents = new Set(after.tasks.filter((t) => t.parentId != null).map((t) => key(t.parentId!)))
  const holder = after.tasks.find((t) => t.isIdea && parents.has(key(t.id)))
  if (!holder) return null
  const flagged = (cs.updateTasks ?? []).some((u) => key(u.id) === key(holder.id) && u.patch.isIdea)
    || (cs.addTasks ?? []).some((t) => key(t.id) === key(holder.id))
  return flagged ? `'${holder.name}' has subtasks: a summary cannot be an idea block`
    : `'${holder.name}' is an idea block: it cannot hold tasks`
}

/** Gantts on the page: with only one, Ctrl+Shift+F works from anywhere. */
const mounted = new Set<symbol>()

export interface GanttHandle {
  focusTask: (id: GanttId) => void
  undo: () => void
  redo: () => void
  fit: () => void
  exportPng: () => Promise<void>
  print: () => void
  select: (ids: GanttId[]) => void
  getModel: () => GanttModel
  /** Run a ChangeSet through the same path as a user action (reason hook, undo, queue). */
  apply: (cs: ChangeSet) => Promise<boolean>
  /** Start a new (draft) row as "+ Task" does. */
  insertTask: (milestone?: boolean) => void
  /** Enter or leave the full-screen layer. */
  setFullScreen: (on: boolean) => void
  /** Forget undo and redo (e.g. the calendar changed: old steps would replay in the wrong unit). */
  clearHistory: () => void
}

export interface GanttProps {
  tasks: GanttTask[]
  links: GanttLink[]
  calendar?: Partial<GanttCalendar> | null
  rights?: GanttRights
  /** Everything read-only (no toolbar edit buttons, no drag). */
  readOnly?: boolean
  onChange?: SaveQueueOptions['onChange']
  /** Last look at a ChangeSet before it is applied: return it (maybe with meta), or null to cancel. */
  beforeChange?: (cs: ChangeSet, model: GanttModel) => ChangeSet | null | Promise<ChangeSet | null>
  onError?: (message: string, error?: unknown) => void
  onNotify?: (message: string) => void
  kinds?: Record<string, GanttKindStyle>
  columns?: (ColumnKey | GanttColumn)[]
  markers?: GanttMarker[]
  showToday?: boolean
  /** Baseline ghosts and slip tails (toolbar toggle starts here). */
  showBaselines?: boolean
  showProgress?: boolean
  /** Critical path highlight on at start. */
  criticalPath?: boolean
  /** The host's critical ids (e.g. the server's); default the engine's. */
  criticalIds?: GanttId[]
  groupByLane?: boolean
  /**
   * Automatic scheduling (MS Project): every change also moves the successors
   * it pushes (later only), in the same undo step; those moves are listed in
   * `meta.derived` of the ChangeSet.
   */
  autoSchedule?: boolean
  linkTypes?: LinkType[]
  allowLag?: boolean
  /** Parents / summary tasks (indent, outdent). Default true. */
  hierarchy?: boolean
  constraints?: boolean
  defaultZoom?: Zoom | 'fit'
  /** CSS height of the scroll area. */
  height?: number | string
  rowHeight?: number
  compact?: boolean
  toolbar?: boolean
  toolbarStart?: ReactNode
  toolbarEnd?: ReactNode
  /** Open the host's task editor; the built-in dialog is used otherwise. */
  onTaskOpen?: (t: GanttTask) => void
  onSelectionChange?: (ids: GanttId[]) => void
  menuItems?: (ids: GanttId[]) => MenuEntry[]
  /** Defaults for a new task (Insert, toolbar). `after` is the nearest leaf above the new row. */
  newTask?: (ctx: { after?: GanttTask; parentId: GanttId | null; start: string; milestone: boolean }) => Partial<GanttTask>
  /** Issues to flag (default: the engine's validation). */
  issues?: Issue[]
  theme?: GanttThemeName
  exportName?: string
  /** Replace the client side MS Project / CSV export (e.g. a server export). */
  onExport?: (fmt: 'mspdi' | 'csv') => void
  className?: string
  /** Shown in the full-screen header strip. */
  title?: string
  /**
   * Content that belongs to the chart (a task panel, notes, a legend): shown
   * under it, and inside the full-screen layer too.
   */
  below?: ReactNode
  /** Host content above the toolbar (e.g. a summary strip), inside the full-screen layer too. */
  above?: ReactNode
  /** Offer the full-screen button (default true unless compact). */
  fullScreen?: boolean
  /** Largest share of the width the table may take (columns drop out beyond it). Default 0.45. */
  maxGridFraction?: number
  /** Tasks flashed and scrolled to by the host (e.g. from a validation list). */
  ariaLabel?: string
}

type DragMode = 'move' | 'start' | 'end' | 'progress'
interface DragState {
  mode: DragMode
  keys: string[]
  delta: number
  progress?: number
  /** Keyboard nudges count working days in a working calendar. */
  unit?: 'work'
}
interface EditState { key: string; col: string }

const DEFAULT_COLUMNS: ColumnKey[] = ['row', 'name', 'start', 'end', 'duration', 'predecessors']
const today0 = () => todayDay()
const isTextTarget = (el: EventTarget | null) => {
  const t = el as HTMLElement | null
  return !!t && (/INPUT|TEXTAREA|SELECT/.test(t.tagName) || t.isContentEditable)
}
/** Keys typed on a button, menu, dialog or toolbar belong to that control, not to the chart. */
const isControlTarget = (el: EventTarget | null) => {
  const t = el as Element | null
  return !!t?.closest?.('button,a,[role=menu],[role=menuitem],[role=dialog],[role=toolbar],[role=listbox]')
}

/** A callback with a stable identity that always runs the latest closure (memoised children). */
function useStable<A extends unknown[], R>(fn: (...a: A) => R): (...a: A) => R {
  const ref = useRef(fn)
  ref.current = fn
  return useCallback((...a: A) => ref.current(...a), [])
}

/** Display order with a local draft row inserted after `afterKey`'s subtree. */
function draftOrder(tree: Tree, id: GanttId, afterKey: string | null): GanttId[] {
  const order = tree.order.map((x) => x.id)
  let at = order.length
  if (afterKey && tree.byId.has(afterKey)) {
    const sub = [afterKey, ...descendants(tree, afterKey).map((x) => key(x.id))]
    at = Math.max(...sub.map((k) => order.findIndex((o) => key(o) === k))) + 1
  }
  order.splice(at, 0, id)
  return order
}

export const Gantt = forwardRef<GanttHandle, GanttProps>(function Gantt(p, ref) {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, '')
  const rowH = p.rowHeight ?? 28
  const readOnly = !!p.readOnly || !!p.compact
  const cal = useMemo(() => makeCal(p.calendar), [p.calendar])
  const working = cal.mode === 'working'
  const kinds = useMemo(() => p.kinds ?? {}, [p.kinds])
  const linkTypes = p.linkTypes ?? LINK_TYPES
  const allowLag = p.allowLag ?? true
  const hierarchy = p.hierarchy ?? true
  const theme = THEMES[p.theme ?? 'dark']

  // ---------------------------------------------------------------- model + saves
  const base = useMemo<GanttModel>(() => ({ tasks: p.tasks, links: p.links }), [p.tasks, p.links])
  const history = useRef(new History())
  const [, setHistTick] = useState(0)
  const bumpHist = () => setHistTick((n) => n + 1)
  const notifyError = useCallback((msg: string, e?: unknown) => {
    if (p.onError) p.onError(msg, e)
    else console.warn(`[gantt] ${msg}`, e ?? '')
  }, [p])
  const errMessage = (e: unknown) => {
    const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    if (typeof d === 'string') return d
    if (d && typeof d === 'object' && 'message' in d) return String((d as { message: unknown }).message)
    if (e instanceof Error && e.message) return e.message
    return 'The change could not be saved'
  }
  /** Undo / redo waiting for a step's save to answer, by history entry. */
  const settleWaiters = useRef(new Map<number, (() => void)[]>())
  const releaseWaiters = (entry: number) => {
    const list = settleWaiters.current.get(entry)
    if (!list) return
    settleWaiters.current.delete(entry)
    for (const r of list) r()
  }
  const remapViewRef = useRef<(m: Record<string, GanttId>) => void>(() => undefined)
  const queue = useSaveQueue(base, {
    onChange: p.onChange,
    // Only the refused change is rolled back (and forgotten by undo).
    onError: (e, tag, seq) => {
      const forgotten = tag ? history.current.refused(tag.entry, seq, tag.dir) : false
      if (tag) releaseWaiters(tag.entry)
      bumpHist()
      notifyError(errMessage(e), e)
      return forgotten && tag ? tag.entry : undefined
    },
    onSettled: (tag, seq) => { if (tag) { history.current.settled(tag.entry, seq); releaseWaiters(tag.entry) } },
    // Tasks the server pushed on its own for a user action: undo restores them too.
    onServerMoves: (tag, moves) => {
      if (!tag || tag.dir !== 'do') return
      history.current.extend(tag.entry,
        { updateTasks: moves.map((m) => ({ id: m.id, patch: { ...m.to } })) },
        { updateTasks: moves.map((m) => ({ id: m.id, patch: { ...m.from } })) })
    },
    onIdMap: (m, lm) => { history.current.remap(m, lm); remapViewRef.current(m) },
  })
  const saved = queue.display
  const modelRef = useRef(saved)
  modelRef.current = saved
  /** A new row that exists only locally until it gets a name (Escape or an empty name drops it). */
  const [draft, setDraft] = useState<{ task: GanttTask; afterKey: string | null } | null>(null)
  const model = useMemo(() => (draft
    ? applyChangeSet(saved, { addTasks: [draft.task], order: draftOrder(buildTree(saved.tasks), draft.task.id, draft.afterKey) })
    : saved), [saved, draft])
  const draftKey = draft ? key(draft.task.id) : null

  // ---------------------------------------------------------------- view state
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [selection, setSelection] = useState<string[]>([])
  const [anchor, setAnchor] = useState<string | null>(null)
  const [active, setActive] = useState<string | null>(null)
  const [drag, setDrag] = useState<DragState | null>(null)
  const [linkDraft, setLinkDraft] = useState<LinkDraft | null>(null)
  const [linkPop, setLinkPop] = useState<{ id: string; x: number; y: number } | null>(null)
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null)
  const [editing, setEditing] = useState<EditState | null>(null)
  const [dialogKey, setDialogKey] = useState<string | null>(null)
  /**
   * Full screen: the SAME component tree becomes a fixed layer over the page
   * (only classes change, nothing remounts), so selection, zoom, scroll,
   * undo history, open panels and draft rows stay.
   */
  const [full, setFull] = useState(false)
  // One Gantt on the page: its full-screen shortcut works anywhere (not only
  // with focus inside it). With several, each answers only for itself.
  useEffect(() => {
    if (p.compact || p.fullScreen === false) return
    const me = Symbol('gantt')
    mounted.add(me)
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || mounted.size !== 1) return
      if (!((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'f' || e.key === 'F'))) return
      e.preventDefault()
      setFull((f) => !f)
    }
    document.addEventListener('keydown', onKey)
    return () => { mounted.delete(me); document.removeEventListener('keydown', onKey) }
  }, [p.compact, p.fullScreen])
  const fullReturnFocus = useRef<HTMLElement | null>(null)
  const [flashKey, setFlashKey] = useState<string | null>(null)
  const [zoom, setZoom] = useState<Zoom | 'fit'>(p.defaultZoom ?? (p.compact ? 'week' : 'day'))
  const [showCritical, setShowCritical] = useState(!!p.criticalPath)
  const [showBaselines, setShowBaselines] = useState(p.showBaselines ?? false)
  useEffect(() => { if (p.showBaselines !== undefined) setShowBaselines(p.showBaselines) }, [p.showBaselines])
  const [dropLine, setDropLine] = useState<{ index: number; where: 'before' | 'after' } | null>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewport, setViewport] = useState({ w: 0, h: 0 })
  const scrollerRef = useRef<HTMLDivElement>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const today = today0()
  const headerH = HEADER_H + ((p.markers?.length ?? 0) > 0 ? MARKER_STRIP : 0)

  // ---------------------------------------------------------------- rights
  const rights = useMemo(() => p.rights ?? {}, [p.rights])
  const canStructure = !readOnly && (rights.structure ?? true)
  const canDates = !readOnly && (rights.dates ?? true)
  const canLinks = !readOnly && (rights.links ?? true)
  const canField = useCallback((t: GanttTask, field: string): boolean => {
    if (readOnly || t.readOnly) return false
    if (rights.field) return rights.field(t, field)
    switch (field) {
      case 'start': case 'duration': return canDates
      case 'links': return canLinks
      case 'progress': return typeof rights.progress === 'function' ? rights.progress(t) : (rights.progress ?? canDates)
      case 'notes': return canStructure || canDates
      default: return canStructure
    }
  }, [readOnly, rights, canDates, canLinks, canStructure])
  const canProgress = useCallback((t: GanttTask) => canField(t, 'progress'), [canField])
  // Undo across a rights change (e.g. the baseline was set) could replay what is no longer allowed.
  // Only when a right is taken away (not on load or when rights arrive).
  const rightsRef = useRef({ canStructure, canDates, canLinks })
  useEffect(() => {
    const prev = rightsRef.current
    rightsRef.current = { canStructure, canDates, canLinks }
    if ((prev.canStructure && !canStructure) || (prev.canDates && !canDates) || (prev.canLinks && !canLinks)) {
      history.current.clear()
      bumpHist()
    }
  }, [canStructure, canDates, canLinks])

  // ---------------------------------------------------------------- derived
  const rowModel = useMemo(() => buildRows(model.tasks, { groupByLane: p.groupByLane, collapsed }), [model.tasks, p.groupByLane, collapsed])
  const { rows, index } = rowModel
  // Structure, order and row numbers follow the stored (ungrouped) order: lane
  // grouping is a view and must not rewrite the order or renumber predecessors.
  const tree = useMemo(() => buildTree(model.tasks), [model.tasks])
  const rowNo = useMemo(() => rowNumbers(tree), [tree])
  const predText = useMemo(() => {
    const m = new Map<string, string>()
    for (const t of tree.order) m.set(key(t.id), formatPredecessors(t.id, model.links, rowNo))
    return m
  }, [tree, model.links, rowNo])
  const sched = useMemo(() => schedule(model.tasks, model.links, p.calendar), [model.tasks, model.links, p.calendar])
  const issues = useMemo(() => p.issues ?? validate(model.tasks, model.links, p.calendar), [p.issues, model.tasks, model.links, p.calendar])
  const flagged = useMemo(() => new Set(issues.filter((i) => i.level === 'error' && i.taskId != null).map((i) => key(i.taskId!))), [issues])
  const isSummaryKey = useCallback((k: string) => (tree.children.get(k)?.length ?? 0) > 0, [tree])

  /** Patches the current drag would write (keyed by task key). */
  const dragPatches = useMemo(() => {
    const out = new Map<string, Partial<GanttTask>>()
    if (!drag || (drag.delta === 0 && drag.mode !== 'progress')) return out
    for (const k of drag.keys) {
      const t = tree.byId.get(k)
      if (!t) continue
      const s = normStart(cal, toDay(t.start))
      const e = endOf(cal, s, t.duration)
      if (drag.mode === 'progress') { if (drag.progress != null) out.set(k, { progress: drag.progress }); continue }
      if (drag.mode === 'move') {
        out.set(k, { start: toIso(drag.unit === 'work' ? cal.dateAt(cal.idx(s) + drag.delta) : nextWork(cal, s + drag.delta)) })
      } else if (drag.mode === 'end' && t.duration > 0) {
        const ne = e + drag.delta
        out.set(k, { duration: Math.max(1, working ? diff(cal, s, ne) : t.duration + drag.delta) })
      } else if (drag.mode === 'start' && t.duration > 0) {
        const ns = nextWork(cal, Math.min(s + drag.delta, e - 1))
        const nd = Math.max(1, working ? diff(cal, ns, e) : e - ns)
        out.set(k, { start: toIso(ns), duration: nd })
      }
    }
    return out
  }, [drag, tree, cal, working])

  const geo = useMemo(() => {
    const m = new Map<string, TaskGeo>()
    // Committed (non-idea) work below each task, as the engine's rollup uses it.
    const hasReal = new Map<string, boolean>()
    for (const t of [...tree.order].reverse()) {
      const kids = tree.children.get(key(t.id)) ?? []
      hasReal.set(key(t.id), kids.length ? kids.some((c) => hasReal.get(key(c.id))) : !t.isIdea)
    }
    for (const t of [...tree.order].reverse()) {
      const k = key(t.id)
      const kids = tree.children.get(k) ?? []
      if (kids.length) {
        // Idea blocks do not stretch a summary (unless it holds only ideas), like the engine.
        const real = kids.filter((c) => hasReal.get(key(c.id)))
        const cs = (real.length ? real : kids).map((c) => m.get(key(c.id))!).filter(Boolean)
        m.set(k, { s: Math.min(...cs.map((c) => c.s)), e: Math.max(...cs.map((c) => c.e)), milestone: false, summary: true })
        continue
      }
      const patch = dragPatches.get(k)
      const start = patch?.start ?? t.start
      const dur = patch?.duration ?? t.duration
      const s = isIsoDay(start) ? normStart(cal, toDay(start)) : today
      m.set(k, { s, e: endOf(cal, s, Math.max(0, dur)), milestone: dur === 0, summary: false })
    }
    return m
  }, [tree, dragPatches, cal, today])

  const displayTask = useCallback((t: GanttTask): GanttTask => {
    const patch = dragPatches.get(key(t.id))
    return patch ? { ...t, ...patch } : t
  }, [dragPatches])
  const displayRows = useMemo(() => (dragPatches.size
    ? rows.map((r) => (r.type === 'task' && dragPatches.has(key(r.task.id)) ? { ...r, task: displayTask(r.task) } : r))
    : rows), [rows, dragPatches, displayTask])

  const criticalSet = useMemo(() => {
    if (!showCritical) return null
    const ids = p.criticalIds ?? sched.criticalIds
    const s = new Set(ids.map(key))
    // Summaries over critical leaves count as critical too.
    for (const t of tree.order) {
      const k = key(t.id)
      if (isSummaryKey(k) && leaves(tree, k).some((l) => s.has(key(l.id)))) s.add(k)
    }
    return s
  }, [showCritical, p.criticalIds, sched, tree, isSummaryKey])

  const brokenLinks = useMemo(() => {
    const s = new Set<string>()
    for (const l of model.links) {
      const f = tree.byId.get(key(l.from)), t = tree.byId.get(key(l.to))
      if (!f || !t || isSummaryKey(key(f.id)) || isSummaryKey(key(t.id))) continue
      if (isIsoDay(f.start) && isIsoDay(t.start) && linkViolated(displayTask(f), displayTask(t), l, cal)) s.add(key(l.id))
    }
    return s
  }, [model.links, tree, isSummaryKey, displayTask, cal])

  const hasHierarchy = useMemo(() => tree.order.some((t) => (tree.depth.get(key(t.id)) ?? 0) > 0), [tree])
  const viewW = viewport.w
  // The user's column choice: shown although crowded, or hidden.
  const [colPrefs, setColPrefs] = useState<{ show: string[]; hide: string[] }>({ show: [], hide: [] })
  const [colPicker, setColPicker] = useState(false)
  const { columns, allColumns, dropped } = useMemo(() => {
    const list = p.compact ? ['name' as ColumnKey] : (p.columns ?? DEFAULT_COLUMNS)
    const all = list.map((c) => (typeof c === 'string' ? BUILTIN_COLUMNS[c] : c))
      .map((c) => (p.compact && c.key === 'name' ? { ...c, width: 190 } : c))
      // A WBS column without subtasks only repeats the row number.
      .filter((c) => c.key !== 'wbs' || hasHierarchy)
    let cols = all.filter((c) => c.key === 'name' || !colPrefs.hide.includes(c.key))
    // Keep the chart readable: the grid takes at most a share of the width.
    const max = viewW ? Math.max(240, viewW * (p.maxGridFraction ?? 0.45)) : Infinity
    const width = () => cols.reduce((n, c) => n + c.width, 0)
    // The task name keeps at least 180 px (it is what people read).
    if (width() > max) cols = cols.map((c) => (c.key === 'name' ? { ...c, width: Math.max(Math.min(180, c.width), c.width - (width() - max)) } : c))
    // Then every column narrows towards its minimum width (dd.mm.yy dates stay readable).
    if (width() > max) {
      const room = cols.reduce((n, c) => n + (c.minWidth != null ? c.width - c.minWidth : 0), 0)
      const need = Math.min(room, width() - max)
      if (room > 0) cols = cols.map((c) => (c.minWidth != null ? { ...c, width: Math.max(c.minWidth, Math.floor(c.width - (c.width - c.minWidth) * need / room)) } : c))
    }
    // Columns drop out from the end of the configured list (the name and the
    // ones the user asked for stay); the header says how many and offers them.
    const out: string[] = []
    while (width() > max && cols.length > 1) {
      const cand = cols.filter((c) => c.key !== 'name' && !colPrefs.show.includes(c.key)).map((c) => c.key).pop()
      if (cand == null) break
      out.unshift(cand)
      cols = cols.filter((c) => c.key !== cand)
    }
    return { columns: cols, allColumns: all, dropped: out }
  }, [p.columns, p.compact, p.maxGridFraction, hasHierarchy, viewW, colPrefs])
  const gw = gridWidth(columns)

  const cellCtx = useCallback((t: GanttTask): CellContext => {
    const k = key(t.id)
    const g = geo.get(k)
    const summary = isSummaryKey(k)
    return {
      geo: g, rowNo: rowNo.get(k), wbs: tree.wbs.get(k),
      predecessors: predText.get(k) ?? '',
      sched: sched.byId.get(t.id), kinds, summary, working,
      summaryDuration: summary && g ? diff(cal, g.s, g.e) : undefined,
      variance: g && t.baselineEnd && isIsoDay(t.baselineEnd) ? cal.idx(g.e) - cal.idx(toDay(t.baselineEnd)) : null,
    }
  }, [geo, isSummaryKey, rowNo, tree, predText, sched, kinds, working, cal])

  // ---------------------------------------------------------------- scale
  const allDays = useMemo(() => {
    const d: number[] = []
    geo.forEach((g) => { d.push(g.s, g.e) })
    for (const t of model.tasks) {
      if (t.baselineStart && isIsoDay(t.baselineStart)) d.push(toDay(t.baselineStart))
      if (t.baselineEnd && isIsoDay(t.baselineEnd)) d.push(toDay(t.baselineEnd))
    }
    for (const m of p.markers ?? []) if (isIsoDay(m.date)) d.push(toDay(m.date))
    if (p.showToday !== false) d.push(today)
    return d
  // The range follows committed data only (not live drags) so the canvas does not jump.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model.tasks, p.markers, p.showToday, today, drag == null])
  const chartViewW = Math.max(200, (viewport.w || 1000) - gw - 2)
  const { range, ppd, unit } = useMemo(() => {
    if (zoom === 'fit') {
      const lo = Math.min(...allDays), hi = Math.max(...allDays)
      const span = Math.max(7, hi - lo)
      const pad = Math.max(2, Math.round(span * 0.03))
      const r = { from: lo - pad, to: hi + pad + 1 }
      const pp = Math.max(0.3, chartViewW / (r.to - r.from))
      return { range: r, ppd: pp, unit: unitFor(pp) }
    }
    // The scale always fills the visible chart (quarter zoom on a short plan too).
    return { range: timelineRange(allDays, zoom, Math.ceil(chartViewW / PX_PER_DAY[zoom])), ppd: PX_PER_DAY[zoom], unit: zoom }
  }, [zoom, allDays, chartViewW])
  const chartW = (range.to - range.from) * ppd

  // ---------------------------------------------------------------- viewport + virtualisation
  useLayoutEffect(() => {
    const el = scrollerRef.current
    if (!el) return
    const measure = () => setViewport({ w: el.clientWidth, h: el.clientHeight })
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  // Vertical scroll re-renders only when the rendered window would change (quantised
  // to a few rows inside the overscan); the header follows horizontal scroll by itself.
  const scrollFrame = useRef(0)
  const onScroll = () => {
    cancelAnimationFrame(scrollFrame.current)
    scrollFrame.current = requestAnimationFrame(() => {
      const el = scrollerRef.current
      if (!el) return
      const q = Math.floor(el.scrollTop / (rowH * 4)) * rowH * 4
      setScrollTop((cur) => (cur === q ? cur : q))
    })
  }
  useEffect(() => () => cancelAnimationFrame(scrollFrame.current), [])
  const win = viewport.h > 0
    ? visibleWindow(scrollTop, viewport.h - headerH, rowH, rows.length)
    : { first: 0, last: rows.length - 1 }

  // Keep the day under the centre when the zoom changes.
  const pendingCenter = useRef<number | null>(null)
  const changeZoom = useCallback((z: Zoom | 'fit') => {
    const el = scrollerRef.current
    if (el && z !== 'fit') pendingCenter.current = range.from + (el.scrollLeft + chartViewW / 2) / ppd
    setZoom(z)
  }, [range.from, ppd, chartViewW])
  useLayoutEffect(() => {
    const el = scrollerRef.current
    if (!el) return
    if (zoom === 'fit') { el.scrollLeft = 0; return }
    if (pendingCenter.current == null) return
    el.scrollLeft = Math.max(0, (pendingCenter.current - range.from) * ppd - chartViewW / 2)
    pendingCenter.current = null
  }, [zoom, range.from, ppd, chartViewW])
  const didInit = useRef(false)
  useLayoutEffect(() => {
    const el = scrollerRef.current
    if (!el || didInit.current || !model.tasks.length) return
    didInit.current = true
    if (zoom === 'fit') return
    // Earliest bar (ideas included) or marker, with room for its label.
    const days: number[] = []
    geo.forEach((g) => days.push(g.s))
    for (const m of p.markers ?? []) if (isIsoDay(m.date)) days.push(toDay(m.date))
    const first = days.length ? Math.min(...days) : today
    el.scrollLeft = Math.max(0, xOf(first, range, ppd) - 2 * ppd - 24)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model.tasks.length, range, ppd, today, zoom])
  // Ctrl + wheel zooms.
  useEffect(() => {
    const el = scrollerRef.current
    if (!el || p.compact) return
    let last = 0
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      const now = Date.now()
      if (now - last < 180) return
      last = now
      setZoom((z) => zoomStep(z === 'fit' ? unitFor(ppd) : z, e.deltaY < 0 ? 1 : -1))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [p.compact, ppd])

  // ---------------------------------------------------------------- selection
  const selSet = useMemo(() => new Set(selection), [selection])
  const onSelRef = useRef(p.onSelectionChange)
  onSelRef.current = p.onSelectionChange
  useEffect(() => {
    onSelRef.current?.(selection.map((k) => tree.byId.get(k)?.id ?? k))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection])
  // Drop selection entries whose task disappeared.
  useEffect(() => {
    setSelection((s) => (s.every((k) => tree.byId.has(k)) ? s : s.filter((k) => tree.byId.has(k))))
    setActive((a) => (a && !tree.byId.has(a) ? null : a))
  }, [tree])
  const taskRows = useMemo(() => rows.flatMap((r) => (r.type === 'task' ? [key(r.task.id)] : [])), [rows])
  const selectKey = (k: string, e?: { shiftKey?: boolean; ctrlKey?: boolean; metaKey?: boolean }) => {
    if (e?.shiftKey && anchor && taskRows.includes(anchor)) {
      const a = taskRows.indexOf(anchor), b = taskRows.indexOf(k)
      setSelection(taskRows.slice(Math.min(a, b), Math.max(a, b) + 1))
    } else if (e?.ctrlKey || e?.metaKey) {
      setSelection((s) => (s.includes(k) ? s.filter((x) => x !== k) : [...s, k]))
      setAnchor(k)
    } else {
      setSelection([k])
      setAnchor(k)
    }
    setActive(k)
  }
  const idsOf = (keys: string[]) => keys.map((k) => tree.byId.get(k)?.id).filter((x): x is GanttId => x != null)

  // ---------------------------------------------------------------- commit

  const commit = useCallback(async (cs0: ChangeSet | null, opts: { history?: boolean; undo?: number; redo?: number } = {}): Promise<boolean> => {
    if (!cs0 || isEmptyChangeSet(cs0)) return false
    let cs = cs0
    const before = modelRef.current
    // An idea block holds no tasks (spec §11): no idea flag on a task with
    // subtasks, nothing indented under an idea.
    if (opts.undo == null && opts.redo == null) {
      const bad = ideaHolding(before, cs)
      if (bad) { notifyError(bad); return false }
    }
    // Automatic scheduling: the successors this action pushes join the same
    // ChangeSet (one undo step), listed in meta.derived. Undo / redo replay
    // their stored ChangeSets as they are.
    if (p.autoSchedule && opts.undo == null && opts.redo == null) cs = autoPushChangeSet(before, cs, p.calendar).cs
    if (p.beforeChange) {
      const r = await p.beforeChange(cs, before)
      if (!r) return false
      cs = r
    }
    if (opts.undo != null || opts.redo != null) {
      const entry = (opts.undo ?? opts.redo)!
      const dir = opts.undo != null ? 'undo' as const : 'redo' as const
      const seq = queue.enqueue(cs, { entry, dir })
      if (dir === 'undo') history.current.confirmUndo(entry, seq)
      else history.current.confirmRedo(entry, seq)
    } else if (opts.history !== false) {
      const entry = history.current.push(modelRef.current, cs)
      const seq = queue.enqueue(cs, entry ? { entry, dir: 'do' } : undefined)
      if (entry) history.current.sent(entry, seq)
    } else queue.enqueue(cs)
    bumpHist()
    return true
  }, [p, queue, notifyError])

  // The entry moves to the other stack only once the change really went out
  // (a cancelled reason dialog leaves the history as it was).
  // Undo / redo run one after the other, and each waits until the step's own
  // save answered: what the server did on its own for it (pushed tasks) is in
  // the step by then, so undo and redo stay symmetric.
  const stepChain = useRef<Promise<unknown>>(Promise.resolve())
  const whenSettled = useCallback((id: number) => new Promise<void>((resolve) => {
    if (!history.current.isPending(id)) { resolve(); return }
    const list = settleWaiters.current.get(id) ?? []
    list.push(resolve)
    settleWaiters.current.set(id, list)
  }), [])
  const step = useCallback((which: 'undo' | 'redo') => {
    const run = async () => {
      const peek = which === 'undo' ? history.current.peekUndo() : history.current.peekRedo()
      if (!peek) return
      await whenSettled(peek.id)
      const h = which === 'undo' ? history.current.peekUndo() : history.current.peekRedo()
      if (!h) return
      await commit(h.cs, which === 'undo' ? { undo: h.id } : { redo: h.id })
      bumpHist()
    }
    const next = stepChain.current.then(run, run)
    stepChain.current = next.catch(() => undefined)
    return next
  }, [commit, whenSettled])
  const undo = useCallback(() => step('undo'), [step])
  const redo = useCallback(() => step('redo'), [step])

  // ---------------------------------------------------------------- actions
  const leafKeys = (keys: string[]) => {
    const out = new Set<string>()
    for (const k of keys) {
      if (isSummaryKey(k)) descendants(tree, k).forEach((d) => { if (!isSummaryKey(key(d.id))) out.add(key(d.id)) })
      else out.add(k)
    }
    return [...out].filter((k) => { const t = tree.byId.get(k); return t && canField(t, 'start') })
  }

  const patchesToChangeSet = (patches: Map<string, Partial<GanttTask>>, label: string): ChangeSet | null => {
    const updateTasks: NonNullable<ChangeSet['updateTasks']> = []
    patches.forEach((patch, k) => {
      const t = tree.byId.get(k)
      if (!t) return
      const real: Partial<GanttTask> = {}
      for (const [f, val] of Object.entries(patch)) {
        if ((t as unknown as Record<string, unknown>)[f] !== val) (real as Record<string, unknown>)[f] = val
      }
      if (Object.keys(real).length) updateTasks.push({ id: t.id, patch: real })
    })
    return updateTasks.length ? { label, updateTasks } : null
  }

  const insertTask = (milestone = false) => {
    if (draft) return
    const after = active && active !== draftKey ? tree.byId.get(active) : undefined
    // Under a selected summary the new task becomes its last child; else a sibling of the selected row.
    const afterIsSummary = !!after && isSummaryKey(key(after.id))
    const parentKey = after ? (afterIsSummary ? key(after.id) : tree.parentOf.get(key(after.id)) ?? null) : null
    const parentId = parentKey ? tree.byId.get(parentKey)!.id : null
    // The nearest leaf above the new row (never a summary) gives the lane.
    const above = after ? [after, ...descendants(tree, after.id)] : tree.order
    const leafAbove = [...above].reverse().find((x) => !isSummaryKey(key(x.id)) && key(x.id) !== draftKey)
    const g = leafAbove ? geo.get(key(leafAbove.id)) : undefined
    const start = toIso(g ? (milestone ? g.e : nextWork(cal, g.e)) : nextWork(cal, sched.finish ? toDay(sched.finish) : today))
    const extra = p.newTask?.({ after: leafAbove, parentId, start, milestone }) ?? {}
    const t: GanttTask = {
      id: tempId('task'), parentId, name: '', start,
      duration: milestone ? 0 : 1, lane: leafAbove?.lane ?? null, ...extra,
      ...(milestone ? { duration: 0 } : {}),
    }
    const k = key(t.id)
    setDraft({ task: t, afterKey: after ? key(after.id) : null })
    setSelection([k]); setAnchor(k); setActive(k)
    setEditing({ key: k, col: 'name' })
  }
  /** The draft row got its name: now it is a real change. */
  const confirmDraft = (name: string) => {
    const d = draft
    setDraft(null)
    if (!d || !name) return
    // Order from the model as it is NOW (an earlier insert may have got its real id meanwhile).
    const order = draftOrder(buildTree(modelRef.current.tasks), d.task.id, d.afterKey)
    void commit({ label: d.task.duration === 0 ? 'Insert milestone' : 'Insert task', addTasks: [{ ...d.task, name }], order })
  }

  const deleteSelection = () => {
    if (!canStructure || !selection.length) return
    if (draftKey && selection.includes(draftKey)) { setDraft(null); setEditing(null) }
    const keys = selection.filter((k) => k !== draftKey)
    if (keys.length) void commit(removeTasksChangeSet(saved, idsOf(keys)))
    setSelection([])
  }
  const duplicate = (keys = selection) => {
    if (!canStructure || !keys.length) return
    void commit(duplicateChangeSet(model, idsOf(keys)))
  }
  const doIndent = (dir: 1 | -1) => {
    if (!canStructure || !hierarchy || !selection.length) return
    const cs = dir === 1 ? indent(tree.order, idsOf(selection)) : outdent(tree.order, idsOf(selection))
    void commit(cs)
  }
  const linkSelection = () => {
    if (!canLinks || selection.length < 2) return
    const cs = chainLinksChangeSet({ tasks: tree.order, links: model.links }, idsOf(selection))
    if (!cs) return
    const bad = cs.addLinks!.find((l) => wouldCycle(model.tasks, model.links, l.from, l.to))
    if (bad) { notifyError('Those links would create a loop'); return }
    if (!linkTypes.includes('FS')) { notifyError('Finish-to-start links are not available here'); return }
    void commit(cs)
  }
  const unlinkSelection = () => {
    if (!canLinks || !selection.length) return
    void commit(unlinkChangeSet(model, idsOf(selection)))
  }

  const addLink = (fromKey: string, fromSide: 'start' | 'end', toKey: string, toSide: 'start' | 'end') => {
    const from = tree.byId.get(fromKey), to = tree.byId.get(toKey)
    if (!from || !to || fromKey === toKey) return
    const type = typeFromSides(fromSide, toSide)
    if (!linkTypes.includes(type)) {
      notifyError(`${type} links are not available here${linkTypes.length === 1 ? `: only ${linkTypes[0]}` : ''}`)
      return
    }
    const refusal = linkRefusal(fromKey, toKey, type)
    if (refusal) { notifyError(refusal); return }
    // An old (read-only) dependency on the pair does not block: drawing it again makes the real, editable link.
    if (model.links.some((l) => !l.readOnly && key(l.from) === fromKey && key(l.to) === toKey)) {
      p.onNotify?.('These tasks are already linked: click the link to change its type or lag')
      return
    }
    if (wouldCycle(model.tasks, model.links, from.id, to.id)) { notifyError('That link would create a loop'); return }
    void commit({ label: 'Link tasks', addLinks: [{ id: tempId('link'), from: from.id, to: to.id, type, lagDays: 0 }] })
  }

  remapViewRef.current = (m) => {
    const has = (k: string | null | undefined) => k != null && k in m
    const rk = (k: string) => (k in m ? key(m[k]) : k)
    setSelection((sel) => (sel.some(has) ? sel.map(rk) : sel))
    setActive((a) => (has(a) ? rk(a!) : a))
    setAnchor((a) => (has(a) ? rk(a!) : a))
    setDialogKey((d) => (has(d) ? rk(d!) : d))
    setEditing((ed) => (ed && has(ed.key) ? { ...ed, key: rk(ed.key) } : ed))
    setCollapsed((c) => ([...c].some(has) ? new Set([...c].map(rk)) : c))
    setDraft((d) => {
      if (!d) return d
      const pid = d.task.parentId
      const np = pid != null && has(key(pid)) ? m[key(pid)] : pid
      const na = has(d.afterKey) ? rk(d.afterKey!) : d.afterKey
      return np === pid && na === d.afterKey ? d : { task: { ...d.task, parentId: np }, afterKey: na }
    })
  }

  /** What the server refuses for a link (spec §11 summary rule), as a message; null when allowed. */
  const linkRefusal = (fromKey: string, toKey: string, type: LinkType): string | null => {
    let a = tree.parentOf.get(toKey) ?? null
    while (a) { if (a === fromKey) return 'A summary task cannot be linked to a task under it'; a = tree.parentOf.get(a) ?? null }
    a = tree.parentOf.get(fromKey) ?? null
    while (a) { if (a === toKey) return 'A task cannot be linked to its own summary'; a = tree.parentOf.get(a) ?? null }
    if (isSummaryKey(toKey) && (type === 'FF' || type === 'SF')) return `${type} links into a summary task are not allowed: link to a task under it`
    return null
  }

  const focusTask = useCallback((id: GanttId) => {
    const k = key(id)
    // Expand collapsed ancestors / groups.
    const t = tree.byId.get(k)
    if (!t) return
    setCollapsed((c) => {
      const n = new Set(c)
      let cur = tree.parentOf.get(k) ?? null
      while (cur) { n.delete(cur); cur = tree.parentOf.get(cur) ?? null }
      for (const x of [...n]) if (x.startsWith('group:')) n.delete(x)
      return n.size === c.size ? c : n
    })
    setSelection([k]); setAnchor(k); setActive(k)
    setFlashKey(k)
    setTimeout(() => setFlashKey((f) => (f === k ? null : f)), 1600)
    requestAnimationFrame(() => {
      const el = scrollerRef.current
      const i = rowModelRef.current.index.get(k)
      if (!el || i == null) return
      el.scrollTop = Math.max(0, i * rowH - 2 * rowH)
      const g = geoRef.current.get(k)
      if (g) el.scrollLeft = Math.max(0, xOf(g.s, rangeRef.current, ppdRef.current) - 60)
    })
  }, [tree, rowH])
  const rowModelRef = useRef(rowModel); rowModelRef.current = rowModel
  const geoRef = useRef(geo); geoRef.current = geo
  const rangeRef = useRef(range); rangeRef.current = range
  const ppdRef = useRef(ppd); ppdRef.current = ppd

  // ---------------------------------------------------------------- exports
  const exportName = p.exportName ?? 'plan'
  const svgInput = () => {
    const all = buildRows(model.tasks, { groupByLane: p.groupByLane }).rows
    // The image has room: the name column fits the longest name (capped).
    const longest = Math.max(0, ...all.map((r) => (r.type === 'task' ? textWidth(r.task.name, 11) + r.depth * 14 + 24 : 0)))
    const cols = columns.map((c) => (c.key === 'name' ? { ...c, width: Math.max(c.width, Math.min(420, Math.ceil(longest))) } : c))
    return svgInputFor(all, cols)
  }
  const svgInputFor = (rowsAll: typeof rows, cols: GanttColumn[]) => ({
    title: exportName, rows: rowsAll, columns: cols, ctx: cellCtx, geo,
    links: model.links, range, ppd, unit, cal, theme: resolveTheme(rootRef.current, theme), kinds,
    markers: p.markers ?? [], today: p.showToday === false ? null : today, critical: criticalSet, showBaselines, rowH,
  })
  const exportPng = async () => {
    try {
      const { svg, width, height } = buildChartSvg(svgInput())
      downloadBlob(await svgToPng(svg, width, height), `${exportName}.png`)
    } catch (e) { notifyError(errMessage(e), e) }
  }
  const print = () => {
    const { svg } = buildChartSvg(svgInput())
    if (!openPrint(svg, exportName)) notifyError('The print window was blocked by the browser')
  }
  const exportData = (fmt: 'mspdi' | 'csv') => {
    if (p.onExport) { p.onExport(fmt); return }
    const text = fmt === 'mspdi'
      ? exportMspdi(tree.order, model.links, { name: `${exportName}.xml`, title: exportName, calendar: p.calendar })
      : exportCsv(tree.order, model.links, p.calendar)
    downloadBlob(new Blob([text], { type: fmt === 'mspdi' ? 'application/xml' : 'text/csv' }), `${exportName}.${fmt === 'mspdi' ? 'xml' : 'csv'}`)
  }

  useImperativeHandle(ref, () => ({
    focusTask, undo: () => void undo(), redo: () => void redo(), fit: () => changeZoom('fit'),
    exportPng, print, select: (ids) => setSelection(ids.map(key)), getModel: () => modelRef.current,
    apply: (cs) => commit(cs),
    insertTask: (milestone) => insertTask(!!milestone),
    setFullScreen: (on) => setFull(on),
    clearHistory: () => { history.current.clear(); bumpHist() },
  }))

  // ---------------------------------------------------------------- pointer: bars
  const latest = useRef({ ppd, tree, geo, commit, cal })
  latest.current = { ppd, tree, geo, commit, cal }

  const onBarDown = (e: ReactPointerEvent, t: GanttTask, mode: DragMode) => {
    if (e.button !== 0) return
    e.stopPropagation()
    e.preventDefault()
    rootRef.current?.focus({ preventScroll: true })
    setLinkPop(null); setMenu(null)
    const k = key(t.id)
    const additive = e.shiftKey || e.ctrlKey || e.metaKey
    const movable = mode === 'progress' ? canProgress(t) : canField(t, 'start')
    let keys: string[]
    if (mode === 'move') keys = leafKeys(selSet.has(k) && selection.length > 1 ? selection : [k])
    else if (mode === 'progress') keys = [k]
    else keys = leafKeys(selSet.has(k) && selection.length > 1 ? selection : [k]).filter((x) => (tree.byId.get(x)?.duration ?? 0) > 0)
    const x0 = e.clientX, y0 = e.clientY
    let moved = false
    const g = geo.get(k)
    const bx = g ? barGeo(g.s, g.e, range, ppd, g.milestone) : null
    const startProgress = Math.round(t.progress ?? 0)
    // Re-render only when the snapped value changes, at most once per frame.
    let last: number | null = null
    let frame = 0
    const onMove = (ev: PointerEvent) => {
      const dx = ev.clientX - x0
      if (!moved && Math.abs(dx) < 3 && Math.abs(ev.clientY - y0) < 3) return
      moved = true
      if (!movable || !keys.length) return
      const value = mode === 'progress' && bx
        ? Math.max(0, Math.min(100, Math.round((startProgress + (dx / Math.max(1, bx.w)) * 100) / 5) * 5))
        : snapDays(dx, latest.current.ppd)
      if (value === last) return
      last = value
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        setDrag(mode === 'progress' ? { mode, keys, delta: 0, progress: value } : { mode, keys, delta: value })
      })
    }
    const onUp = async (ev: PointerEvent) => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
      cancelAnimationFrame(frame)
      if (ev.type === 'pointercancel') { setDrag(null); return }
      if (!moved) {
        setDrag(null)
        selectKey(k, { ctrlKey: additive && !ev.shiftKey, metaKey: false, shiftKey: ev.shiftKey })
        return
      }
      if (!movable || !keys.length) { setDrag(null); return }
      const dx = ev.clientX - x0
      const final: DragState = mode === 'progress' && bx
        ? { mode, keys, delta: 0, progress: Math.max(0, Math.min(100, Math.round((startProgress + (dx / Math.max(1, bx.w)) * 100) / 5) * 5)) }
        : { mode, keys, delta: snapDays(dx, latest.current.ppd) }
      setDrag(final)
      const patches = computePatchesRef.current(final)
      const label = mode === 'progress' ? 'Progress' : mode === 'move' ? (keys.length > 1 ? `Move ${keys.length} tasks` : 'Move task') : 'Resize task'
      await latest.current.commit(patchesToChangeSetRef.current(patches, label))
      setDrag(null)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
  }
  const patchesToChangeSetRef = useRef(patchesToChangeSet)
  patchesToChangeSetRef.current = patchesToChangeSet

  /** Same rules as dragPatches, for a given state (used at pointer up). */
  const computePatches = (d: DragState) => {
    const out = new Map<string, Partial<GanttTask>>()
    for (const k of d.keys) {
      const t = tree.byId.get(k)
      if (!t) continue
      const s = normStart(cal, toDay(t.start))
      const e = endOf(cal, s, t.duration)
      if (d.mode === 'progress') { if (d.progress != null) out.set(k, { progress: d.progress }); continue }
      if (d.delta === 0) continue
      if (d.mode === 'move') out.set(k, { start: toIso(d.unit === 'work' ? cal.dateAt(cal.idx(s) + d.delta) : nextWork(cal, s + d.delta)) })
      else if (d.mode === 'end' && t.duration > 0) out.set(k, { duration: Math.max(1, working ? diff(cal, s, e + d.delta) : t.duration + d.delta) })
      else if (d.mode === 'start' && t.duration > 0) {
        const ns = nextWork(cal, Math.min(s + d.delta, e - 1))
        out.set(k, { start: toIso(ns), duration: Math.max(1, working ? diff(cal, ns, e) : e - ns) })
      }
    }
    return out
  }

  // ---------------------------------------------------------------- pointer: links
  const svgPoint = (cx: number, cy: number) => {
    const r = svgRef.current?.getBoundingClientRect()
    return { x: cx - (r?.left ?? 0), y: cy - (r?.top ?? 0) }
  }
  const onLinkHandleDown = (e: ReactPointerEvent, t: GanttTask, side: 'start' | 'end') => {
    if (e.button !== 0 || !canLinks) return
    e.stopPropagation()
    e.preventDefault()
    const k = key(t.id)
    const i = index.get(k)
    const g = geo.get(k)
    if (i == null || !g) return
    const b = barGeo(g.s, g.e, range, ppd, g.milestone)
    const x1 = anchorX(b, side) + (side === 'start' ? -5 : 5)
    const y1 = i * rowH + rowH / 2
    let moved = false
    let frame = 0
    const onMove = (ev: PointerEvent) => {
      moved = true
      const pt = svgPoint(ev.clientX, ev.clientY)
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => setLinkDraft({ x1, y1, x2: pt.x, y2: pt.y }))
    }
    const onUp = (ev: PointerEvent) => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
      cancelAnimationFrame(frame)
      setLinkDraft(null)
      if (!moved || ev.type === 'pointercancel') return
      const el = (typeof document.elementFromPoint === 'function' ? document.elementFromPoint(ev.clientX, ev.clientY) : null)
        ?? (ev.target as Element | null)
      const hit = el?.closest?.('[data-task-id]')
      const toKey = hit?.getAttribute('data-task-id')
      if (!toKey || toKey === k) return
      let toSide = (el?.getAttribute?.('data-side') as 'start' | 'end' | null) ?? null
      if (!toSide) {
        const tg = geoRef.current.get(toKey)
        const pt = svgPoint(ev.clientX, ev.clientY)
        if (tg) {
          const tb = barGeo(tg.s, tg.e, rangeRef.current, ppdRef.current, tg.milestone)
          toSide = pt.x > tb.x + tb.w / 2 && !tg.milestone ? 'end' : 'start'
        } else toSide = 'start'
      }
      addLinkRef.current(k, side, toKey, toSide)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
  }
  const addLinkRef = useRef(addLink)
  addLinkRef.current = addLink

  // ---------------------------------------------------------------- pointer: row reorder
  const onReorderDown = (e: ReactPointerEvent, t: GanttTask) => {
    if (e.button !== 0 || !canStructure) return
    const k = key(t.id)
    const y0 = e.clientY
    let target: { index: number; where: 'before' | 'after' } | null = null
    const gridEl = (e.currentTarget as HTMLElement).closest('[data-testid="gantt-grid"]') as HTMLElement | null
    const onMove = (ev: PointerEvent) => {
      if (Math.abs(ev.clientY - y0) < 4 && !target) return
      const top = gridEl?.getBoundingClientRect().top ?? 0
      const y = ev.clientY - top
      const i = Math.max(0, Math.min(rows.length - 1, Math.floor(y / rowH)))
      const where: 'before' | 'after' = y - i * rowH < rowH / 2 ? 'before' : 'after'
      target = { index: i, where }
      setDropLine(target)
    }
    const onUp = (ev: PointerEvent) => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
      setDropLine(null)
      if (!target || ev.type === 'pointercancel') return
      const r = rows[target.index]
      const keys = selSet.has(k) ? selection : [k]
      if (r.type === 'group') {
        // Dropped on a group header: first task of that group, before it.
        const next = rows.slice(target.index + 1).find((x) => x.type === 'task')
        if (next?.type !== 'task') return
        moveTo(keys, key(next.task.id), 'before', r.label)
        return
      }
      moveTo(keys, key(r.task.id), target.where, p.groupByLane ? (r.group ?? undefined) : undefined)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
  }
  const moveTo = (keys: string[], targetKey: string, where: 'before' | 'after', lane?: string) => {
    const cs = moveRows(tree.order, idsOf(keys), tree.byId.get(targetKey)!.id, where)
    const lanePatches = lane !== undefined && p.groupByLane
      ? keys.map((k) => tree.byId.get(k)!).filter((t) => (t.lane ?? '').trim() !== (lane === 'Unassigned' ? '' : lane))
        .map((t) => ({ id: t.id, patch: { lane: lane === 'Unassigned' ? null : lane } }))
      : []
    if (!cs && !lanePatches.length) return
    void commit({ label: cs?.label ?? 'Move row', updateTasks: [...(cs?.updateTasks ?? []), ...lanePatches], ...(cs?.order ? { order: cs.order } : {}) })
  }

  // ---------------------------------------------------------------- grid edits
  const commitEdit = (t: GanttTask, col: GanttColumn, value: string) => {
    setEditing(null)
    const k = key(t.id)
    const val = value.trim()
    if (k === draftKey) { if (col.key === 'name') confirmDraft(val); return }
    const patch = (pt: Partial<GanttTask>, label: string) => void commit(patchesToChangeSet(new Map([[k, pt]]), label))
    switch (col.key) {
      case 'name':
        if (!val) { notifyError('A task needs a name'); return }
        patch({ name: val }, 'Rename task'); return
      case 'lane': patch({ lane: val || null }, 'Change lane'); return
      case 'start':
        if (val === '') { notifyError('Start is required'); return }
        if (!isIsoDay(val)) { notifyError(readDateInput(val).error ?? 'Type the date as dd.mm.yyyy'); return }
        if (!inYearRange(val)) { notifyError(`Dates must lie between ${LIMITS.minYear} and ${LIMITS.maxYear}`); return }
        patch({ start: val }, 'Change start'); return
      case 'end': {
        if (val === '') return
        if (!isIsoDay(val)) { notifyError(readDateInput(val).error ?? 'Type the date as dd.mm.yyyy'); return }
        if (!inYearRange(val)) { notifyError(`Dates must lie between ${LIMITS.minYear} and ${LIMITS.maxYear}`); return }
        if (t.duration === 0) { patch({ start: val }, 'Move milestone'); return }
        const s = normStart(cal, toDay(t.start))
        if (toDay(val) < s) { notifyError('The finish cannot be before the start'); return }
        patch({ duration: durationFromLastDay(cal, s, toDay(val)) }, 'Change finish'); return
      }
      case 'duration': {
        // An emptied field keeps the value (Number('') would turn the task into a milestone).
        if (val === '') return
        const n = Math.round(Number(val.replace(/[a-z]+$/i, '')))
        if (!Number.isFinite(n) || n < 0) { notifyError('The duration must be 0 or more days'); return }
        if (n > LIMITS.maxDuration) { notifyError(`A task lasts at most ${LIMITS.maxDuration} days`); return }
        patch({ duration: n }, 'Change duration'); return
      }
      case 'actualStart': case 'actualEnd': {
        if (val !== '' && !isIsoDay(val)) { notifyError(readDateInput(val).error ?? 'Type the date as dd.mm.yyyy'); return }
        if (val && val > toIso(todayDay() + 1)) { notifyError('Actual dates cannot lie in the future'); return }
        patch(col.key === 'actualStart' ? { actualStart: val || null } : { actualEnd: val || null }, 'Actual dates'); return
      }
      case 'progress': {
        if (val === '') return
        const n = Math.round(Number(val.replace('%', '')))
        if (!Number.isFinite(n)) return
        patch({ progress: Math.max(0, Math.min(100, n)) }, 'Progress'); return
      }
      case 'predecessors': {
        const { changes, errors } = predecessorChangeSet(t.id, val, tree.order, model.links, cal.mode)
        if (errors.length) { notifyError(errors[0]); return }
        if (!changes) return
        const added = [...(changes.addLinks ?? []), ...(changes.updateLinks ?? []).map((u) => ({ ...model.links.find((l) => key(l.id) === key(u.id))!, ...u.patch }))]
        const touched = [...(changes.updateLinks ?? []).map((u) => u.id), ...(changes.removeLinks ?? [])]
        if (model.links.some((l) => l.readOnly && touched.some((id) => key(id) === key(l.id)))) {
          notifyError('This is an old dependency: draw the link again on the chart to replace it, then edit or remove it')
          return
        }
        const refused = added.map((l) => linkRefusal(key(l.from), key(l.to), l.type)).find(Boolean)
        if (refused) { notifyError(refused); return }
        const badType = added.find((l) => !linkTypes.includes(l.type))
        if (badType) { notifyError(`${badType.type} links are not available here`); return }
        if (!allowLag && added.some((l) => l.lagDays !== 0)) { notifyError('Lag and lead are not available here'); return }
        if (added.some((l) => Math.abs(l.lagDays) > LIMITS.maxLag)) { notifyError(`A lag or lead is at most ${LIMITS.maxLag} days`); return }
        const after = applyChangeSet(model, changes)
        if (schedule(after.tasks, after.links, p.calendar).cycle.length) { notifyError('Those predecessors would create a loop'); return }
        void commit(changes)
        return
      }
      default: {
        const custom = col as GanttColumn & { apply?: (value: string, t: GanttTask) => Partial<GanttTask> | null }
        const pt = custom.apply?.(val, t)
        if (pt) patch(pt, `Change ${col.title}`)
      }
    }
  }
  const canEditCell = (t: GanttTask, col: GanttColumn) => {
    if (!col.edit) return false
    const k = key(t.id)
    if (k === draftKey) return col.key === 'name'
    if (isSummaryKey(k) && ['start', 'end', 'duration', 'progress', 'actualStart', 'actualEnd'].includes(col.key)) return false
    return canField(t, col.field ?? col.key)
  }

  // ---------------------------------------------------------------- keyboard
  const nudge = useRef<{ keys: string[]; delta: number; timer: ReturnType<typeof setTimeout> | null } | null>(null)
  useEffect(() => () => { if (nudge.current?.timer) clearTimeout(nudge.current.timer) }, [])
  const flushNudge = async () => {
    const n = nudge.current
    nudge.current = null
    if (!n || n.delta === 0) { setDrag(null); return }
    const d: DragState = { mode: 'move', keys: n.keys, delta: n.delta, unit: 'work' }
    await commit(patchesToChangeSetRef.current(computePatchesRef.current(d), n.keys.length > 1 ? `Move ${n.keys.length} tasks` : 'Move task'))
    setDrag(null)
  }
  const computePatchesRef = useRef(computePatches)
  computePatchesRef.current = computePatches
  const flushRef = useRef(flushNudge)
  flushRef.current = flushNudge

  const onKeyDown = (e: ReactKeyboardEvent) => {
    if (p.compact) return
    // Full screen toggles from anywhere in the Gantt (toolbar and editors included).
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'f' || e.key === 'F')) {
      e.preventDefault(); if (p.fullScreen !== false) setFull((f) => !f); return
    }
    if (isTextTarget(e.target)) return
    // Only keys typed in the chart / grid (or on the root after a click there);
    // toolbar buttons, menus and dialogs keep their own keys, Tab keeps moving focus.
    const mod = e.ctrlKey || e.metaKey
    const k = e.key
    const inChart = e.target === rootRef.current || !!scrollerRef.current?.contains(e.target as Node)
    if (!inChart || isControlTarget(e.target)) return
    if (k === 'Escape') {
      // In full screen an open popup gets Escape first; the next one closes the
      // layer and keeps the selection (the window listener sees preventDefault).
      if (full) {
        e.preventDefault()
        if (menu || linkPop || editing || draft) { setEditing(null); setDraft(null); setMenu(null); setLinkPop(null) } else setFull(false)
        return
      }
      setSelection([]); setEditing(null); setDraft(null); setMenu(null); setLinkPop(null); return
    }
    if (mod && (k === 'z' || k === 'Z')) { e.preventDefault(); if (e.shiftKey) void redo(); else void undo(); return }
    if (mod && (k === 'y' || k === 'Y')) { e.preventDefault(); void redo(); return }
    if (mod && (k === 'a' || k === 'A')) { e.preventDefault(); setSelection(taskRows); return }
    if (mod && (k === 'd' || k === 'D')) { e.preventDefault(); duplicate(); return }
    if (mod && (k === 'c' || k === 'C')) { clipboard.current = [...selection]; return }
    if (mod && (k === 'v' || k === 'V')) { e.preventDefault(); duplicate(clipboard.current.filter((x) => tree.byId.has(x))); return }
    if (k === 'Insert') { e.preventDefault(); if (canStructure) insertTask(); return }
    if (k === 'Tab') { if (!canStructure || !hierarchy || !selection.length) return; e.preventDefault(); doIndent(e.shiftKey ? -1 : 1); return }
    if ((k === 'Delete' || k === 'Backspace') && selection.length) { e.preventDefault(); deleteSelection(); return }
    if ((k === 'Enter' || k === 'F2') && active) {
      e.preventDefault()
      const t = tree.byId.get(active)
      if (k === 'F2') { if (t && canField(t, 'name')) setEditing({ key: active, col: 'name' }) }
      else if (t) openTask(t)
      return
    }
    if (k === 'ArrowUp' || k === 'ArrowDown') {
      e.preventDefault()
      if (!taskRows.length) return
      const i = active ? taskRows.indexOf(active) : -1
      const ni = Math.max(0, Math.min(taskRows.length - 1, i + (k === 'ArrowDown' ? 1 : -1)))
      const nk = taskRows[ni]
      selectKey(nk, { shiftKey: e.shiftKey })
      const el = scrollerRef.current
      if (el) {
        const idx = index.get(nk) ?? 0
        const top = idx * rowH, bottom = top + rowH
        const viewTop = el.scrollTop, viewBottom = el.scrollTop + el.clientHeight - headerH
        if (top < viewTop) el.scrollTop = top
        else if (bottom > viewBottom && el.clientHeight) el.scrollTop = bottom - (el.clientHeight - headerH)
      }
      return
    }
    if ((k === 'ArrowLeft' || k === 'ArrowRight') && selection.length && canDates) {
      e.preventDefault()
      // One working day (calendar: one day); shift: a week (5 working days / 7 days).
      const step = (k === 'ArrowLeft' ? -1 : 1) * (e.shiftKey ? (working ? 5 : 7) : 1)
      const keys = nudge.current?.keys ?? leafKeys(selection)
      if (!keys.length) return
      if (nudge.current?.timer) clearTimeout(nudge.current.timer)
      const delta = (nudge.current?.delta ?? 0) + step
      nudge.current = { keys, delta, timer: setTimeout(() => { void flushRef.current() }, 450) }
      setDrag({ mode: 'move', keys, delta, unit: 'work' })
    }
  }
  const clipboard = useRef<string[]>([])

  const openTask = (t: GanttTask) => {
    if (p.onTaskOpen) p.onTaskOpen(t)
    else setDialogKey(key(t.id))
  }

  // ---------------------------------------------------------------- menu
  const menuEntries = (): MenuEntry[] => {
    const ids = idsOf(selection)
    const one = selection.length === 1 ? tree.byId.get(selection[0]) : undefined
    const items: MenuEntry[] = []
    if (one) items.push({ label: 'Task information', onSelect: () => openTask(one), shortcut: 'Enter', testId: 'gantt-menu-open' })
    if (one) items.push({ label: 'Scroll to task', onSelect: () => focusTask(one.id) })
    if (canStructure) {
      items.push('separator')
      items.push({ label: 'Insert task', onSelect: () => insertTask(), shortcut: 'Ins', testId: 'gantt-menu-insert' })
      items.push({ label: 'Insert milestone', onSelect: () => insertTask(true), testId: 'gantt-menu-milestone' })
      items.push({ label: 'Duplicate', onSelect: () => duplicate(), shortcut: 'Ctrl+D', disabled: !ids.length, testId: 'gantt-menu-duplicate' })
      if (hierarchy) {
        items.push({ label: 'Indent', onSelect: () => doIndent(1), shortcut: 'Tab', disabled: !ids.length, testId: 'gantt-menu-indent' })
        items.push({ label: 'Outdent', onSelect: () => doIndent(-1), shortcut: 'Shift+Tab', disabled: !ids.length, testId: 'gantt-menu-outdent' })
      }
    }
    if (canLinks) {
      items.push('separator')
      items.push({ label: 'Link tasks', onSelect: linkSelection, disabled: ids.length < 2, testId: 'gantt-menu-link' })
      items.push({ label: 'Unlink tasks', onSelect: unlinkSelection, disabled: !ids.length, testId: 'gantt-menu-unlink' })
    }
    const extra = p.menuItems?.(ids) ?? []
    if (extra.length) items.push('separator', ...extra)
    if (canStructure) {
      items.push('separator')
      items.push({ label: ids.length > 1 ? `Delete ${ids.length} tasks` : 'Delete task', onSelect: deleteSelection, danger: true, disabled: !ids.length, shortcut: 'Del', testId: 'gantt-menu-delete' })
    }
    while (items[0] === 'separator') items.shift()
    return items.filter((x, i, a) => !(x === 'separator' && a[i - 1] === 'separator'))
  }
  const openMenu = (e: React.MouseEvent, t: GanttTask) => {
    if (p.compact) return
    e.preventDefault()
    const k = key(t.id)
    if (!selSet.has(k)) { setSelection([k]); setAnchor(k) }
    setActive(k)
    setMenu({ x: e.clientX, y: e.clientY })
  }

  // ---------------------------------------------------------------- full screen
  useEffect(() => {
    if (!full) return
    fullReturnFocus.current = (document.activeElement as HTMLElement | null) ?? null
    const rootEl = rootRef.current
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    // Focus into the layer: the chart.
    requestAnimationFrame(() => scrollerRef.current?.focus({ preventScroll: true }))
    // Escape closes, unless something inside takes it first (a dialog, a menu,
    // a popover or an inline editor handle it and stop it, or are open).
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      const t = e.target as Element | null
      if (t && (/INPUT|TEXTAREA|SELECT/.test(t.tagName) || (t as HTMLElement).isContentEditable)) return
      if (document.querySelector('[role=dialog], [role=menu], [data-testid=date-popover]')) return
      e.preventDefault()
      setFull(false)
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
      // Focus goes back where it was, unless the user is typing in a cell
      // editor right now (moving focus would commit or drop the edit).
      const now = document.activeElement as HTMLElement | null
      const typing = !!now && !!rootEl?.contains(now) && isTextTarget(now)
      const back = fullReturnFocus.current
      if (!typing && back && document.contains(back)) back.focus({ preventScroll: true })
    }
  }, [full])

  // ---------------------------------------------------------------- stable handlers (memoised panes)
  const linkLabel = (l: GanttLink) => {
    const f = tree.byId.get(key(l.from)), t = tree.byId.get(key(l.to))
    const lag = l.lagDays ? ` ${l.lagDays > 0 ? '+' : ''}${l.lagDays}d` : ''
    return `${l.type}${lag}: #${rowNo.get(key(l.from)) ?? '?'} ${f?.name ?? ''} to #${rowNo.get(key(l.to)) ?? '?'} ${t?.name ?? ''}`
  }
  const h = {
    canEditCell: useStable(canEditCell),
    rowClick: useStable((e: React.MouseEvent, t: GanttTask) => { if (!p.compact) selectKey(key(t.id), e) }),
    rowDouble: useStable((t: GanttTask) => { if (!p.compact) openTask(t) }),
    openMenu: useStable(openMenu),
    toggle: useStable((rk: string) => setCollapsed((c) => { const n = new Set(c); if (n.has(rk)) n.delete(rk); else n.add(rk); return n })),
    startEdit: useStable((t: GanttTask, col: string) => setEditing({ key: key(t.id), col })),
    commitEdit: useStable(commitEdit),
    cancelEdit: useStable(() => { if (editing?.key === draftKey) setDraft(null); setEditing(null) }),
    reorderDown: useStable(onReorderDown),
    linkLabel: useStable(linkLabel),
    canDrag: useStable((t: GanttTask) => !p.compact && canField(t, 'start')),
    canProgressBar: useStable((t: GanttTask) => !p.compact && canProgress(t)),
    barDown: useStable(onBarDown),
    linkHandleDown: useStable(onLinkHandleDown),
    linkClick: useStable((e: React.MouseEvent, l: GanttLink) => { if (!p.compact) setLinkPop({ id: key(l.id), x: e.clientX, y: e.clientY }) }),
    /** Keyboard on a focused link: Enter / Space edits it, Delete removes it. */
    linkKey: useStable((e: React.KeyboardEvent, l: GanttLink) => {
      if (p.compact) return
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault(); e.stopPropagation()
        const r = (e.currentTarget as Element).getBoundingClientRect?.()
        setLinkPop({ id: key(l.id), x: r ? r.left + r.width / 2 : 200, y: r ? r.top + r.height / 2 : 200 })
      } else if ((e.key === 'Delete' || e.key === 'Backspace') && canLinks && !l.readOnly) {
        e.preventDefault(); e.stopPropagation()
        void commit({ label: 'Remove link', removeLinks: [l.id] })
      }
    }),
    /** Keyboard on a focused bar: Space selects, Enter opens. */
    barKey: useStable((e: React.KeyboardEvent, t: GanttTask) => {
      if (p.compact) return
      if (e.key === ' ') { e.preventDefault(); e.stopPropagation(); selectKey(key(t.id), e) }
      else if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); selectKey(key(t.id)); openTask(t) }
    }),
    backgroundDown: useStable((e: ReactPointerEvent) => {
      rootRef.current?.focus({ preventScroll: true })
      if (!(e.shiftKey || e.ctrlKey || e.metaKey)) setSelection([])
    }),
  }

  // ---------------------------------------------------------------- render
  const vars = themeVars(theme)
  const bodyH = Math.max(rows.length, 1) * rowH
  const heightCss = p.height ?? (p.compact ? 320 : '70vh')
  const popLink = linkPop ? model.links.find((l) => key(l.id) === linkPop.id) : undefined
  const dialogTask = dialogKey ? tree.byId.get(dialogKey) : undefined
  const hasBaselines = model.tasks.some((t) => t.baselineStart)
  const btn = 'inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-40'
  const btnStyle = { borderColor: v('gridLine'), background: v('panel'), color: v('text') }
  const TB = ({ label, onClick, disabled, testId, title, pressed }: { label: ReactNode; onClick: (e?: React.MouseEvent) => void; disabled?: boolean; testId: string; title: string; pressed?: boolean }) => (
    <button type="button" className={btn} style={pressed ? { ...btnStyle, background: v('accent'), color: '#fff', borderColor: v('accent') } : btnStyle}
      onClick={onClick} disabled={disabled} data-testid={testId} title={title} aria-label={title} aria-pressed={pressed}>{label}</button>
  )
  const [exportOpen, setExportOpen] = useState(false)
  const [tasksMenu, setTasksMenu] = useState<{ x: number; y: number } | null>(null)

  return (
    <div ref={rootRef} tabIndex={-1} onKeyDown={onKeyDown} data-testid="gantt-root" data-theme={p.theme ?? 'dark'}
      data-full-screen={full || undefined}
      className={full
        ? 'fixed inset-0 z-[45] !m-0 flex flex-col gap-2 overflow-hidden p-3'
        : `space-y-2 ${p.className ?? ''}`}
      style={{ ...(vars as React.CSSProperties), outline: 'none', ...(full ? { background: v('bg') } : {}) }}
      role={full ? 'region' : undefined}
      aria-label={full ? `${p.title ?? p.ariaLabel ?? 'Gantt planner'} (full screen)` : p.ariaLabel ?? 'Gantt planner'}>
      {full && (
        <div className="flex shrink-0 items-center gap-3 border-b pb-2" style={{ borderColor: v('gridLine') }} data-testid="gantt-full-header">
          <h2 className="truncate text-sm font-semibold" style={{ color: v('text') }}>{p.title ?? p.ariaLabel ?? 'Plan'}</h2>
          <span className="text-[11px]" style={{ color: v('textFaint') }}>Esc or Ctrl+Shift+F closes</span>
          <button type="button" className="ml-auto rounded-md border px-2 py-1 text-xs" data-testid="gantt-full-close"
            style={{ borderColor: v('gridLine'), color: v('text'), background: v('panel') }}
            aria-label="Close full screen" onClick={() => setFull(false)}>Close &#10005;</button>
        </div>
      )}
      {p.above != null && (
        <div className={full ? 'max-h-[35vh] shrink-0 overflow-y-auto' : undefined} data-testid="gantt-above">{p.above}</div>
      )}
      {p.toolbar !== false && !p.compact && (
        <div className="flex flex-wrap items-center gap-1.5" data-testid="gantt-toolbar" role="toolbar" aria-label="Gantt tools">
          {p.toolbarStart}
          {!readOnly && (canStructure || canDates || canLinks) && (
            <>
              <TB label="Undo" onClick={() => void undo()} disabled={!history.current.canUndo} testId="gantt-undo"
                title={history.current.undoLabel ? `Undo ${history.current.undoLabel} (Ctrl+Z)` : 'Undo (Ctrl+Z)'} />
              <TB label="Redo" onClick={() => void redo()} disabled={!history.current.canRedo} testId="gantt-redo" title="Redo (Ctrl+Y)" />
            </>
          )}
          {canStructure && (
            <>
              <span className="mx-0.5 h-5 w-px" style={{ background: v('gridLine') }} />
              <TB label="+ Task" onClick={() => insertTask()} testId="gantt-add-task" title="Insert a task after the selected row (Insert)" />
              <TB label="+ Milestone" onClick={() => insertTask(true)} testId="gantt-add-milestone" title="Insert a milestone" />
            </>
          )}
          {(canStructure || canLinks) && (
            <div className="relative">
              <TB label="Tasks" onClick={(e?: React.MouseEvent) => {
                const r = (e?.currentTarget as HTMLElement | undefined)?.getBoundingClientRect()
                setTasksMenu(r ? { x: r.left, y: r.bottom + 4 } : { x: 200, y: 80 })
              }} testId="gantt-tasks-menu" title="Indent, outdent, link, unlink or delete the selected tasks" />
              {tasksMenu && (
                <ContextMenu x={tasksMenu.x} y={tasksMenu.y} onClose={() => setTasksMenu(null)} items={[
                  ...(canStructure && hierarchy ? [
                    { label: 'Indent', shortcut: 'Tab', onSelect: () => doIndent(1), disabled: !selection.length, testId: 'gantt-indent' },
                    { label: 'Outdent', shortcut: 'Shift+Tab', onSelect: () => doIndent(-1), disabled: !selection.length, testId: 'gantt-outdent' },
                  ] : []),
                  ...(canLinks ? [
                    { label: 'Link finish-to-start', onSelect: linkSelection, disabled: selection.length < 2, testId: 'gantt-link-selected' },
                    { label: 'Unlink', onSelect: unlinkSelection, disabled: !selection.length, testId: 'gantt-unlink' },
                  ] : []),
                  ...(canStructure ? [
                    { label: 'Delete', shortcut: 'Del', onSelect: deleteSelection, disabled: !selection.length, danger: true, testId: 'gantt-delete' },
                  ] : []),
                ]} />
              )}
            </div>
          )}
          <div className="ml-auto flex flex-wrap items-center gap-1.5">
            {queue.saving && (
              <span className="flex items-center gap-1.5 text-[11px]" style={{ color: v('textMuted') }} data-testid="gantt-saving" role="status">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full" style={{ background: v('accent') }} />Saving
              </span>
            )}
            <TB label="Critical path" onClick={() => setShowCritical((x) => !x)} pressed={showCritical} testId="gantt-critical-toggle" title="Show the critical path" />
            {hasBaselines && (
              <TB label="Baseline" onClick={() => setShowBaselines((x) => !x)} pressed={showBaselines} testId="gantt-baseline-toggle" title="Show baselines and slip" />
            )}
            <div className="inline-flex overflow-hidden rounded-md border" role="group" aria-label="Zoom" style={{ borderColor: v('gridLine') }}>
              {[...ZOOMS, 'fit' as const].map((z) => (
                <button key={z} type="button" aria-pressed={zoom === z} data-testid={`gantt-zoom-${z}`}
                  aria-label={z === 'fit' ? 'Fit the plan to the width' : `Zoom to ${z}s`}
                  className="px-2 py-1 text-xs capitalize"
                  style={zoom === z ? { background: v('accent'), color: '#fff' } : { background: v('panel'), color: v('textMuted') }}
                  onClick={() => changeZoom(z)}>{z}</button>
              ))}
            </div>
            <div className="relative">
              <TB label="Export" onClick={() => setExportOpen((o) => !o)} testId="gantt-export" title="Export or print the plan" />
              {exportOpen && (
                <ContextMenu x={(rootRef.current?.getBoundingClientRect().right ?? 400) - 220} y={(rootRef.current?.getBoundingClientRect().top ?? 0) + 34}
                  onClose={() => setExportOpen(false)} items={[
                    { label: 'Chart image (.png)', onSelect: () => void exportPng(), testId: 'gantt-export-png' },
                    { label: 'Print', onSelect: print, testId: 'gantt-export-print' },
                    'separator',
                    { label: 'MS Project (.xml)', onSelect: () => exportData('mspdi'), testId: 'gantt-export-xml' },
                    { label: 'Spreadsheet (.csv)', onSelect: () => exportData('csv'), testId: 'gantt-export-csv' },
                  ]} />
              )}
            </div>
            {p.toolbarEnd}
            {p.fullScreen !== false && (
              <button type="button" className={btn} style={full ? { ...btnStyle, background: v('accent'), color: '#fff', borderColor: v('accent') } : btnStyle}
                onClick={() => setFull((f) => !f)} data-testid="gantt-full-screen" aria-pressed={full}
                aria-label="Full screen" title={full ? 'Leave full screen (Esc, Ctrl+Shift+F)' : 'Full screen (Ctrl+Shift+F)'}>
                <span aria-hidden="true">{full ? '\u2923' : '\u2922'}</span>
              </button>
            )}
          </div>
        </div>
      )}

      <div ref={scrollerRef} onScroll={onScroll} data-testid="gantt-scroller" tabIndex={0}
        aria-label="Plan chart. Arrow keys select rows; with tasks selected, left and right move them."
        className={`relative overflow-auto rounded-lg border outline-none focus-visible:ring-1 ${full ? 'min-h-0 flex-1' : ''}`}
        style={{ height: full ? undefined : heightCss, maxHeight: p.compact && !full ? 320 : undefined, borderColor: v('gridLine'), background: v('bg') }}>
        <div style={{ width: gw + chartW, position: 'relative' }}>
          <div className="sticky top-0 z-20 flex" style={{ height: headerH }}>
            <div className="sticky left-0 z-30 border-r" style={{ borderColor: v('gridLine'), background: v('headerBg') }}>
              <GridHeader columns={columns} height={headerH} extra={!p.compact && allColumns.length > 1 ? (
                <ColumnPicker all={allColumns} shown={columns} dropped={dropped} open={colPicker} onOpen={setColPicker}
                  onToggle={(k, on) => setColPrefs((cp) => ({
                    show: on ? [...cp.show.filter((x) => x !== k), k] : cp.show.filter((x) => x !== k),
                    hide: on ? cp.hide.filter((x) => x !== k) : [...cp.hide.filter((x) => x !== k), k],
                  }))} />
              ) : undefined} />
            </div>
            <ChartHeader range={range} ppd={ppd} unit={unit} today={p.showToday === false ? null : today}
              markers={p.markers ?? []} scrollerRef={scrollerRef} cal={cal} />
          </div>
          <div className="flex" style={{ height: bodyH }}>
            <div className="sticky left-0 z-10 border-r" style={{ borderColor: v('gridLine'), background: v('bg') }}>
              <GridBody columns={columns} rows={displayRows} rowH={rowH} first={win.first} last={win.last}
                selected={selSet} flashKey={flashKey} flagged={flagged} pending={queue.pendingIds} ctx={cellCtx}
                canEdit={h.canEditCell} canReorder={canStructure} editing={editing} dropLine={dropLine} activeKey={active}
                onRowClick={h.rowClick} onRowDoubleClick={h.rowDouble} onRowContext={h.openMenu}
                onToggle={h.toggle} onStartEdit={h.startEdit} onCommitEdit={h.commitEdit}
                onCancelEdit={h.cancelEdit} onReorderDown={h.reorderDown} />
            </div>
            <ChartBody uid={uid} rows={displayRows} rowH={rowH} first={win.first} last={win.last} range={range} ppd={ppd}
              unit={unit} cal={cal} geo={geo} links={model.links} kinds={kinds} selected={selSet} critical={criticalSet}
              showBaselines={showBaselines} showProgress={p.showProgress ?? false} pending={queue.pendingIds}
              flashKey={flashKey} markers={p.markers ?? []} today={p.showToday === false ? null : today}
              linkLabels={h.linkLabel} brokenLinks={brokenLinks}
              canDrag={h.canDrag} canLink={canLinks} canProgress={h.canProgressBar}
              linkDraft={linkDraft} svgRef={svgRef}
              onBarDown={p.compact ? undefined : h.barDown}
              onLinkHandleDown={h.linkHandleDown}
              onLinkClick={h.linkClick} onLinkKey={h.linkKey}
              onBackgroundDown={p.compact ? undefined : h.backgroundDown}
              onBarContext={h.openMenu} onBarDoubleClick={h.rowDouble} onBarKey={h.barKey} />
          </div>
        </div>
      </div>

      {p.below != null && (
        <div className={full ? 'max-h-[45vh] shrink-0 space-y-2 overflow-y-auto' : 'space-y-2'} data-testid="gantt-below">{p.below}</div>
      )}

      {menu && <ContextMenu x={menu.x} y={menu.y} items={menuEntries()} onClose={() => setMenu(null)} />}
      {popLink && linkPop && (
        <LinkPopover x={linkPop.x} y={linkPop.y} link={popLink} title={linkLabel(popLink)}
          types={linkTypes.filter((ty) => !linkRefusal(key(popLink.from), key(popLink.to), ty))}
          allowLag={allowLag} canEdit={canLinks && !popLink.readOnly} unit={working ? 'working days' : 'days'}
          note={popLink.readOnly ? 'Old dependency, re-draw to edit' : undefined}
          onClose={() => setLinkPop(null)}
          onDelete={() => { setLinkPop(null); void commit({ label: 'Remove link', removeLinks: [popLink.id] }) }}
          onSave={(patch) => {
            setLinkPop(null)
            if (patch.type !== popLink.type && !linkTypes.includes(patch.type)) return
            const refused = linkRefusal(key(popLink.from), key(popLink.to), patch.type)
            if (refused) { notifyError(refused); return }
            void commit({ label: 'Edit link', updateLinks: [{ id: popLink.id, patch }] })
          }} />
      )}
      {dialogTask && (
        <TaskDialog task={dialogTask} working={working} allowConstraints={p.constraints ?? true}
          summary={isSummaryKey(key(dialogTask.id))}
          canField={(f) => canField(dialogTask, f) && !(isSummaryKey(key(dialogTask.id)) && ['start', 'duration', 'progress'].includes(f))}
          onClose={() => setDialogKey(null)}
          onSave={(pt) => void commit(patchesToChangeSet(new Map([[key(dialogTask.id), pt]]), 'Edit task'))} />
      )}
    </div>
  )
})

export default Gantt
