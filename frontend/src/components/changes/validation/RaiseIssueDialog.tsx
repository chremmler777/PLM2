/**
 * Raise a validation issue. From a failed check it arrives prefilled: the
 * category from the check, the check's department as owner, the fail note
 * as the description.
 */
import { useEffect, useState } from 'react'
import { validationIssuesApi } from '../../../api/validationIssues'
import type { IssueCategory, IssueSeverity } from '../../../types/validationIssue'
import { Field, Segmented } from '../offer/ui'
import Dialog from '../../common/Dialog'
import Button from '../../common/Button'
import FieldGroup from '../../common/FieldGroup'
import { inputCls } from '../offer/offerFormat'
import { CATEGORY_LABEL, SEVERITY, categoryForCheck } from './issueModel'
import { useIssueMutation } from './useIssueMutation'
import { departmentLabel } from '../../../lib/departments'

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
  departments: { id: number; name: string; is_active?: boolean }[]
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

  const ok = title.trim() && description.trim() && dept != null

  return (
    <Dialog open={open} onClose={onClose} title="Raise a validation issue" size="lg" busy={save.isPending}
      closeOnBackdrop={false} data-testid="raise-dialog"
      description={prefill?.checkLabel
        ? `From the failed check "${prefill.checkLabel}". The owner department contains it and finds the cause; PM or the lead decides the route.`
        : 'The owner department contains it and finds the cause; PM or the lead decides the route.'}
      footer={(
        <>
          <Button onClick={onClose} disabled={save.isPending}>Cancel</Button>
          <Button variant="primary" data-testid="raise-submit" disabled={!ok} loading={save.isPending}
            onClick={() => save.mutate(undefined)}>
            Raise issue
          </Button>
        </>
      )}>
        <div className="space-y-3">
          <Field label="Title">
            <input data-testid="raise-title" data-autofocus value={title} onChange={(e) => setTitle(e.target.value)}
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
                {departments.map((d) => <option key={d.id} value={d.id}>{departmentLabel(d)}</option>)}
              </select>
            </Field>
          </div>
          <FieldGroup legend="Severity"
            hint={severity === 3 ? 'Blocks production: containment is required before a route, and the issue starts at level 2.' : undefined}>
            <Segmented<string> value={String(severity)} testId="raise-severity" ariaLabel="Severity"
              onChange={(v) => setSeverity(Number(v) as IssueSeverity)}
              options={([1, 2, 3] as IssueSeverity[]).map((s) => ({ value: String(s), label: SEVERITY[s].label }))} />
          </FieldGroup>
          <Field label="Tool or equipment number (optional)">
            <input data-testid="raise-tool" value={tool} onChange={(e) => setTool(e.target.value)}
              maxLength={120} className={`${inputCls} w-full`} />
          </Field>
          <Field label="What happened">
            <textarea data-testid="raise-description" rows={3} value={description}
              onChange={(e) => setDescription(e.target.value)} className={`${inputCls} w-full`} />
          </Field>
        </div>
    </Dialog>
  )
}
