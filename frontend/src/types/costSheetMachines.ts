/** MachineDB presses in the cost sheet (migration 105). */

export interface CostSheetMachine {
  id: number
  machinedb_id: number
  internal_name: string
  /** MachineDB's plant key: usa, mexico, weissenburg, solingen, serbia. */
  machinedb_plant: string | null
  /** The plm2 plant it maps to; null = unmapped. */
  plant_id: number | null
  clamping_force_t: number | null
  tonnage_class: string | null
  two_k_type: string | null
  manufacturer: string | null
  model: string | null
  in_service_from: string | null
  planned_scrap_from: string | null
  active: boolean
  /** MachineDB no longer lists it. */
  retired: boolean
  synced_at: string | null
  /** The cost sheet class its tonnage falls in. */
  machine_class_id: number | null
  machine_class: string | null
  /** Its own rate in the version asked for; null = the class rate applies. */
  rate_id: number | null
  hourly_rate: number | null
  currency: string | null
  note: string | null
  /** The currency of the machine's plant: a new own rate defaults to it.
   *  null = unmapped, the currency has to be chosen. */
  plant_currency: string | null
  /** The rate as typed in the plant's local currency (Silao: MXN); null
   *  when typed as hourly_rate. */
  entered_rate: number | null
  entered_currency: string | null
  /** The plant's second currency; null for single-currency plants. */
  local_currency: string | null
  /** The rate in local_currency: typed there, or converted at the version's rate. */
  local_rate: number | null
  /** Which of the two was typed: 'local', 'quote' or null (no rate yet). */
  entered_in: 'local' | 'quote' | null
  /** The class rate of its plant in that version (the fallback). */
  class_rate: number | null
  class_rate_currency: string | null
}

export interface MachineSyncSummary {
  at?: string | null
  failed_at?: string | null
  error?: string | null
  /** The last attempt was refused as a broken MachineDB answer; a forced sync applies it. */
  guard?: boolean
  total?: number
  new?: number
  changed?: number
  retired?: number
  unmapped?: number
}

export interface PlantMapEntry {
  plant_id: number | null
  /** 'setting' (mapped by hand), 'default' (by plant name), or why nothing maps. */
  source: string
}

export interface MachinesListing {
  version_id: number | null
  machines: CostSheetMachine[]
  machinedb: { configured: boolean; missing: string[]; host: string | null }
  last_sync: MachineSyncSummary | null
  can_sync: boolean
  can_edit_rates: boolean
  plant_map: Record<string, PlantMapEntry>
  /** The currencies a rate may be in. */
  currencies?: string[]
}

export interface SyncEntry {
  machinedb_id: number
  internal_name: string
  machinedb_plant: string | null
  plant_id: number | null
  fields?: string[]
  planned_scrap_from?: string | null
}

export interface MachineSyncResult extends MachineSyncSummary {
  report: {
    new: SyncEntry[]
    changed: SyncEntry[]
    retired: SyncEntry[]
    scrapped: SyncEntry[]
    returned: SyncEntry[]
    unmapped: { machinedb_plant: string; count: number; machines: string[] }[]
    skipped: string[]
  }
}
