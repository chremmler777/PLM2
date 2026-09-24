/**
 * DfmArchive - the folder-like archive on a tool: one row per topic (title,
 * status, who it waits on, last step, message count) and "+ topic". Opening a
 * topic replaces the list with that topic's flow; its "DFM archive"
 * breadcrumb returns here. "Open in window" moves the archive into its own
 * browser window (inWindow is that window: fills it, no further pop-out).
 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { createTopic, listTopics } from '../../api/dfm';
import type { PaneDocument } from '../parts/DocumentPane';
import DfmFlow from './DfmFlow';
import { lastStepText, waitingSummary } from './dfmFlow';
import { openDfmWindow } from './dfmWindow';
import { apiErrorMessage } from '../../lib/apiError';

interface Props {
  partId: number;
  onOpenPdf(doc: PaneDocument): void;
  /** Topic to open first (the pop-out window's ?topic=). */
  initialTopic?: number | null;
  /** Rendered in its own window: fill the height, no "Open in window". */
  inWindow?: boolean;
}

export default function DfmArchive({ partId, onOpenPdf, initialTopic = null, inWindow = false }: Props) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<number | null>(initialTopic);
  const [newTitle, setNewTitle] = useState<string | null>(null);  // null = not adding

  const { data: topics, isError } = useQuery({
    queryKey: ['dfm-topics', partId],
    queryFn: () => listTopics(partId),
    refetchOnWindowFocus: true,
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

  const frame = inWindow
    ? 'flex flex-col flex-1 min-h-0 p-4'
    : 'bg-slate-800 rounded-lg border border-slate-700 p-5 mb-8';

  if (selected !== null) {
    return (
      <div data-testid="dfm-archive" className={frame}>
        <DfmFlow partId={partId} topicId={selected} onOpenPdf={onOpenPdf} onBack={() => setSelected(null)}
          onPopOut={inWindow ? undefined : () => openDfmWindow(partId, selected)} fill={inWindow} />
      </div>
    );
  }

  if (!topics) return null;

  return (
    <div data-testid="dfm-archive" className={frame}>
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <h2 className="text-lg font-semibold text-slate-100 mr-auto">DFM archive</h2>
        {newTitle === null ? (
          <button data-testid="dfm-new-topic" onClick={() => setNewTitle('')}
            className="px-3 py-1 rounded-md bg-blue-600 hover:bg-blue-500 text-white text-sm">+ topic</button>
        ) : (
          <div className="flex items-center gap-2">
            <input data-testid="dfm-topic-title" autoFocus value={newTitle} onChange={(e) => setNewTitle(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') submit(); if (e.key === 'Escape') setNewTitle(null); }}
              placeholder="Topic, e.g. Gate position"
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-slate-100 text-sm w-64" />
            <button data-testid="dfm-create-topic" onClick={submit} disabled={create.isPending}
              className="px-3 py-1 rounded-md bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white text-sm">Open topic</button>
            <button onClick={() => setNewTitle(null)} className="px-3 py-1 rounded-md bg-slate-700 hover:bg-slate-600 text-slate-100 text-sm">Cancel</button>
          </div>
        )}
        {!inWindow && (
          <button data-testid="dfm-popout" onClick={() => openDfmWindow(partId, null)} title="Open the DFM archive in its own window"
            className="px-3 py-1 rounded-md bg-slate-700 hover:bg-slate-600 text-slate-100 text-sm">Open in window</button>
        )}
      </div>

      {topics.length === 0 && <p className="text-slate-500 text-sm">No DFM topic yet. Open one for the first request or study.</p>}
      <div className={`divide-y divide-slate-700/70 ${inWindow ? 'overflow-auto min-h-0' : ''}`}>
        {topics.map((t) => {
          const waiting = waitingSummary(t);
          return (
            <button key={t.id} data-testid={`dfm-topic-${t.id}`} onClick={() => setSelected(t.id)}
              className="w-full flex flex-wrap items-center gap-x-3 gap-y-0.5 py-2.5 px-2 text-left text-sm rounded hover:bg-slate-700/50">
              <span className="flex-1 min-w-[10rem] text-slate-100 font-medium">{t.title}</span>
              <span className={`text-xs px-2 py-0.5 rounded-full ring-1 ring-inset ${t.status === 'open' ? 'bg-emerald-500/15 text-emerald-200 ring-emerald-400/40' : 'bg-slate-700 text-slate-300 ring-slate-500'}`}>
                {t.status === 'open' ? 'Open' : 'Finished confirmed'}
              </span>
              {waiting && (
                <span data-testid={`dfm-topic-waiting-${t.id}`}
                  className={`text-xs ${t.waiting_on?.length ? 'text-amber-300' : 'text-emerald-300'}`}>{waiting}</span>
              )}
              {t.last_step && (
                <span data-testid={`dfm-topic-last-${t.id}`} className="text-xs text-slate-400">{lastStepText(t.last_step)}</span>
              )}
              <span className="text-xs text-slate-400 w-24 text-right tabular-nums">{t.entry_count} {t.entry_count === 1 ? 'message' : 'messages'}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
