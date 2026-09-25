/** Cost sheet (spec §15 / §15a): Finance's versioned rates. */

export type CostSheetStatus = 'draft' | 'published'
export type CostSheetSection = 'rates' | 'machines' | 'sampling' | 'overheads'

export interface CostSheetVersionSummary {
  id: number
  version: number
  status: CostSheetStatus
  valid_from: string | null
  valid_to: string | null
  note: string | null
  based_on_version_id: number | null
  created_at: string | null
  published_at: string | null
  published_by: number | null
}

export interface OverheadRef {
  id: number
  kind: 'percent' | 'per_hour'
  value: number
  currency: string | null
  department_id: number | null
  plant_id: number | null
}

export interface PositionRate {
  id: number
  department_id: number
  position: string | null
  plant_id: number | null
  hourly_rate: number
  currency: string
  min_factor: number | null
  note: string | null
  /** null: a per-hour overhead in another currency makes it undefined. */
  effective_rate: number | null
  overhead: OverheadRef | null
}

export interface MachineRate {
  id: number
  plant_id: number | null
  machine_class_id: number | null
  machine_class: string
  machine_ref: string | null
  tonnage_min: number | null
  tonnage_max: number | null
  hourly_rate: number
  currency: string
  note: string | null
}

export interface SamplingBreakdown {
  mode: 'flat' | 'components'
  flat_price?: number
  setup_hours?: number
  run_hours?: number
  machine_rate?: number | null
  machine_cost?: number
  labour_hours?: number
  labour_rate?: number | null
  labour_cost?: number
  handling_cost?: number
  missing?: string[]
  complete?: boolean
}

export interface SamplingRate {
  id: number
  plant_id: number | null
  machine_class_id: number | null
  machine_class: string
  mode: 'flat' | 'components'
  flat_price: number | null
  setup_hours: number | null
  run_hours_default: number | null
  labour_hours: number | null
  labour_department_id: number | null
  labour_position: string | null
  handling_cost: number | null
  currency: string
  note: string | null
  computed_price: number | null
  breakdown: SamplingBreakdown | null
}

export interface Overhead {
  id: number
  plant_id: number | null
  department_id: number | null
  kind: 'percent' | 'per_hour'
  value: number
  currency: string | null
  note: string | null
}

export interface CostSheetVersionDetail extends CostSheetVersionSummary {
  rates: PositionRate[]
  machine_rates: MachineRate[]
  sampling_rates: SamplingRate[]
  overheads: Overhead[]
}

export interface StaleStatus {
  stale: boolean
  review_months: number
  latest_version: number | null
  reviewed_on: string | null
  due_on: string | null
  reason: 'no_published_version' | 'review_due' | null
}

export interface MachineClass {
  id: number
  name: string
  tonnage_min: number | null
  tonnage_max: number | null
  sort_order: number
  is_active: boolean
}

export interface PlantCurrency {
  id: number
  name: string
  code: string
  is_active: boolean
  currency: string
  /** false: set from the location by the migration, Finance has not confirmed. */
  currency_confirmed: boolean
}

export interface CostSheetOverview {
  versions: CostSheetVersionSummary[]
  current_version_id: number | null
  draft_version_id: number | null
  can_edit: boolean
  stale: StaleStatus
  departments: { id: number; name: string; is_active: boolean }[]
  plants: PlantCurrency[]
  currencies: string[]
  machine_classes: MachineClass[]
}

export interface DiffChange {
  changes: Record<string, { old: unknown; new: unknown }>
  pct?: number
  [key: string]: unknown
}

export interface DiffSection {
  added: Record<string, unknown>[]
  removed: Record<string, unknown>[]
  changed: DiffChange[]
}

export interface CostSheetDiff {
  from_version: number | null
  from_version_id: number | null
  to_version: number
  to_version_id: number
  rates: DiffSection
  machines: DiffSection
  sampling: DiffSection
  overheads: DiffSection
}

export type CostSheetRow = Record<string, unknown>
