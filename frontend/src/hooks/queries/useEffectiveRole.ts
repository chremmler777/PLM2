/**
 * The caller's effective role from /auth/me: "admin" | "engineer" (member of an
 * active department, or acting as one) | "viewer" (plm2_Viewer only, no
 * department: read only). Undefined until /auth/me answers or when it does not
 * say; callers then show what an engineer sees. Through the shared client, so
 * acting-as is followed.
 */
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';

export function useEffectiveRole(): string | undefined {
  const { data } = useQuery({
    queryKey: ['auth-me-effective-role'],
    queryFn: async () => (await client.get('/v1/auth/me')).data as { effective_role?: string | null },
    staleTime: 5 * 60_000,
  });
  return data?.effective_role ?? undefined;
}

/** Read-only user: may read PLM2 but has no department to work in changes. */
export function useIsReadOnlyViewer(): boolean {
  return useEffectiveRole() === 'viewer';
}
