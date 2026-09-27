/**
 * Plants that exist in the data but are not in use yet. For now PLM runs for
 * the US plant only; Mexico (Silao) is kept (its rates, exchange rate and
 * machines stay as they are) and shown with a quiet note. Access per plant
 * will be role based later; until then this list is the one place to change.
 *
 * A plant is recognised by what the payload at hand carries: its code
 * (plants list, cost sheet), its location, or its second currency (costing
 * context and machine rows carry only `local_currency`).
 */

export interface PlantNotInUse {
  /** Shown in the note: "Mexico (Silao)". */
  label: string
  country: string
  code: string
  location: string
  localCurrency: string
}

export const PLANTS_NOT_IN_USE: readonly PlantNotInUse[] = [
  { label: 'Mexico (Silao)', country: 'Mexico', code: 'SIL', location: 'MX', localCurrency: 'MXN' },
]

/** Any plant-ish shape: a plant row, a cost sheet plant, a costing context. */
export interface PlantKeys {
  code?: string | null
  location?: string | null
  local_currency?: string | null
}

const norm = (s?: string | null) => (s ?? '').trim().toUpperCase()

/** The not-in-use entry this plant matches; null for a plant in use. */
export function plantNotInUse(p: PlantKeys | null | undefined): PlantNotInUse | null {
  if (!p) return null
  const code = norm(p.code)
  const loc = norm(p.location)
  const local = norm(p.local_currency)
  return PLANTS_NOT_IN_USE.find((e) =>
    (!!code && code === e.code)
    || (!!loc && loc === e.location)
    || (!!local && local === e.localCurrency)) ?? null
}

/** The distinct not-in-use entries among these plants, in registry order. */
export function plantsNotInUse(plants: readonly (PlantKeys | null | undefined)[]): PlantNotInUse[] {
  const hit = new Set(plants.map(plantNotInUse).filter(Boolean))
  return PLANTS_NOT_IN_USE.filter((e) => hit.has(e))
}

export const plantNotInUseText = (e: PlantNotInUse): string =>
  `${e.label} is not in use yet. PLM runs for the US plant only for now; `
  + `access for ${e.country} will be role based later.`

/** The sentence the training manual adds wherever it describes Silao or MXN. */
export const MEXICO_NOT_IN_USE_TEXT = plantNotInUseText(PLANTS_NOT_IN_USE[0])
