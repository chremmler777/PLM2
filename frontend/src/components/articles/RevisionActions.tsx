/**
 * RevisionActions - Buttons for revision operations
 */

import { useState } from 'react';
import { ArticleResponse, RevisionResponse, RevisionStatusEnum } from '../../types/article';
import {
  useCreateEngineeringRevision,
  useReleaseRevision,
  useCreateChangeProposal,
} from '../../hooks/queries/useArticles';
import { toast } from 'sonner';

interface Props {
  articleId: number;
  selectedRevision: RevisionResponse | undefined;
  allRevisions: RevisionResponse[];
}

export default function RevisionActions({
  articleId,
  selectedRevision,
  allRevisions,
}: Props) {
  const createEngineering = useCreateEngineeringRevision(articleId);
  const releaseRevision = useReleaseRevision(articleId);
  const createChangeProposal = useCreateChangeProposal(articleId);

  const canCreateEngineering = true;
  const canRelease =
    selectedRevision?.status === RevisionStatusEnum.APPROVED &&
    selectedRevision?.revision_type === 'engineering';
  const canCreateChange =
    selectedRevision?.revision_type === 'released' &&
    selectedRevision?.status === RevisionStatusEnum.RELEASED;

  const handleCreateEngineering = async () => {
    try {
      await createEngineering.mutateAsync();
      toast.success('Engineering revision created');
    } catch (error) {
      toast.error('Failed to create revision');
    }
  };

  const handleRelease = async () => {
    if (!selectedRevision) return;
    try {
      await releaseRevision.mutateAsync({
        revisionId: selectedRevision.id,
        notes: `Released from ${selectedRevision.revision}`,
      });
      toast.success('Revision released');
    } catch (error) {
      toast.error('Failed to release revision');
    }
  };

  const handleCreateChange = async () => {
    if (!selectedRevision) return;
    try {
      await createChangeProposal.mutateAsync({
        releasedIndexId: selectedRevision.id,
        changeSummary: 'Change proposal created',
      });
      toast.success('Change proposal created');
    } catch (error) {
      toast.error('Failed to create change proposal');
    }
  };

  return (
    <div className="flex gap-3">
      <button
        onClick={handleCreateEngineering}
        disabled={createEngineering.isPending}
        className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-slate-600 font-medium text-sm"
      >
        {createEngineering.isPending ? 'Creating...' : 'New Engineering Revision'}
      </button>

      {canRelease && (
        <button
          onClick={handleRelease}
          disabled={releaseRevision.isPending}
          className="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:bg-slate-600 font-medium text-sm"
        >
          {releaseRevision.isPending ? 'Releasing...' : 'Release to Production'}
        </button>
      )}

      {canCreateChange && (
        <button
          onClick={handleCreateChange}
          disabled={createChangeProposal.isPending}
          className="px-4 py-2 bg-amber-600 text-white rounded-md hover:bg-amber-700 disabled:bg-slate-600 font-medium text-sm"
        >
          {createChangeProposal.isPending ? 'Creating...' : 'Create Change Proposal'}
        </button>
      )}

      {!canRelease && !canCreateChange && selectedRevision && (
        <div className="text-sm text-slate-400 py-2">
          {selectedRevision.revision_type === 'engineering'
            ? 'Approve revision to release'
            : 'Select a revision to perform actions'}
        </div>
      )}
    </div>
  );
}
