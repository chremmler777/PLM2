/**
 * DfmLedger - one topic's three-column ledger: Toolmaker | KTX | Tier 1.
 * One row per entry, chronological, in its author's column. Updates show
 * "(updated)" with the earlier versions collapsed. A finished topic is
 * read-only with Reopen; an open one has Finish confirmed.
 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { closeTopic, dfmFileUrl, getTopic, reopenTopic, PARTIES, PARTY_LABELS, type DfmEntry, type DfmParty } from '../../api/dfm';
import type { PaneDocument } from '../parts/DocumentPane';
import DfmEntryForm from './DfmEntryForm';

export function initials(name: string | null | undefined): string {
  const parts = (name ?? '').trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  return parts.map((p) => p[0].toUpperCase()).join('');
}

export function shortDate(iso: string | null | undefined): string {
  return iso ? iso.slice(5, 10) : '';
}

function errMsg(error: unknown, fallback: string) {
  return (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;
}

interface Props {
  partId: number;
  topicId: number;
  onOpenPdf(doc: PaneDocument): void;
}

type FormState = { party: DfmParty; supersedesId: number | null } | null;

export default function DfmLedger({ partId, topicId, onOpenPdf }: Props) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<FormState>(null);
  const [openHistory, setOpenHistory] = useState<Set<number>>(new Set());

  const { data: topic } = useQuery({
    queryKey: ['dfm-topic', partId, topicId],
    queryFn: () => getTopic(partId, topicId),
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['dfm-topic', partId, topicId] });
    queryClient.invalidateQueries({ queryKey: ['dfm-topics', partId] });
  };
  const finish = useMutation({
    mutationFn: () => closeTopic(partId, topicId),
    onSuccess: () => { toast.success('Topic finished confirmed'); setForm(null); refresh(); },
    onError: (e) => toast.error(errMsg(e, 'Could not finish the topic')),
  });
  const reopen = useMutation({
    mutationFn: () => reopenTopic(partId, topicId),
    onSuccess: () => { toast.success('Topic reopened'); refresh(); },
    onError: (e) => toast.error(errMsg(e, 'Could not reopen the topic')),
  });

  if (!topic) return <div className="text-slate-400 text-sm">Loading…</div>;
  const open = topic.status === 'open';

  const fileLink = (f: DfmEntry['files'][number]) =>
    f.original_filename.toLowerCase().endsWith('.pdf') ? (
      <button key={f.id} data-testid={`dfm-file-${f.id}`}
        onClick={() => onOpenPdf({ fileId: f.id, filename: f.original_filename, kind: 'pdf', revisionName: topic.title, inlineUrl: dfmFileUrl(partId, f.id, 'inline') })}
        className="font-mono text-xs text-blue-300 hover:underline">{f.original_filename}</button>
    ) : (
      <a key={f.id} data-testid={`dfm-file-${f.id}`} href={dfmFileUrl(partId, f.id, 'download')}
        className="font-mono text-xs text-blue-300 hover:underline">{f.original_filename}</a>
    );

  const body = (e: Omit<DfmEntry, 'history'>) => (
    <>
      <div className="text-xs text-slate-400">
        {shortDate(e.sent_at ?? e.recorded_at)} → {e.addressed_to.map((p) => PARTY_LABELS[p]).join(', ')}
      </div>
      {e.note && <div className="text-slate-100 whitespace-pre-wrap">{e.note}</div>}
      {e.files.length > 0 && (
        <div className="flex flex-col gap-0.5 mt-1">
          {e.files.map((f) => <span key={f.id}>{fileLink(f)} <span className="text-xs text-slate-500">↑{initials(f.uploaded_by_name)}</span></span>)}
        </div>
      )}
    </>
  );

  return (
    <div data-testid="dfm-ledger" className="mt-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <span className="text-lg font-semibold text-slate-100">{topic.title}</span>
          <span className={`ml-2 text-xs px-2 py-0.5 rounded ${open ? 'bg-emerald-900 text-emerald-200' : 'bg-slate-700 text-slate-200'}`}>
            {open ? 'Open' : 'Finished confirmed'}
          </span>
        </div>
        {open ? (
          <button data-testid="dfm-finish" onClick={() => finish.mutate()} disabled={finish.isPending}
            className="px-3 py-1 rounded bg-emerald-700 hover:bg-emerald-600 disabled:bg-slate-600 text-white text-sm">Finish confirmed</button>
        ) : (
          <button data-testid="dfm-reopen" onClick={() => reopen.mutate()} disabled={reopen.isPending}
            className="px-3 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100 text-sm">Reopen</button>
        )}
      </div>

      <div className="grid grid-cols-3 gap-3">
        {PARTIES.map((p) => (
          <div key={p} data-testid={`dfm-column-${p}`} className="border-b border-slate-600 pb-2 flex items-center justify-between">
            <span className="font-semibold text-slate-200">{PARTY_LABELS[p]}</span>
            {open && (
              <button data-testid={`dfm-add-${p}`} onClick={() => setForm({ party: p, supersedesId: null })}
                className="text-xs px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-100">+ entry</button>
            )}
          </div>
        ))}
        {topic.entries.map((e) => (
          <div key={e.id} className="contents">
            {PARTIES.map((p) => (
              <div key={p} className="min-h-[1px]">
                {p === e.party && (
                  <div data-testid={`dfm-entry-${e.id}`} data-party={e.party}
                    className="rounded-lg border border-slate-700 bg-slate-800 p-2 text-sm">
                    {body(e)}
                    <div className="flex items-center gap-2 mt-1 text-xs text-slate-500">
                      <span>↑{initials(e.recorded_by_name)}</span>
                      {e.history.length > 0 && <span className="text-amber-300">(updated)</span>}
                      {open && (
                        <button data-testid={`dfm-update-${e.id}`} onClick={() => setForm({ party: e.party, supersedesId: e.id })}
                          className="ml-auto text-slate-400 hover:text-slate-200">Update this entry</button>
                      )}
                    </div>
                    {e.history.length > 0 && (
                      <div className="mt-1">
                        <button data-testid={`dfm-history-${e.id}`}
                          onClick={() => setOpenHistory((cur) => { const next = new Set(cur); if (next.has(e.id)) next.delete(e.id); else next.add(e.id); return next; })}
                          className="text-xs text-slate-400 hover:text-slate-200">
                          {openHistory.has(e.id) ? '▾' : '▸'} {e.history.length} earlier version{e.history.length > 1 ? 's' : ''}
                        </button>
                        {openHistory.has(e.id) && e.history.map((h) => (
                          <div key={h.id} className="mt-1 pl-2 border-l border-slate-600 opacity-75">{body(h)}</div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>

      {form && open && (
        <DfmEntryForm partId={partId} topicId={topicId} party={form.party} supersedesId={form.supersedesId}
          onDone={() => { setForm(null); refresh(); }} onCancel={() => setForm(null)} />
      )}
    </div>
  );
}
