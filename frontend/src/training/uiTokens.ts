import type { RoleState } from '../api/training'
import { btnPrimary, btnSecondary } from '../components/common/buttonStyles'

//: Non-component helpers shared by the training pages (kept out of ui.tsx so
//: fast refresh keeps working there).

export type RoleStage = 'not_started' | 'tasks_open' | 'signed_off' | 'retrain_due'

export function stageOf(r: RoleState): RoleStage {
  if (r.cleared) return 'signed_off'
  if (r.retrain_due) return 'retrain_due'
  if (r.attested_at) return 'tasks_open'
  return 'not_started'
}

// The shared button looks (components/common/buttonStyles), under the names
// the training pages already use.
export const BUTTON_PRIMARY = btnPrimary

export const BUTTON_SECONDARY = btnSecondary

export const INPUT =
  'w-full rounded-lg bg-slate-900 border border-slate-600 px-3 py-2 text-sm text-slate-100 ' +
  'focus:outline-none focus:border-sky-500'
