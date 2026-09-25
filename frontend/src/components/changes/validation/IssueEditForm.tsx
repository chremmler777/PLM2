/**
 * Correct what was raised: title, what happened, severity, category, the
 * owner department, the affected tool and whether the customer must be
 * told. Only the fields that changed are sent.
 */
import { useState } from 'react'
import { validationIssuesApi } from '../../../api/validationIssues'
import type { IssueCategory, IssueOut, IssuePatch, IssueSeverity } from '../../../types/validationIssue'
import { Field, Segmented, Toggle } from '../offer/ui'
import { inputCls } from '../offer/offerFormat'
import { CATEGORY_LABEL, SEVERITY } from './issueModel'
import { useIssueMutation } from './useIssueMutation'

interface Draft {
  title: string; description: string; severity: IssueSeverity; category: IssueCategory
  department_id: number | null; affected_tool_ref: string; customer_inform: boolean
}

const draftOf = (i: IssueOut): Draft => ({
  title: i.title, description: i.description, severity: i.severity, category: i.category,
  department_id: i.department_id ?? null, affected_tool_ref: i.affected_tool_ref ?? '',
  customer_inform: !!i.customer_inform,
})

/** The PATCH body: the changed fields only. */
export function issuePatch(i: IssueOut, d: Draft): IssuePatch {
  const before = draftOf(i)
  const out: IssuePatch = {}
  if (d.title.trim() !== before.title) out.title = d.title.trim()
  if (d.description.trim() !== before.description) out.description = d.description.trim()
  if (d.severity !== before.severity) out.severity = d.severity
  if (d.category !== before.category) out.category = d.category
  if (d.department_id !== before.department_id) out.department_id = d.department_id
  if (d.affected_tool_ref.trim() !== before.affected_tool_ref) out.affected_tool_ref = d.affected_tool_ref.trim() || null
  if (d.customer_inform !== before.customer_inform) out.customer_inform = d.customer_inform
  return out
}

export default function IssueEditForm({ changeId, issue, departments, onDone }: {
  changeId: number
  issue: IssueOut
  departments: { id: number; name: string }[]
  onDone: () => void
}) {
  const [d, setD] = useState<Draft>(() => draftOf(issue))
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }))
  const patch = issuePatch(issue, d)
  const save = useIssueMutation(changeId, () => validationIssuesApi.update(changeId, issue.id, patch),
    { error: 'Could not save the issue', onDone })
  const ok = d.title.trim() && d.description.trim() && d.department_id != null && Object.keys(patch).length > 0

  return (
    <div data-testid={`issue-edit-form-${issue.id}`} className="space-y-3 rounded-lg border border-slate-700 bg-slate-900/40 p-3">
      <Field label="Title">
        <input data-testid="edit-title" value={d.title} maxLength={200}
          onChange={(e) => set('title', e.target.value)} className={`${inputCls} w-full`} />
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Category">
          <select data-testid="edit-category" value={d.category}
            onChange={(e) => set('category', e.target.value as IssueCategory)} className={`${inputCls} w-full`}>
            {(Object.keys(CATEGORY_LABEL) as IssueCategory[]).map((c) => (
              <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>
            ))}
          </select>
        </Field>
        <Field label="Owner department (fixes it)">
          <select data-testid="edit-department" value={d.department_id ?? ''}
            onChange={(e) => set('department_id', e.target.value ? Number(e.target.value) : null)}
            className={`${inputCls} w-full`}>
            <option value="">Pick a department</option>
            {departments.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        </Field>
      </div>
      <Field label="Severity">
        <Segmented<string> value={String(d.severity)} testId="edit-severity"
          onChange={(v) => set('severity', Number(v) as IssueSeverity)}
          options={([1, 2, 3] as IssueSeverity[]).map((s) => ({ value: String(s), label: SEVERITY[s].label }))} />
      </Field>
      <Field label="Tool or equipment number (optional)">
        <input data-testid="edit-tool" value={d.affected_tool_ref} maxLength={120}
          onChange={(e) => set('affected_tool_ref', e.target.value)} className={`${inputCls} w-full`} />
      </Field>
      <Field label="What happened">
        <textarea data-testid="edit-description" rows={3} value={d.description}
          onChange={(e) => set('description', e.target.value)} className={`${inputCls} w-full`} />
      </Field>
      <label className="flex items-center gap-2 text-xs text-slate-300">
        <Toggle checked={d.customer_inform} onChange={(v) => set('customer_inform', v)}
          label="Customer must be informed" testId="edit-inform" />
        Customer must be informed
      </label>
      <div className="flex items-center gap-2">
        <button type="button" data-testid="edit-submit" disabled={!ok || save.isPending}
          onClick={() => save.mutate(undefined)}
          className="rounded-lg bg-sky-600 px-3 py-1 text-xs font-semibold text-white hover:bg-sky-500 disabled:opacity-50">
          Save changes
        </button>
        <button type="button" onClick={onDone} className="px-1 text-xs text-slate-400 hover:text-slate-200">Cancel</button>
      </div>
    </div>
  )
}
