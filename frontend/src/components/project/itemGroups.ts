/** Grouping, search and display order of the project items list. */
import type { Part, TreeNode } from './projectTypes';

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
