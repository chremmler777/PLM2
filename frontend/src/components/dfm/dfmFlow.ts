/**
 * DFM flow helpers: lane geometry for the sequence view, the actions valid on
 * a message card (answer, ask again, forward, update) as prefilled steps for
 * the guided form, and the plain-word lines for status strip and topic list.
 * The rules mirror docs/superpowers/specs/2026-09-23-dfm-flow-api.md.
 */
import {
  KIND_LABELS, PARTIES, PARTY_LABELS,
  type DfmEntry, type DfmKind, type DfmLastStep, type DfmNextStep, type DfmParty, type DfmTopicSummary,
} from '../../api/dfm';

export function initials(name: string | null | undefined): string {
  const parts = (name ?? '').trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  return parts.map((p) => p[0].toUpperCase()).join('');
}

export function shortDate(iso: string | null | undefined): string {
  return iso ? iso.slice(5, 10) : '';
}

export function formatDays(days: number): string {
  if (days <= 0) return 'today';
  return days === 1 ? '1 day' : `${days} days`;
}

export const partyList = (ps: DfmParty[]) => ps.map((p) => PARTY_LABELS[p]).join(', ');

/** Tailwind classes per kind: badge, arrow line colour, arrowhead colour, legend swatch, label text. */
export const KIND_STYLE: Record<DfmKind, { badge: string; line: string; head: string; swatch: string; text: string }> = {
  original: { badge: 'bg-blue-500/15 text-blue-200 ring-blue-400/40', line: 'border-blue-400', head: 'text-blue-400', swatch: 'bg-blue-400', text: 'text-blue-300' },
  forward: { badge: 'bg-violet-500/15 text-violet-200 ring-violet-400/40', line: 'border-violet-400', head: 'text-violet-400', swatch: 'bg-violet-400', text: 'text-violet-300' },
  answer: { badge: 'bg-emerald-500/15 text-emerald-200 ring-emerald-400/40', line: 'border-emerald-400', head: 'text-emerald-400', swatch: 'bg-emerald-400', text: 'text-emerald-300' },
  question: { badge: 'bg-amber-500/15 text-amber-200 ring-amber-400/40', line: 'border-amber-400', head: 'text-amber-400', swatch: 'bg-amber-400', text: 'text-amber-300' },
};

/**
 * Tailwind classes per party, used for every party mention: sender names,
 * lane headers, lane tint, receiver markers and waiting pills.
 */
export const PARTY_STYLE: Record<DfmParty, { text: string; tint: string; header: string; marker: string; pill: string }> = {
  toolmaker: { text: 'text-sky-300', tint: 'bg-sky-400/[0.04]', header: 'border-sky-400/60', marker: 'bg-sky-300', pill: 'bg-sky-500/15 text-sky-200 ring-sky-400/40' },
  ktx: { text: 'text-fuchsia-300', tint: 'bg-fuchsia-400/[0.04]', header: 'border-fuchsia-400/60', marker: 'bg-fuchsia-300', pill: 'bg-fuchsia-500/15 text-fuchsia-200 ring-fuchsia-400/40' },
  tier1: { text: 'text-amber-300', tint: 'bg-amber-400/[0.04]', header: 'border-amber-400/60', marker: 'bg-amber-300', pill: 'bg-amber-500/15 text-amber-200 ring-amber-400/40' },
};

/** "Answer #8 · KTX to Toolmaker", for the document pane title bar. */
export function sourceLabel(e: { id: number; kind: DfmKind; party: DfmParty; addressed_to: DfmParty[] }): string {
  return `${KIND_LABELS[e.kind]} #${e.id} · ${PARTY_LABELS[e.party]} to ${partyList(e.addressed_to)}`;
}

export const laneIndex = (p: DfmParty) => PARTIES.indexOf(p);
export const laneCenterPct = (lane: number) => ((lane * 2 + 1) / (PARTIES.length * 2)) * 100;
/** A card sits centred on its sender's lane line. */
export const cardLane = (e: { party: DfmParty }) => laneIndex(e.party);

