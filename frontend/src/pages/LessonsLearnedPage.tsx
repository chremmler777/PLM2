/**
 * LessonsLearnedPage - strict lessons lifecycle.
 * in_review → (accept: owner+target+actions) → in_work → (owner sends, all done)
 * → verification → (verified) closed | (feedback) back to in_work.
 * in_review → rejected (categorized reason). Capture lands directly in review.
 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
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
  target_date: string | null;
  target_overdue: boolean;
  reject_category: string | null;
  reject_reason: string | null;
  created_at: string;
  days_in_state: number | null;
  stale: boolean;
  open_actions: number;
  total_actions: number;
  allowed_transitions: string[];
  editable_fields: string[];
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

interface LessonFile {
  id: number;
  filename: string;
  size_bytes: number;
  created_at: string;
}

interface LessonDetail extends Lesson {
  owner_name: string | null;
  created_by_name: string | null;
  effectiveness_note: string | null;
  actions: LessonAction[];
  comments: LessonComment[];
  files: LessonFile[];
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
const REJECT_CATEGORIES = ['duplicate', 'not_actionable', 'out_of_scope', 'insufficient_info'];
const STATUSES = ['in_review', 'in_work', 'verification', 'closed', 'rejected'];
const STEPPER_STATES = ['in_review', 'in_work', 'verification', 'closed'];

const STATUS_STYLE: Record<string, string> = {
  in_review: 'bg-amber-600/30 text-amber-300',
  in_work: 'bg-blue-600/30 text-blue-300',
  verification: 'bg-purple-600/30 text-purple-300',
  closed: 'bg-emerald-600/30 text-emerald-300',
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
const inputCls = 'w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm';

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

function useTagSuggestions() {
  return useQuery({
    queryKey: ['lesson-tags'],
    queryFn: async () => (await client.get('/v1/lessons/tags')).data as { tag: string; count: number }[],
  });
}

/** Tags input with autocomplete chips from existing tags. */
function TagInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { data: suggestions } = useTagSuggestions();
  const current = value.split(',').map((t) => t.trim().toLowerCase()).filter(Boolean);
  const lastFragment = value.split(',').pop()?.trim().toLowerCase() ?? '';
  const matches = (suggestions ?? [])
    .filter((s) => !current.includes(s.tag))
    .filter((s) => !lastFragment || s.tag.includes(lastFragment))
    .slice(0, 6);

  const addTag = (tag: string) => {
    // replace the fragment being typed with the clicked suggestion
    const parts = value.split(',').map((t) => t.trim()).filter(Boolean);
    parts.pop();
    onChange([...parts.filter((p) => p.toLowerCase() !== tag), tag].join(', '));
  };

  return (
    <div>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Tags (comma-separated)"
        className={inputCls}
      />
      {matches.length > 0 && (
        <div className="flex gap-1 flex-wrap mt-1">
          {matches.map((s) => (
            <button
              key={s.tag}
              type="button"
              onClick={() => addTag(s.tag)}
              className="text-xs px-2 py-0.5 rounded bg-slate-700 text-slate-300 hover:bg-slate-600"
            >
              + {s.tag} <span className="text-slate-500">({s.count})</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Lifecycle stepper with time-in-state. */
function LifecycleStepper({ lesson }: { lesson: Lesson }) {
  if (lesson.status === 'rejected') {
    return (
      <div className="flex items-center gap-2 text-xs">
        <span className="px-2 py-1 rounded bg-red-600/30 text-red-300">
          ✕ rejected ({label(lesson.reject_category ?? '')})
        </span>
        <span className="text-slate-500">{lesson.reject_reason}</span>
      </div>
    );
  }
  const currentIdx = STEPPER_STATES.indexOf(lesson.status);
  return (
    <div className="flex items-center gap-1 flex-wrap text-xs">
      {STEPPER_STATES.map((s, i) => {
        const done = i < currentIdx || lesson.status === 'closed';
        const active = i === currentIdx && lesson.status !== 'closed';
        return (
          <div key={s} className="flex items-center gap-1">
            {i > 0 && <span className={done || active ? 'text-slate-400' : 'text-slate-700'}>→</span>}
            <span
              className={`px-2 py-1 rounded ${
                active
                  ? STATUS_STYLE[s] + ' ring-1 ring-current'
                  : done
                    ? 'bg-emerald-900/40 text-emerald-400'
                    : 'bg-slate-800 text-slate-600'
              }`}
            >
              {done && !active ? '✓ ' : ''}{label(s)}
              {active && lesson.days_in_state !== null && (
                <span className="ml-1 opacity-75">· {lesson.days_in_state}d</span>
              )}
            </span>
          </div>
        );
      })}
      {lesson.stale && (
        <span className="px-2 py-1 rounded bg-red-600/30 text-red-300 ml-1">⏰ stale</span>
      )}
      {lesson.target_overdue && (
        <span className="px-2 py-1 rounded bg-red-600/30 text-red-300 ml-1">⚠ past target</span>
      )}
    </div>
  );
}

function NewLessonModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const { data: projects } = useProjects();
  const titleRef = useRef<HTMLInputElement>(null);
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
  const [duplicates, setDuplicates] = useState<{ id: number; title: string; status: string }[]>([]);

  useEffect(() => {
    titleRef.current?.focus();
  }, []);

  // Debounced duplicate guard
  useEffect(() => {
    if (form.title.trim().length < 4) {
      setDuplicates([]);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const res = await client.get(`/v1/lessons/check-duplicates?title=${encodeURIComponent(form.title)}`);
        setDuplicates(res.data);
      } catch {
        /* guard is advisory only */
      }
    }, 400);
    return () => clearTimeout(t);
  }, [form.title]);

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
      toast.success('Lesson captured — now in the review queue');
      queryClient.invalidateQueries({ queryKey: ['lessons'] });
      queryClient.invalidateQueries({ queryKey: ['lesson-stats'] });
      queryClient.invalidateQueries({ queryKey: ['lesson-kpis'] });
      onClose();
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to create lesson'),
  });

  const canSubmit = form.title.length >= 3 && form.description.length >= 3 && !mutation.isPending;

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center" onClick={onClose}>
      <div
        className="bg-slate-800 rounded-lg border border-slate-700 p-6 max-w-lg w-full mx-4 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && canSubmit) mutation.mutate();
        }}
      >
        <h2 className="text-lg font-bold text-slate-100">Capture Lesson</h2>
        <p className="text-xs text-slate-400 mb-4">Goes directly to the review queue. Ctrl+Enter to submit.</p>
        <div className="space-y-3">
          <input
            ref={titleRef}
            type="text"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            placeholder="Title *"
            className={inputCls}
          />
          {duplicates.length > 0 && (
            <div className="text-xs bg-amber-600/10 border border-amber-700/40 rounded p-2 text-amber-200">
              ⚠ Similar lessons already exist — avoid double entries:
              {duplicates.map((d) => (
                <div key={d.id} className="mt-1 text-amber-100">
                  • {d.title} <span className="text-amber-400/70">({label(d.status)})</span>
                </div>
              ))}
            </div>
          )}
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
          <TagInput value={form.tags} onChange={(tags) => setForm({ ...form, tags })} />
        </div>
        <div className="flex gap-3 mt-5">
          <button
            onClick={() => mutation.mutate()}
            disabled={!canSubmit}
            className="flex-1 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded px-4 py-2 text-sm font-medium"
          >
            Capture → Review
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
  const [closeDialog, setCloseDialog] = useState<{ verified: boolean; note: string } | null>(null);
  const [rejectDialog, setRejectDialog] = useState<{ category: string; reason: string } | null>(null);
  const [sendBackDialog, setSendBackDialog] = useState<{ feedback: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { data: lesson } = useQuery({
    queryKey: ['lesson', lessonId],
    queryFn: async () => (await client.get(`/v1/lessons/${lessonId}`)).data as LessonDetail,
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['lesson', lessonId] });
    queryClient.invalidateQueries({ queryKey: ['lessons'] });
    queryClient.invalidateQueries({ queryKey: ['lesson-stats'] });
    queryClient.invalidateQueries({ queryKey: ['lesson-kpis'] });
  };

  const onApiError = (error: any) => toast.error(error.response?.data?.detail || 'Request failed');

  const transition = useMutation({
    mutationFn: async (payload: Record<string, unknown>) =>
      client.post(`/v1/lessons/${lessonId}/transition`, payload),
    onSuccess: (_d, payload: any) => {
      toast.success(`Status: ${label(payload.status)}`);
      setCloseDialog(null);
      setRejectDialog(null);
      setSendBackDialog(null);
      refresh();
    },
    onError: onApiError,
  });

  const patchLesson = useMutation({
    mutationFn: async (payload: Record<string, unknown>) => client.patch(`/v1/lessons/${lessonId}`, payload),
    onSuccess: () => refresh(),
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

  const uploadFile = useMutation({
    mutationFn: async (file: globalThis.File) => {
      const fd = new FormData();
      fd.append('file', file);
      return client.post(`/v1/lessons/${lessonId}/files`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
    },
    onSuccess: () => { toast.success('Evidence attached'); refresh(); },
    onError: onApiError,
  });

  const deleteFile = useMutation({
    mutationFn: async (fileId: number) => client.delete(`/v1/lessons/files/${fileId}`),
    onSuccess: refresh,
    onError: onApiError,
  });

  if (!lesson) return null;

  const can = (field: string) => lesson.editable_fields.includes(field);
  const workable = lesson.status === 'in_review' || lesson.status === 'in_work';
  const terminal = lesson.status === 'closed' || lesson.status === 'rejected';
  const allDone = lesson.actions.length > 0 && lesson.actions.every((a) => a.status === 'done');

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center" onClick={onClose}>
      <div
        className="bg-slate-800 rounded-lg border border-slate-700 p-6 max-w-3xl w-full mx-4 max-h-[92vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span>{TYPE_ICON[lesson.lesson_type]}</span>
              <h2 className="text-lg font-bold text-slate-100">{lesson.title}</h2>
              <span className={`text-xs ${SEVERITY_STYLE[lesson.severity] || ''}`}>{label(lesson.severity)}</span>
            </div>
            <div className="text-xs text-slate-400 mt-1">
              {label(lesson.category)} · created by {lesson.created_by_name}
              {lesson.owner_name && <> · responsible: <span className="text-slate-200">{lesson.owner_name}</span></>}
              {lesson.target_date && (
                <> · target <span className={lesson.target_overdue ? 'text-red-400' : 'text-slate-200'}>
                  {lesson.target_date.slice(0, 10)}
                </span></>
              )}
            </div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200">✕</button>
        </div>

        <div className="mt-3">
          <LifecycleStepper lesson={lesson} />
        </div>

        {/* Project link */}
        <div className="mt-3 flex items-center gap-2 text-sm">
          {lesson.project_id ? (
            <span className="text-slate-300">
              Project: <span className="text-blue-300">{lesson.project_name}</span>
            </span>
          ) : (
            <>
              <span className="text-xs px-2 py-0.5 rounded bg-amber-600/30 text-amber-300">
                not linked{lesson.project_ref ? ` — "${lesson.project_ref}"` : ''}
              </span>
              {can('project_id') && (
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

        {/* Content */}
        <div className="mt-4 space-y-3 text-sm">
          <div>
            <div className="text-xs uppercase text-slate-500 mb-1">What happened</div>
            <p className="text-slate-200 whitespace-pre-wrap">{lesson.description}</p>
          </div>
          <div>
            <div className="text-xs uppercase text-slate-500 mb-1">Root cause</div>
            {can('root_cause') ? (
              <textarea
                defaultValue={lesson.root_cause ?? ''}
                onBlur={(e) => {
                  if (e.target.value !== (lesson.root_cause ?? '')) {
                    patchLesson.mutate({ root_cause: e.target.value || null });
                  }
                }}
                placeholder="Why did it happen?"
                rows={2}
                className={inputCls}
              />
            ) : (
              <p className="text-slate-200 whitespace-pre-wrap">{lesson.root_cause || <span className="text-slate-500">—</span>}</p>
            )}
          </div>
          <div>
            <div className="text-xs uppercase text-slate-500 mb-1">Recommendation</div>
            {can('recommendation') ? (
              <textarea
                defaultValue={lesson.recommendation ?? ''}
                onBlur={(e) => {
                  if (e.target.value !== (lesson.recommendation ?? '')) {
                    patchLesson.mutate({ recommendation: e.target.value || null });
                  }
                }}
                placeholder="What should we do differently?"
                rows={2}
                className={inputCls}
              />
            ) : (
              <p className="text-slate-200 whitespace-pre-wrap">{lesson.recommendation || <span className="text-slate-500">—</span>}</p>
            )}
          </div>
          {lesson.tags && (
            <div className="flex gap-1 flex-wrap">
              {lesson.tags.split(',').map((t) => (
                <span key={t} className="text-xs px-2 py-0.5 rounded bg-slate-700 text-slate-300">{t.trim()}</span>
              ))}
            </div>
          )}
        </div>

        {/* Triage box (in_review): define responsible + timing, then accept/reject */}
        {lesson.status === 'in_review' && (
          <div className="mt-4 bg-slate-900/60 border border-amber-700/40 rounded p-3 space-y-2">
            <div className="text-sm font-medium text-amber-200">
              Triage — define responsible, timing and actions, then accept or reject
            </div>
            <div className="flex gap-2">
              <select
                value={lesson.owner_id ?? ''}
                onChange={(e) => e.target.value && patchLesson.mutate({ owner_id: Number(e.target.value) })}
                className={inputCls}
              >
                <option value="">Responsible owner *</option>
                {users?.map((u) => (
                  <option key={u.id} value={u.id}>{u.name}</option>
                ))}
              </select>
              <input
                type="date"
                value={lesson.target_date?.slice(0, 10) ?? ''}
                onChange={(e) =>
                  e.target.value && patchLesson.mutate({ target_date: `${e.target.value}T00:00:00` })
                }
                className={inputCls}
              />
            </div>
            <div className="text-xs text-slate-500">
              Actions defined below: {lesson.total_actions} {lesson.total_actions === 0 && '— at least one required'}
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => transition.mutate({ status: 'in_work' })}
                disabled={transition.isPending}
                className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded px-4 py-1.5 text-sm"
              >
                ✓ Accept → In Work
              </button>
              <button
                onClick={() => setRejectDialog({ category: 'duplicate', reason: '' })}
                className="bg-slate-700 hover:bg-red-900/60 text-red-300 rounded px-4 py-1.5 text-sm"
              >
                ✕ Reject…
              </button>
            </div>
            {rejectDialog && (
              <div className="space-y-2 border-t border-slate-700 pt-2">
                <select
                  value={rejectDialog.category}
                  onChange={(e) => setRejectDialog({ ...rejectDialog, category: e.target.value })}
                  className={inputCls}
                >
                  {REJECT_CATEGORIES.map((c) => (
                    <option key={c} value={c}>{label(c)}</option>
                  ))}
                </select>
                <textarea
                  value={rejectDialog.reason}
                  onChange={(e) => setRejectDialog({ ...rejectDialog, reason: e.target.value })}
                  placeholder="Reason (required, the submitter will be notified)"
                  rows={2}
                  className={inputCls}
                />
                <div className="flex gap-2">
                  <button
                    onClick={() =>
                      transition.mutate({
                        status: 'rejected',
                        reject_category: rejectDialog.category,
                        reject_reason: rejectDialog.reason,
                      })
                    }
                    disabled={!rejectDialog.reason.trim() || transition.isPending}
                    className="bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white rounded px-3 py-1 text-xs"
                  >
                    Confirm reject
                  </button>
                  <button onClick={() => setRejectDialog(null)} className="bg-slate-700 text-slate-300 rounded px-3 py-1 text-xs">
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Send to verification (in_work) */}
        {lesson.status === 'in_work' && (
          <div className="mt-4 flex items-center gap-2 border-t border-slate-700 pt-3">
            <button
              onClick={() => transition.mutate({ status: 'verification' })}
              disabled={!allDone || transition.isPending}
              className="bg-purple-700 hover:bg-purple-600 disabled:opacity-50 text-white rounded px-4 py-1.5 text-sm"
            >
              Send to verification →
            </button>
            {!allDone && (
              <span className="text-xs text-slate-500">all actions must be done first ({lesson.open_actions} open)</span>
            )}
          </div>
        )}

        {/* Verification review */}
        {lesson.status === 'verification' && (
          <div className="mt-4 bg-slate-900/60 border border-purple-700/40 rounded p-3 space-y-2">
            <div className="text-sm font-medium text-purple-200">
              Verification — did the recommendation work? Check actions and evidence below.
            </div>
            {!closeDialog && !sendBackDialog && (
              <div className="flex gap-2">
                <button
                  onClick={() => setCloseDialog({ verified: false, note: '' })}
                  className="bg-emerald-700 hover:bg-emerald-600 text-white rounded px-4 py-1.5 text-sm"
                >
                  ✓ Verify & close…
                </button>
                <button
                  onClick={() => setSendBackDialog({ feedback: '' })}
                  className="bg-slate-700 hover:bg-slate-600 text-amber-300 rounded px-4 py-1.5 text-sm"
                >
                  ↩ Send back to work…
                </button>
              </div>
            )}
            {closeDialog && (
              <div className="space-y-2">
                <label className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={closeDialog.verified}
                    onChange={(e) => setCloseDialog({ ...closeDialog, verified: e.target.checked })}
                  />
                  The recommendation was applied and verified effective
                </label>
                <textarea
                  value={closeDialog.note}
                  onChange={(e) => setCloseDialog({ ...closeDialog, note: e.target.value })}
                  placeholder="How was effectiveness verified? (e.g. no recurrence on next build)"
                  rows={2}
                  className={inputCls}
                />
                <div className="flex gap-2">
                  <button
                    onClick={() =>
                      transition.mutate({
                        status: 'closed',
                        effectiveness_verified: true,
                        effectiveness_note: closeDialog.note || undefined,
                      })
                    }
                    disabled={!closeDialog.verified || transition.isPending}
                    className="bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 text-white rounded px-3 py-1 text-xs"
                  >
                    Close lesson
                  </button>
                  <button onClick={() => setCloseDialog(null)} className="bg-slate-700 text-slate-300 rounded px-3 py-1 text-xs">
                    Cancel
                  </button>
                </div>
              </div>
            )}
            {sendBackDialog && (
              <div className="space-y-2">
                <textarea
                  value={sendBackDialog.feedback}
                  onChange={(e) => setSendBackDialog({ feedback: e.target.value })}
                  placeholder="Feedback for the owner — what is missing? (required)"
                  rows={2}
                  className={inputCls}
                />
                <div className="flex gap-2">
                  <button
                    onClick={() => transition.mutate({ status: 'in_work', feedback: sendBackDialog.feedback })}
                    disabled={!sendBackDialog.feedback.trim() || transition.isPending}
                    className="bg-amber-700 hover:bg-amber-600 disabled:opacity-50 text-white rounded px-3 py-1 text-xs"
                  >
                    Send back
                  </button>
                  <button onClick={() => setSendBackDialog(null)} className="bg-slate-700 text-slate-300 rounded px-3 py-1 text-xs">
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {lesson.status === 'closed' && lesson.effectiveness_note && (
          <div className="mt-3 text-xs text-emerald-400">
            ✓ Effectiveness verified: <span className="text-slate-300">{lesson.effectiveness_note}</span>
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
                  disabled={!workable}
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
          {workable && (
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

        {/* Evidence */}
        <div className="mt-4 border-t border-slate-700 pt-3">
          <div className="flex items-center justify-between mb-2">
            <div className="text-xs uppercase text-slate-500">Evidence ({lesson.files.length})</div>
            {workable && (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) uploadFile.mutate(f);
                    e.target.value = '';
                  }}
                />
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploadFile.isPending}
                  className="text-xs px-3 py-1 rounded border border-slate-600 text-slate-300 hover:border-slate-400"
                >
                  📎 Attach file
                </button>
              </>
            )}
          </div>
          <div className="space-y-1">
            {lesson.files.map((f) => (
              <div key={f.id} className="flex items-center gap-2 text-sm">
                <button
                  onClick={async () => {
                    const res = await client.get(`/v1/lessons/files/${f.id}/download`, { responseType: 'blob' });
                    const url = URL.createObjectURL(res.data);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = f.filename;
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                  className="text-blue-400 hover:text-blue-300 underline"
                >
                  {f.filename}
                </button>
                <span className="text-xs text-slate-500">{(f.size_bytes / 1024).toFixed(0)} KB</span>
                {workable && (
                  <button
                    onClick={() => deleteFile.mutate(f.id)}
                    className="text-xs text-slate-500 hover:text-red-400"
                  >
                    ✕
                  </button>
                )}
              </div>
            ))}
            {lesson.files.length === 0 && <div className="text-xs text-slate-500">No evidence attached.</div>}
          </div>
        </div>

        {/* Activity */}
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
          {!terminal && (
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
          )}
        </div>
      </div>
    </div>
  );
}

export default function LessonsLearnedPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [showNew, setShowNew] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(
    searchParams.get('lesson') ? Number(searchParams.get('lesson')) : null
  );
  const [statusFilter, setStatusFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [unlinkedOnly, setUnlinkedOnly] = useState(false);
  const [mineOnly, setMineOnly] = useState(false);
  const [search, setSearch] = useState('');
  const [queueMode, setQueueMode] = useState(false);
  const projectFilter = searchParams.get('project') ? Number(searchParams.get('project')) : null;

  const closeDetail = () => {
    setSelectedId(null);
    if (searchParams.get('lesson')) {
      searchParams.delete('lesson');
      setSearchParams(searchParams, { replace: true });
    }
  };

  const { data: lessons, isLoading } = useQuery({
    queryKey: ['lessons', statusFilter, categoryFilter, typeFilter, unlinkedOnly, mineOnly, search, projectFilter, queueMode],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (queueMode) params.set('status', 'in_review');
      else if (statusFilter) params.set('status', statusFilter);
      if (categoryFilter) params.set('category', categoryFilter);
      if (typeFilter) params.set('lesson_type', typeFilter);
      if (unlinkedOnly) params.set('unlinked', 'true');
      if (mineOnly) params.set('mine', 'true');
      if (search) params.set('q', search);
      if (projectFilter) params.set('project_id', String(projectFilter));
      return (await client.get(`/v1/lessons?${params}`)).data as Lesson[];
    },
  });

  const visibleLessons = queueMode
    ? (lessons ?? []).slice().sort((a, b) => (a.created_at < b.created_at ? -1 : 1))
    : lessons;

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
          <p className="text-sm text-slate-400">
            Capture → review (owner + timing + actions) → in work (evidence) → verification → closed.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => navigate('/lessons/kpis')}
            className="border border-slate-600 hover:border-slate-400 text-slate-300 rounded px-4 py-2 text-sm"
          >
            📊 KPI Board
          </button>
          <button
            onClick={() => setQueueMode(!queueMode)}
            className={`border rounded px-4 py-2 text-sm ${
              queueMode ? 'border-amber-400 text-amber-300' : 'border-slate-600 text-slate-300 hover:border-slate-400'
            }`}
          >
            📥 Review Queue{queueMode ? ' ✓' : ''}
          </button>
          <button
            onClick={() => setShowNew(true)}
            className="bg-blue-600 hover:bg-blue-500 text-white rounded px-4 py-2 text-sm font-medium"
          >
            + Capture Lesson
          </button>
        </div>
      </div>

      {projectFilter && (
        <div className="mb-3 text-xs text-slate-400">
          Filtered to project #{projectFilter}{' '}
          <button
            onClick={() => { searchParams.delete('project'); setSearchParams(searchParams, { replace: true }); }}
            className="text-blue-400 hover:text-blue-300 ml-1"
          >
            clear
          </button>
        </div>
      )}

      {queueMode && (
        <div className="mb-3 text-xs px-3 py-2 rounded bg-amber-600/10 border border-amber-700/40 text-amber-200">
          Review queue, oldest first. Open a lesson to triage: define responsible owner, target date
          and actions, then accept into work — or reject with a reason.
        </div>
      )}

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
        {(queueMode ? [] : ['', ...STATUSES]).map((s) => (
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
          <input type="checkbox" checked={mineOnly} onChange={(e) => setMineOnly(e.target.checked)} />
          lessons I own
        </label>
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
              <th className="px-4 py-2">Target</th>
              <th className="px-4 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {visibleLessons?.map((l) => (
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
                <td className="px-4 py-2 text-xs">
                  {l.target_date ? (
                    <span className={l.target_overdue ? 'text-red-400 font-semibold' : 'text-slate-400'}>
                      {l.target_date.slice(0, 10)}{l.target_overdue && ' ⚠'}
                    </span>
                  ) : (
                    <span className="text-slate-600">—</span>
                  )}
                </td>
                <td className="px-4 py-2">
                  <span className={`text-xs px-2 py-0.5 rounded ${STATUS_STYLE[l.status] || ''}`}>
                    {label(l.status)}
                  </span>
                  {l.stale && <span className="text-xs text-red-400 ml-1" title="stale">⏰</span>}
                  {l.days_in_state !== null && (
                    <span className="text-xs text-slate-500 ml-1">{Math.round(l.days_in_state)}d</span>
                  )}
                </td>
              </tr>
            ))}
            {!isLoading && visibleLessons?.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-slate-500 text-sm">
                  {queueMode ? 'Review queue is empty — nothing waiting for triage.' : 'No lessons yet — capture the first one.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {showNew && <NewLessonModal onClose={() => setShowNew(false)} />}
      {selectedId !== null && <LessonDetailModal lessonId={selectedId} onClose={closeDetail} />}
    </div>
  );
}
