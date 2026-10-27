/**
 * May the signed-in caller raise a change request?
 *
 * The rule lives in the backend (membership in a can_start_change department —
 * Project Management since migration 152, or admin; internal changes also
 * the can_start_internal_change engineering departments), so the UI asks rather than
 * hardcoding a role list. Because it goes through the shared client, acting-as
 * is followed automatically.
 *
 * Fails open: while the answer is loading, or if the endpoint is unavailable,
 * the button stays enabled and the POST's 403 is surfaced in the modal. A
 * transport hiccup must never lock Project Management out of its own job.
 */
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';

export interface ChangePermissions {
  can_start_change: boolean;
  /** P3 + D1: internal changes only (Development, Process, Tool, Manufacturing Engineer). */
  can_start_internal_change?: boolean;
  /** Mother-plant side track (spec §14): starters plus Project Management. */
  can_start_mother_plant?: boolean;
  mother_plants?: string[];
  default_mother_plant?: string;
  /** Project team (responsible, backup): Project Management or an admin. */
  can_manage_team?: boolean;
}

export function useChangePermissions(): ChangePermissions | undefined {
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
  return data;
}

/** A change may be started at all: an ordinary one, or one from the mother plant. */
export function useCanStartChange(): boolean {
  const data = useChangePermissions();
  return data?.can_start_change !== false || data?.can_start_internal_change === true
    || data?.can_start_mother_plant === true;
}

/** P3: the caller may start internal changes only (no customer change). */
export function useInternalOnlyStarter(): boolean {
  const data = useChangePermissions();
  return data?.can_start_change === false && data?.can_start_internal_change === true;
}
