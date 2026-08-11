/**
 * May the signed-in caller raise a change request?
 *
 * The rule lives in the backend (membership in a can_start_change department —
 * Sales and Project Management today — or admin), so the UI asks rather than
 * hardcoding a role list. Because it goes through the shared client, acting-as
 * is followed automatically.
 *
 * Fails open: while the answer is loading, or if the endpoint is unavailable,
 * the button stays enabled and the POST's 403 is surfaced in the modal. A
 * transport hiccup must never lock Sales out of their own job.
 */
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';

export interface ChangePermissions {
  can_start_change: boolean;
}

export function useCanStartChange(): boolean {
  const { data } = useQuery<ChangePermissions>({
    queryKey: ['change-permissions'],
    // An unreachable or absent endpoint answers "allowed" rather than rejecting:
    // the failure is ours, and the POST still enforces the real rule.
    queryFn: async () => {
      try {
        return (await client.get('/v1/changes/permissions')).data;
      } catch {
        return { can_start_change: true };
      }
    },
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
  return data?.can_start_change !== false;
}
