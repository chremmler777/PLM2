/**
 * Pinned detail header: name, numbers, phase, active revision, type and
 * category, mirror link, gauge calibration, and the part actions. It never
 * scrolls; the tab content below it does.
 */
import { useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../../api/client';
import { revisionLabel } from '../parts/RevisionBadge';
import { apiErrorMessage } from '../../lib/apiError';
import type { StructureArticle } from '../../hooks/queries/useProjectStructure';
import type { ArticleSelection } from '../../hooks/useArticleSelection';
import { CATEGORY_META, typeColor, type Part } from './projectTypes';

export default function DetailHeader({ projectId, part, article, sel, onPopOut }: {
  projectId: number;
  part: Part;
  article: StructureArticle | undefined;
  sel: ArticleSelection;
  onPopOut?: () => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const markCalibratedMutation = useMutation({
    mutationFn: async (partId: number) => {
      await client.put(`/v1/parts/${partId}`, { last_calibrated_at: new Date().toISOString() });
    },
    onSuccess: () => {
      toast.success('Calibration recorded');
      queryClient.invalidateQueries({ queryKey: ['parts', projectId] });
    },
    onError: (error: unknown) => {
      toast.error(apiErrorMessage(error, 'Failed to record calibration'));
    },
  });

  const activeRevision = sel.partRevisions?.find((r) => r.id === part.active_revision_id);
  const phase = article?.lifecycle_phase ?? part.lifecycle_phase;
  const category = CATEGORY_META[part.item_category];
  const overdue = !!part.next_calibration_due && new Date(part.next_calibration_due) < new Date();
  const facts = [
    part.supplier ? `Supplier: ${part.supplier}` : null,
    part.data_classification ? `Classification: ${part.data_classification}` : null,
  ].filter(Boolean).join(' · ');

  return (
    <div data-testid="detail-header" className="flex-shrink-0 px-4 py-3 border-b border-slate-700 bg-slate-800">
      <div className="flex items-start justify-between gap-3">
        <h2 className="min-w-0 truncate text-lg font-bold text-slate-100">{part.name}</h2>
        <div className="flex gap-2 flex-shrink-0">
          {onPopOut && (
            <button
              aria-label="Open detail in new window"
              title="Open detail in new window"
              onClick={onPopOut}
              className="px-3 py-1 rounded border border-slate-600 text-slate-300 hover:bg-slate-700 text-xs font-medium"
            >
              ⧉ Pop out
            </button>
          )}
          <button
            onClick={() => navigate(`/parts/${part.id}`)}
            className="px-3 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium"
          >
            Revisions & Lifecycle →
          </button>
        </div>
      </div>
      <div className="text-slate-400 text-sm mt-1 flex items-center gap-2 flex-wrap">
        <span className="font-mono">{part.part_number}</span>
        {part.customer_part_number && <span className="font-mono" title="Customer (OEM) part number">{part.customer_part_number}</span>}
        {part.tier1_part_number && <span className="font-mono" data-testid="selected-tier1-number" title="Tier 1 part number">Tier 1 {part.tier1_part_number}</span>}
        {phase && <span data-testid="detail-phase" className="text-xs text-slate-300">{phase}</span>}
        {activeRevision && (
          <span data-testid="detail-active-revision" title="Active revision" className="px-1.5 py-0.5 rounded bg-slate-700 text-xs text-slate-200 font-mono">
            {revisionLabel(activeRevision.revision_name, activeRevision.customer_index)}
          </span>
        )}
        <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${typeColor(part.part_type)}`}>
          {part.part_type.replace(/_/g, ' ')}
        </span>
        {category && (
          <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${category.badge}`}>
            {category.icon} {category.label}
          </span>
        )}
        {article?.mirror_of && (
          <button data-testid="mirror-chip" onClick={() => sel.openPart(article.mirror_of!.part_id)}
            className="px-2 py-0.5 rounded border border-red-500 text-red-300 text-xs">
            ⇄ Mirror of {article.mirror_of.customer_part_number ?? article.mirror_of.part_number} · data on that part
          </button>
        )}
      </div>
      {part.item_category === 'gauge' && (
        <div className="mt-2 flex items-center gap-3 text-sm">
          {part.next_calibration_due ? (
            <span className={overdue ? 'text-red-400 font-medium' : 'text-slate-300'}>
              📏 Calibration due {new Date(part.next_calibration_due).toLocaleDateString()}
              {overdue && ' (overdue)'}
            </span>
          ) : (
            <span className="text-amber-400">📏 No calibration recorded</span>
          )}
          <button
            onClick={() => markCalibratedMutation.mutate(part.id)}
            disabled={markCalibratedMutation.isPending}
            className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-medium"
          >
            {markCalibratedMutation.isPending ? 'Saving...' : 'Mark calibrated today'}
          </button>
        </div>
      )}
      {facts && <p className="text-slate-500 text-xs mt-1">{facts}</p>}
    </div>
  );
}
