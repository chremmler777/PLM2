import { useState } from 'react'
import { toastError } from '../../lib/apiError'
import { btnSm } from '../common/buttonStyles'
import { Pencil } from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import type { ChangeRequest } from '../../types/change'


/**
 * F1(b): overview-tab display + edit of `customer_relevant` — the flag that
 * decides whether a change routes through the customer quote path or the
 * internal cost-approval path. Editable only while the routing decision is
 * still open (captured/scoping) and only for the change lead or an admin.
 *
 * Reads as "Cost carrier: Customer change / Internal change" rather than a
 * yes/no on "customer-relevant" — the question is really who pays, and the
 * answer names the branch. Not worded "internal/external": the D1 master has
 * its own independent "CM internal"/"CM external" flags meaning something else.
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
      toast.success('Cost carrier saved')
      setOpen(false)
    },
    onError: (e: unknown) => toastError(e, 'Could not save the cost carrier'),
  })

  return (
    <p className="flex items-center gap-2">
      <span className="text-slate-400">Cost carrier:</span>
      <span>{change.customer_relevant ? 'Customer change' : 'Internal change'}</span>
      {editable && !open && (
        <button type="button" data-testid="customer-relevant-edit"
          onClick={() => { setValue(!!change.customer_relevant); setOpen(true) }}
          className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200 underline decoration-dotted underline-offset-2">
          <Pencil aria-hidden="true" size={11} />edit
        </button>
      )}
      {editable && open && (
        <span className="flex items-center gap-2">
          <select value={value ? 'yes' : 'no'}
            onChange={(e) => setValue(e.target.value === 'yes')}
            className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100">
            <option value="yes">Customer change</option>
            <option value="no">Internal change</option>
          </select>
          <button type="button"
            className={btnSm.primary}
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
