/**
 * ProjectLessonsSection - lessons linked to this project + reuse prompt.
 * Records "lesson reviewed for this project" references, which feed the reuse-rate KPI.
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import { toast } from 'sonner';

interface LessonRow {
  id: number;
  title: string;
  category: string;
  severity: string;
  status: string;
  lesson_type: string;
  project_id: number | null;
}

interface ReferenceRow {
  id: number;
  lesson_id: number;
  lesson_title: string;
  lesson_category: string;
  note: string | null;
  created_by_name: string | null;
}

const TYPE_ICON: Record<string, string> = { success: '✅', problem: '⚠️', improvement: '💡' };
const label = (s: string) => s.replace(/_/g, ' ');

function ReviewLessonsModal({ projectId, referencedIds, onClose }: {
  projectId: number;
  referencedIds: Set<number>;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');

  const { data: lessons } = useQuery({
    queryKey: ['lessons', 'review-pool', search],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (search) params.set('q', search);
      return (await client.get(`/v1/lessons?${params}`)).data as LessonRow[];
    },
  });

  const reference = useMutation({
    mutationFn: async (lessonId: number) =>
      client.post(`/v1/lessons/${lessonId}/references`, {
        project_id: projectId,
        note: 'Reviewed for applicability',
      }),
    onSuccess: () => {
      toast.success('Recorded as reviewed for this project');
      queryClient.invalidateQueries({ queryKey: ['lesson-references', projectId] });
      queryClient.invalidateQueries({ queryKey: ['lesson-kpis'] });
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to record'),
  });

  const candidates = (lessons ?? []).filter((l) => l.project_id !== projectId && l.status !== 'draft');

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center" onClick={onClose}>
      <div
        className="bg-slate-800 rounded-lg border border-slate-700 p-6 max-w-2xl w-full mx-4 max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-1">
          <h2 className="text-lg font-bold text-slate-100">Review Applicable Lessons</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200">✕</button>
        </div>
        <p className="text-xs text-slate-400 mb-3">
          Check lessons from other projects at kickoff and before gates. Marking one as reviewed
          records it for this project and counts toward the reuse KPI.
        </p>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search lessons (title, tags, description)…"
          className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm mb-3"
        />
        <div className="space-y-1">
          {candidates.map((l) => (
            <div key={l.id} className="flex items-center gap-2 text-sm bg-slate-900/40 rounded px-3 py-2">
              <span>{TYPE_ICON[l.lesson_type]}</span>
              <span className="text-slate-200 flex-1">{l.title}</span>
              <span className="text-xs text-slate-500">{label(l.category)} · {label(l.severity)}</span>
              {referencedIds.has(l.id) ? (
                <span className="text-xs text-emerald-400">✓ reviewed</span>
              ) : (
                <button
                  onClick={() => reference.mutate(l.id)}
                  disabled={reference.isPending}
                  className="text-xs px-2 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white"
                >
                  Mark reviewed
                </button>
              )}
            </div>
          ))}
          {candidates.length === 0 && (
            <div className="text-xs text-slate-500 py-4 text-center">No lessons from other projects found.</div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ProjectLessonsSection({ projectId }: { projectId: number }) {
  const navigate = useNavigate();
  const [showReview, setShowReview] = useState(false);

  const { data: lessons } = useQuery({
    queryKey: ['lessons', 'project', projectId],
    queryFn: async () =>
      (await client.get(`/v1/lessons?project_id=${projectId}`)).data as LessonRow[],
  });

  const { data: references } = useQuery({
    queryKey: ['lesson-references', projectId],
    queryFn: async () =>
      (await client.get(`/v1/lessons/projects/${projectId}/references`)).data as ReferenceRow[],
  });

  const referencedIds = new Set((references ?? []).map((r) => r.lesson_id));
  const needsReview = references !== undefined && references.length === 0;

  return (
    <div className="mb-4 bg-slate-800 rounded-lg border border-slate-700 p-3">
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-sm font-semibold text-slate-300">📘 Lessons</span>
        <button
          onClick={() => navigate(`/lessons?project=${projectId}`)}
          className="text-xs text-blue-400 hover:text-blue-300"
        >
          {lessons?.length ?? 0} from this project
        </button>
        <span className="text-xs text-slate-500">·</span>
        <span className="text-xs text-slate-400">{references?.length ?? 0} reviewed for reuse</span>
        {needsReview && (
          <span className="text-xs px-2 py-0.5 rounded bg-amber-600/30 text-amber-300">
            Gate prep: no lessons review recorded yet
          </span>
        )}
        <button
          onClick={() => setShowReview(true)}
          className="ml-auto text-xs px-3 py-1 rounded border border-slate-600 text-slate-300 hover:border-slate-400"
        >
          Review applicable lessons
        </button>
      </div>
      {showReview && (
        <ReviewLessonsModal
          projectId={projectId}
          referencedIds={referencedIds}
          onClose={() => setShowReview(false)}
        />
      )}
    </div>
  );
}
