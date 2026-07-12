import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import type { ChangeRequest } from '../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

/**
 * F1(b): overview-tab display + edit of `customer_relevant` — the flag that
 * decides whether a change routes through the customer quote path or the
 * internal cost-approval path. Editable only while the routing decision is
 * still open (captured/scoping) and only for the change lead or an admin.
 */
export function CustomerRelevantEditor({ change, canEdit }: {
  change: ChangeRequest; canEdit: boolean
}) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState(!!change.customer_relevant)
  const editable = canEdit && (change.status === 'captured' || change.status === 'scoping')

  const save = useMutation({
    mutationFn: (customer_relevant: boolean) =>
      changesApi.update(change.id, { customer_relevant }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['change', change.id] })
      toast.success('Saved')
      setOpen(false)
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Failed to save'),
  })

  return (
    <p className="flex items-center gap-2">
      <span className="text-slate-400">Customer-relevant:</span>
      <span>{change.customer_relevant ? 'Yes' : 'No'}</span>
      {editable && !open && (
        <button type="button" data-testid="customer-relevant-edit"
          onClick={() => { setValue(!!change.customer_relevant); setOpen(true) }}
          className="text-xs text-slate-400 hover:text-slate-200 underline decoration-dotted underline-offset-2">
          ✎ edit
        </button>
      )}
      {editable && open && (
        <span className="flex items-center gap-2">
          <select value={value ? 'yes' : 'no'}
            onChange={(e) => setValue(e.target.value === 'yes')}
            className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100">
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
          <button type="button"
            className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50"
            disabled={save.isPending}
            onClick={() => save.mutate(value)}>
            Save
          </button>
          <button type="button" className="text-xs text-slate-400 hover:text-slate-200"
            onClick={() => setOpen(false)}>
            Cancel
          </button>
        </span>
      )}
    </p>
  )
}
