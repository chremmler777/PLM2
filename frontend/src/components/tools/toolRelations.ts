/**
 * Shared shapes and helpers for a tool's part relations: what it produces
 * (Task 10 chips) and, on the standalone tool page and the project page's
 * Tool tab, the fallback cavity count parsed off a produces note.
 */
export interface ToolRelation {
  id: number;
  relation_type: string;
  direction: 'outgoing' | 'incoming';
  other_part_id: number;
  other_part_number: string;
  other_part_name: string;
  other_item_category: string;
  other_active_revision_name: string | null;
  other_active_customer_index: string | null;
  notes: string | null;
}

export interface ProducedArticle {
  part_id: number;
  part_number: string;
  name: string;
  revision_name: string | null;
  customer_index: string | null;
  notes: string | null;
}

export function producedArticles(relations: ToolRelation[]): ProducedArticle[] {
  return relations
    .filter((r) => r.relation_type === 'produces' && r.direction === 'outgoing')
    .map((r) => ({
      part_id: r.other_part_id, part_number: r.other_part_number, name: r.other_part_name,
      revision_name: r.other_active_revision_name, customer_index: r.other_active_customer_index, notes: r.notes,
    }))
    .sort((a, b) => a.part_number.localeCompare(b.part_number));
}
