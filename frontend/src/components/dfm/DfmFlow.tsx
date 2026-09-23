/**
 * DfmFlow - one DFM topic as a swimlane sequence: Toolmaker | KTX | Tier 1.
 * One row per current message in server order; the card sits in the sender's
 * lane and an arrow runs to each addressee, coloured by kind (original blue,
 * forward violet, answer green, question amber), dashed while that party
 * still owes an answer. Arrow positions come from lane indices only, so the
 * view needs no layout measurement. Card actions open the guided form
 * prefilled. A finished topic is read-only with Reopen.
 */
import { Fragment, useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  closeTopic, dfmFileUrl, getTopic, reopenTopic, KIND_LABELS, KINDS, PARTIES, PARTY_LABELS,
  type DfmEntry,
} from '../../api/dfm';
import type { PaneDocument } from '../parts/DocumentPane';
import { apiErrorMessage } from '../../lib/apiError';
import DfmEntryForm from './DfmEntryForm';
import {
  arrowGeometry, cardActions, currentIds, formatDays, initials, KIND_STYLE, laneCenterPct, laneIndex,
  newOriginalStep, nextStepText, partyList, shortDate, type DfmStep,
} from './dfmFlow';

interface Props {
  partId: number;
  topicId: number;
  onOpenPdf(doc: PaneDocument): void;
}

const ARROW_GAP = 8;

