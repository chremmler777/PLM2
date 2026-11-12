import { useQuery } from '@tanstack/react-query'
import { lopApi, lopKeys } from '../../api/lop'
import type { LopProjectResponse } from '../../types/lop'

/** The newest meeting with its marks (GET /meetings/{id}), open or closed. */
export function useMeetingDetail(projectId: number, data: LopProjectResponse | null | undefined) {
  const id = data?.meeting?.id ?? null
  return useQuery({
    queryKey: lopKeys.meeting(projectId, id ?? 0),
    queryFn: () => lopApi.meeting(id!),
    enabled: id != null,
  })
}
