/**
 * Shapes and helpers shared by the project page, its panes and the pop-out
 * detail window. Moved out of ProjectDetailPage without change.
 */
import { comparePartNumbers } from '../../lib/partDisplay';

export type CustomerNaming = 'vw' | 'scout' | null;
export const CUSTOMER_NAMING_LABELS: Record<Exclude<CustomerNaming, null>, string> = { vw: 'VW group', scout: 'Scout' };

export interface Project {
  id: number;
  name: string;
  code: string;
  status: string;
  customer_naming?: CustomerNaming;
}

export interface Part {
  id: number;
  part_number: string;
  customer_part_number?: string | null;
  tier1_part_number?: string | null;
  name: string;
  part_type: string;
  supplier?: string | null;
  data_classification?: string;
  active_revision_id: number | null;
  parent_part_id?: number | null;
  item_category: string;
  calibration_interval_months?: number | null;
  last_calibrated_at?: string | null;
  next_calibration_due?: string | null;
  lifecycle_phase?: string;
  tool_cavities?: number | null;
  toolmaker_id?: number | null;
  tool_tonnage_class?: number | null;
  tool_cycle_time_s?: number | null;
}

// Controlled item categories (automotive PLM)
export const CATEGORY_META: Record<string, { label: string; icon: string; badge: string }> = {
  article: { label: 'Article', icon: '📄', badge: 'bg-slate-600 text-slate-200' },
  tool: { label: 'Tool', icon: '🔧', badge: 'bg-orange-900/50 text-orange-300' },
  assembly_equipment: { label: 'Equipment', icon: '🏗️', badge: 'bg-cyan-900/50 text-cyan-300' },
  gauge: { label: 'Gauge', icon: '📏', badge: 'bg-pink-900/50 text-pink-300' },
};

export interface PartRevision {
  id: number;
  part_id: number;
  revision_name: string;
  phase: 'review' | 'official';
  status: string;
  created_at: string;
  summary?: string;
  part_phase_at_receipt?: string;
  customer_index?: string | null;
}

export interface ContextMenuState {
  partId: number;
  x: number;
  y: number;
}

export interface TreeNode {
  part: Part;
  children: TreeNode[];
}

export interface RevisionFile {
  id: number;
  revision_id: number;
  filename: string;
  file_type: string;
  mime_type: string;
  file_size: number;
  cad_format: string | null;
  has_viewer: boolean;
  uploaded_at: string;
  uploaded_by?: number | null;
  uploaded_by_name?: string | null;
  kind?: string | null;
  note?: string | null;
}

export const LOCKED_REVISION_STATUSES = ['frozen', 'cancelled', 'archived'];

export interface AssemblyFileEntry {
  part_id: number;
  part_number: string;
  part_name: string;
  revision_id: number;
  revision_name: string;
  file_id: number;
  // Optional throughout: files uploaded before provenance was recorded have none.
  uploaded_at?: string | null;
  uploaded_by?: number | null;
  uploaded_by_name?: string | null;
}

export interface ChangelogEntry {
  id: number;
  action: string;
  action_description: string;
  performed_by_user: string | null;
  performed_at: string;
  revision_id: number | null;
}

export interface CatalogPart {
  id: number;
  part_number: string;
  name: string;
  supplier: string | null;
  unit: string;
}

// Order by the embedded tool number: "3450" for a tool, the middle "3450" for
// an article like "20-3450-001-0". Groups each tool with the articles it produces
// (tool first), so the list runs 3450 → 3457 instead of all 10-/20- prefixes first.
export function comparePartNodes(a: TreeNode, b: TreeNode): number {
  return comparePartNumbers(a.part.part_number, b.part.part_number);
}

// Build tree structure from flat parts list
export function buildPartTree(parts: Part[]): TreeNode[] {
  const partMap = new Map<number, Part>(parts.map((p) => [p.id, p]));
  const roots: TreeNode[] = [];
  const visited = new Set<number>();

  function buildNode(partId: number): TreeNode | null {
    if (visited.has(partId)) return null;
    visited.add(partId);

    const part = partMap.get(partId);
    if (!part) return null;

    const children: TreeNode[] = [];
    for (const candidate of parts) {
      if (candidate.parent_part_id === partId) {
        const childNode = buildNode(candidate.id);
        if (childNode) children.push(childNode);
      }
    }

    children.sort(comparePartNodes);
    return { part, children };
  }

  // Find root parts (no parent)
  for (const part of parts) {
    if (!part.parent_part_id) {
      const node = buildNode(part.id);
      if (node) roots.push(node);
    }
  }

  roots.sort(comparePartNodes);
  return roots;
}

// Collect a part's descendant ids (for drag-and-drop cycle prevention)
export function getDescendantIds(parts: Part[], partId: number): Set<number> {
  const ids = new Set<number>();
  const walk = (id: number) => {
    for (const p of parts) {
      if (p.parent_part_id === id && !ids.has(p.id)) {
        ids.add(p.id);
        walk(p.id);
      }
    }
  };
  walk(partId);
  return ids;
}

export function typeColor(partType: string): string {
  const colors: Record<string, string> = {
    purchased: 'bg-slate-600 text-slate-200',
    internal_mfg: 'bg-amber-900/50 text-amber-300',
    sub_assembly: 'bg-blue-900/50 text-blue-300',
  };
  return colors[partType] || 'bg-slate-700 text-slate-300';
}

export function phaseColor(phase: string): string {
  return phase === 'official' ? 'bg-amber-900/30 text-amber-300' : 'bg-blue-900/30 text-blue-300';
}

export function statusColor(status: string): string {
  const colors: Record<string, string> = {
    draft: 'text-slate-400',
    in_progress: 'text-blue-400',
    in_review: 'text-yellow-400',
    approved: 'text-green-400',
    frozen: 'text-green-500',
    rejected: 'text-red-400',
    cancelled: 'text-slate-500',
  };
  return colors[status] || 'text-slate-300';
}
