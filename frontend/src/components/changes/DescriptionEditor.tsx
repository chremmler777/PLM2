import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'
import type { ChangeRequest } from '../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

// The description is Sales' capture text. It freezes at kickoff: from scoping on
// the project team's thinking lives in the mail thread attached to the change,
// so the text a decision was made on cannot move underneath it.
const EDITABLE_STATUSES = ['captured']

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
      <div>
        <p>
          <span className="text-slate-400">{t('description.label')}:</span>{' '}
          <span className="whitespace-pre-wrap">{change.description?.trim() || t('description.none')}</span>
        </p>
        {/* Why there is no editor: say it, so nobody hunts for one. */}
        <p data-testid="description-state" className="text-xs text-slate-500">
          {!EDITABLE_STATUSES.includes(change.status) ? t('description.frozen') : t('description.readOnly')}
        </p>
      </div>
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
      <div className="flex items-center gap-2">
        <button type="button" data-testid="description-save"
          className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50"
          disabled={!dirty || save.isPending}
          onClick={() => save.mutate(value.trim())}>
          {save.isPending ? t('saving') : t('common.save')}
        </button>
        {dirty && (
          <button type="button" data-testid="description-discard"
            onClick={() => setValue(change.description ?? '')}
            className="text-xs text-slate-400 hover:text-slate-200">
            {t('description.discard')}
          </button>
        )}
        <span data-testid="description-state" className={`text-xs ${dirty ? 'text-amber-300' : 'text-slate-500'}`}>
          {dirty ? t('description.unsaved') : change.description?.trim() ? t('description.savedState') : t('description.empty')}
        </span>
      </div>
    </div>
  )
}
