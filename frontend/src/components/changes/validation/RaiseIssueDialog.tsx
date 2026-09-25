/**
 * Raise a validation issue. From a failed check it arrives prefilled: the
 * category from the check, the check's department as owner, the fail note
 * as the description.
 */
import { useEffect, useState } from 'react'
import { validationIssuesApi } from '../../../api/validationIssues'
import type { IssueCategory, IssueSeverity } from '../../../types/validationIssue'
import { Field, Segmented } from '../offer/ui'
import { inputCls } from '../offer/offerFormat'
import { CATEGORY_LABEL, SEVERITY, categoryForCheck } from './issueModel'
import { useIssueMutation } from './useIssueMutation'

export interface RaisePrefill {
  checkKey?: string
  checkId?: number | null
  checkLabel?: string
  departmentId?: number | null
  note?: string | null
}

export default function RaiseIssueDialog({ open, changeId, departments, prefill, onClose }: {
  open: boolean
  changeId: number
  departments: { id: number; name: string }[]
  prefill?: RaisePrefill | null
  onClose: () => void
}) {
  const [title, setTitle] = useState('')
  const [category, setCategory] = useState<IssueCategory>('other')
  const [severity, setSeverity] = useState<IssueSeverity>(2)
  const [dept, setDept] = useState<number | null>(null)
  const [tool, setTool] = useState('')
  const [description, setDescription] = useState('')

  useEffect(() => {
    if (!open) return
    setTitle(prefill?.checkLabel ? `${prefill.checkLabel}: failed` : '')
    setCategory(categoryForCheck(prefill?.checkKey))
    setSeverity(2)
    setDept(prefill?.departmentId ?? null)
    setTool('')
    setDescription(prefill?.note ?? '')
  }, [open, prefill])

  const save = useIssueMutation(changeId, () => validationIssuesApi.create(changeId, {
    title: title.trim(), category, severity, department_id: dept, description: description.trim(),
    ...(prefill?.checkId != null ? { check_id: prefill.checkId } : {}),
    ...(prefill?.checkKey ? { check_key: prefill.checkKey, check_department_id: prefill.departmentId ?? null } : {}),
    ...(tool.trim() ? { affected_tool_ref: tool.trim() } : {}),
  }), { error: 'Could not raise the issue', onDone: onClose })

  if (!open) return null
  const ok = title.trim() && description.trim() && dept != null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-label="Raise issue">
      <div className="w-full max-w-lg rounded-xl border border-slate-700 bg-slate-800 p-5 shadow-2xl">
        <h3 className="text-base font-semibold text-slate-100">Raise a validation issue</h3>
        <p className="mt-0.5 text-sm text-slate-400">
          {prefill?.checkLabel
            ? `From the failed check "${prefill.checkLabel}". The owner department contains it and finds the cause; PM or the lead decides the route.`
            : 'The owner department contains it and finds the cause; PM or the lead decides the route.'}
        </p>
        <div className="mt-4 space-y-3">
          <Field label="Title">
            <input data-testid="raise-title" value={title} onChange={(e) => setTitle(e.target.value)}
              maxLength={200} className={`${inputCls} w-full`} />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Category">
              <select data-testid="raise-category" value={category}
                onChange={(e) => setCategory(e.target.value as IssueCategory)} className={`${inputCls} w-full`}>
                {(Object.keys(CATEGORY_LABEL) as IssueCategory[]).map((c) => (
                  <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>
                ))}
              </select>
            </Field>
            <Field label="Owner department (fixes it)">
              <select data-testid="raise-department" value={dept ?? ''}
                onChange={(e) => setDept(e.target.value ? Number(e.target.value) : null)} className={`${inputCls} w-full`}>
                <option value="">Pick a department</option>
                {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </Field>
          </div>
          <Field label="Severity">
            <Segmented<string> value={String(severity)} testId="raise-severity"
              onChange={(v) => setSeverity(Number(v) as IssueSeverity)}
              options={([1, 2, 3] as IssueSeverity[]).map((s) => ({ value: String(s), label: SEVERITY[s].label }))} />
          </Field>
          {severity === 3 && (
            <p className="text-[11px] text-rose-300">Blocks production: containment is required before a route, and the issue starts at level 2.</p>
          )}
          <Field label="Tool or equipment number (optional)">
            <input data-testid="raise-tool" value={tool} onChange={(e) => setTool(e.target.value)}
              maxLength={120} className={`${inputCls} w-full`} />
          </Field>
          <Field label="What happened">
            <textarea data-testid="raise-description" rows={3} value={description}
              onChange={(e) => setDescription(e.target.value)} className={`${inputCls} w-full`} />
          </Field>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onClose}
            className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-700">Cancel</button>
          <button type="button" data-testid="raise-submit" disabled={!ok || save.isPending}
            onClick={() => save.mutate(undefined)}
            className="rounded-lg bg-rose-700 px-3 py-1.5 text-sm font-semibold text-white hover:bg-rose-600 disabled:opacity-50">
            Raise issue
          </button>
        </div>
      </div>
    </div>
  )
}
