/**
 * Grid column definitions: the built-in MS Project style columns and the
 * shape of custom ones.
 */
import type { ReactNode } from 'react'
import { fmtShort, toIso } from './engine/calendar'
import type { GanttTask, ScheduledTask } from './engine/types'
import type { TaskGeo } from './GanttChart'
import { DEFAULT_KIND, type GanttKindStyle } from './theme'

export type ColumnKey = 'row' | 'wbs' | 'name' | 'start' | 'end' | 'duration' | 'predecessors' | 'lane' | 'kind' | 'progress' | 'slack'
export type EditKind = 'text' | 'date' | 'number' | 'predecessors'

export interface CellContext {
  geo: TaskGeo | undefined
  rowNo: number | undefined
  wbs: string | undefined
  predecessors: string
  sched: ScheduledTask | undefined
  kinds: Record<string, GanttKindStyle>
  summary: boolean
  /** Duration units spanned by a summary. */
  summaryDuration?: number
  working: boolean
}

export interface GanttColumn {
  key: string
  title: string
  width: number
  align?: 'left' | 'right'
  /** Inline editor type; omit for read-only columns. */
  edit?: EditKind
  /** Rights field name checked before editing (defaults to the key). */
  field?: string
  text?: (t: GanttTask, c: CellContext) => string
  render?: (t: GanttTask, c: CellContext) => ReactNode
  /** Value put in the editor (defaults to `text`). */
  editValue?: (t: GanttTask, c: CellContext) => string
}

export const BUILTIN_COLUMNS: Record<ColumnKey, GanttColumn> = {
  row: { key: 'row', title: '#', width: 34, align: 'right', text: (_t, c) => String(c.rowNo ?? '') },
  wbs: { key: 'wbs', title: 'WBS', width: 44, text: (_t, c) => c.wbs ?? '' },
  name: { key: 'name', title: 'Task', width: 220, edit: 'text', text: (t) => t.name },
  start: {
    key: 'start', title: 'Start', width: 76, edit: 'date',
    text: (_t, c) => fmtShort(c.geo?.s), editValue: (t) => t.start,
  },
  end: {
    key: 'end', title: 'Finish', width: 76, edit: 'date', field: 'duration',
    text: (_t, c) => (c.geo ? fmtShort(c.geo.milestone ? c.geo.s : c.geo.e - 1) : '-'),
    editValue: (_t, c) => (c.geo ? toIso(c.geo.milestone ? c.geo.s : c.geo.e - 1) : ''),
  },
  duration: {
    key: 'duration', title: 'Dur.', width: 50, align: 'right', edit: 'number',
    text: (t, c) => (c.summary ? `${c.summaryDuration ?? 0}${c.working ? 'wd' : 'd'}`
      : t.duration === 0 ? '0d' : `${t.duration}${c.working ? 'wd' : 'd'}`),
    editValue: (t) => String(t.duration),
  },
  predecessors: { key: 'predecessors', title: 'Predecessors', width: 92, edit: 'predecessors', field: 'links', text: (_t, c) => c.predecessors },
  lane: { key: 'lane', title: 'Lane', width: 96, edit: 'text', text: (t) => t.lane ?? '' },
  kind: { key: 'kind', title: 'Kind', width: 84, text: (t, c) => (t.kind ? (c.kinds[t.kind] ?? DEFAULT_KIND).label : '') },
  progress: {
    key: 'progress', title: 'Done', width: 50, align: 'right', edit: 'number',
    text: (t, c) => `${c.summary && c.sched ? c.sched.progress : Math.round(t.progress ?? 0)}%`,
    editValue: (t) => String(Math.round(t.progress ?? 0)),
  },
  slack: {
    key: 'slack', title: 'Slack', width: 50, align: 'right',
    text: (_t, c) => (c.sched?.totalSlack == null ? '' : `${c.sched.totalSlack}d`),
  },
}

export const gridWidth = (cols: GanttColumn[]) => cols.reduce((n, c) => n + c.width, 0)
