import { useQueries } from '@tanstack/react-query'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'
import { humanize } from '../../lib/humanLabels'
import type { ChangeConcern } from '../../types/change'

/**
 * A concern reads with its own department's words: a risk raised by Tooling
 * shows Tooling's risk type and checklist row, whatever department the viewer
 * is in (or acting as). Each department's vocabulary is fetched once and
 * shared by key with the forms that already ask for it.
 */
export function useConcernLabels(concerns: ChangeConcern[], enabled = true) {
  const depts = [...new Set(concerns
    .filter((c) => c.department_id != null && (!!c.risk_type || !!c.checklist_key))
    .map((c) => c.department_id as number))].sort((a, b) => a - b)
  const riskTypes = useQueries({
    queries: depts.map((d) => ({
      queryKey: ['risk-types', d],
      queryFn: () => changesApi.riskTypes(d),
      enabled: enabled && concerns.some((c) => c.department_id === d && !!c.risk_type),
      retry: false,
      staleTime: 5 * 60_000,
    })),
  })
  const checklists = useQueries({
    queries: depts.map((d) => ({
      queryKey: ['assessment-checklist', d],
      queryFn: () => changesApi.assessmentChecklist(d),
      enabled: enabled && concerns.some((c) => c.department_id === d && !!c.checklist_key),
      staleTime: 5 * 60_000,
    })),
  })
  const at = (c: ChangeConcern) => (c.department_id == null ? -1 : depts.indexOf(c.department_id))

  /** The risk type's label: the raising department's served label, else the
   *  catalogued one, else the key made readable. Never the raw key. */
  const riskTypeLabel = (c: Pick<ChangeConcern, 'department_id' | 'risk_type'>) => {
    const k = c.risk_type
    if (!k) return t('risk.kind')
    const i = at(c as ChangeConcern)
    const served = i < 0 ? undefined : riskTypes[i]?.data?.items?.find((x) => x.key === k)?.label_en
    if (served) return served
    const cat = t(`risktype.${k}`)
    return cat !== `risktype.${k}` ? cat : humanize(k)
  }
  /** The checklist row a risk was raised from, in its department's words. */
  const originLabel = (c: Pick<ChangeConcern, 'department_id' | 'checklist_key'>) => {
    const key = c.checklist_key
    if (!key) return ''
    if (key.startsWith('free:')) return key.slice(5)
    const i = at(c as ChangeConcern)
    const defs = i < 0 ? [] : checklists[i]?.data ?? []
    return defs.find((d) => d.key === key)?.label_en ?? humanize(key)
  }
  return { riskTypeLabel, originLabel }
}
