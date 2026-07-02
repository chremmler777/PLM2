/**
 * StartWorkflowModal - Select a template and start a workflow for a revision
 */

import { useState } from 'react';
import { useTemplates } from '../../hooks/queries/useWorkflows';
import { useStartWorkflow } from '../../hooks/queries/useWorkflows';
import { WfInstance } from '../../types/workflow';

interface Props {
  revisionId: number;
  onStarted: (instance: WfInstance) => void;
  onCancel: () => void;
}

export default function StartWorkflowModal({ revisionId, onStarted, onCancel }: Props) {
  const { data: templates = [], isLoading } = useTemplates();
  const startMutation = useStartWorkflow(revisionId);
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | ''>('');

  const activeTemplates = templates.filter((t) => t.is_active);

  const handleStart = () => {
    if (!selectedTemplateId) return;
    startMutation.mutate(
      { template_id: selectedTemplateId },
      {
        onSuccess: (instance) => onStarted(instance),
      },
    );
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-slate-800 border border-slate-700 rounded-lg shadow-lg max-w-md w-full mx-4">
        <div className="p-6">
          <h2 className="text-lg font-semibold text-slate-100 mb-4">Start Workflow</h2>

          {isLoading ? (
            <div className="text-slate-400 text-sm">Loading templates…</div>
          ) : activeTemplates.length === 0 ? (
            <div className="text-slate-400 text-sm">
              No active workflow templates found. Create a template in the Workflows section first.
            </div>
          ) : (
            <div className="mb-6">
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Select Template
              </label>
              <select
                value={selectedTemplateId}
                onChange={(e) =>
                  setSelectedTemplateId(e.target.value ? Number(e.target.value) : '')
                }
                className="w-full bg-slate-700 border border-slate-600 text-slate-100 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">— Choose a template —</option>
                {activeTemplates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} (v{t.version})
                  </option>
                ))}
              </select>
            </div>
          )}

          {startMutation.isError && (
            <p className="text-red-400 text-sm mb-4">
              Failed to start workflow. Please try again.
            </p>
          )}

          <div className="flex gap-3 justify-end">
            <button
              onClick={onCancel}
              disabled={startMutation.isPending}
              className="px-4 py-2 bg-slate-700 text-slate-100 rounded-md hover:bg-slate-600 disabled:opacity-50 font-medium"
            >
              Cancel
            </button>
            <button
              onClick={handleStart}
              disabled={!selectedTemplateId || startMutation.isPending}
              className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 font-medium"
            >
              {startMutation.isPending ? 'Starting…' : 'Start Workflow'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
