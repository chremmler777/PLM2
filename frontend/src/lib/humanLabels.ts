/**
 * Human words for the codes the change screens carry around: verdicts, change
 * types, priorities, task kinds, audit values. One place, so no screen ever
 * shows "feasible_with_conditions" or "physical_part" to a person.
 */
import { t } from '../i18n/cmLabels'
import { STATUS_LABELS } from './changeStatus'
import type { ChangeStatus } from '../types/change'

/** "some_code_value" -> "Some code value": the last resort for an unknown code. */
export function humanize(code: string | null | undefined): string {
  if (code == null || code === '') return '-'
  const s = String(code).replace(/[_-]+/g, ' ').trim()
  return s ? s[0].toUpperCase() + s.slice(1) : '-'
}

export const VERDICT_LABELS: Record<string, string> = {
  pending: 'Not answered yet',
  feasible: 'Feasible',
  feasible_with_conditions: 'Feasible with conditions',
  not_feasible: 'Not feasible',
}
export const verdictLabel = (v: string | null | undefined): string =>
  (v && VERDICT_LABELS[v]) || humanize(v)

export const CHANGE_TYPE_LABELS: Record<string, string> = {
  physical_part: 'Physical part',
  tooling: 'Tooling',
  document_spec: 'Document / specification',
  process_im: 'Process (IM)',
  packaging: 'Packaging',
}
export const changeTypeLabel = (v: string | null | undefined): string =>
  (v && CHANGE_TYPE_LABELS[v]) || humanize(v)

export const PRIORITY_LABELS: Record<string, string> = {
  low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical',
}
export const priorityLabel = (v: string | null | undefined): string =>
  (v && PRIORITY_LABELS[v]) || humanize(v)

/** My Tasks kinds: the catalogued label, else the code made readable. */
export function taskKindLabel(kind: string, serverLabel?: string | null): string {
  if (serverLabel) return serverLabel
  const key = `tasks.kind.${kind}`
  const hit = t(key)
  return hit === key ? humanize(kind) : hit
}

export const CONCERN_KIND_LABELS: Record<string, string> = {
  needs_info: 'Question',
  reject_proposal: 'Cancel vote',
  risk: 'Risk',
}

export const COST_CARRIER_LABELS: Record<string, string> = {
  customer: 'Customer (customer relevant)',
  internal: 'Internal (plant pays)',
}

/**
 * An audit / changelog value as a person reads it: statuses, verdicts, types,
 * priorities and booleans get their names, ISO dates the one date format.
 */
export function auditValueLabel(field: string | null | undefined, value: string | null | undefined): string {
  if (value == null || value === '') return '-'
  const v = value.startsWith('"') && value.endsWith('"') ? value.slice(1, -1) : value
  if (v === 'true') return 'Yes'
  if (v === 'false') return 'No'
  if (v === 'null' || v === 'None') return '-'
  const f = (field ?? '').toLowerCase()
  if (f === 'status' || f.endsWith('_status')) return STATUS_LABELS[v as ChangeStatus] ?? humanize(v)
  if (f === 'verdict') return verdictLabel(v)
  if (f === 'change_type') return changeTypeLabel(v)
  if (f === 'priority') return priorityLabel(v)
  if (f === 'cost_carrier') return COST_CARRIER_LABELS[v] ?? humanize(v)
  if (f === 'customer_relevant') return v === '1' ? 'Yes' : v === '0' ? 'No' : v
  const iso = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(v)
  if (iso) return iso[4] ? `${iso[3]}.${iso[2]}.${iso[1]} ${iso[4]}:${iso[5]}` : `${iso[3]}.${iso[2]}.${iso[1]}`
  if (STATUS_LABELS[v as ChangeStatus]) return STATUS_LABELS[v as ChangeStatus]
  if (VERDICT_LABELS[v]) return VERDICT_LABELS[v]
  // snake_case codes read as words; free text stays as typed.
  return /^[a-z]+(_[a-z0-9]+)+$/.test(v) ? humanize(v) : v
}

/** "1 risk", "2 risks". */
export const plural = (n: number, one: string, many = `${one}s`): string =>
  `${n} ${n === 1 ? one : many}`
