/**
 * The project's part data mail list: who gets the digest mail (one per
 * project, a few minutes after new customer data, iterations, files or
 * status changes). PM members and admins keep it; for everyone else the
 * server refuses the list and the card stays hidden.
 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../../api/client';
import { toastError } from '../../lib/apiError';
import { btnSm } from '../common/buttonStyles';

interface MailRecipient {
  id: number;
  email: string;
  display_name: string | null;
  active: boolean;
}

export function ProjectMailListCard({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const [email, setEmail] = useState('');
  const key = ['project-mail-recipients', projectId];
  const { data: rows = [], isLoading, isError } = useQuery<MailRecipient[]>({
    queryKey: key,
    queryFn: async () => (await client.get(`/v1/projects/${projectId}/mail-recipients`)).data,
    retry: false,
  });
  const add = useMutation({
    mutationFn: async (value: string) =>
      (await client.post(`/v1/projects/${projectId}/mail-recipients`, { email: value })).data,
    onSuccess: () => {
      toast.success('Added to the mail list');
      setEmail('');
      qc.invalidateQueries({ queryKey: key });
    },
    onError: (e: unknown) => { toastError(e, 'Could not add the address'); },
  });
  const remove = useMutation({
    mutationFn: async (id: number) =>
      client.delete(`/v1/projects/${projectId}/mail-recipients/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
    onError: (e: unknown) => { toastError(e, 'Could not remove the address'); },
  });

  if (isLoading || isError) return null;

  return (
    <div data-testid="project-mail-list-card">
      <h3 className="text-[11px] uppercase tracking-wide text-slate-400 mb-1">Part data mail list</h3>
      {rows.length === 0 ? (
        <p className="text-xs text-slate-500 mb-1">Nobody yet. No mails are sent for this project.</p>
      ) : (
        <ul className="space-y-0.5 mb-1">
          {rows.map((r) => (
            <li key={r.id} className="flex items-center gap-2 text-sm" data-testid={`mail-row-${r.id}`}>
              <span className="flex-1 min-w-0 truncate text-slate-200" title={r.email}>
                {r.display_name || r.email}
                {!r.active && <span className="text-slate-500"> (inactive)</span>}
              </span>
              <button type="button" data-testid={`mail-remove-${r.id}`}
                aria-label={`Remove ${r.email}`}
                disabled={remove.isPending}
                onClick={() => remove.mutate(r.id)}
                className={`${btnSm.ghost} flex-shrink-0 text-slate-400 hover:text-red-300`}>
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      <form className="flex items-center gap-2"
        onSubmit={(e) => { e.preventDefault(); if (email.trim()) add.mutate(email.trim()); }}>
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
          placeholder="name@us.ktx.group" aria-label="Email address to add"
          data-testid="mail-add-input"
          className="h-7 flex-1 min-w-0 rounded-md border border-slate-600 bg-slate-900 px-2 text-xs text-slate-100 focus:border-sky-500 focus:outline-none" />
        <button type="submit" data-testid="mail-add" disabled={add.isPending || !email.trim()}
          className={`${btnSm.secondary} flex-shrink-0`}>
          Add
        </button>
      </form>
    </div>
  );
}

export default ProjectMailListCard;
