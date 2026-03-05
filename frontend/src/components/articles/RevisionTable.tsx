/**
 * RevisionTable - Display revisions in table format with status editing
 */

import { RevisionResponse, RevisionStatusEnum } from '../../types/article';
import { useTransitionRevisionStatus, useSetActiveRevision } from '../../hooks/queries/useArticles';
import { toast } from 'sonner';
import { useState } from 'react';

interface Props {
  revisions: RevisionResponse[];
  selectedRevisionId: number | null;
  onSelectRevision: (revisionId: number) => void;
  articleId: number;
  activeRevisionId: number | null;
}

const statusLabels: Record<RevisionStatusEnum, string> = {
  [RevisionStatusEnum.DRAFT]: 'Draft',
  [RevisionStatusEnum.RFQ]: 'RFQ',
  [RevisionStatusEnum.IN_REVIEW]: 'In Review',
  [RevisionStatusEnum.APPROVED]: 'Approved',
  [RevisionStatusEnum.IN_IMPLEMENTATION]: 'Implementing',
  [RevisionStatusEnum.RELEASED]: 'Released',
  [RevisionStatusEnum.REJECTED]: 'Rejected',
  [RevisionStatusEnum.CANCELED]: 'Canceled',
  [RevisionStatusEnum.SUPERSEDED]: 'Superseded',
};

const validTransitions: Record<RevisionStatusEnum, RevisionStatusEnum[]> = {
  [RevisionStatusEnum.DRAFT]: [RevisionStatusEnum.RFQ, RevisionStatusEnum.CANCELED],
  [RevisionStatusEnum.RFQ]: [RevisionStatusEnum.IN_REVIEW, RevisionStatusEnum.DRAFT, RevisionStatusEnum.CANCELED],
  [RevisionStatusEnum.IN_REVIEW]: [RevisionStatusEnum.APPROVED, RevisionStatusEnum.REJECTED, RevisionStatusEnum.DRAFT],
  [RevisionStatusEnum.APPROVED]: [RevisionStatusEnum.IN_IMPLEMENTATION, RevisionStatusEnum.REJECTED],
  [RevisionStatusEnum.IN_IMPLEMENTATION]: [RevisionStatusEnum.RELEASED, RevisionStatusEnum.REJECTED],
  [RevisionStatusEnum.RELEASED]: [],
  [RevisionStatusEnum.REJECTED]: [],
  [RevisionStatusEnum.CANCELED]: [],
  [RevisionStatusEnum.SUPERSEDED]: [],
};

export default function RevisionTable({
  revisions,
  selectedRevisionId,
  onSelectRevision,
  articleId,
  activeRevisionId,
}: Props) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingStatus, setEditingStatus] = useState<RevisionStatusEnum | null>(null);
  const transitionStatus = useTransitionRevisionStatus(articleId);
  const setActive = useSetActiveRevision(articleId);

  const handleStatusChange = async (revisionId: number, currentStatus: RevisionStatusEnum, newStatus: RevisionStatusEnum) => {
    try {
      await transitionStatus.mutateAsync({
        revisionId,
        newStatus,
        notes: `Transitioned to ${newStatus}`,
      });
      toast.success(`Status updated to ${newStatus}`);
      setEditingId(null);
      setEditingStatus(null);
    } catch (error) {
      toast.error('Failed to update status');
    }
  };

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
      <table className="w-full">
        <thead className="bg-slate-700 border-b border-slate-600">
          <tr>
            <th className="px-6 py-3 text-left text-xs font-semibold text-slate-200 uppercase tracking-wider">
              Revision
            </th>
            <th className="px-6 py-3 text-left text-xs font-semibold text-slate-200 uppercase tracking-wider">
              Type
            </th>
            <th className="px-6 py-3 text-left text-xs font-semibold text-slate-200 uppercase tracking-wider">
              Status
            </th>
            <th className="px-6 py-3 text-left text-xs font-semibold text-slate-200 uppercase tracking-wider">
              Created
            </th>
            <th className="px-6 py-3 text-left text-xs font-semibold text-slate-200 uppercase tracking-wider">
              BOM
            </th>
            <th className="px-6 py-3 text-left text-xs font-semibold text-slate-200 uppercase tracking-wider">
              Actions
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700">
          {revisions.map((rev) => (
            <tr
              key={rev.id}
              className={`hover:bg-slate-700 cursor-pointer ${
                selectedRevisionId === rev.id ? 'bg-blue-900' : ''
              }`}
              onClick={() => onSelectRevision(rev.id)}
            >
              <td className="px-6 py-4 whitespace-nowrap">
                <span className="font-mono font-semibold text-slate-100">{rev.revision}</span>
              </td>
              <td className="px-6 py-4 whitespace-nowrap">
                <span className="text-sm text-slate-300 capitalize">
                  {rev.revision_type.replace(/_/g, ' ')}
                </span>
              </td>
              <td className="px-6 py-4 whitespace-nowrap">
                {editingId === rev.id ? (
                  <select
                    value={editingStatus || rev.status}
                    onChange={(e) => setEditingStatus(e.target.value as RevisionStatusEnum)}
                    onClick={(e) => e.stopPropagation()}
                    className="px-2 py-1 border border-slate-600 rounded text-sm"
                  >
                    <option value={rev.status}>{statusLabels[rev.status]}</option>
                    {validTransitions[rev.status].map((status) => (
                      <option key={status} value={status}>
                        {statusLabels[status]}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="px-3 py-1 rounded-full text-xs font-semibold bg-slate-700 text-slate-100">
                    {statusLabels[rev.status]}
                  </span>
                )}
              </td>
              <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-300">
                {new Date(rev.created_at).toLocaleDateString()}
              </td>
              <td className="px-6 py-4 whitespace-nowrap text-sm" onClick={(e) => e.stopPropagation()}>
                {activeRevisionId === rev.id ? (
                  <span className="px-2 py-0.5 bg-green-900/60 text-green-300 rounded text-xs font-medium">Active</span>
                ) : (
                  <button
                    onClick={() => {
                      setActive.mutate(rev.id, {
                        onSuccess: () => toast.success(`Revision ${rev.revision} set as active`),
                        onError: () => toast.error('Failed to set active revision'),
                      });
                    }}
                    disabled={setActive.isPending}
                    className="text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50"
                  >
                    Set active
                  </button>
                )}
              </td>
              <td className="px-6 py-4 whitespace-nowrap text-sm" onClick={(e) => e.stopPropagation()}>
                {validTransitions[rev.status].length > 0 && (
                  <>
                    {editingId === rev.id ? (
                      <div className="flex gap-2">
                        <button
                          onClick={() =>
                            handleStatusChange(rev.id, rev.status, editingStatus || rev.status)
                          }
                          className="px-2 py-1 bg-blue-600 text-white rounded text-xs hover:bg-blue-700"
                        >
                          Save
                        </button>
                        <button
                          onClick={() => {
                            setEditingId(null);
                            setEditingStatus(null);
                          }}
                          className="px-2 py-1 bg-slate-700 text-slate-100 rounded text-xs hover:bg-slate-600"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setEditingId(rev.id)}
                        className="px-2 py-1 bg-slate-700 text-slate-200 rounded text-xs hover:bg-slate-600"
                      >
                        Edit Status
                      </button>
                    )}
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {revisions.length === 0 && (
        <div className="px-6 py-8 text-center text-slate-400">
          No revisions yet. Create one to get started.
        </div>
      )}
    </div>
  );
}
