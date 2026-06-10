/**
 * PartRelationsSection - Cross-links between controlled items:
 * tool produces article, gauge checks article, equipment assembles article.
 */
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import { toast } from 'sonner';

interface Relation {
  id: number;
  relation_type: string;
  direction: 'outgoing' | 'incoming';
  label: string;
  other_part_id: number;
  other_part_number: string;
  other_part_name: string;
  other_item_category: string;
  notes: string | null;
}

interface PartOption {
  id: number;
  part_number: string;
  name: string;
  item_category: string;
}

interface Props {
  partId: number;
  itemCategory: string;
  projectParts: PartOption[];
  onSelectPart?: (partId: number) => void;
}

const CATEGORY_ICONS: Record<string, string> = {
  article: '📄',
  tool: '🔧',
  assembly_equipment: '🏗️',
  gauge: '📏',
};

const DEFAULT_TYPE_BY_CATEGORY: Record<string, string> = {
  tool: 'produces',
  gauge: 'checks',
  assembly_equipment: 'assembles',
  article: 'related',
};

export default function PartRelationsSection({ partId, itemCategory, projectParts, onSelectPart }: Props) {
  const queryClient = useQueryClient();
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({
    to_part_id: '',
    relation_type: DEFAULT_TYPE_BY_CATEGORY[itemCategory] ?? 'related',
  });

  const { data: relations } = useQuery<Relation[]>({
    queryKey: ['part-relations', partId],
    queryFn: async () => (await client.get(`/v1/parts/${partId}/relations`)).data,
    enabled: !!partId,
  });

  const addMutation = useMutation({
    mutationFn: async () => {
      await client.post(`/v1/parts/${partId}/relations`, {
        to_part_id: parseInt(form.to_part_id, 10),
        relation_type: form.relation_type,
      });
    },
    onSuccess: () => {
      toast.success('Relation added');
      queryClient.invalidateQueries({ queryKey: ['part-relations'] });
      setShowAdd(false);
      setForm({ ...form, to_part_id: '' });
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to add relation');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (relationId: number) => {
      await client.delete(`/v1/parts/relations/${relationId}`);
    },
    onSuccess: () => {
      toast.success('Relation removed');
      queryClient.invalidateQueries({ queryKey: ['part-relations'] });
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to remove relation');
    },
  });

  const availableParts = projectParts.filter((p) => p.id !== partId);

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-200">Relations</h3>
        {!showAdd && (
          <button
            onClick={() => setShowAdd(true)}
            className="px-3 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium"
          >
            + Link Item
          </button>
        )}
      </div>

      {!relations || relations.length === 0 ? (
        <p className="text-slate-500 text-sm">
          No linked items — connect tools, gauges, or equipment to the articles they serve
        </p>
      ) : (
        <div className="space-y-1.5">
          {relations.map((rel) => (
            <div
              key={`${rel.id}-${rel.direction}`}
              className="flex items-center justify-between p-2 bg-slate-700/50 rounded border border-slate-600 text-sm"
            >
              <button
                onClick={() => onSelectPart?.(rel.other_part_id)}
                className="flex-1 text-left min-w-0 hover:text-blue-300"
              >
                <span className="text-slate-400 text-xs">{rel.label}</span>{' '}
                <span className="text-slate-100">
                  {CATEGORY_ICONS[rel.other_item_category] ?? ''} {rel.other_part_name}
                </span>
                <span className="text-slate-500 text-xs font-mono ml-1">{rel.other_part_number}</span>
              </button>
              <button
                onClick={() => deleteMutation.mutate(rel.id)}
                disabled={deleteMutation.isPending}
                className="text-red-400 hover:text-red-300 text-xs ml-2 flex-shrink-0"
                title="Remove relation"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      {showAdd && (
        <div className="mt-3 p-3 bg-slate-700/50 rounded border border-slate-600 space-y-2">
          <div className="flex gap-2">
            <select
              value={form.relation_type}
              onChange={(e) => setForm({ ...form, relation_type: e.target.value })}
              className="bg-slate-700 border border-slate-600 rounded px-2 py-1.5 text-slate-100 text-xs"
            >
              <option value="produces">produces</option>
              <option value="checks">checks</option>
              <option value="assembles">assembles</option>
              <option value="related">related to</option>
            </select>
            <select
              value={form.to_part_id}
              onChange={(e) => setForm({ ...form, to_part_id: e.target.value })}
              className="flex-1 bg-slate-700 border border-slate-600 rounded px-2 py-1.5 text-slate-100 text-xs"
            >
              <option value="">-- Select item --</option>
              {availableParts.map((p) => (
                <option key={p.id} value={p.id}>
                  {CATEGORY_ICONS[p.item_category] ?? ''} {p.part_number} — {p.name}
                </option>
              ))}
            </select>
          </div>
          <div className="flex gap-2 justify-end">
            <button
              onClick={() => setShowAdd(false)}
              className="px-3 py-1 rounded border border-slate-600 text-slate-300 hover:bg-slate-700 text-xs font-medium"
            >
              Cancel
            </button>
            <button
              onClick={() => addMutation.mutate()}
              disabled={!form.to_part_id || addMutation.isPending}
              className="px-3 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white text-xs font-medium"
            >
              {addMutation.isPending ? 'Linking...' : 'Link'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