export default function DfmFlow({ partId, topicId, onOpenPdf }: Props) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<{ step: DfmStep; n: number } | null>(null);
  const [openHistory, setOpenHistory] = useState<Set<number>>(new Set());
  const [highlighted, setHighlighted] = useState<number | null>(null);
  const cardRefs = useRef(new Map<number, HTMLDivElement>());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

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
    onError: (e) => toast.error(apiErrorMessage(e, 'Could not finish the topic')),
  });
  const reopen = useMutation({
    mutationFn: () => reopenTopic(partId, topicId),
    onSuccess: () => { toast.success('Topic reopened'); refresh(); },
    onError: (e) => toast.error(apiErrorMessage(e, 'Could not reopen the topic')),
  });

  if (!topic) return <div className="text-slate-400 text-sm">Loading…</div>;
  const open = topic.status === 'open';
  const entries = topic.entries;
  const ids = currentIds(entries);
  const byId = new Map(entries.map((e) => [e.id, e]));
  const waitingOn = open ? topic.waiting_on ?? [] : [];
  const waitingCount = (p: string) => waitingOn.find((w) => w.party === p)?.count ?? 0;

  const openStep = (step: DfmStep) => setForm((cur) => ({ step, n: (cur?.n ?? 0) + 1 }));
  const jumpTo = (id: number) => {
    cardRefs.current.get(id)?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
    setHighlighted(id);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setHighlighted(null), 2000);
  };

  const formEl = form && open && (
    <DfmEntryForm key={form.n} partId={partId} topicId={topicId} step={form.step}
      onDone={() => { setForm(null); refresh(); }} onCancel={() => setForm(null)} />
  );

  const fileLink = (f: DfmEntry['files'][number]) =>
    f.original_filename.toLowerCase().endsWith('.pdf') ? (
      <button key={f.id} data-testid={`dfm-file-${f.id}`}
        onClick={() => onOpenPdf({ fileId: f.id, filename: f.original_filename, kind: 'pdf', revisionName: topic.title, inlineUrl: dfmFileUrl(partId, f.id, 'inline') })}
        className="font-mono text-xs text-blue-300 hover:underline text-left break-all">{f.original_filename}</button>
    ) : (
      <a key={f.id} data-testid={`dfm-file-${f.id}`} href={dfmFileUrl(partId, f.id, 'download')}
        className="font-mono text-xs text-blue-300 hover:underline break-all">{f.original_filename}</a>
    );

  const body = (e: Omit<DfmEntry, 'history'>) => (
    <>
      <div className="text-xs text-slate-400">
        to {partyList(e.addressed_to)} · {shortDate(e.sent_at ?? e.recorded_at)} · {initials(e.recorded_by_name)}
      </div>
      {e.note && <div className="text-slate-100 whitespace-pre-wrap mt-0.5">{e.note}</div>}
      {e.files.length > 0 && (
        <div className="flex flex-col gap-0.5 mt-1">
          {e.files.map((f) => <span key={f.id}>{fileLink(f)}</span>)}
        </div>
      )}
    </>
  );

  const statusLines = (e: DfmEntry) => {
    const answered = e.answered_by.map((a) => (
      <div key={`a-${a.entry_id}`} className="text-emerald-300">Answered by {PARTY_LABELS[a.party]} {shortDate(a.date)}</div>
    ));
    const waiting = open ? e.awaiting.map((w) => (
      <div key={`w-${w.party}`} className="text-amber-300">Waiting on {PARTY_LABELS[w.party]} · {formatDays(w.days)}</div>
    )) : [];
    if (answered.length + waiting.length === 0) return null;
    return <div data-testid={`dfm-status-${e.id}`} className="mt-1 text-xs">{answered}{waiting}</div>;
  };

  const arrows = (e: DfmEntry) => {
    const from = laneIndex(e.party);
    const waiting = new Set(open ? e.awaiting.map((w) => w.party) : []);
    return e.addressed_to.map((p, i) => {
      const to = laneIndex(p);
      const g = arrowGeometry(from, to);
      const dashed = waiting.has(p);
      const style = KIND_STYLE[e.kind];
      return (
        <div key={p} data-testid={`dfm-arrow-${e.id}-${p}`} data-from-lane={from} data-to-lane={to} data-kind={e.kind}
          data-dashed={String(dashed)}
          className={`absolute h-0 border-t-2 ${style.line} ${dashed ? 'border-dashed' : 'border-solid'}`}
          style={{ left: `${g.leftPct}%`, width: `${g.widthPct}%`, top: 6 + i * ARROW_GAP }}>
          <span aria-hidden className={`absolute ${style.head}`}
            style={{
              top: -6, width: 0, height: 0, borderTop: '5px solid transparent', borderBottom: '5px solid transparent',
              ...(g.direction === 'right'
                ? { right: -2, borderLeft: '9px solid currentColor' }
                : { left: -2, borderRight: '9px solid currentColor' }),
            }} />
        </div>
      );
    });
  };

  const card = (e: DfmEntry) => {
    const style = KIND_STYLE[e.kind];
    const target = e.reply_to_id != null ? byId.get(ids.get(e.reply_to_id) ?? -1) : undefined;
    const lit = highlighted === e.id;
    return (
      <div ref={(el) => { if (el) cardRefs.current.set(e.id, el); else cardRefs.current.delete(e.id); }}
        data-testid={`dfm-entry-${e.id}`} data-party={e.party} data-lane={laneIndex(e.party)} data-kind={e.kind}
        data-highlighted={String(lit)}
        className={`relative rounded-lg border border-slate-700 border-l-4 ${style.line} bg-slate-800 p-2 text-sm transition-shadow ${lit ? 'ring-2 ring-yellow-300' : ''}`}>
        <div className="flex items-center gap-2 mb-0.5">
          <span data-testid="dfm-kind-badge" className={`text-xs px-1.5 py-0.5 rounded border ${style.badge}`}>{KIND_LABELS[e.kind]}</span>
          <span className="text-xs text-slate-500">#{e.id}</span>
          {e.history.length > 0 && <span className="text-xs text-amber-300">(updated)</span>}
        </div>
        {target && (
          <button data-testid={`dfm-reply-link-${e.id}`} onClick={() => jumpTo(target.id)}
            className="text-xs text-slate-400 hover:text-slate-200 underline decoration-dotted">
            reply to #{target.id} {KIND_LABELS[target.kind]}
          </button>
        )}
        {body(e)}
        {statusLines(e)}
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
        {open && (
          <div className="flex flex-wrap gap-1 mt-2">
            {cardActions(e, entries).map((a) => (
              <button key={a.key} data-testid={`dfm-action-${e.id}-${a.key}`} data-action={a.key} onClick={() => openStep(a.step)}
                className={`text-xs px-2 py-0.5 rounded ${a.key === 'update' ? 'text-slate-400 hover:text-slate-200' : 'bg-slate-700 hover:bg-slate-600 text-slate-100'}`}>
                {a.label}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  };

  let strip: string;
  if (!open) strip = 'Finished confirmed, read only';
  else if (entries.length === 0) strip = 'No messages yet. Record the first DFM with + New DFM.';
  else if (topic.next_step) strip = nextStepText(topic.next_step);
  else strip = topic.all_answered ? 'All answered' : 'Nothing waiting';

  return (
    <div data-testid="dfm-flow" className="mt-4">
      <div className="flex items-center justify-between mb-3 gap-2">
        <div>
          <span className="text-lg font-semibold text-slate-100">{topic.title}</span>
          <span className={`ml-2 text-xs px-2 py-0.5 rounded ${open ? 'bg-emerald-900 text-emerald-200' : 'bg-slate-700 text-slate-200'}`}>
            {open ? 'Open' : 'Finished confirmed'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {open && (
            <button data-testid="dfm-new-original" onClick={() => openStep(newOriginalStep())}
              className="px-3 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm">+ New DFM</button>
          )}
          {open ? (
            <button data-testid="dfm-finish" onClick={() => finish.mutate()} disabled={finish.isPending}
              className="px-3 py-1 rounded bg-emerald-700 hover:bg-emerald-600 disabled:bg-slate-600 text-white text-sm">Finish confirmed</button>
          ) : (
            <button data-testid="dfm-reopen" onClick={() => reopen.mutate()} disabled={reopen.isPending}
              className="px-3 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100 text-sm">Reopen</button>
          )}
        </div>
      </div>

      <div data-testid="dfm-status-strip"
        className={`flex flex-wrap items-center gap-x-4 gap-y-1 mb-3 px-3 py-2 rounded border text-sm ${open && topic.next_step ? 'border-amber-700 bg-amber-950/40 text-amber-200' : 'border-slate-700 bg-slate-900 text-slate-200'}`}>
        <span className="font-medium">{strip}</span>
        {waitingOn.map((w) => (
          <span key={w.party} className="text-xs text-amber-300">{PARTY_LABELS[w.party]}: {w.count} waiting</span>
        ))}
        <span data-testid="dfm-legend" className="ml-auto flex items-center gap-3 text-xs text-slate-400">
          {KINDS.map((k) => (
            <span key={k} className="flex items-center gap-1">
              <span aria-hidden className={`inline-block w-4 h-0.5 ${KIND_STYLE[k].swatch}`} />{KIND_LABELS[k]}
            </span>
          ))}
        </span>
      </div>

      {form?.step.anchorId === null && formEl}

      <div className="grid grid-cols-3 mb-1">
        {PARTIES.map((p) => (
          <div key={p} data-testid={`dfm-lane-${p}`} data-waiting={waitingCount(p)}
            className="mx-1.5 border-b border-slate-600 pb-1 flex items-center justify-center gap-2">
            <span className="font-semibold text-slate-200">{PARTY_LABELS[p]}</span>
            {waitingCount(p) > 0 && (
              <span className="text-xs px-1.5 rounded bg-amber-900 text-amber-200">{waitingCount(p)} waiting</span>
            )}
          </div>
        ))}
      </div>

      <div className="relative">
        {PARTIES.map((p, i) => (
          <div key={p} aria-hidden className="absolute top-0 bottom-0 border-l border-dashed border-slate-700"
            style={{ left: `${laneCenterPct(i)}%` }} />
        ))}
        {entries.map((e) => (
          <Fragment key={e.id}>
            <div data-testid={`dfm-row-${e.id}`} className="relative pb-2">
              <div className="relative" style={{ height: 12 + (e.addressed_to.length - 1) * ARROW_GAP }}>{arrows(e)}</div>
              <div className="grid grid-cols-3">
                <div className="px-1.5" style={{ gridColumnStart: laneIndex(e.party) + 1 }}>{card(e)}</div>
              </div>
            </div>
            {form?.step.anchorId === e.id && <div className="relative pb-2">{formEl}</div>}
          </Fragment>
        ))}
      </div>
    </div>
  );
}
