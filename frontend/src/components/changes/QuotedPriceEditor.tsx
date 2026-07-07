import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import type { ChangeRequest } from '../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const EDITABLE_STATUSES = ['costing', 'quoted']

/**
 * F7: inline quoted-price editor for the commercial tab (customer branch).
 * Editable while the change is in costing/quoted — the window in which
 * Sales enters or revises the quote before customer acceptance.
 */
export function QuotedPriceEditor({ change }: { change: ChangeRequest }) {
  const qc = useQueryClient()
  const editable = EDITABLE_STATUSES.includes(change.status)
  const [value, setValue] = useState(change.quoted_price != null ? String(change.quoted_price) : '')

  const save = useMutation({
    mutationFn: (quoted_price: number) => changesApi.update(change.id, { quoted_price }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['change', change.id] })
      toast.success('Quoted price saved')
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Failed to save quoted price'),
  })

  if (!editable) {
    return <p><span className="text-gray-500">Quoted price:</span> {change.quoted_price ?? '—'}</p>
  }

  const parsed = Number(value)
  const canSave = value.trim() !== '' && !Number.isNaN(parsed) && !save.isPending

  return (
    <p className="flex items-center gap-2">
      <span className="text-gray-500">Quoted price:</span>
      <input type="number" step="0.01" value={value}
        onChange={(e) => setValue(e.target.value)}
        className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-sm text-slate-100 w-32" />
      <button type="button"
        className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50"
        disabled={!canSave}
        onClick={() => save.mutate(parsed)}>
        Save
      </button>
    </p>
  )
}
