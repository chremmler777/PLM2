/**
 * ActsAsSwitch — admin-only "act as department" control.
 *
 * Picking a department stores it per-tab; the shared axios client attaches it to
 * every request as X-Acts-As-Department, and the backend then treats the admin
 * as an engineer of that department. Because the whole app's data changes
 * meaning under the switch, changing it reloads rather than trying to invalidate
 * query by query.
 */
import { useDepartments } from '../../hooks/queries/useWorkflows'
import { getActsAsDepartmentId, setActsAsDepartmentId } from '../../lib/actsAs'
import { t } from '../../i18n/cmLabels'

export default function ActsAsSwitch({ collapsed = false }: { collapsed?: boolean }) {
  const { data: departments = [] } = useDepartments()
  const active = departments.filter((d) => d.is_active)
  const current = getActsAsDepartmentId()
  const currentName = current == null ? null
    : departments.find((d) => d.id === current)?.name ?? `#${current}`

  const apply = (id: number | null) => {
    setActsAsDepartmentId(id)
    // Everything cached was fetched under the old identity.
    window.location.reload()
  }

  if (collapsed) {
    // Collapsed rail has no room for the picker; the acting state still has to
    // be visible, and one click gets out of it.
    return current == null ? null : (
      <button type="button" data-testid="acts-as-clear" title={`${t('actsAs.acting')}: ${currentName}`}
        onClick={() => apply(null)}
        className="w-full px-2 py-2 rounded-md bg-fuchsia-900/60 text-fuchsia-100 text-xs font-medium">
        ✕
      </button>
    )
  }

  return (
    <div className="space-y-1">
      <label htmlFor="acts-as" className="sr-only">{t('actsAs.label')}</label>
      <select id="acts-as" data-testid="acts-as-select" value={current ?? ''}
        onChange={(e) => apply(e.target.value ? Number(e.target.value) : null)}
        className="w-full bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-xs text-slate-200">
        <option value="">{t('actsAs.myself')}</option>
        {active.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
      </select>
      {current != null && (
        <div data-testid="acts-as-banner"
          className="flex items-center gap-1.5 rounded-md bg-fuchsia-900/60 text-fuchsia-100 px-2 py-1 text-xs">
          <span className="truncate">{t('actsAs.acting')}: {currentName}</span>
          <button type="button" data-testid="acts-as-clear" title={t('actsAs.clear')}
            aria-label={t('actsAs.clear')}
            onClick={() => apply(null)}
            className="ml-auto flex-shrink-0 hover:text-white">✕</button>
        </div>
      )}
    </div>
  )
}
