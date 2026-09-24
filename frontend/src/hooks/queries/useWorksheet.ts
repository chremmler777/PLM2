import { useQuery } from '@tanstack/react-query';
import { getWorksheet } from '../../api/worksheet';

export const WORKSHEET_KEY = 'worksheet';

export function useWorksheet(projectId: number) {
  return useQuery({
    queryKey: [WORKSHEET_KEY, projectId],
    queryFn: () => getWorksheet(projectId),
    enabled: !!projectId,
  });
}