/** Card width cap and the gap between an arrowhead and the receiver marker, in px. */
export const CARD_MAX_PX = 300;
export const MARKER_GAP_PX = 6;
/** Side margin that keeps a card inside its lane when the lane is narrower than the cap. */
export const CARD_MARGIN_PX = 12;

const pct = (n: number) => `${Number(n.toFixed(4))}%`;
/** Half the card width in CSS: the cap, or the lane half minus the margin on narrow canvases. */
const cardHalf = `min(${CARD_MAX_PX / 2}px, ${pct(50 / PARTIES.length)} - ${CARD_MARGIN_PX}px)`;

/**
 * Horizontal span of an arrow inside the lanes area, as CSS lengths (percent
 * of the lanes area plus px), so no layout measurement is needed. The arrow
 * leaves the card edge that faces the receiver and stops just short of the
 * marker dot on the receiver's lane line (markerPct).
 */
export function arrowSpan(fromLane: number, toLane: number) {
  const a = laneCenterPct(fromLane);
  const b = laneCenterPct(toLane);
  const direction = (toLane > fromLane ? 'right' : 'left') as 'right' | 'left';
  const width = `calc(${pct(Math.abs(a - b))} - ${cardHalf} - ${MARKER_GAP_PX}px)`;
  const left = direction === 'right' ? `calc(${pct(a)} + ${cardHalf})` : `calc(${pct(b)} + ${MARKER_GAP_PX}px)`;
  return { direction, left, width, markerPct: b };
}

/** The day a message belongs to on the timeline: mail date, else the recording date. */
export const entryDay = (e: { sent_at: string | null; recorded_at: string }) => (e.sent_at ?? e.recorded_at).slice(0, 10);

export type FlowRow = { type: 'day'; date: string } | { type: 'entry'; entry: DfmEntry };

