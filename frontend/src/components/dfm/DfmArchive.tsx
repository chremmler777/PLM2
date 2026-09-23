/**
 * DfmArchive - the folder-like archive on a tool: one row per topic (title,
 * status, entries, last activity), "+ topic", and the selected topic's ledger.
 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { createTopic, listTopics } from '../../api/dfm';
import type { PaneDocument } from '../parts/DocumentPane';
import DfmLedger from './DfmLedger';
import { apiErrorMessage } from '../../lib/apiError';

interface Props {
  partId: number;
  onOpenPdf(doc: PaneDocument): void;
}

export default function DfmArchive({ partId, onOpenPdf }: Props) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<number | null>(null);
  const [newTitle, setNewTitle] = useState<string | null>(null);  // null = not adding

  const { data: topics, isError } = useQuery({
    queryKey: ['dfm-topics', partId],
    queryFn: () => listTopics(partId),
  });

  const create = useMutation({
    mutationFn: (title: string) => createTopic(partId, title),
    onSuccess: (t) => {
      toast.success(`Topic "${t.title}" opened`);
      setNewTitle(null);
      setSelected(t.id);
      queryClient.invalidateQueries({ queryKey: ['dfm-topics', partId] });
      queryClient.invalidateQueries({ queryKey: ['changelog', String(partId)] });
    },
    onError: (e) => toast.error(apiErrorMessage(e, 'Could not open the topic')),
  });

  const submit = () => {
    const title = (newTitle ?? '').trim();
    if (!title) { toast.error('Give the topic a title'); return; }
    create.mutate(title);
  };

  if (isError) {
    return (
      <p data-testid="dfm-archive-error" className="text-red-400 text-sm mb-8">
        Could not load the DFM archive
      </p>
    );
  }

  if (!topics) return null;

  return (
    <div data-testid="dfm-archive" className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-8">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-xl font-bold text-slate-100">DFM archive</h2>
        {newTitle === null ? (
          <button data-testid="dfm-new-topic" onClick={() => setNewTitle('')}
            className="px-3 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm">+ topic</button>
        ) : (
          <div className="flex items-center gap-2">
            <input data-testid="dfm-topic-title" autoFocus value={newTitle} onChange={(e) => setNewTitle(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') submit(); if (e.key === 'Escape') setNewTitle(null); }}
              placeholder="Topic, e.g. Gate position"
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-slate-100 text-sm w-64" />
            <button data-testid="dfm-create-topic" onClick={submit} disabled={create.isPending}
              className="px-3 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white text-sm">Open topic</button>
            <button onClick={() => setNewTitle(null)} className="px-3 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100 text-sm">Cancel</button>
          </div>
        )}
      </div>

      {topics && topics.length === 0 && <p className="text-slate-500 text-sm">No DFM topic yet. Open one for the first request or study.</p>}
      <div className="divide-y divide-slate-700">
        {topics?.map((t) => (
          <button key={t.id} data-testid={`dfm-topic-${t.id}`} onClick={() => setSelected(t.id)}
            className={`w-full flex items-center gap-3 py-2 px-2 text-left text-sm rounded ${selected === t.id ? 'bg-slate-700' : 'hover:bg-slate-700/50'}`}>
            <span className="flex-1 text-slate-100 font-medium">{t.title}</span>
            <span className={`text-xs px-2 py-0.5 rounded ${t.status === 'open' ? 'bg-emerald-900 text-emerald-200' : 'bg-slate-600 text-slate-200'}`}>
              {t.status === 'open' ? 'Open' : 'Finished confirmed'}
            </span>
            <span className="text-slate-400 w-20 text-right">{t.entry_count} {t.entry_count === 1 ? 'entry' : 'entries'}</span>
            <span className="text-slate-500 font-mono text-xs w-24 text-right">{t.last_activity.slice(0, 10)}</span>
          </button>
        ))}
      </div>

      {selected !== null && <DfmLedger partId={partId} topicId={selected} onOpenPdf={onOpenPdf} />}
    </div>
  );
}
