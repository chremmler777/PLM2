import { useId, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { btnSm } from '../common/buttonStyles'
import { toastError } from '../../lib/apiError'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'
import type { ChangeRequest } from '../../types/change'

/** The scope is written while the change is captured or in scoping, read
 *  only afterwards (backend: ChangeService.set_scope_definition). */
export const SCOPE_EDITABLE_STATUSES = ['captured', 'scoping']

/**
 * "Scope (defined by PM)": what is in scope of the change, in the project
 * manager's words (2026-10-14). Editable on the Scoping tab by Project
 * Management, the change lead or an admin; every other tab shows it read only
 * so the departments see what they are assessing and costing. Optional: it
 * gates nothing.
 */
export default function ScopeDefinitionBlock({
  change, canEdit = false, hideWhenEmpty = false,
}: {
  change: Pick<ChangeRequest, 'id' | 'status' | 'scope_definition'>
  /** PM member, change lead or admin (acts-as aware); the status is checked here. */
  canEdit?: boolean
  /** Read-only placements leave no empty box behind. */
  hideWhenEmpty?: boolean
}) {
  const qc = useQueryClient()
  const fieldId = useId()
  const text = change.scope_definition?.trim() ?? ''
  const editable = canEdit && SCOPE_EDITABLE_STATUSES.includes(change.status)
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(text)

  const save = useMutation({
    mutationFn: (v: string) => changesApi.setScopeDefinition(change.id, v.trim() || null),
    onSuccess: () => {
      setEditing(false)
      qc.invalidateQueries({ queryKey: ['change', change.id] })
      toast.success(t('scope.saved'))
    },
    onError: (e: unknown) => toastError(e, 'Could not save the scope'),
  })

  if (!text && !editable && hideWhenEmpty) return null
  // Why there is no editor, said once: past scoping it is the record.
  const rightsNote = !SCOPE_EDITABLE_STATUSES.includes(change.status) ? t('scope.readOnly')
    : editable ? null : t('scope.rights')

  // No scope yet while it can still be written = open work, red as in costing.
  const missing = !text && SCOPE_EDITABLE_STATUSES.includes(change.status)

  return (
    <section data-testid="scope-definition" data-missing={missing || undefined}
      className={`rounded-lg border p-3 space-y-2 ${missing
        ? 'border-red-600/80 ring-1 ring-red-700/40 bg-red-950/20' : 'border-sky-800/60 bg-sky-950/20'}`}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-sky-300">
          {t('scope.title')}
        </h3>
        {editable && !editing && (
          <button type="button" data-testid="scope-edit"
            className="text-xs text-sky-300 hover:text-sky-200"
            onClick={() => { setValue(text); setEditing(true) }}>
            {text ? t('scope.edit') : t('scope.define')}
          </button>
        )}
      </div>
      {editing ? (
        <div className="space-y-2">
          <label htmlFor={fieldId} className="sr-only">{t('scope.title')}</label>
          <textarea id={fieldId} data-testid="scope-input" rows={4} value={value}
            placeholder={t('scope.placeholder')}
            onChange={(e) => setValue(e.target.value)}
            className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-sm text-slate-100" />
          <div className="flex items-center gap-2">
            <button type="button" data-testid="scope-save" className={btnSm.primary}
              disabled={save.isPending || value.trim() === text}
              onClick={() => save.mutate(value)}>
              {t('scope.save')}
            </button>
            <button type="button" className="text-xs text-slate-400 hover:text-slate-200"
              onClick={() => { setEditing(false); setValue(text) }}>
              {t('common.cancel')}
            </button>
          </div>
        </div>
      ) : text ? (
        <p data-testid="scope-text" className="whitespace-pre-wrap text-sm text-slate-100">{text}</p>
      ) : (
        <p data-testid="scope-empty" className={`text-xs ${missing ? 'text-red-300' : 'text-slate-500'}`}>{t('scope.empty')}</p>
      )}
      {!editing && rightsNote && (
        <p className="text-[11px] text-slate-500" data-testid="scope-rights">{rightsNote}</p>
      )}
    </section>
  )
}
