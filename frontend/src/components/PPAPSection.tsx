/**
 * PPAPSection - Quality module: PPAP submission checklist per revision.
 */
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import { toast } from 'sonner';

interface PPAPElement {
  id: number;
  position: number;
  name: string;
  required: boolean;
  status: string;
  file_id: number | null;
  comment: string | null;
}

interface PPAPSubmission {
  id: number;
  revision_id: number;
  level: number;
  status: string;
  customer: string | null;
  progress: { done: number; required: number };
  decision_notes: string | null;
  elements: PPAPElement[];
}

interface RevisionFileOption {
  id: number;
  filename: string;
}

interface Props {
  revisionId: number;
  revisionName?: string;
  revisionFiles: RevisionFileOption[];
}

const STATUS_COLORS: Record<string, string> = {
  draft: 'bg-slate-600 text-slate-200',
  submitted: 'bg-blue-900/60 text-blue-300',
  approved: 'bg-green-900/60 text-green-300',
  rejected: 'bg-red-900/60 text-red-300',
};

const ELEMENT_STATUSES = ['pending', 'attached', 'approved', 'rejected', 'na'];

export default function PPAPSection({ revisionId, revisionName, revisionFiles }: Props) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [level, setLevel] = useState('3');

  const { data: ppap } = useQuery<PPAPSubmission | null>({
    queryKey: ['ppap', revisionId],
    queryFn: async () => (await client.get(`/v1/quality/revisions/${revisionId}/ppap`)).data,
    enabled: !!revisionId,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['ppap', revisionId] });
  const onError = (error: any) =>
    toast.error(error.response?.data?.detail || 'PPAP action failed');

  const createMutation = useMutation({
    mutationFn: async () => {
      await client.post(`/v1/quality/revisions/${revisionId}/ppap`, {
        level: parseInt(level, 10),
      });
    },
    onSuccess: () => {
      toast.success('PPAP submission created');
      invalidate();
      setExpanded(true);
    },
    onError,
  });

  const elementMutation = useMutation({
    mutationFn: async ({ id, ...patch }: { id: number; status?: string; file_id?: number }) => {
      await client.patch(`/v1/quality/ppap/elements/${id}`, patch);
    },
    onSuccess: invalidate,
    onError,
  });

  const transitionMutation = useMutation({
    mutationFn: async (action: 'submit' | 'approve' | 'reject') => {
      await client.post(`/v1/quality/ppap/${ppap!.id}/${action}`, action === 'submit' ? undefined : {});
    },
    onSuccess: () => {
      toast.success('PPAP updated');
      invalidate();
    },
    onError,
  });

  const editable = ppap && (ppap.status === 'draft' || ppap.status === 'submitted');

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-200">
          Quality / PPAP
          {revisionName ? <span className="text-slate-400 font-normal"> — {revisionName}</span> : null}
        </h3>
        {!ppap ? (
          <div className="flex items-center gap-2">
            <select
              value={level}
              onChange={(e) => setLevel(e.target.value)}
              className="bg-slate-700 border border-slate-600 rounded px-2 py-1 text-slate-100 text-xs"
            >
              {[1, 2, 3, 4, 5].map((l) => (
                <option key={l} value={l}>Level {l}</option>
              ))}
            </select>
            <button
              onClick={() => createMutation.mutate()}
              disabled={createMutation.isPending}
              className="px-3 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white text-xs font-medium"
            >
              {createMutation.isPending ? 'Creating...' : '+ Start PPAP'}
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[ppap.status] ?? 'bg-slate-600'}`}>
              Level {ppap.level} · {ppap.status}
            </span>
            <span className="text-xs text-slate-400">
              {ppap.progress.done}/{ppap.progress.required} required
            </span>
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-slate-400 hover:text-slate-200 text-xs"
            >
              {expanded ? '▲' : '▼'}
            </button>
          </div>
        )}
      </div>

      {ppap && (
        <div className="mt-2 h-1.5 bg-slate-700 rounded overflow-hidden">
          <div
            className={`h-full transition-all ${ppap.status === 'rejected' ? 'bg-red-500' : 'bg-green-500'}`}
            style={{
              width: `${ppap.progress.required ? (ppap.progress.done / ppap.progress.required) * 100 : 0}%`,
            }}
          />
        </div>
      )}

      {ppap && expanded && (
        <div className="mt-3 space-y-1">
          {ppap.elements.map((e) => (
            <div
              key={e.id}
              className={`flex items-center gap-2 p-1.5 rounded border text-xs ${
                e.required ? 'bg-slate-700/50 border-slate-600' : 'bg-slate-800/50 border-slate-700 opacity-70'
              }`}
            >
              <span className="text-slate-500 w-5 text-right">{e.position}.</span>
              <span className="flex-1 text-slate-200 min-w-0 truncate">
                {e.name}
                {e.required && <span className="text-amber-400 ml-1">*</span>}
              </span>
              {editable ? (
                <>
                  <select
                    value={e.file_id ?? ''}
                    onChange={(ev) =>
                      ev.target.value &&
                      elementMutation.mutate({ id: e.id, file_id: parseInt(ev.target.value, 10) })
                    }
                    className="bg-slate-700 border border-slate-600 rounded px-1 py-0.5 text-slate-300 text-xs max-w-[110px]"
                    title="Attach evidence file from this revision"
                  >
                    <option value="">{e.file_id ? '📎 attached' : '📎 file...'}</option>
                    {revisionFiles.map((f) => (
                      <option key={f.id} value={f.id}>{f.filename}</option>
                    ))}
                  </select>
                  <select
                    value={e.status}
                    onChange={(ev) => elementMutation.mutate({ id: e.id, status: ev.target.value })}
                    className="bg-slate-700 border border-slate-600 rounded px-1 py-0.5 text-slate-300 text-xs"
                  >
                    {ELEMENT_STATUSES.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </>
              ) : (
                <span className="text-slate-400">{e.status}</span>
              )}
            </div>
          ))}

          <div className="flex gap-2 justify-end pt-2">
            {ppap.status === 'draft' && (
              <button
                onClick={() => transitionMutation.mutate('submit')}
                disabled={transitionMutation.isPending}
                className="px-3 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white text-xs font-medium"
              >
                Submit PPAP
              </button>
            )}
            {ppap.status === 'submitted' && (
              <>
                <button
                  onClick={() => transitionMutation.mutate('reject')}
                  disabled={transitionMutation.isPending}
                  className="px-3 py-1 rounded bg-red-600 hover:bg-red-500 disabled:bg-slate-600 text-white text-xs font-medium"
                >
                  Reject
                </button>
                <button
                  onClick={() => transitionMutation.mutate('approve')}
                  disabled={transitionMutation.isPending}
                  className="px-3 py-1 rounded bg-green-600 hover:bg-green-500 disabled:bg-slate-600 text-white text-xs font-medium"
                >
                  Approve
                </button>
              </>
            )}
          </div>
          {ppap.decision_notes && (
            <p className="text-xs text-slate-400 pt-1">Decision notes: {ppap.decision_notes}</p>
          )}
        </div>
      )}

      {!ppap && (
        <p className="text-slate-500 text-xs mt-2">
          No PPAP submission for this revision yet
        </p>
      )}
    </div>
  );
}
