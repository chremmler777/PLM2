/**
 * Equipment numbers hang on the tool they serve: <tool number>-<family><index>
 * (backend app/services/equipment_numbering.py). Family 1 is an EOAT, 2 an in-cell
 * station, 3 a secondary station, 4 a gauge; each family has ten slots (0 to 9).
 * The same function numbers equipment without a tool on the project code.
 * The create dialog suggests the next free slot so nobody has to look it up.
 */

/** What the create dialog offers; an EOAT is stored as assembly equipment. */
export type ItemKind = 'article' | 'tool' | 'gauge' | 'assembly_equipment' | 'eoat';

export const EQUIPMENT_KINDS: ReadonlySet<ItemKind> = new Set<ItemKind>(['gauge', 'assembly_equipment', 'eoat']);

/** The item_category a kind is stored under. */
export function categoryOfKind(kind: ItemKind): string {
  return kind === 'eoat' ? 'assembly_equipment' : kind;
}

/** Number family of a kind; assembly equipment is an in-cell (2) or a secondary (3) station. */
export function familyOfKind(kind: ItemKind, station: '2' | '3' = '2'): number | null {
  if (kind === 'eoat') return 1;
  if (kind === 'assembly_equipment') return Number(station);
  if (kind === 'gauge') return 4;
  return null;
}

/**
 * Equipment that serves no tool hangs on the project code instead: <code>-6x for an
 * assembly operation (assembly equipment or EOAT), <code>-7x for an assembly gauge.
 * Same two families as the backend (equipment_numbering.py).
 */
export const NO_TOOL_STATION_FAMILY = 6;
export const NO_TOOL_GAUGE_FAMILY = 7;

export function noToolFamilyOfKind(kind: ItemKind): number {
  return kind === 'gauge' ? NO_TOOL_GAUGE_FAMILY : NO_TOOL_STATION_FAMILY;
}

/**
 * Next free number of the family for this tool: ('3345', 4, ['3345-40']) gives '3345-41'.
 * Null when all ten slots are taken; the user then types a number.
 */
export function suggestEquipmentNumber(toolNumber: string, family: number, existingNumbers: Iterable<string>): string | null {
  const taken = new Set(Array.from(existingNumbers, (n) => n.trim()));
  for (let index = 0; index <= 9; index += 1) {
    const candidate = `${toolNumber}-${family}${index}`;
    if (!taken.has(candidate)) return candidate;
  }
  return null;
}
