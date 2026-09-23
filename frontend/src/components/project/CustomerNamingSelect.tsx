/** Per-project choice of the customer's file naming convention (used by the guided upload). */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../../api/client';
import { CUSTOMER_NAMING_LABELS, type CustomerNaming } from './projectTypes';

export function CustomerNamingSelect({ projectId, value }: { projectId: number; value: CustomerNaming }) {
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: async (next: CustomerNaming) => {
      const res = await client.patch(`/v1/plants/projects/${projectId}`, { customer_naming: next });
      return res.data;
    },
    onSuccess: () => {
      toast.success('Customer file naming saved');
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
    },
    onError: (error: unknown) => {
      toast.error((error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to save');
    },
  });
  return (
    <label className="flex items-center gap-2 text-xs text-slate-400">
      Customer file naming
      <select
        aria-label="Customer file naming"
        value={value ?? ''}
        disabled={save.isPending}
        onChange={(e) => save.mutate((e.target.value || null) as CustomerNaming)}
        className="px-2 py-1 rounded bg-slate-900 border border-slate-700 text-slate-100 text-xs"
      >
        <option value="">None</option>
        {(Object.keys(CUSTOMER_NAMING_LABELS) as Array<'vw' | 'scout'>).map((k) => (
          <option key={k} value={k}>{CUSTOMER_NAMING_LABELS[k]}</option>
        ))}
      </select>
    </label>
  );
}
