/**
 * Lessons learned, as a step of the release: anyone on the change writes down
 * what should go differently next time; PM (or the lead, an admin) closes the
 * step with at least one lesson or a stated reason why there is none.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { changeReleaseApi } from '../../../api/changeRelease'
import type {
  LessonCategory, LessonIn, LessonSeverity, LessonType, ReleaseState,
} from '../../../types/changeRelease'
import { fmtDate, inputCls } from '../offer/offerFormat'
import { Field } from '../offer/ui'
import { releaseKey } from './releaseKeys'
import { Check } from 'lucide-react'
import { btnSm } from '../../common/buttonStyles'
import { toastError } from '../../../lib/apiError'

const CATEGORIES: LessonCategory[] = [
  'design', 'manufacturing', 'quality', 'supplier', 'logistics', 'project_management', 'tooling', 'other',
]
const TYPES: LessonType[] = ['problem', 'improvement', 'success']
const SEVERITIES: LessonSeverity[] = ['low', 'medium', 'high', 'critical']
const human = (s: string) => (s[0]?.toUpperCase() ?? '') + s.slice(1).replace(/_/g, ' ')

const SEV_TONE: Record<string, string> = {
  low: 'text-slate-400', medium: 'text-sky-300', high: 'text-amber-300', critical: 'text-rose-300',
}

const EMPTY: LessonIn = {
  title: '', description: '', recommendation: '', category: 'other', lesson_type: 'problem', severity: 'medium',
}

export default function LessonsStep({
  changeId, lessons, canAdd, canComplete,
}: {
  changeId: number
  lessons: ReleaseState['lessons']
  canAdd: boolean
  canComplete: boolean
}) {
  const qc = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState<LessonIn>(EMPTY)
  const [noneReason, setNoneReason] = useState('')
  const items = lessons.items ?? []
  const done = !!lessons.done_at

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: releaseKey(changeId) })
    qc.invalidateQueries({ queryKey: ['change', changeId] })
    qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
  }
  const add = useMutation({
    mutationFn: () => changeReleaseApi.addLesson(changeId, {
      ...form, title: form.title.trim(), description: form.description.trim(),
      ...(form.recommendation?.trim() ? { recommendation: form.recommendation.trim() } : { recommendation: undefined }),
    }),
    onSuccess: () => { setForm(EMPTY); setAdding(false); invalidate() },
    onError: (e: unknown) => toastError(e, 'Could not save the lesson'),
  })
  const complete = useMutation({
    mutationFn: () => changeReleaseApi.completeLessons(changeId,
      items.length === 0 ? noneReason.trim() : undefined),
    onSuccess: invalidate,
    onError: (e: unknown) => toastError(e, 'Could not complete the step'),
  })

  const set = <K extends keyof LessonIn>(k: K, v: LessonIn[K]) => setForm((f) => ({ ...f, [k]: v }))
  const canSubmit = form.title.trim() !== '' && form.description.trim() !== '' && !add.isPending

  return (
    <div className="space-y-3">
      {items.length === 0 ? (
        <p className="text-xs text-slate-400">No lessons linked to this change yet.</p>
      ) : (
        <ul className="divide-y divide-slate-700/60 rounded-lg border border-slate-700">
          {items.map((l) => (
            <li key={l.id} data-testid={`lesson-${l.id}`} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
              <span className="min-w-0 flex-1 text-slate-100">{l.title}</span>
              <span className="text-[11px] text-slate-400">{human(String(l.lesson_type))}</span>
              <span className={`text-[11px] ${SEV_TONE[String(l.severity)] ?? 'text-slate-400'}`}>{human(String(l.severity))}</span>
              <span className="rounded border border-slate-600 px-1.5 py-0 text-[11px] text-slate-300">{human(String(l.status))}</span>
            </li>
          ))}
        </ul>
      )}

      {canAdd && !adding && !done && (
        <button type="button" data-testid="lesson-add" onClick={() => setAdding(true)}
          className="text-xs text-sky-300 hover:text-sky-200">+ Add lesson</button>
      )}
      {adding && (
        <div data-testid="lesson-form" className="grid gap-2 rounded-lg border border-slate-700 bg-slate-900/50 p-3 sm:grid-cols-3">
          <Field label="Title" className="sm:col-span-3">
            <input data-testid="lesson-title" className={`${inputCls} w-full`} value={form.title}
              onChange={(e) => set('title', e.target.value)} />
          </Field>
          <Field label="What happened" className="sm:col-span-3">
            <textarea data-testid="lesson-description" rows={2} className={`${inputCls} w-full`} value={form.description}
              onChange={(e) => set('description', e.target.value)} />
          </Field>
          <Field label="Recommendation" className="sm:col-span-3">
            <textarea rows={2} className={`${inputCls} w-full`} value={form.recommendation ?? ''}
              onChange={(e) => set('recommendation', e.target.value)} />
          </Field>
          <Field label="Category">
            <select className={`${inputCls} w-full`} value={form.category}
              onChange={(e) => set('category', e.target.value as LessonCategory)}>
              {CATEGORIES.map((c) => <option key={c} value={c}>{human(c)}</option>)}
            </select>
          </Field>
          <Field label="Type">
            <select className={`${inputCls} w-full`} value={form.lesson_type}
              onChange={(e) => set('lesson_type', e.target.value as LessonType)}>
              {TYPES.map((c) => <option key={c} value={c}>{human(c)}</option>)}
            </select>
          </Field>
          <Field label="Severity">
            <select className={`${inputCls} w-full`} value={form.severity}
              onChange={(e) => set('severity', e.target.value as LessonSeverity)}>
              {SEVERITIES.map((c) => <option key={c} value={c}>{human(c)}</option>)}
            </select>
          </Field>
          <div className="flex justify-end gap-2 sm:col-span-3">
            <button type="button" onClick={() => { setAdding(false); setForm(EMPTY) }}
              className={btnSm.ghost}>Cancel</button>
            <button type="button" data-testid="lesson-submit" disabled={!canSubmit} onClick={() => add.mutate()}
              className={btnSm.primary}>
              Save lesson
            </button>
          </div>
        </div>
      )}

      {done ? (
        <p data-testid="lessons-done" className="text-xs text-emerald-400">
          <Check aria-hidden="true" size={12} className="mr-1 inline" />Step completed{lessons.done_by_name ? ` by ${lessons.done_by_name}` : ''}{lessons.done_at ? `, ${fmtDate(lessons.done_at)}` : ''}
          {lessons.none_reason ? <span className="text-slate-400">. No lessons: {lessons.none_reason}</span> : null}
        </p>
      ) : canComplete ? (
        <div className="flex flex-wrap items-center gap-2 border-t border-slate-700/60 pt-3">
          {items.length === 0 && (
            <input data-testid="lessons-none-reason" value={noneReason} onChange={(e) => setNoneReason(e.target.value)}
              aria-label="Why there are no lessons" aria-describedby="lessons-none-hint"
              placeholder="No lessons, because…" className={`${inputCls} min-w-0 flex-1`} />
          )}
          <button type="button" data-testid="lessons-complete"
            disabled={(items.length === 0 && !noneReason.trim()) || complete.isPending}
            onClick={() => complete.mutate()}
            className={btnSm.secondary}>
            Complete lessons step
          </button>
          {items.length === 0 && (
            <span id="lessons-none-hint" className="w-full text-[11px] text-slate-400">Add at least one lesson, or say why there is none.</span>
          )}
        </div>
      ) : (
        <p className="text-[11px] text-slate-400">PM, the change lead or an admin completes this step.</p>
      )}
    </div>
  )
}
