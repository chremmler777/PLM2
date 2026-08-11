import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'
import type { ChangeRequest } from '../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

// The description is written while the request is being captured and may still
// be sharpened during scoping. Once departments assess against it, it is
// history — shown, not edited.
const EDITABLE_STATUSES = ['captured', 'scoping']

export function DescriptionEditor({ change, canEdit = true }:
    { change: ChangeRequest; canEdit?: boolean }) {
  const qc = useQueryClient()
  const editable = canEdit && EDITABLE_STATUSES.includes(change.status)
  const [value, setValue] = useState(change.description ?? '')

  const save = useMutation({
    mutationFn: (description: string) => changesApi.update(change.id, { description }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['change', change.id] })
      toast.success(t('description.saved'))
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Failed to save the description'),
  })

  if (!editable) {
    return (
      <p>
        <span className="text-slate-400">{t('description.label')}:</span>{' '}
        <span className="whitespace-pre-wrap">{change.description ?? '—'}</span>
      </p>
    )
  }

  const dirty = value.trim() !== (change.description ?? '').trim()

  return (
    <div className="space-y-1">
      <label htmlFor="cd-description" className="block text-slate-400">
        {t('description.label')}
      </label>
      <textarea id="cd-description" rows={3} value={value}
        data-testid="description-input"
        placeholder={t('description.placeholder')}
        onChange={(e) => setValue(e.target.value)}
        className="w-full bg-slate-800 border border-slate-600 rounded px-2 py-1 text-sm text-slate-100" />
      <button type="button" data-testid="description-save"
        className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50"
        disabled={!dirty || save.isPending}
        onClick={() => save.mutate(value.trim())}>
        {t('common.save')}
      </button>
    </div>
  )
}
