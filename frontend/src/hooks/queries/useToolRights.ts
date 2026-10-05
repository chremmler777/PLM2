/**
 * May the viewer change tool data (tool fields, produces links, shrinkage, DFM)?
 * Tool Engineer or admin (backend app/services/tool_rights.py, /auth/me can_edit_tools;
 * "Act as" another department makes it view only). The backend enforces it; this only
 * hides the controls. Until /auth/me answers, and when it does not say, controls stay.
 */
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';

export function useCanEditTools(): boolean {
  const { data } = useQuery({
    queryKey: ['auth-me-tool-rights'],
    queryFn: async () => (await client.get('/v1/auth/me')).data as { can_edit_tools?: boolean },
    staleTime: 5 * 60_000,
  });
  return data?.can_edit_tools !== false;
}
