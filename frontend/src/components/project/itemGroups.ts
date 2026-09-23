/** Grouping, search and display order of the project items list. */
import type { Part, TreeNode } from './projectTypes';
import { articleOf, type ProjectStructure } from '../../hooks/queries/useProjectStructure';
import { revisionLabel } from '../parts/RevisionBadge';
import { shortName } from '../../lib/partDisplay';

export type GroupKey = 'article' | 'tool' | 'equipment' | 'gauge' | 'assemblies';

export interface ItemGroup {
  key: GroupKey;
  label: string;
  nodes: TreeNode[];
}

export const ITEM_GROUPS: { key: GroupKey; label: string }[] = [
  { key: 'article', label: 'Articles' },
  { key: 'tool', label: 'Tools' },
  { key: 'equipment', label: 'Equipment' },
  { key: 'gauge', label: 'Gauges' },
  { key: 'assemblies', label: 'Assemblies' },
];

export function groupOf(part: Part): GroupKey {
  if (part.part_type === 'sub_assembly') return 'assemblies';
  if (part.item_category === 'tool') return 'tool';
  if (part.item_category === 'assembly_equipment' || part.item_category === 'eoat') return 'equipment';
  if (part.item_category === 'gauge') return 'gauge';
  return 'article';
}

export function matchesSearch(part: Part, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [part.part_number, part.customer_part_number, part.tier1_part_number, part.name]
    .some((v) => !!v && v.toLowerCase().includes(q));
}

/** Root nodes into the fixed groups; empty groups are left out. */
export function groupNodes(nodes: TreeNode[]): ItemGroup[] {
  return ITEM_GROUPS
    .map((g) => ({ ...g, nodes: nodes.filter((n) => groupOf(n.part) === g.key) }))
    .filter((g) => g.nodes.length > 0);
}

/** Part ids in the order the list shows them: open groups, expanded children. */
export function visibleOrder(
  groups: ItemGroup[],
  collapsed: ReadonlySet<GroupKey>,
  isExpanded: (node: TreeNode) => boolean,
): number[] {
  const out: number[] = [];
  const walk = (n: TreeNode) => {
    out.push(n.part.id);
    if (n.children.length > 0 && isExpanded(n)) n.children.forEach(walk);
  };
  for (const g of groups) {
    if (!collapsed.has(g.key)) g.nodes.forEach(walk);
  }
  return out;
}

/** The node for a part id anywhere in the tree, or undefined. */
export function findNode(nodes: TreeNode[], partId: number): TreeNode | undefined {
  for (const n of nodes) {
    if (n.part.id === partId) return n;
    const hit = findNode(n.children, partId);
    if (hit) return hit;
  }
  return undefined;
}

export interface TableRow {
  id: number;
  thumbnailUrl: string | null;
  ktxNumber: string;
  customerNumber: string;
  tier1: string;
  name: string;
  phase: string;
  revision: string;
  revisionName: string;
  revisionIndex: string | null;
  tools: string;
  cavities: string;
}

/** The API sends tool_cavities (even as null) once the tool fields exist; before that the key is missing. */
export function hasToolFields(parts: Part[]): boolean {
  return parts.some((p) => p.tool_cavities !== undefined);
}

/** Cells of one row of the items table shown while the detail is popped out. */
export function tableRow(part: Part, parts: Part[], structure: ProjectStructure | undefined, projectCode: string): TableRow {
  const article = articleOf(structure, part.id);
  const customer = part.customer_part_number ?? article?.customer_part_number ?? null;
  const active = article?.revisions.find((r) => r.is_active);
  const toolLinks = (article?.related ?? []).filter((r) => r.item_category === 'tool');
  const linkedCavities = toolLinks
    .map((r) => parts.find((p) => p.id === r.part_id)?.tool_cavities)
    .filter((c): c is number => c !== null && c !== undefined);
  const ownCavities = part.item_category === 'tool' && part.tool_cavities != null ? [part.tool_cavities] : [];
  return {
    id: part.id,
    thumbnailUrl: part.thumbnail_url ?? article?.thumbnail_url ?? null,
    ktxNumber: part.part_number,
    customerNumber: customer ?? '',
    tier1: part.tier1_part_number ?? '',
    name: shortName(part.name, projectCode, customer),
    phase: article?.lifecycle_phase ?? part.lifecycle_phase ?? '',
    revision: active ? revisionLabel(active.revision_name, active.customer_index) : '',
    revisionName: active?.revision_name ?? '',
    revisionIndex: active?.customer_index ?? null,
    tools: toolLinks.map((r) => r.part_number).join(', '),
    cavities: [...ownCavities, ...linkedCavities].join(', '),
  };
}
