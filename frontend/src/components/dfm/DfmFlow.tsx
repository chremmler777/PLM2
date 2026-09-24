/**
 * DfmFlow - one DFM topic as a swimlane sequence: Toolmaker | KTX | Tier 1.
 * A slim date column on the left carries a divider whenever the day changes.
 * Each message card (max 300px) is centred on its sender's lane line; an
 * arrow leaves the card edge facing each addressee and ends on a marker on
 * that addressee's lane line, labelled and coloured by kind, dashed while
 * that party still owes an answer. Geometry comes from lane indices only, so
 * the view needs no layout measurement to be correct. The canvas zooms
 * (50% to 150%, Ctrl+wheel, Fit) and shows compact cards below 75%.
 * Card actions open the guided form prefilled. A finished topic is read-only
 * with Reopen.
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
  arrowSpan, CARD_MARGIN_PX, CARD_MAX_PX, cardActions, cardLane, currentIds, dayLabel, flowRows, formatDays, initials,
  KIND_STYLE, laneCenterPct, laneIndex, newOriginalStep, nextStepText, PARTY_STYLE, shortDate, sourceLabel,
  type DfmStep,
} from './dfmFlow';
import { fitZoom, isCompact, useDfmZoom, ZOOM_MAX, ZOOM_MIN } from './dfmZoom';

interface Props {
  partId: number;
  topicId: number;
  onOpenPdf(doc: PaneDocument): void;
  /** Back to the topic list (the "DFM archive" breadcrumb). */
  onBack(): void;
  /** Opens the archive in its own window; hidden when absent (already in one). */
  onPopOut?: () => void;
  /** Fill the parent height (pop-out window) instead of a capped scroll box. */
  fill?: boolean;
}

/** Width of the date column and the narrowest canvas (date column plus three lanes), in px. */
const DATE_COL_PX = 64;
const MIN_CANVAS_PX = DATE_COL_PX + 3 * 270;
/** Arrow line position inside a message row: first line, then one per extra addressee. */
const ARROW_TOP_PX = 22;
const ARROW_GAP_PX = 18;
const cardWidth = `min(${CARD_MAX_PX}px, calc(100% - ${CARD_MARGIN_PX * 2}px))`;

const iconBtn = 'h-7 min-w-7 px-2 text-sm text-slate-300 hover:text-white hover:bg-slate-700 disabled:opacity-40 disabled:hover:bg-transparent';

