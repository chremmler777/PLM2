/**
 * WorkflowProgress - Live view of a running workflow instance
 * Shows stage progress bar, current-stage tasks, and action buttons.
 */

import { useState } from 'react';
import { WfInstance, WfInstanceTask, WfDecision } from '../../types/workflow';
import { rasicColors, instanceStatusColors } from '../../lib/constants';

interface Props {
  instance: WfInstance;
  onCompleteTask: (taskId: number, decision: WfDecision, notes?: string) => void;
  onCancel: () => void;
  isCompletingTask: boolean;
  isCanceling: boolean;
}

interface RejectState {
  taskId: number;
  notes: string;
}

export default function WorkflowProgress({
  instance,
  onCompleteTask,
  onCancel,
  isCompletingTask,
  isCanceling,
}: Props) {
  const [rejectState, setRejectState] = useState<RejectState | null>(null);

  // Derive unique stage orders from tasks for the progress bar
  const stageOrders = Array.from(new Set(instance.tasks.map((t) => t.stage_order))).sort(
    (a, b) => a - b,
  );

  const currentTasks = instance.tasks.filter(
    (t) => t.stage_order === instance.current_stage_order,
  );

  const statusLabel = instance.status.charAt(0).toUpperCase() + instance.status.slice(1);
  const statusClass = instanceStatusColors[instance.status] ?? 'bg-slate-600 text-white';

  const startedDate = new Date(instance.started_at).toLocaleDateString();

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <span className="font-semibold text-slate-100">{instance.template_name}</span>
          <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusClass}`}>
            {statusLabel}
          </span>
          <span className="text-xs text-slate-400">Started {startedDate}</span>
        </div>
        {instance.status === 'active' && (
          <button
            onClick={onCancel}
            disabled={isCanceling}
            className="px-3 py-1.5 text-sm bg-slate-700 text-slate-300 rounded hover:bg-slate-600 disabled:opacity-50"
          >
            {isCanceling ? 'Canceling…' : 'Cancel Workflow'}
          </button>
        )}
      </div>

      {/* Stage Progress Bar */}
      {stageOrders.length > 0 && (
        <div className="flex items-center gap-1">
          {stageOrders.map((order, idx) => {
            const isPast = order < instance.current_stage_order;
            const isCurrent = order === instance.current_stage_order;
            return (
              <div key={order} className="flex items-center gap-1">
                <div
                  className={`flex items-center justify-center w-7 h-7 rounded-full text-xs font-semibold transition-colors ${
                    isPast
                      ? 'bg-green-700 text-green-100'
                      : isCurrent
                      ? 'bg-blue-600 text-white ring-2 ring-blue-400'
                      : 'bg-slate-700 text-slate-400'
                  }`}
                  title={`Stage ${order}`}
                >
                  {isPast ? '✓' : order}
                </div>
                {idx < stageOrders.length - 1 && (
                  <div
                    className={`h-0.5 w-6 ${isPast ? 'bg-green-700' : 'bg-slate-700'}`}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Terminal state messages */}
      {instance.status === 'completed' && (
        <div className="bg-green-900 border border-green-700 rounded-lg p-4 text-green-200 text-sm">
          Workflow completed successfully.
        </div>
      )}
      {instance.status === 'rejected' && (
        <div className="bg-red-900 border border-red-700 rounded-lg p-4 text-red-200 text-sm">
          Workflow was rejected.
        </div>
      )}
      {instance.status === 'canceled' && (
        <div className="bg-slate-700 border border-slate-600 rounded-lg p-4 text-slate-300 text-sm">
          Workflow was canceled.{instance.cancel_reason ? ` Reason: ${instance.cancel_reason}` : ''}
        </div>
      )}

      {/* Current stage tasks */}
      {instance.status === 'active' && currentTasks.length > 0 && (
        <div className="space-y-2">
          <div className="text-sm font-medium text-slate-300">
            Stage {instance.current_stage_order} — Tasks
          </div>
          {currentTasks.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              isCompletingTask={isCompletingTask}
              onApprove={() => onCompleteTask(task.id, 'approved')}
              onReject={() => setRejectState({ taskId: task.id, notes: '' })}
            />
          ))}
        </div>
      )}

      {/* Reject confirmation with notes */}
      {rejectState && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-slate-800 border border-slate-700 rounded-lg shadow-lg max-w-md w-full mx-4 p-6">
            <h3 className="text-lg font-semibold text-slate-100 mb-3">Reject Task</h3>
            <p className="text-slate-300 text-sm mb-4">
              Rejecting this task will stop the entire workflow. Add an optional note below.
            </p>
            <textarea
              value={rejectState.notes}
              onChange={(e) => setRejectState({ ...rejectState, notes: e.target.value })}
              rows={3}
              placeholder="Reason for rejection (optional)…"
              className="w-full bg-slate-700 border border-slate-600 text-slate-100 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500 mb-4"
            />
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setRejectState(null)}
                className="px-4 py-2 bg-slate-700 text-slate-100 rounded-md hover:bg-slate-600 font-medium"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  onCompleteTask(rejectState.taskId, 'rejected', rejectState.notes || undefined);
                  setRejectState(null);
                }}
                disabled={isCompletingTask}
                className="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 disabled:opacity-50 font-medium"
              >
                {isCompletingTask ? 'Rejecting…' : 'Confirm Reject'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TaskRow — individual task within the current stage
// ---------------------------------------------------------------------------

interface TaskRowProps {
  task: WfInstanceTask;
  isCompletingTask: boolean;
  onApprove: () => void;
  onReject: () => void;
}

function TaskRow({ task, isCompletingTask, onApprove, onReject }: TaskRowProps) {
  const colors = rasicColors[task.rasic_letter] ?? rasicColors['R'];

  if (!task.is_actionable) {
    // S/I/C — auto-noted
    return (
      <div className="flex items-center gap-3 bg-slate-800 border border-slate-700 rounded-lg px-4 py-3 opacity-60">
        <span
          className={`${colors.bg} ${colors.text} text-xs font-semibold px-1.5 py-0.5 rounded`}
        >
          {task.rasic_letter}
        </span>
        <span className="text-slate-300 text-sm flex-1">{task.department_name}</span>
        <span className="text-xs bg-slate-700 text-slate-400 px-2 py-0.5 rounded">Noted</span>
      </div>
    );
  }

  if (task.status === 'approved') {
    return (
      <div className="flex items-center gap-3 bg-slate-800 border border-green-800 rounded-lg px-4 py-3">
        <span
          className={`${colors.bg} ${colors.text} text-xs font-semibold px-1.5 py-0.5 rounded`}
        >
          {task.rasic_letter}
        </span>
        <span className="text-slate-300 text-sm flex-1">{task.department_name}</span>
        <span className="text-xs bg-green-800 text-green-200 px-2 py-0.5 rounded font-medium">
          Approved
        </span>
      </div>
    );
  }

  if (task.status === 'rejected') {
    return (
      <div className="flex items-center gap-3 bg-slate-800 border border-red-800 rounded-lg px-4 py-3">
        <span
          className={`${colors.bg} ${colors.text} text-xs font-semibold px-1.5 py-0.5 rounded`}
        >
          {task.rasic_letter}
        </span>
        <span className="text-slate-300 text-sm flex-1">{task.department_name}</span>
        <span className="text-xs bg-red-800 text-red-200 px-2 py-0.5 rounded font-medium">
          Rejected
        </span>
      </div>
    );
  }

  // Active actionable task
  return (
    <div className="flex items-center gap-3 bg-slate-800 border border-slate-700 rounded-lg px-4 py-3">
      <span
        className={`${colors.bg} ${colors.text} text-xs font-semibold px-1.5 py-0.5 rounded`}
      >
        {task.rasic_letter}
      </span>
      <span className="text-slate-100 text-sm font-medium flex-1">{task.department_name}</span>
      <span className="text-xs text-slate-400 mr-2">{task.step_name}</span>
      <div className="flex gap-2">
        <button
          onClick={onApprove}
          disabled={isCompletingTask}
          className="px-3 py-1 text-xs bg-green-700 text-green-100 rounded hover:bg-green-600 disabled:opacity-50 font-medium"
        >
          Approve
        </button>
        <button
          onClick={onReject}
          disabled={isCompletingTask}
          className="px-3 py-1 text-xs bg-red-700 text-red-100 rounded hover:bg-red-600 disabled:opacity-50 font-medium"
        >
          Reject
        </button>
      </div>
    </div>
  );
}
