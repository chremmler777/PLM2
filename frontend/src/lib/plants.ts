/** Default-plant selection (spec: Phase E Task 21).
 *
 * Preference order, per the kickoff decision (default = the change's project
 * plant, else "USA" for now):
 *   1. the project's plant, if present in the active plant list
 *   2. the plant named "USA Toccoa" (the canonical seeded name — see
 *      backend/app/services/plant_repair.py) if active
 *   3. the first active plant
 *   4. null (no active plants at all)
 *
 * Inactive plants (is_active === false) are never returned — callers that
 * feed a full (unfiltered) plant list still get a sane default.
 */

export const CANONICAL_USA_PLANT_NAME = 'USA Toccoa';

export interface PlantLike {
  id: number;
  name: string;
  is_active?: boolean;
}

const isActive = (p: PlantLike): boolean => p.is_active !== false;

export function defaultPlantId(
  plants: PlantLike[],
  projectPlantId?: number | null,
): number | null {
  const active = plants.filter(isActive);

  if (projectPlantId != null) {
    const match = active.find((p) => p.id === projectPlantId);
    if (match) return match.id;
  }

  const usaToccoa = active.find((p) => p.name === CANONICAL_USA_PLANT_NAME);
  if (usaToccoa) return usaToccoa.id;

  return active[0]?.id ?? null;
}