export default function DfmFlow({ partId, topicId, onOpenPdf, onBack, onPopOut, fill = false }: Props) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<{ step: DfmStep; n: number } | null>(null);
  const [openHistory, setOpenHistory] = useState<Set<number>>(new Set());
  const [highlighted, setHighlighted] = useState<number | null>(null);
  const [menuFor, setMenuFor] = useState<number | null>(null);
  const [viewport, setViewport] = useState<HTMLDivElement | null>(null);
  const [viewportWidth, setViewportWidth] = useState(0);
  const { zoom, setZoom, zoomBy } = useDfmZoom();
  const cardRefs = useRef(new Map<number, HTMLDivElement>());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  // Track the scroll box width (for the canvas width and Fit); jsdom has no ResizeObserver.
  useEffect(() => {
    if (!viewport) return;
    setViewportWidth(viewport.clientWidth);
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => setViewportWidth(viewport.clientWidth));
    ro.observe(viewport);
    return () => ro.disconnect();
  }, [viewport]);

  // Ctrl+wheel zooms the canvas instead of the page; needs a non-passive listener.
  useEffect(() => {
    if (!viewport) return;
    const onWheel = (ev: WheelEvent) => {
      if (!ev.ctrlKey && !ev.metaKey) return;
      ev.preventDefault();
      if (ev.deltaY !== 0) zoomBy(ev.deltaY < 0 ? 1 : -1);
    };
    viewport.addEventListener('wheel', onWheel, { passive: false });
    return () => viewport.removeEventListener('wheel', onWheel);
  }, [viewport, zoomBy]);

  const { data: topic } = useQuery({
    queryKey: ['dfm-topic', partId, topicId],
    queryFn: () => getTopic(partId, topicId),
    refetchOnWindowFocus: true,
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
  const compact = isCompact(zoom);
  const canvasWidth = Math.max(MIN_CANVAS_PX, Math.floor((viewportWidth * 100) / zoom));
  const formWidth = viewportWidth > 0 ? Math.min(720, Math.max(320, viewportWidth - 96)) : 720;

  const openStep = (step: DfmStep) => { setMenuFor(null); setForm((cur) => ({ step, n: (cur?.n ?? 0) + 1 })); };
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

  const fileLink = (e: Omit<DfmEntry, 'history'>, f: DfmEntry['files'][number]) =>
    f.original_filename.toLowerCase().endsWith('.pdf') ? (
      <button key={f.id} data-testid={`dfm-file-${f.id}`}
        onClick={() => onOpenPdf({ fileId: f.id, filename: f.original_filename, kind: 'pdf', revisionName: topic.title, sourceLabel: sourceLabel(e), inlineUrl: dfmFileUrl(partId, f.id, 'inline') })}
        className="font-mono text-xs text-blue-300 hover:underline text-left break-all">{f.original_filename}</button>
    ) : (
      <a key={f.id} data-testid={`dfm-file-${f.id}`} href={dfmFileUrl(partId, f.id, 'download')}
        className="font-mono text-xs text-blue-300 hover:underline break-all">{f.original_filename}</a>
    );

  const route = (e: Omit<DfmEntry, 'history'>) => (
    <span className="text-slate-400">
      <span className={`font-semibold ${PARTY_STYLE[e.party].text}`}>{PARTY_LABELS[e.party]}</span>
      {' → '}
      {e.addressed_to.map((p, i) => (
        <Fragment key={p}>{i > 0 && ', '}<span className={PARTY_STYLE[p].text}>{PARTY_LABELS[p]}</span></Fragment>
      ))}
    </span>
  );

  const body = (e: Omit<DfmEntry, 'history'>) => (
    <>
      <div className="text-xs">
        {route(e)}
        <span className="text-slate-500" title={e.recorded_by_name ? `Recorded by ${e.recorded_by_name}` : undefined}> · {initials(e.recorded_by_name)}</span>
      </div>
      {e.note && <div className="text-slate-100 whitespace-pre-wrap mt-1 leading-snug">{e.note}</div>}
      {e.files.length > 0 && (
        <div className="flex flex-col gap-0.5 mt-1.5">
          {e.files.map((f) => <span key={f.id}>{fileLink(e, f)}</span>)}
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
    return <div data-testid={`dfm-status-${e.id}`} className={`text-xs ${compact ? 'mt-0.5' : 'mt-1.5'}`}>{answered}{waiting}</div>;
  };

  const arrows = (e: DfmEntry) => {
    const from = laneIndex(e.party);
    const waiting = new Set(open ? e.awaiting.map((w) => w.party) : []);
    const style = KIND_STYLE[e.kind];
    return e.addressed_to.map((p, i) => {
      const to = laneIndex(p);
      const g = arrowSpan(from, to);
      const dashed = waiting.has(p);
      const top = ARROW_TOP_PX + i * ARROW_GAP_PX;
      return (
        <Fragment key={p}>
          <div data-testid={`dfm-arrow-${e.id}-${p}`} data-from-lane={from} data-to-lane={to} data-kind={e.kind}
            data-dashed={String(dashed)} data-direction={g.direction}
            className={`absolute z-10 h-0 border-t-2 ${style.line} ${dashed ? 'border-dashed' : 'border-solid'}`}
            style={{ left: g.left, width: g.width, top }}>
            <span aria-hidden className={`absolute ${style.head}`}
              style={{
                top: -6, width: 0, height: 0, borderTop: '5px solid transparent', borderBottom: '5px solid transparent',
                ...(g.direction === 'right'
                  ? { right: -1, borderLeft: '8px solid currentColor' }
                  : { left: -1, borderRight: '8px solid currentColor' }),
              }} />
            <span data-testid="dfm-kind-label"
              className={`absolute left-1/2 -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded bg-slate-900 px-1 text-[10px] leading-[14px] font-medium ${style.text}`}
              style={{ top: -1 }}>
              {KIND_LABELS[e.kind]}
            </span>
          </div>
          <span data-testid={`dfm-marker-${e.id}-${p}`} aria-hidden
            className={`absolute z-10 h-2 w-2 -translate-x-1/2 rounded-full ring-2 ring-slate-900 ${PARTY_STYLE[p].marker}`}
            style={{ left: `${g.markerPct}%`, top: top - 3 }} />
        </Fragment>
      );
    });
  };

  const actionsFor = (e: DfmEntry) => (open ? cardActions(e, entries) : []);
  const actionButton = (e: DfmEntry, a: ReturnType<typeof cardActions>[number], inMenu = false) => (
    <button key={a.key} data-testid={`dfm-action-${e.id}-${a.key}`} data-action={a.key} onClick={() => openStep(a.step)}
      className={inMenu
        ? 'block w-full text-left text-xs px-3 py-1.5 text-slate-100 hover:bg-slate-700'
        : `text-xs px-2 py-0.5 rounded ${a.key === 'update' ? 'text-slate-400 hover:text-slate-200' : 'bg-slate-700 hover:bg-slate-600 text-slate-100'}`}>
      {a.label}
    </button>
  );

  const card = (e: DfmEntry) => {
    const style = KIND_STYLE[e.kind];
    const target = e.reply_to_id != null ? byId.get(ids.get(e.reply_to_id) ?? -1) : undefined;
    const lit = highlighted === e.id;
    const acts = actionsFor(e);
    const badge = (
      <span data-testid="dfm-kind-badge" className={`text-[11px] font-medium px-1.5 py-px rounded ring-1 ring-inset ${style.badge}`}>
        {KIND_LABELS[e.kind]}
      </span>
    );
    return (
      <div ref={(el) => { if (el) cardRefs.current.set(e.id, el); else cardRefs.current.delete(e.id); }}
        data-testid={`dfm-entry-${e.id}`} data-party={e.party} data-lane={cardLane(e)} data-kind={e.kind}
        data-highlighted={String(lit)} data-compact={String(compact)}
        style={{ width: cardWidth }}
        className={`relative z-20 mx-auto rounded-md bg-slate-800 ring-1 ring-slate-700 shadow-md shadow-black/20 text-sm transition-shadow ${compact ? 'px-2 py-1.5' : 'p-2.5'} ${lit ? 'ring-2 ring-yellow-300' : ''}`}>
        {compact ? (
          <>
            <div className="flex items-center gap-1.5 text-xs">
              {badge}
              <span className="min-w-0 truncate">{route(e)}</span>
              <span className="ml-auto tabular-nums text-slate-400">{shortDate(e.sent_at ?? e.recorded_at)}</span>
              {acts.length > 0 && (
                <span className="relative">
                  <button data-testid={`dfm-menu-${e.id}`} aria-label="Actions" aria-expanded={menuFor === e.id}
                    onClick={() => setMenuFor((cur) => (cur === e.id ? null : e.id))}
                    className="px-1 rounded text-slate-400 hover:text-white hover:bg-slate-700 leading-none">⋯</button>
                  {menuFor === e.id && (
                    <div className="absolute right-0 top-full mt-1 z-30 min-w-[10rem] rounded-md bg-slate-800 ring-1 ring-slate-600 shadow-lg py-1">
                      {acts.map((a) => actionButton(e, a, true))}
                    </div>
                  )}
                </span>
              )}
            </div>
            {statusLines(e)}
          </>
        ) : (
          <>
            <div className="flex items-center gap-2 mb-1">
              {badge}
              <span className="text-xs text-slate-500 tabular-nums">#{e.id}</span>
              {e.history.length > 0 && <span className="text-xs text-amber-300">(updated)</span>}
              {target && (
                <button data-testid={`dfm-reply-link-${e.id}`} onClick={() => jumpTo(target.id)}
                  className="ml-auto text-xs text-slate-400 hover:text-slate-200 underline decoration-dotted underline-offset-2">
                  reply to #{target.id} {KIND_LABELS[target.kind]}
                </button>
              )}
            </div>
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
            {acts.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2 pt-2 border-t border-slate-700/70">
                {acts.map((a) => actionButton(e, a))}
              </div>
            )}
          </>
        )}
      </div>
    );
  };

  let strip: string;
  let stripTone = 'text-slate-300';
  if (!open) strip = 'Finished confirmed, read only';
  else if (entries.length === 0) strip = 'No messages yet. Record the first DFM with + New DFM.';
  else if (topic.next_step) strip = nextStepText(topic.next_step);
  else if (topic.all_answered) { strip = 'All answered'; stripTone = 'text-emerald-300 font-medium'; }
  else strip = 'Nothing waiting';

  const grid = { display: 'grid', gridTemplateColumns: `${DATE_COL_PX}px 1fr` } as const;

  return (
    <div data-testid="dfm-flow" className={fill ? 'flex flex-col min-h-0 flex-1' : ''}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 mb-2">
        <nav data-testid="dfm-breadcrumb" aria-label="Breadcrumb" className="flex items-baseline gap-1.5 min-w-0">
          <button data-testid="dfm-breadcrumb-archive" onClick={onBack}
            className="text-sm text-slate-400 hover:text-slate-100 hover:underline underline-offset-2">DFM archive</button>
          <span aria-hidden className="text-slate-600">/</span>
          <h2 className="text-lg font-semibold text-slate-100 truncate">{topic.title}</h2>
        </nav>
        <span data-testid="dfm-topic-status"
          className={`text-xs px-2 py-0.5 rounded-full ring-1 ring-inset ${open ? 'bg-emerald-500/15 text-emerald-200 ring-emerald-400/40' : 'bg-slate-700 text-slate-200 ring-slate-500'}`}>
          {open ? 'Open' : 'Finished confirmed'}
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div role="group" aria-label="Zoom" className="flex items-center rounded-md bg-slate-900 ring-1 ring-slate-700 overflow-hidden">
            <button data-testid="dfm-zoom-out" aria-label="Zoom out" onClick={() => zoomBy(-1)} disabled={zoom <= ZOOM_MIN} className={iconBtn}>−</button>
            <span data-testid="dfm-zoom-level" className="w-12 text-center text-xs tabular-nums text-slate-200">{zoom}%</span>
            <button data-testid="dfm-zoom-in" aria-label="Zoom in" onClick={() => zoomBy(1)} disabled={zoom >= ZOOM_MAX} className={iconBtn}>+</button>
            <button data-testid="dfm-zoom-fit" onClick={() => setZoom(fitZoom(viewportWidth, MIN_CANVAS_PX))}
              className={`${iconBtn} text-xs border-l border-slate-700`}>Fit</button>
          </div>
          {open && (
            <button data-testid="dfm-new-original" onClick={() => openStep(newOriginalStep())}
              className="px-3 py-1 rounded-md bg-blue-600 hover:bg-blue-500 text-white text-sm">+ New DFM</button>
          )}
          {open ? (
            <button data-testid="dfm-finish" onClick={() => finish.mutate()} disabled={finish.isPending}
              className="px-3 py-1 rounded-md bg-emerald-700 hover:bg-emerald-600 disabled:bg-slate-600 text-white text-sm">Finish confirmed</button>
          ) : (
            <button data-testid="dfm-reopen" onClick={() => reopen.mutate()} disabled={reopen.isPending}
              className="px-3 py-1 rounded-md bg-slate-700 hover:bg-slate-600 text-slate-100 text-sm">Reopen</button>
          )}
          {onPopOut && (
            <button data-testid="dfm-popout" onClick={onPopOut} title="Open the DFM archive in its own window"
              className="px-3 py-1 rounded-md bg-slate-700 hover:bg-slate-600 text-slate-100 text-sm">Open in window</button>
          )}
        </div>
      </div>

      <div data-testid="dfm-status-strip"
        className="flex flex-wrap items-center gap-x-3 gap-y-1 mb-2 px-3 py-1.5 rounded-md bg-slate-900/60 ring-1 ring-slate-700/70 text-xs">
        {waitingOn.map((w) => (
          <span key={w.party} data-testid={`dfm-waiting-${w.party}`}
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 ring-1 ring-inset ${PARTY_STYLE[w.party].pill}`}>
            <span className="font-medium">{PARTY_LABELS[w.party]}</span>
            <span className="font-semibold tabular-nums">{w.count}</span>
            <span className="opacity-80"> · {formatDays(w.oldest_days)}</span>
          </span>
        ))}
        <span className={stripTone}>{strip}</span>
        <span data-testid="dfm-legend" className="ml-auto flex items-center gap-2.5 text-[11px] text-slate-500">
          {KINDS.map((k) => (
            <span key={k} className="flex items-center gap-1">
              <span aria-hidden className={`inline-block w-3 h-0.5 rounded ${KIND_STYLE[k].swatch}`} />{KIND_LABELS[k]}
            </span>
          ))}
        </span>
      </div>

      {form?.step.anchorId === null && <div className="mb-2">{formEl}</div>}

      <div ref={setViewport} data-testid="dfm-flow-viewport"
        className={`overflow-auto rounded-md ring-1 ring-slate-700 bg-slate-900 ${fill ? 'flex-1 min-h-0' : 'max-h-[75vh]'}`}>
        <div data-testid="dfm-flow-body" data-zoom={zoom} style={{ zoom: zoom / 100, width: canvasWidth }}>
          <div data-testid="dfm-lane-headers" className="sticky top-0 z-40 bg-slate-900" style={grid}>
            <div className="border-b border-slate-700 border-r border-r-slate-800" />
            <div className="grid grid-cols-3">
              {PARTIES.map((p) => (
                <div key={p} data-testid={`dfm-lane-${p}`} data-waiting={waitingCount(p)}
                  className={`flex items-center justify-center gap-2 py-2 border-b-2 ${PARTY_STYLE[p].header} ${PARTY_STYLE[p].tint}`}>
                  <span className={`text-sm font-semibold ${PARTY_STYLE[p].text}`}>{PARTY_LABELS[p]}</span>
                  {waitingCount(p) > 0 && (
                    <span className={`text-[11px] px-1.5 rounded-full ring-1 ring-inset ${PARTY_STYLE[p].pill}`}>{waitingCount(p)} waiting</span>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className="relative pb-4">
            <div aria-hidden className="absolute inset-y-0 border-r border-slate-800" style={{ left: 0, width: DATE_COL_PX }} />
            <div aria-hidden className="absolute inset-y-0 right-0 grid grid-cols-3" style={{ left: DATE_COL_PX }}>
              {PARTIES.map((p) => <div key={p} className={PARTY_STYLE[p].tint} />)}
            </div>
            <div aria-hidden className="absolute inset-y-0 right-0" style={{ left: DATE_COL_PX }}>
              {PARTIES.map((p, i) => (
                <div key={p} className="absolute inset-y-0 border-l border-dashed border-slate-700"
                  style={{ left: `${laneCenterPct(i)}%` }} />
              ))}
            </div>

            {flowRows(entries).map((r) => {
              if (r.type === 'day') {
                const d = dayLabel(r.date);
                return (
                  <div key={`day-${r.date}`} data-testid={`dfm-day-${r.date}`} className="relative h-4 mt-2" style={grid}>
                    {/* The label hangs into the next row, beside the first card of the day. */}
                    <div className="absolute left-2 top-1 z-10 leading-tight">
                      <div className="text-xs font-semibold text-slate-200 tabular-nums whitespace-nowrap">{d.day} {d.month}</div>
                      <div className="text-[10px] text-slate-500 tabular-nums">{d.year}</div>
                    </div>
                    <div />
                    <div className="self-center border-t border-slate-700/80" />
                  </div>
                );
              }
              const e = r.entry;
              return (
                <Fragment key={e.id}>
                  <div data-testid={`dfm-row-${e.id}`} className="relative pt-1 pb-3" style={grid}>
                    <div />
                    <div className="relative">
                      {arrows(e)}
                      <div className="grid grid-cols-3">
                        <div style={{ gridColumnStart: cardLane(e) + 1 }}>{card(e)}</div>
                      </div>
                    </div>
                  </div>
                  {form?.step.anchorId === e.id && (
                    <div className="relative pb-3" style={grid}>
                      <div />
                      <div className="relative z-30 flex justify-center">
                        {/* Counter-zoom so the form stays readable at any zoom level. */}
                        <div style={{ zoom: 100 / zoom, width: formWidth }}>{formEl}</div>
                      </div>
                    </div>
                  )}
                </Fragment>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
