/**
 * My Tasks as one list (spec §16): change tasks and workflow tasks side by side,
 * one row per job. A department that is both R and A on the same step owes one
 * piece of work, so its two rows fold into one that carries both letters. The
 * sidebar badge counts exactly these rows, so badge and page always agree.
 */
import type { ChangeTask } from '../types/change'
import type { MyTask } from '../types/workflow'

const earlier = (a: string | null | undefined, b: string | null | undefined) =>
  !a ? (b ?? null) : !b ? a : (a < b ? a : b)

const LETTER_ORDER = 'RASCI'
const sortLetters = (ls: string[]) =>
  [...new Set(ls.filter(Boolean))].sort((x, y) => LETTER_ORDER.indexOf(x) - LETTER_ORDER.indexOf(y))

/** One change-task row per change, kind and department. */
export function foldChangeTasks(tasks: ChangeTask[] | null | undefined): ChangeTask[] {
  const out = new Map<string, ChangeTask>()
  for (const task of Array.isArray(tasks) ? tasks : []) {
    const key = `${task.change_id}|${task.kind}|${task.department_id ?? ''}`
    const seen = out.get(key)
    const letters = task.rasic_letters ?? []
    if (!seen) {
      out.set(key, { ...task, rasic_letters: sortLetters(letters) })
      continue
    }
    out.set(key, {
      ...seen,
      due_date: earlier(seen.due_date, task.due_date),
      overdue: seen.overdue || task.overdue,
      mine: !!(seen.mine || task.mine),
      owner_name: seen.owner_name ?? task.owner_name,
      rasic_letters: sortLetters([...(seen.rasic_letters ?? []), ...letters]),
    })
  }
  return [...out.values()]
}

export interface FoldedWorkflowTask extends MyTask {
  /** Every letter the department holds on this step (R and A fold together). */
  letters: string[]
}

/** One workflow row per instance, step, stage and department. */
export function foldWorkflowTasks(tasks: MyTask[] | null | undefined): FoldedWorkflowTask[] {
  const out = new Map<string, FoldedWorkflowTask>()
  for (const task of Array.isArray(tasks) ? tasks : []) {
    const key = `${task.instance_id}|${task.stage_order}|${task.step_name}|${task.department_name}`
    const seen = out.get(key)
    if (!seen) {
      out.set(key, { ...task, letters: sortLetters([task.rasic_letter]) })
      continue
    }
    out.set(key, {
      ...seen,
      due_date: earlier(seen.due_date, task.due_date),
      overdue: seen.overdue || task.overdue,
      mine: seen.mine || task.mine,
      owner_id: seen.owner_id ?? task.owner_id,
      owner_name: seen.owner_name ?? task.owner_name,
      letters: sortLetters([...seen.letters, task.rasic_letter]),
    })
  }
  return [...out.values()]
}

/** Overdue first, then the nearest due date, undated last. */
export function byUrgency<T extends { overdue: boolean; due_date: string | null }>(a: T, b: T): number {
  if (a.overdue !== b.overdue) return a.overdue ? -1 : 1
  if (!a.due_date || !b.due_date) return a.due_date ? -1 : b.due_date ? 1 : 0
  return a.due_date.localeCompare(b.due_date)
}