/** Timeline rows: a day divider whenever the date changes, then the messages of that day. */
export function flowRows(entries: DfmEntry[]): FlowRow[] {
  const rows: FlowRow[] = [];
  let last: string | null = null;
  for (const e of entries) {
    const d = entryDay(e);
    if (d !== last) { rows.push({ type: 'day', date: d }); last = d; }
    rows.push({ type: 'entry', entry: e });
  }
  return rows;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "2026-09-13" as { day: '13', month: 'Sep', year: '2026' }, no locale involved. */
export function dayLabel(iso: string) {
  const [y, m, d] = iso.slice(0, 10).split('-');
  return { day: String(Number(d)), month: MONTHS[Number(m) - 1] ?? m, year: y };
}

/** Every id (current or earlier version) mapped to the id of the current message. */
export function currentIds(entries: DfmEntry[]): Map<number, number> {
  const m = new Map<number, number>();
  for (const e of entries) {
    m.set(e.id, e.id);
    for (const h of e.history) m.set(h.id, e.id);
  }
  return m;
}

export const others = (p: DfmParty) => PARTIES.filter((x) => x !== p);

/** One step for the guided form, prefilled from a card action or "+ New DFM". */
export interface DfmStep {
  kind: DfmKind;
  from: DfmParty;
  fromEditable: boolean;
  to: DfmParty[];
  lockedTo: DfmParty[];
  /** Parties that may be addressed; the sender's two others when null. */
  allowedTo: DfmParty[] | null;
  replyTo: { id: number; kind: DfmKind } | null;
  supersedes: { id: number; kind: DfmKind } | null;
  /** The card the form opens under; null for a new original. */
  anchorId: number | null;
}

export interface DfmAction {
  key: string;
  label: string;
  step: DfmStep;
}

export function newOriginalStep(): DfmStep {
  return { kind: 'original', from: 'toolmaker', fromEditable: true, to: ['ktx'], lockedTo: [], allowedTo: null, replyTo: null, supersedes: null, anchorId: null };
}

/** The actions valid on a current message, in display order. */
export function cardActions(e: DfmEntry, entries: DfmEntry[]): DfmAction[] {
  const ids = currentIds(entries);
  const byId = new Map(entries.map((x) => [x.id, x]));
  const reply = { id: e.id, kind: e.kind };
  const base = { fromEditable: false, supersedes: null, anchorId: e.id, replyTo: reply };
  const acts: DfmAction[] = [];
  const many = e.addressed_to.length > 1;

  if (e.kind === 'answer') {
    for (const p of e.addressed_to) {
      acts.push({ key: `ask-${p}`, label: many ? `Ask again as ${PARTY_LABELS[p]}` : 'Ask again',
        step: { ...base, kind: 'question', from: p, to: [e.party], lockedTo: [e.party], allowedTo: others(p) } });
    }
  } else {
    const answered = new Set(e.answered_by.map((a) => a.party));
    for (const p of e.addressed_to.filter((x) => !answered.has(x))) {
      acts.push({ key: `answer-${p}`, label: many ? `Answer as ${PARTY_LABELS[p]}` : 'Answer',
        step: { ...base, kind: 'answer', from: p, to: [e.party], lockedTo: [e.party], allowedTo: others(p) } });
    }
  }

  if (e.party !== 'ktx' && e.addressed_to.includes('ktx')) {
    const forwarded = new Set(entries
      .filter((x) => x.kind === 'forward' && x.reply_to_id != null && ids.get(x.reply_to_id) === e.id)
      .flatMap((x) => x.addressed_to));
    const targets = PARTIES.filter((p) => p !== e.party && !e.addressed_to.includes(p) && !forwarded.has(p));
    for (const t of targets) {
      acts.push({ key: `forward-${t}`, label: `Forward to ${PARTY_LABELS[t]}`,
        step: { ...base, kind: 'forward', from: 'ktx', to: [t], lockedTo: [], allowedTo: targets } });
    }
  }

  const target = e.reply_to_id != null ? byId.get(ids.get(e.reply_to_id) ?? -1) : undefined;
  const primary = target?.party ?? e.addressed_to[0];
  const locked = e.kind === 'answer' || e.kind === 'question' ? [primary] : e.kind === 'forward' ? e.addressed_to : [];
  acts.push({ key: 'update', label: 'Update',
    step: { kind: e.kind, from: e.party, fromEditable: false, to: e.addressed_to, lockedTo: locked,
      allowedTo: e.kind === 'forward' ? e.addressed_to : null,
      replyTo: target ? { id: target.id, kind: target.kind } : null,
      supersedes: { id: e.id, kind: e.kind }, anchorId: e.id } });
  return acts;
}

const ref = (r: { id: number; kind: DfmKind }) => `${KIND_LABELS[r.kind]} #${r.id}`;

export function stepSentence(step: DfmStep, from: DfmParty, to: DfmParty[]): string {
  const route = `from ${PARTY_LABELS[from]} to ${to.length ? partyList(to) : '(pick a party)'}`;
  if (step.supersedes) return `Update of ${ref(step.supersedes)} ${route}`;
  const head = `${KIND_LABELS[step.kind]} ${route}`;
  if (!step.replyTo) return head;
  return `${head} ${step.kind === 'forward' ? 'of' : 'on'} ${ref(step.replyTo)}`;
}

export function nextStepText(n: DfmNextStep): string {
  const since = n.days <= 0 ? 'since today' : `for ${formatDays(n.days)}`;
  return `Waiting on ${PARTY_LABELS[n.to]} ${since}: ${ref({ id: n.entry_id, kind: n.kind })} from ${PARTY_LABELS[n.from]}`;
}

export function waitingSummary(t: DfmTopicSummary): string | null {
  if (t.status !== 'open') return null;
  const waiting = t.waiting_on ?? [];
  if (waiting.length) {
    return waiting.map((w) => `waiting on ${PARTY_LABELS[w.party]}${w.count > 1 ? ` (${w.count})` : ''} · ${w.oldest_days} d`).join(', ');
  }
  return t.all_answered ? 'all answered' : null;
}

export function lastStepText(l: DfmLastStep): string {
  return `${KIND_LABELS[l.kind]} ${PARTY_LABELS[l.party]} → ${partyList(l.addressed_to)} ${shortDate(l.date)}`;
}
