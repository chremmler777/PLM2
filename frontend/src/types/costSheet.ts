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

/** A two-currency plant's view of a rate row (106): the rate in the
 * plant's local currency, typed there or converted at the version's rate. */
export interface DualRate {
  /** The rate as typed in the local currency; null when typed as hourly_rate. */
  entered_rate?: number | null
  entered_currency?: string | null
  /** The plant's local currency; null for single-currency plants and all-plants rows. */
  local_currency?: string | null
  local_rate?: number | null
  /** Which of the two was typed: 'local', 'quote' or null (no rate yet). */
  entered_in?: 'local' | 'quote' | null
}

export interface FxRate {
  /** "USD/MXN": one base is `rate` quote. */
  pair: string
  base: string
  quote: string
  /** The decimal as typed, e.g. "17.30". */
  rate: string
}

export interface PositionRate extends DualRate {
  id: number
  department_id: number
  /** Always null since 104: one rate per department and plant. */
  position: string | null
  plant_id: number | null
  /** null: no rate yet (a seeded row); costing shows "No rate in the cost sheet". */
  hourly_rate: number | null
  currency: string
  min_factor: number | null
  note: string | null
  /** null: a per-hour overhead in another currency makes it undefined. */
  effective_rate: number | null
  overhead: OverheadRef | null
}

export interface MachineRate extends DualRate {
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

/** A row whose currency is not its plant's quote currency (flagged, never relabelled). */
export interface CurrencyMismatchRow {
  section: 'rates' | 'machines' | 'sampling' | 'overheads' | 'machine_items'
  row_id: number
  plant_id: number
  plant_name: string
  currency: string
  plant_currency: string
}

export interface CostSheetVersionDetail extends CostSheetVersionSummary {
  /** The exchange rates of this version, frozen on publish. */
  fx_rates?: FxRate[]
  /** Rows not in their plant's quote currency: a warning on the draft and on publish. */
  currency_mismatch?: CurrencyMismatchRow[]
  /** The pairs the org's two-currency plants need (quote/local). */
  fx_needed?: { pair: string; base: string; quote: string }[]
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
  /** A second currency the plant works in (Silao: MXN next to USD); null = one only. */
  local_currency?: string | null
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
  /** Exchange rates that differ, old and new as typed. */
  fx_rates?: { pair: string; old: string | null; new: string | null }[]
  from_version: number | null
  from_version_id: number | null
  to_version: number
  to_version_id: number
  rates: DiffSection
  machines: DiffSection
  sampling: DiffSection
  overheads: DiffSection
  /** Per-machine rates of MachineDB presses (keyed by machine_id). */
  machine_items?: DiffSection
}

export type CostSheetRow = Record<string, unknown>
