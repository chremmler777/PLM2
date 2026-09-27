import client from './client';
import type {
  CostSheetMachine, MachineSyncResult, MachinesListing, PlantMapEntry,
} from '../types/costSheetMachines';

const base = '/v1/cost-sheet/machines';

export interface MachineFilter {
  version_id?: number | null
  plant_id?: number | null
  active_only?: boolean
  min_tonnage?: number | null
  max_tonnage?: number | null
}

export const costSheetMachinesApi = {
  /** The synced machines; with a version each carries its own and its class rate there. */
  list: (f: MachineFilter = {}): Promise<MachinesListing> => {
    const params: Record<string, string | number | boolean> = {}
    for (const [k, v] of Object.entries(f)) if (v !== null && v !== undefined && v !== false) params[k] = v
    return client.get(base, { params }).then((r) => r.data)
  },

  /** force applies an answer the server refused as broken (empty, mostly unreadable, most machines gone). */
  sync: (force = false): Promise<MachineSyncResult> =>
    client.post(`${base}/sync`, null, force ? { params: { force: true } } : undefined).then((r) => r.data),

  /** Merged into the stored mapping: a plant id maps, null keeps the MachineDB plant unmapped on purpose. */
  setPlantMap: (mapping: Record<string, number | null>): Promise<Record<string, PlantMapEntry>> =>
    client.put(`${base}/plant-map`, { mapping }).then((r) => r.data),

  /** Drops one hand mapping; the default by plant name applies again. */
  deletePlantMap: (key: string): Promise<Record<string, PlantMapEntry>> =>
    client.delete(`${base}/plant-map/${encodeURIComponent(key)}`).then((r) => r.data),

  /** hourly_rate (or entered_rate) null removes the machine's own rate (the class rate applies).
   *  entered_rate + entered_currency: typed in the plant's local currency. */
  setRate: (machineId: number, body: {
    version_id: number; hourly_rate?: number | null; currency?: string | null; note?: string | null
    entered_rate?: number | null; entered_currency?: string | null
  }): Promise<CostSheetMachine | null> =>
    client.put(`${base}/${machineId}/rate`, body).then((r) => r.data),
};
