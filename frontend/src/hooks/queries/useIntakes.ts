import { useQuery } from '@tanstack/react-query'
import { intakeKeys, intakesApi } from '../../api/intakes'

/** The part's new customer indexes still pending (spec §17). */
export function usePartIntakes(partId: number | undefined) {
  return useQuery({
    queryKey: intakeKeys.part(partId ?? 0),
    queryFn: () => intakesApi.list({ part_id: partId!, waiting: true }),
    enabled: !!partId,
  })
}
