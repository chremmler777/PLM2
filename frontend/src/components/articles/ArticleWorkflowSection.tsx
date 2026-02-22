/**
 * ArticleWorkflowSection - Workflow instance management for an article revision
 */

import { useState } from 'react';
import { toast } from 'sonner';
import { LoadingSkeleton } from '../common/LoadingSkeleton';
import ConfirmModal from '../common/ConfirmModal';
import StartWorkflowModal from '../workflows/StartWorkflowModal';
import WorkflowProgress from '../workflows/WorkflowProgress';
import {
  useRevisionWorkflow,
  useCompleteTask,
  useCancelWorkflow,
} from '../../hooks/queries/useWorkflows';
import { WfDecision } from '../../types/workflow';

interface Props {
  articleId: number;
  revisionId: number;
}

export default function ArticleWorkflowSection({ revisionId }: Props) {
  const { data: instance, isLoading } = useRevisionWorkflow(revisionId);
  const completeMutation = useCompleteTask(instance?.id ?? 0, revisionId);
  const cancelMutation = useCancelWorkflow(instance?.id ?? 0, revisionId);

  const [showStartModal, setShowStartModal] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);

  const handleCompleteTask = (taskId: number, decision: WfDecision, notes?: string) => {
    completeMutation.mutate(
      { taskId, data: { decision, notes } },
      {
        onSuccess: () => toast.success(decision === 'approved' ? 'Task approved' : 'Task rejected'),
        onError: () => toast.error('Failed to complete task'),
      },
    );
  };

  const handleCancelWorkflow = () => {
    cancelMutation.mutate(
      {},
      {
        onSuccess: () => {
          setConfirmCancel(false);
          toast.success('Workflow canceled');
        },
        onError: () => toast.error('Failed to cancel workflow'),
      },
    );
  };

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-6">
      <h3 className="font-semibold text-slate-100 mb-4">Workflow</h3>

      {isLoading ? (
        <LoadingSkeleton count={3} />
      ) : !instance ? (
        /* No workflow started yet */
        <div className="text-center py-8">
          <p className="text-slate-400 mb-4">No active workflow for this revision.</p>
          <button
            onClick={() => setShowStartModal(true)}
            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 font-medium text-sm"
          >
            Start Workflow
          </button>
        </div>
      ) : (
        <WorkflowProgress
          instance={instance}
          onCompleteTask={handleCompleteTask}
          onCancel={() => setConfirmCancel(true)}
          isCompletingTask={completeMutation.isPending}
          isCanceling={cancelMutation.isPending}
        />
      )}

      {showStartModal && (
        <StartWorkflowModal
          revisionId={revisionId}
          onStarted={() => {
            setShowStartModal(false);
            toast.success('Workflow started');
          }}
          onCancel={() => setShowStartModal(false)}
        />
      )}

      {confirmCancel && (
        <ConfirmModal
          isOpen
          title="Cancel Workflow"
          message="Cancel this workflow? All tasks will be stopped and no further approvals can be made."
          confirmText="Cancel Workflow"
          isDangerous
          onConfirm={handleCancelWorkflow}
          onCancel={() => setConfirmCancel(false)}
          isLoading={cancelMutation.isPending}
        />
      )}
    </div>
  );
}
