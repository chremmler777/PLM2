/**
 * ActsAsSwitch — admin-only "act as department" and "act as person" control.
 *
 * Department: picking one stores it per-tab; the shared axios client attaches
 * it to every request as X-Acts-As-Department, and the backend then treats
 * the admin as an engineer of that department.
 *
 * Person (Christoph 2026-10-26): picking one sends X-Acts-As-User instead;
 * the backend answers exactly as that person (their departments, manager
 * role, My Tasks, team slots; never admin) and audits writes as the admin
 * acting as them. The two exclude each other. Because the whole app's data
 * changes meaning under the switch, changing it reloads rather than
 * invalidating query by query.
 */
import { useQuery } from '@tanstack/react-query'
import client from '../../api/client'
import { useDepartments } from '../../hooks/queries/useWorkflows'
import {
  getActsAsDepartmentId, getActsAsUserId, setActsAsDepartmentId, setActsAsUserId,
} from '../../lib/actsAs'
import { t } from '../../i18n/cmLabels'

type Options = { departments: { id: number; name: string }[]; people?: { id: number; name: string }[] }

export default function ActsAsSwitch({ collapsed = false }: { collapsed?: boolean }) {
  const { data: departments = [] } = useDepartments()
  const { data: options } = useQuery<Options>({
    queryKey: ['acts-as', 'options'],
    queryFn: async () => (await client.get('/v1/auth/acts-as/options')).data,
    staleTime: 5 * 60_000,
  })
  const people = options?.people ?? []
  const active = departments.filter((d) => d.is_active)
  const current = getActsAsDepartmentId()
  const currentUser = getActsAsUserId()
  const currentName = current == null ? null
    : departments.find((d) => d.id === current)?.name ?? `#${current}`
  const currentUserName = currentUser == null ? null
    : people.find((p) => p.id === currentUser)?.name ?? `#${currentUser}`

  const apply = (id: number | null) => {
    setActsAsUserId(null)
    setActsAsDepartmentId(id)
    // Everything cached was fetched under the old identity.
    window.location.reload()
  }
  const applyUser = (id: number | null) => {
    setActsAsDepartmentId(null)
    setActsAsUserId(id)
    window.location.reload()
  }
  const backToMe = () => { setActsAsDepartmentId(null); setActsAsUserId(null); window.location.reload() }

  if (collapsed) {
    // Collapsed rail has no room for the picker; the acting state still has to
    // be visible, and one click gets out of it.
    const label = currentUserName ?? currentName
    return label == null ? null : (
      <button type="button" data-testid="acts-as-clear" title={`${t('actsAs.acting')}: ${label}`}
        onClick={backToMe}
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
      {people.length > 0 && (
        <>
          <label htmlFor="acts-as-user" className="sr-only">{t('actsAs.person')}</label>
          <select id="acts-as-user" data-testid="acts-as-user-select" value={currentUser ?? ''}
            onChange={(e) => applyUser(e.target.value ? Number(e.target.value) : null)}
            className="w-full bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-xs text-slate-200">
            <option value="">{t('actsAs.noPerson')}</option>
            {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </>
      )}
      {current != null && currentUser == null && (
        <div data-testid="acts-as-banner"
          className="flex items-center gap-1.5 rounded-md bg-fuchsia-900/60 text-fuchsia-100 px-2 py-1 text-xs">
          <span className="truncate">{t('actsAs.acting')}: {currentName}</span>
          <button type="button" data-testid="acts-as-clear" title={t('actsAs.clear')}
            aria-label={t('actsAs.clear')}
            onClick={backToMe}
            className="ml-auto flex-shrink-0 hover:text-white">✕</button>
        </div>
      )}
    </div>
  )
}

/** The page-wide banner while an admin sees PLM as a person. */
export function ViewingAsBanner({ name }: { name: string }) {
  return (
    <div role="status" data-testid="viewing-as-banner"
      className="flex items-center justify-center gap-3 bg-fuchsia-800 px-4 py-1.5 text-sm text-white">
      <span>{t('actsAs.viewingAs').replace('{x}', name)}</span>
      <button type="button" data-testid="viewing-as-back"
        onClick={() => { setActsAsUserId(null); setActsAsDepartmentId(null); window.location.reload() }}
        className="rounded-md bg-white/15 px-2 py-0.5 text-xs font-semibold hover:bg-white/25">
        {t('actsAs.backToMe')}
      </button>
    </div>
  )
}
