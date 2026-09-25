import type { RoleState } from '../api/training'

//: Non-component helpers shared by the training pages (kept out of ui.tsx so
//: fast refresh keeps working there).

export type RoleStage = 'not_started' | 'tasks_open' | 'signed_off' | 'retrain_due'

export function stageOf(r: RoleState): RoleStage {
  if (r.cleared) return 'signed_off'
  if (r.retrain_due) return 'retrain_due'
  if (r.attested_at) return 'tasks_open'
  return 'not_started'
}

export const BUTTON_PRIMARY =
  'rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 ' +
  'disabled:opacity-40 disabled:cursor-not-allowed active:translate-y-[1px] transition'

export const BUTTON_SECONDARY =
  'rounded-lg border border-slate-600 px-3 py-1.5 text-sm font-medium text-slate-200 ' +
  'hover:bg-slate-700/60 active:translate-y-[1px] transition'

export const INPUT =
  'w-full rounded-lg bg-slate-900 border border-slate-600 px-3 py-2 text-sm text-slate-100 ' +
  'focus:outline-none focus:border-sky-500'
