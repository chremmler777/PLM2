/**
 * Version tree rules: customer versions (E2, E1, 1 …) with our iterations
 * (E1.1) nested, the state of each in plain words, and which file types each
 * version holds, still takes from an older version, or lacks entirely
 * ("new data, old drawing").
 */
import { groupByMajor } from './revisionGrouping';

export type Slot = 'native' | 'step' | 'drawing';
export const SLOTS: { slot: Slot; label: string; what: string }[] = [
  { slot: 'native', label: '3D', what: 'native CAD' },
  { slot: 'step', label: 'STEP', what: 'STEP (3D preview)' },
  { slot: 'drawing', label: '2D', what: 'drawing' },
];

export interface TreeRevision {
  id: number;
  revision_name: string;
  phase: 'review' | 'official';
  status: string;
  customer_index?: string | null;
  parent_revision_id?: number | null;
  summary?: string | null;
  customer_received_at?: string | null;
  created_at: string;
}

export interface TreeFile {
  id: number;
  revision_id: number;
  filename: string;
  file_type: string;
  cad_format: string | null;
}

/** here: the version holds it. stale: a customer version without it, an
 *  older version's file still applies. inherited: an iteration without it
 *  uses its parent's (normal, iterations hold only what changed). missing:
 *  no version holds one. */
export type SlotState<F extends TreeFile = TreeFile, R extends TreeRevision = TreeRevision> =
  | { kind: 'here'; files: F[] }
  | { kind: 'stale' | 'inherited'; from: R; file: F }
  | { kind: 'missing' };

export type Tone = 'active' | 'waiting' | 'open' | 'done' | 'dead' | 'neutral';
export interface VersionState { label: string; tone: Tone }

export interface VersionNode<F extends TreeFile = TreeFile, R extends TreeRevision = TreeRevision> {
  rev: R;
  minor: boolean;
  state: VersionState;
  files: F[];
  slots: Record<Slot, SlotState<F, R>>;
  /** Worst gap, for the collapsed row; null when complete. */
  issue: { slot: Slot; kind: 'stale' | 'missing' } | null;
  children: VersionNode<F, R>[];
}

const NATIVE = new Set(['catia', 'jt']);
const DEAD = new Set(['rejected', 'cancelled']);

export function fileSlot(f: Pick<TreeFile, 'file_type' | 'cad_format'>): Slot | null {
  if (f.file_type === 'drawing') return 'drawing';
  if (f.file_type !== 'cad') return null;
  if (f.cad_format === 'step') return 'step';
  return f.cad_format && NATIVE.has(f.cad_format) ? 'native' : null;
}

export function versionState(
  rev: Pick<TreeRevision, 'id' | 'status' | 'parent_revision_id'>,
  opts: { activeId: number | null; pending?: Map<number, string>; olderThanActive?: boolean },
): VersionState {
  const minor = rev.parent_revision_id != null;
  if (rev.status === 'rejected') return { label: 'rejected', tone: 'dead' };
  if (rev.status === 'cancelled') return { label: 'closed', tone: 'dead' };
  const pending = opts.pending?.get(rev.id);
  if (pending) return { label: pending, tone: 'waiting' };
  if (minor) {
    if (rev.status === 'approved') return { label: 'adopted by customer', tone: 'done' };
    if (rev.status === 'archived') return { label: 'superseded', tone: 'dead' };
    return { label: 'open iteration', tone: 'open' };
  }
  if (rev.id === opts.activeId) return { label: 'active', tone: 'active' };
  if (rev.status === 'frozen') return { label: 'frozen', tone: 'neutral' };
  if (rev.status === 'archived' || opts.olderThanActive) return { label: 'superseded', tone: 'dead' };
  return { label: rev.status.replace(/_/g, ' '), tone: 'neutral' };
}

function holdings<F extends TreeFile>(files: F[]): Record<Slot, F[]> {
  const out: Record<Slot, F[]> = { native: [], step: [], drawing: [] };
  for (const f of files) {
    const s = fileSlot(f);
    if (s) out[s].push(f);
  }
  return out;
}

function worst<F extends TreeFile, R extends TreeRevision>(slots: Record<Slot, SlotState<F, R>>): VersionNode['issue'] {
  for (const kind of ['missing', 'stale'] as const) {
    for (const { slot } of SLOTS) if (slots[slot].kind === kind) return { slot, kind };
  }
  return null;
}

export function buildVersionTree<F extends TreeFile, R extends TreeRevision>(
  revisions: R[],
  files: F[],
  opts: { activeId: number | null; pending?: Map<number, string> },
): VersionNode<F, R>[] {
  const filesOf = (id: number) => files.filter((f) => f.revision_id === id);
  const groups = groupByMajor(revisions);
  const activeAt = groups.findIndex((g) => g.major.id === opts.activeId);
  const held = new Map(groups.map((g) => [g.major.id, holdings(filesOf(g.major.id))] as const));

  return groups.map(({ major, minors }, i) => {
    // Older customer versions come after this one in groupByMajor's order.
    const older = groups.slice(i + 1).map((g) => g.major).filter((r) => !DEAD.has(r.status));
    const own = held.get(major.id)!;
    const slots = {} as Record<Slot, SlotState<F, R>>;
    for (const { slot } of SLOTS) {
      if (own[slot].length) { slots[slot] = { kind: 'here', files: own[slot] }; continue; }
      const src = older.find((r) => held.get(r.id)![slot].length);
      slots[slot] = src ? { kind: 'stale', from: src, file: held.get(src.id)![slot][0] } : { kind: 'missing' };
    }
    const children = minors.map((m) => {
      const mine = holdings(filesOf(m.id));
      const ms = {} as Record<Slot, SlotState<F, R>>;
      for (const { slot } of SLOTS) {
        const p = slots[slot];
        if (mine[slot].length) ms[slot] = { kind: 'here', files: mine[slot] };
        else if (p.kind === 'here') ms[slot] = { kind: 'inherited', from: major, file: p.files[0] };
        else if (p.kind === 'missing') ms[slot] = p;
        else ms[slot] = { kind: 'inherited', from: p.from, file: p.file };
      }
      return {
        rev: m, minor: true, state: versionState(m, opts), files: filesOf(m.id), slots: ms,
        issue: worst(ms), children: [],
      };
    });
    return {
      rev: major, minor: false,
      state: versionState(major, { ...opts, olderThanActive: activeAt >= 0 && i > activeAt }),
      files: filesOf(major.id), slots, issue: worst(slots), children,
    };
  });
}

/** Brose names share a long prefix (206_883_607____PCA_TM__003_____…): the
 *  part number is the same for every file of the part, so drop it, squeeze
 *  underscore runs and cut in the middle so type, index and extension stay. */
export function shortName(name: string, max = 32): string {
  const n = name.replace(/^\d{3}[._]\d{3}[._]\d{3}[._-]+/, '').replace(/_{2,}/g, '_') || name;
  if (n.length <= max) return n;
  const tail = Math.ceil((max - 1) * 0.5);
  return `${n.slice(0, max - 1 - tail)}…${n.slice(-tail)}`;
}
