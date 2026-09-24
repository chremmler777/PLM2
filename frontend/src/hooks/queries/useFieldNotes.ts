import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  addFieldComment, getFieldNoteThread, listPartFieldNotes, listProjectFieldNotes, setFieldFlag,
  type FieldFlag, type FieldNoteSummary,
} from '../../api/fieldNotes';
import { apiErrorMessage } from '../../lib/apiError';
import { indexByField } from '../../lib/fieldNotes';

/** Every field note query starts with this key, so one invalidation refreshes markers everywhere. */
export const FIELD_NOTES_KEY = 'field-notes';

export function usePartFieldNotes(partId: number | null | undefined) {
  return useQuery({
    queryKey: [FIELD_NOTES_KEY, 'part', partId],
    queryFn: () => listPartFieldNotes(partId as number),
    enabled: !!partId,
  });
}

export function usePartFieldNoteIndex(partId: number | null | undefined): Map<string, FieldNoteSummary> {
  const { data } = usePartFieldNotes(partId);
  return useMemo(() => indexByField(Array.isArray(data) ? data : []), [data]);
}

export function useProjectFieldNotes(projectId: number) {
  return useQuery({
    queryKey: [FIELD_NOTES_KEY, 'project', projectId],
    queryFn: () => listProjectFieldNotes(projectId),
    enabled: !!projectId,
  });
}

export function useFieldNoteThread(partId: number, fieldKey: string, enabled: boolean) {
  return useQuery({
    queryKey: [FIELD_NOTES_KEY, 'thread', partId, fieldKey],
    queryFn: () => getFieldNoteThread(partId, fieldKey),
    enabled,
  });
}

export function useFieldNoteActions(partId: number, fieldKey: string) {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: [FIELD_NOTES_KEY] });
  const addComment = useMutation({
    mutationFn: (body: string) => addFieldComment(partId, fieldKey, body),
    onSuccess: refresh,
    onError: (e) => toast.error(apiErrorMessage(e, 'Could not add the comment')),
  });
  const setFlag = useMutation({
    mutationFn: (status: FieldFlag | null) => setFieldFlag(partId, fieldKey, status),
    onSuccess: refresh,
    onError: (e) => toast.error(apiErrorMessage(e, 'Could not set the flag')),
  });
  return { addComment, setFlag };
}
