/**
 * Controlled-item grouping for pickers and the impact tree.
 *
 * `item_category` on a Part is the coarse controlled-item class (article, tool,
 * assembly_equipment, eoat, gauge). It does not separate the article families,
 * which WinCarat encodes in the part-number prefix instead: 10/11/20/22 are
 * physical parts, 40 is resin/material, 65 is returnables/dunnage. People think
 * in those families ("the dunnage change"), so grouping splits articles by
 * prefix and leaves every other category as-is.
 */

export type ItemGroupKey =
  | 'article' | 'material' | 'dunnage'
  | 'tool' | 'eoat' | 'in_cell_station' | 'secondary_station'
  | 'assembly_equipment' | 'gauge' | 'other';

interface PartLike {
  part_number: string;
  item_category: string;
}

const ARTICLE_PREFIX_GROUP: Record<string, ItemGroupKey> = {
  '10': 'article', '11': 'article', '20': 'article', '22': 'article',
  '40': 'material',   // resin / material
  '65': 'dunnage',    // returnables / dunnage
};

/**
 * Equipment is numbered `<tool#>-<2-digit op code>`, and the first digit of
 * that op code is what says which kind it is. Mirrors OP_CODE_KINDS in
 * backend/app/services/equipment_numbering.py. This has to lead over
 * item_category: an EOAT is stored as item_category 'assembly_equipment', so
 * only the number distinguishes it from an in-cell station.
 * A bare tool number (no suffix) is the mold itself.
 */
const OP_CODE_GROUP: Record<string, ItemGroupKey> = {
  '1': 'eoat',
  '2': 'in_cell_station',
  '3': 'secondary_station',
  '4': 'gauge',
};
const EQUIPMENT_NUMBER = /^\d{3,4}-(\d)\d$/;

/** Order the groups appear in. Articles first — the common change target. */
export const ITEM_GROUP_ORDER: ItemGroupKey[] = [
  'article', 'material', 'dunnage',
  'tool', 'eoat', 'in_cell_station', 'secondary_station',
  'assembly_equipment', 'gauge', 'other',
];

export const ITEM_GROUP_LABEL: Record<ItemGroupKey, string> = {
  article: 'Articles',
  material: 'Resin & material',
  dunnage: 'Returnables & dunnage',
  tool: 'Tools & molds',
  eoat: 'EOAT',
  in_cell_station: 'In-cell stations',
  secondary_station: 'Secondary stations',
  assembly_equipment: 'Assembly equipment',
  gauge: 'Gauges',
  other: 'Other',
};

export function itemGroup(p: PartLike): ItemGroupKey {
  if (p.item_category !== 'article') {
    const opCode = EQUIPMENT_NUMBER.exec(p.part_number)?.[1];
    if (opCode && OP_CODE_GROUP[opCode]) return OP_CODE_GROUP[opCode];
    return (ITEM_GROUP_ORDER as string[]).includes(p.item_category)
      ? (p.item_category as ItemGroupKey)
      : 'other';
  }
  // An article whose prefix we don't recognise is still an article — it is a
  // real part somebody can change, not an oddity to hide under "Other".
  return ARTICLE_PREFIX_GROUP[p.part_number.split('-')[0]] ?? 'article';
}

/** Bucket items into groups, in ITEM_GROUP_ORDER, dropping empty groups. */
export function groupItems<T extends PartLike>(items: T[]): { key: ItemGroupKey; label: string; items: T[] }[] {
  const buckets = new Map<ItemGroupKey, T[]>();
  for (const it of items) {
    const k = itemGroup(it);
    const bucket = buckets.get(k);
    if (bucket) bucket.push(it);
    else buckets.set(k, [it]);
  }
  return ITEM_GROUP_ORDER
    .filter((k) => buckets.has(k))
    .map((k) => ({ key: k, label: ITEM_GROUP_LABEL[k], items: buckets.get(k)! }));
}
