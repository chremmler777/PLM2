/**
 * LessonsLearnedPage - capture, review and act on project lessons.
 * Lifecycle: draft → submitted → in_review → approved → implemented → closed (rejected → draft).
 * Lessons can be captured before their project exists in the PLM and linked afterwards.
 */
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import { toast } from 'sonner';

interface Lesson {
  id: number;
  title: string;
  project_id: number | null;
  project_name: string | null;
  project_ref: string | null;
  category: string;
  lesson_type: string;
  severity: string;
  description: string;
  root_cause: string | null;
  recommendation: string | null;
  tags: string | null;
  status: string;
  owner_id: number | null;
  created_at: string;
  open_actions: number;
  total_actions: number;
  allowed_transitions: string[];
}

interface LessonAction {
  id: number;
  description: string;
  assignee_id: number | null;
  assignee_name: string | null;
  due_date: string | null;
  status: string;
  overdue: boolean;
}

interface LessonComment {
  id: number;
  user_name: string | null;
  body: string;
  is_system: boolean;
  created_at: string;
}

interface LessonDetail extends Lesson {
  owner_name: string | null;
  created_by_name: string | null;
  actions: LessonAction[];
  comments: LessonComment[];
}

interface PickerUser {
  id: number;
  name: string;
}

const CATEGORIES = [
  'design', 'manufacturing', 'quality', 'supplier',
  'logistics', 'project_management', 'tooling', 'other',
];
const TYPES = ['success', 'problem', 'improvement'];
const SEVERITIES = ['low', 'medium', 'high', 'critical'];

const STATUS_STYLE: Record<string, string> = {
  draft: 'bg-slate-600/40 text-slate-300',
  submitted: 'bg-blue-600/30 text-blue-300',
  in_review: 'bg-amber-600/30 text-amber-300',
  approved: 'bg-emerald-600/30 text-emerald-300',
  implemented: 'bg-teal-600/30 text-teal-300',
  closed: 'bg-slate-700 text-slate-400',
  rejected: 'bg-red-600/30 text-red-300',
};

const SEVERITY_STYLE: Record<string, string> = {
  low: 'text-slate-400',
  medium: 'text-blue-300',
  high: 'text-amber-300',
  critical: 'text-red-400 font-semibold',
};

const TYPE_ICON: Record<string, string> = {
  success: '✅',
  problem: '⚠️',
  improvement: '💡',
};

const label = (s: string) => s.replace(/_/g, ' ');

function useProjects() {
  return useQuery({
    queryKey: ['projects'],
    queryFn: async () => (await client.get('/v1/plants/projects')).data as { id: number; name: string }[],
  });
}

function usePickerUsers() {
  return useQuery({
    queryKey: ['lesson-users'],
    queryFn: async () => (await client.get('/v1/lessons/assignable-users')).data as PickerUser[],
  });
}

const inputCls = 'w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm';

function NewLessonModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const { data: projects } = useProjects();
  const [form, setForm] = useState({
    title: '',
    description: '',
    category: 'other',
    lesson_type: 'problem',
    severity: 'medium',
    project_id: '' as string,
    project_ref: '',
    recommendation: '',
    tags: '',
  });

  const mutation = useMutation({
    mutationFn: async () => {
      await client.post('/v1/lessons', {
        title: form.title,
        description: form.description,
        category: form.category,
        lesson_type: form.lesson_type,
        severity: form.severity,
        project_id: form.project_id ? Number(form.project_id) : null,
        project_ref: form.project_id ? null : form.project_ref || null,
        recommendation: form.recommendation || null,
        tags: form.tags || null,
      });
    },
    onSuccess: () => {
      toast.success('Lesson captured');
      queryClient.invalidateQueries({ queryKey: ['lessons'] });
      queryClient.invalidateQueries({ queryKey: ['lesson-stats'] });
      onClose();
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to create lesson'),
  });

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center" onClick={onClose}>
      <div
        className="bg-slate-800 rounded-lg border border-slate-700 p-6 max-w-lg w-full mx-4 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-bold text-slate-100 mb-4">Capture Lesson</h2>
        <div className="space-y-3">
          <input
            type="text"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            placeholder="Title *"
            className={inputCls}
          />
          <textarea
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="What happened? *"
            rows={3}
            className={inputCls}
          />
          <div className="flex gap-3">
            <select
              value={form.lesson_type}
              onChange={(e) => setForm({ ...form, lesson_type: e.target.value })}
              className={inputCls}
            >
              {TYPES.map((t) => (
                <option key={t} value={t}>{TYPE_ICON[t]} {label(t)}</option>
              ))}
            </select>
            <select
              value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value })}
              className={inputCls}
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{label(c)}</option>
              ))}
            </select>
            <select
              value={form.severity}
              onChange={(e) => setForm({ ...form, severity: e.target.value })}
              className={inputCls}
            >
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>{label(s)}</option>
              ))}
            </select>
          </div>
          <select
            value={form.project_id}
            onChange={(e) => setForm({ ...form, project_id: e.target.value })}
            className={inputCls}
          >
            <option value="">— No PLM project (link later) —</option>
            {projects?.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          {!form.project_id && (
            <input
              type="text"
              value={form.project_ref}
              onChange={(e) => setForm({ ...form, project_ref: e.target.value })}
              placeholder="Project name (free text, for projects not in PLM yet)"
              className={inputCls}
            />
          )}
          <textarea
            value={form.recommendation}
            onChange={(e) => setForm({ ...form, recommendation: e.target.value })}
            placeholder="Recommendation — what should we do differently?"
            rows={2}
            className={inputCls}
          />
          <input
            type="text"
            value={form.tags}
            onChange={(e) => setForm({ ...form, tags: e.target.value })}
            placeholder="Tags (comma-separated)"
            className={inputCls}
          />
        </div>
        <div className="flex gap-3 mt-5">
          <button
            onClick={() => mutation.mutate()}
            disabled={form.title.length < 3 || form.description.length < 3 || mutation.isPending}
            className="flex-1 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded px-4 py-2 text-sm font-medium"
          >
            Capture
          </button>
          <button onClick={onClose} className="flex-1 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded px-4 py-2 text-sm">
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function LessonDetailModal({ lessonId, onClose }: { lessonId: number; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { data: projects } = useProjects();
  const { data: users } = usePickerUsers();
  const [newComment, setNewComment] = useState('');
  const [newAction, setNewAction] = useState({ description: '', assignee_id: '', due_date: '' });
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState({ root_cause: '', recommendation: '', owner_id: '' });

  const { data: lesson } = useQuery({
    queryKey: ['lesson', lessonId],
    queryFn: async () => (await client.get(`/v1/lessons/${lessonId}`)).data as LessonDetail,
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['lesson', lessonId] });
    queryClient.invalidateQueries({ queryKey: ['lessons'] });
    queryClient.invalidateQueries({ queryKey: ['lesson-stats'] });
  };

  const onApiError = (error: any) => toast.error(error.response?.data?.detail || 'Request failed');

  const transition = useMutation({
    mutationFn: async (status: string) => client.post(`/v1/lessons/${lessonId}/transition`, { status }),
    onSuccess: (_d, status) => { toast.success(`Status: ${label(status)}`); refresh(); },
    onError: onApiError,
  });

  const patchLesson = useMutation({
    mutationFn: async (payload: Record<string, unknown>) => client.patch(`/v1/lessons/${lessonId}`, payload),
    onSuccess: () => { toast.success('Lesson updated'); setEditing(false); refresh(); },
    onError: onApiError,
  });

  const addAction = useMutation({
    mutationFn: async () =>
      client.post(`/v1/lessons/${lessonId}/actions`, {
        description: newAction.description,
        assignee_id: newAction.assignee_id ? Number(newAction.assignee_id) : null,
        due_date: newAction.due_date ? `${newAction.due_date}T00:00:00` : null,
      }),
    onSuccess: () => { setNewAction({ description: '', assignee_id: '', due_date: '' }); refresh(); },
    onError: onApiError,
  });

  const toggleAction = useMutation({
    mutationFn: async (a: LessonAction) =>
      client.patch(`/v1/lessons/actions/${a.id}`, { status: a.status === 'open' ? 'done' : 'open' }),
    onSuccess: refresh,
    onError: onApiError,
  });

  const addComment = useMutation({
    mutationFn: async () => client.post(`/v1/lessons/${lessonId}/comments`, { body: newComment }),
    onSuccess: () => { setNewComment(''); refresh(); },
    onError: onApiError,
  });

  if (!lesson) return null;
  const readOnly = lesson.status === 'closed';

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center" onClick={onClose}>
      <div
        className="bg-slate-800 rounded-lg border border-slate-700 p-6 max-w-3xl w-full mx-4 max-h-[92vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <span>{TYPE_ICON[lesson.lesson_type]}</span>
              <h2 className="text-lg font-bold text-slate-100">{lesson.title}</h2>
              <span className={`text-xs px-2 py-0.5 rounded ${STATUS_STYLE[lesson.status] || ''}`}>
                {label(lesson.status)}
              </span>
              <span className={`text-xs ${SEVERITY_STYLE[lesson.severity] || ''}`}>{label(lesson.severity)}</span>
            </div>
            <div className="text-xs text-slate-400 mt-1">
              {label(lesson.category)} · created by {lesson.created_by_name}
              {lesson.owner_name && <> · owner {lesson.owner_name}</>}
            </div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200">✕</button>
        </div>

        {/* Project link */}
        <div className="mt-4 flex items-center gap-2 text-sm">
          {lesson.project_id ? (
            <span className="text-slate-300">
              Project: <span className="text-blue-300">{lesson.project_name}</span>
            </span>
          ) : (
            <>
              <span className="text-xs px-2 py-0.5 rounded bg-amber-600/30 text-amber-300">
                not linked{lesson.project_ref ? ` — "${lesson.project_ref}"` : ''}
              </span>
              {!readOnly && (
                <select
                  value=""
                  onChange={(e) => e.target.value && patchLesson.mutate({ project_id: Number(e.target.value) })}
                  className="bg-slate-700 border border-slate-600 rounded px-2 py-1 text-slate-100 text-xs"
                >
                  <option value="">Link to project…</option>
                  {projects?.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              )}
            </>
          )}
        </div>

        {/* Body */}
        <div className="mt-4 space-y-3 text-sm">
          <div>
            <div className="text-xs uppercase text-slate-500 mb-1">What happened</div>
            <p className="text-slate-200 whitespace-pre-wrap">{lesson.description}</p>
          </div>
          {lesson.root_cause && (
            <div>
              <div className="text-xs uppercase text-slate-500 mb-1">Root cause</div>
              <p className="text-slate-200 whitespace-pre-wrap">{lesson.root_cause}</p>
            </div>
          )}
          {lesson.recommendation && (
            <div>
              <div className="text-xs uppercase text-slate-500 mb-1">Recommendation</div>
              <p className="text-slate-200 whitespace-pre-wrap">{lesson.recommendation}</p>
            </div>
          )}
          {lesson.tags && (
            <div className="flex gap-1 flex-wrap">
              {lesson.tags.split(',').map((t) => (
                <span key={t} className="text-xs px-2 py-0.5 rounded bg-slate-700 text-slate-300">{t.trim()}</span>
              ))}
            </div>
          )}
        </div>

        {/* Edit root cause / recommendation / owner */}
        {!readOnly && (
          <div className="mt-3">
            {editing ? (
              <div className="space-y-2 bg-slate-900/50 rounded p-3">
                <textarea
                  value={editForm.root_cause}
                  onChange={(e) => setEditForm({ ...editForm, root_cause: e.target.value })}
                  placeholder="Root cause"
                  rows={2}
                  className={inputCls}
                />
                <textarea
                  value={editForm.recommendation}
                  onChange={(e) => setEditForm({ ...editForm, recommendation: e.target.value })}
                  placeholder="Recommendation"
                  rows={2}
                  className={inputCls}
                />
                <select
                  value={editForm.owner_id}
                  onChange={(e) => setEditForm({ ...editForm, owner_id: e.target.value })}
                  className={inputCls}
                >
                  <option value="">Owner (accountable person)…</option>
                  {users?.map((u) => (
                    <option key={u.id} value={u.id}>{u.name}</option>
                  ))}
                </select>
                <div className="flex gap-2">
                  <button
                    onClick={() =>
                      patchLesson.mutate({
                        root_cause: editForm.root_cause || null,
                        recommendation: editForm.recommendation || null,
                        owner_id: editForm.owner_id ? Number(editForm.owner_id) : null,
                      })
                    }
                    className="bg-blue-600 hover:bg-blue-500 text-white rounded px-3 py-1 text-xs"
                  >
                    Save
                  </button>
                  <button onClick={() => setEditing(false)} className="bg-slate-700 text-slate-300 rounded px-3 py-1 text-xs">
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => {
                  setEditForm({
                    root_cause: lesson.root_cause ?? '',
                    recommendation: lesson.recommendation ?? '',
                    owner_id: lesson.owner_id ? String(lesson.owner_id) : '',
                  });
                  setEditing(true);
                }}
                className="text-xs text-blue-400 hover:text-blue-300"
              >
                Edit analysis / owner
              </button>
            )}
          </div>
        )}

        {/* Workflow */}
        {lesson.allowed_transitions.length > 0 && (
          <div className="mt-4 flex items-center gap-2 border-t border-slate-700 pt-3">
            <span className="text-xs text-slate-500">Move to:</span>
            {lesson.allowed_transitions.map((s) => (
              <button
                key={s}
                onClick={() => transition.mutate(s)}
                disabled={transition.isPending}
                className={`text-xs px-3 py-1 rounded border border-slate-600 hover:border-slate-400 ${STATUS_STYLE[s] || 'text-slate-300'}`}
              >
                {label(s)}
              </button>
            ))}
          </div>
        )}

        {/* Actions */}
        <div className="mt-4 border-t border-slate-700 pt-3">
          <div className="text-xs uppercase text-slate-500 mb-2">
            Actions ({lesson.actions.filter((a) => a.status === 'done').length}/{lesson.actions.length} done)
          </div>
          <div className="space-y-1">
            {lesson.actions.map((a) => (
              <div key={a.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={a.status === 'done'}
                  disabled={readOnly}
                  onChange={() => toggleAction.mutate(a)}
                />
                <span className={a.status === 'done' ? 'line-through text-slate-500' : 'text-slate-200'}>
                  {a.description}
                </span>
                {a.assignee_name && <span className="text-xs text-blue-300">@{a.assignee_name}</span>}
                {a.due_date && (
                  <span className={`text-xs ${a.overdue ? 'text-red-400 font-semibold' : 'text-slate-500'}`}>
                    due {a.due_date.slice(0, 10)}{a.overdue && ' ⚠'}
                  </span>
                )}
              </div>
            ))}
            {lesson.actions.length === 0 && <div className="text-xs text-slate-500">No actions yet.</div>}
          </div>
          {!readOnly && (
            <div className="flex gap-2 mt-2">
              <input
                type="text"
                value={newAction.description}
                onChange={(e) => setNewAction({ ...newAction, description: e.target.value })}
                placeholder="New action…"
                className={`${inputCls} flex-1`}
              />
              <select
                value={newAction.assignee_id}
                onChange={(e) => setNewAction({ ...newAction, assignee_id: e.target.value })}
                className="bg-slate-700 border border-slate-600 rounded px-2 text-slate-100 text-xs"
              >
                <option value="">Assignee</option>
                {users?.map((u) => (
                  <option key={u.id} value={u.id}>{u.name}</option>
                ))}
              </select>
              <input
                type="date"
                value={newAction.due_date}
                onChange={(e) => setNewAction({ ...newAction, due_date: e.target.value })}
                className="bg-slate-700 border border-slate-600 rounded px-2 text-slate-100 text-xs"
              />
              <button
                onClick={() => addAction.mutate()}
                disabled={newAction.description.length < 3 || addAction.isPending}
                className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded px-3 text-sm"
              >
                Add
              </button>
            </div>
          )}
        </div>

        {/* Comments */}
        <div className="mt-4 border-t border-slate-700 pt-3">
          <div className="text-xs uppercase text-slate-500 mb-2">Activity</div>
          <div className="space-y-2 max-h-48 overflow-y-auto">
            {lesson.comments.map((c) =>
              c.is_system ? (
                <div key={c.id} className="text-xs text-slate-500 italic">
                  {c.body} · {c.created_at?.slice(0, 16).replace('T', ' ')}
                </div>
              ) : (
                <div key={c.id} className="text-sm">
                  <span className="text-blue-300 text-xs">{c.user_name}</span>{' '}
                  <span className="text-slate-500 text-xs">{c.created_at?.slice(0, 16).replace('T', ' ')}</span>
                  <p className="text-slate-200">{c.body}</p>
                </div>
              )
            )}
            {lesson.comments.length === 0 && <div className="text-xs text-slate-500">No activity yet.</div>}
          </div>
          <div className="flex gap-2 mt-2">
            <input
              type="text"
              value={newComment}
              onChange={(e) => setNewComment(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && newComment.trim() && addComment.mutate()}
              placeholder="Add a comment…"
              className={`${inputCls} flex-1`}
            />
            <button
              onClick={() => addComment.mutate()}
              disabled={!newComment.trim() || addComment.isPending}
              className="bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-200 rounded px-3 text-sm"
            >
              Post
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function LessonsLearnedPage() {
  const [showNew, setShowNew] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [unlinkedOnly, setUnlinkedOnly] = useState(false);
  const [search, setSearch] = useState('');

  const { data: lessons, isLoading } = useQuery({
    queryKey: ['lessons', statusFilter, categoryFilter, typeFilter, unlinkedOnly, search],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (statusFilter) params.set('status', statusFilter);
      if (categoryFilter) params.set('category', categoryFilter);
      if (typeFilter) params.set('lesson_type', typeFilter);
      if (unlinkedOnly) params.set('unlinked', 'true');
      if (search) params.set('q', search);
      return (await client.get(`/v1/lessons?${params}`)).data as Lesson[];
    },
  });

  const { data: stats } = useQuery({
    queryKey: ['lesson-stats'],
    queryFn: async () => (await client.get('/v1/lessons/stats')).data,
  });

  const statCard = (labelText: string, value: number | string, accent = 'text-slate-100') => (
    <div className="bg-slate-800 border border-slate-700 rounded-lg px-4 py-3">
      <div className={`text-xl font-bold ${accent}`}>{value}</div>
      <div className="text-xs text-slate-400">{labelText}</div>
    </div>
  );

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-slate-100">Lessons Learned</h1>
          <p className="text-sm text-slate-400">Capture, review, act — close only when actions are done.</p>
        </div>
        <button
          onClick={() => setShowNew(true)}
          className="bg-blue-600 hover:bg-blue-500 text-white rounded px-4 py-2 text-sm font-medium"
        >
          + Capture Lesson
        </button>
      </div>

      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
          {statCard('Total lessons', stats.total)}
          {statCard('In review', stats.by_status?.in_review ?? 0, 'text-amber-300')}
          {statCard('Open actions', stats.open_actions, 'text-blue-300')}
          {statCard('Overdue actions', stats.overdue_actions, stats.overdue_actions ? 'text-red-400' : 'text-slate-100')}
          {statCard('Not linked to project', stats.unlinked, stats.unlinked ? 'text-amber-300' : 'text-slate-100')}
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        {['', 'draft', 'submitted', 'in_review', 'approved', 'implemented', 'closed', 'rejected'].map((s) => (
          <button
            key={s || 'all'}
            onClick={() => setStatusFilter(s)}
            className={`text-xs px-3 py-1 rounded-full border ${
              statusFilter === s ? 'border-blue-400 text-blue-300' : 'border-slate-600 text-slate-400 hover:border-slate-400'
            }`}
          >
            {s ? label(s) : 'all'}
          </button>
        ))}
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-slate-300 text-xs"
        >
          <option value="">all categories</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>{label(c)}</option>
          ))}
        </select>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-slate-300 text-xs"
        >
          <option value="">all types</option>
          {TYPES.map((t) => (
            <option key={t} value={t}>{label(t)}</option>
          ))}
        </select>
        <label className="text-xs text-slate-400 flex items-center gap-1 cursor-pointer">
          <input type="checkbox" checked={unlinkedOnly} onChange={(e) => setUnlinkedOnly(e.target.checked)} />
          unlinked only
        </label>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search…"
          className="bg-slate-800 border border-slate-600 rounded px-3 py-1 text-slate-100 text-xs ml-auto"
        />
      </div>

      {/* Table */}
      <div className="bg-slate-800 border border-slate-700 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-400 border-b border-slate-700">
              <th className="px-4 py-2">Lesson</th>
              <th className="px-4 py-2">Project</th>
              <th className="px-4 py-2">Category</th>
              <th className="px-4 py-2">Severity</th>
              <th className="px-4 py-2">Actions</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2">Created</th>
            </tr>
          </thead>
          <tbody>
            {lessons?.map((l) => (
              <tr
                key={l.id}
                onClick={() => setSelectedId(l.id)}
                className="border-b border-slate-700/50 hover:bg-slate-700/30 cursor-pointer"
              >
                <td className="px-4 py-2 text-slate-100">
                  {TYPE_ICON[l.lesson_type]} {l.title}
                </td>
                <td className="px-4 py-2">
                  {l.project_id ? (
                    <span className="text-blue-300">{l.project_name}</span>
                  ) : (
                    <span className="text-xs px-2 py-0.5 rounded bg-amber-600/30 text-amber-300">
                      not linked{l.project_ref ? `: ${l.project_ref}` : ''}
                    </span>
                  )}
                </td>
                <td className="px-4 py-2 text-slate-300">{label(l.category)}</td>
                <td className={`px-4 py-2 ${SEVERITY_STYLE[l.severity] || ''}`}>{label(l.severity)}</td>
                <td className="px-4 py-2 text-slate-300">
                  {l.total_actions > 0 ? `${l.total_actions - l.open_actions}/${l.total_actions}` : '—'}
                </td>
                <td className="px-4 py-2">
                  <span className={`text-xs px-2 py-0.5 rounded ${STATUS_STYLE[l.status] || ''}`}>
                    {label(l.status)}
                  </span>
                </td>
                <td className="px-4 py-2 text-slate-400 text-xs">{l.created_at?.slice(0, 10)}</td>
              </tr>
            ))}
            {!isLoading && lessons?.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-slate-500 text-sm">
                  No lessons yet — capture the first one.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {showNew && <NewLessonModal onClose={() => setShowNew(false)} />}
      {selectedId !== null && <LessonDetailModal lessonId={selectedId} onClose={() => setSelectedId(null)} />}
    </div>
  );
}
