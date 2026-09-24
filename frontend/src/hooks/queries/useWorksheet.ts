import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { auditParams, getWorksheet, getWorksheetAudit, type WorksheetAuditFilters } from '../../api/worksheet';

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

export const WORKSHEET_AUDIT_KEY = 'worksheet-audit';

/** The worksheet audit log, newest first; fetchNextPage loads older entries (before the last id). */
export function useWorksheetAudit(projectId: number, filters: WorksheetAuditFilters) {
  return useInfiniteQuery({
    queryKey: [WORKSHEET_AUDIT_KEY, projectId, auditParams(filters)],
    queryFn: ({ pageParam }) => getWorksheetAudit(projectId, filters, pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => (last.has_more ? last.entries[last.entries.length - 1]?.id : undefined),
    enabled: !!projectId,
  });
}

const FIELD_HISTORY_LIMIT = 50;

/** One field's audit entries (the field note popover's History). */
export function useFieldAudit(projectId: number | null | undefined, partId: number, fieldKey: string, enabled: boolean) {
  return useQuery({
    queryKey: [WORKSHEET_AUDIT_KEY, projectId, { part_id: partId, field_key: fieldKey }],
    queryFn: () => getWorksheetAudit(projectId as number, { part_id: partId, field_key: fieldKey }, undefined, FIELD_HISTORY_LIMIT),
    enabled: enabled && !!projectId,
  });
}
