import { useQuery } from '@tanstack/react-query';
import { getWorksheet } from '../../api/worksheet';

export const WORKSHEET_KEY = 'worksheet';

/** A missing worksheet (404) will not appear on retry: show the error at once; other failures get two retries. */
export function retryUnlessNotFound(failureCount: number, error: unknown): boolean {
  const status = (error as { response?: { status?: number } } | null)?.response?.status;
  return status !== 404 && failureCount < 2;
}

export function useWorksheet(projectId: number) {
  return useQuery({
    queryKey: [WORKSHEET_KEY, projectId],
    queryFn: () => getWorksheet(projectId),
    enabled: !!projectId,
    retry: retryUnlessNotFound,
  });
}
