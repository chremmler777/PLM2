/**
 * Version navigator: an explorer-style side panel for the Documents tab.
 * Customer versions (E2 · 005, E1 · 003) as folders, our iterations (E1.1)
 * nested, files as leaves. Each version says where it stands (state chip,
 * first line of its summary, date) and which file types it holds, still takes
 * from an older version (drawing not updated) or lacks.
 */
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
  Box, Check, ChevronDown, ChevronRight, FileBox, FileImage, FileText, Folder, FolderOpen,
  GitBranch, History, PanelLeftClose, PanelLeftOpen, Plus, X,
} from 'lucide-react';
import { revisionLabel } from './RevisionBadge';
import { formatDate } from '../../lib/format';
import { buildVersionTree, fileSlot, shortName, SLOTS, type Slot, type SlotState, type Tone, type TreeFile, type TreeRevision, type VersionNode } from './versionTree';

export interface NavFile extends TreeFile { has_viewer: boolean; mime_type: string }

interface Props {
  revisions: (TreeRevision & { intake_pending?: boolean })[];
  files: NavFile[];
  activeId: number | null;
  selectedRevisionId: number | null;
  viewingFileId: number | null;
  onSelectRevision(id: number): void;
  onFile(file: NavFile): void;
  onNewIteration?(majorId: number): void;
}

const STORE_KEY = 'plm2.versionNav.collapsed';
const NARROW_PX = 560;

const TONE: Record<Tone, string> = {
  active: 'bg-emerald-900/50 text-emerald-300',
  waiting: 'bg-amber-900/50 text-amber-200',
  open: 'bg-sky-900/50 text-sky-300',
  done: 'bg-violet-900/50 text-violet-300',
  dead: 'bg-slate-800 text-slate-400',
  neutral: 'bg-slate-700 text-slate-300',
};

function readStored(): boolean | null {
  try {
    const v = window.localStorage.getItem(STORE_KEY);
    return v === null ? null : v === '1';
  } catch { return null; }
}
function store(collapsed: boolean) {
  try { window.localStorage.setItem(STORE_KEY, collapsed ? '1' : '0'); } catch { /* private mode */ }
}

const nameOf = (r: TreeRevision) => revisionLabel(r.revision_name, r.customer_index);

function slotText(slot: Slot, s: SlotState<NavFile, TreeRevision>): string {
  const what = SLOTS.find((x) => x.slot === slot)!.what;
  switch (s.kind) {
    case 'here': return `${what}: ${s.files.map((f) => f.filename).join(', ')}`;
    case 'stale': return `${what} not updated: still ${s.file.filename} from ${nameOf(s.from)}`;
    case 'inherited': return `${what} from ${nameOf(s.from)}: ${s.file.filename}`;
    case 'missing': return `no ${what} in any version`;
  }
}

function SlotChip({ slot, state }: { slot: Slot; state: SlotState<NavFile, TreeRevision> }) {
  const label = SLOTS.find((x) => x.slot === slot)!.label;
  const look = {
    here: { cls: 'text-emerald-300', Icon: Check },
    stale: { cls: 'text-amber-300 bg-amber-900/40', Icon: History },
    inherited: { cls: 'text-slate-400', Icon: History },
    missing: { cls: 'text-red-300 bg-red-900/40', Icon: X },
  }[state.kind];
  const from = state.kind === 'stale' || state.kind === 'inherited' ? ` ${state.from.revision_name}` : '';
  return (
    <span data-testid={`slot-${slot}`} data-kind={state.kind} title={slotText(slot, state)}
      className={`inline-flex items-center gap-0.5 rounded px-1 py-px text-[10px] font-medium tabular-nums ${look.cls}`}>
      {label}<look.Icon aria-hidden className="h-3 w-3" strokeWidth={2.5} />{from}
    </span>
  );
}

function fileIcon(f: NavFile) {
  const slot = fileSlot(f);
  if (slot === 'native') return Box;
  if (slot === 'step') return FileBox;
  if (f.file_type === 'picture') return FileImage;
  return FileText;
}

function FileLeaf({ file, viewing, onFile, depth }: { file: NavFile; viewing: boolean; onFile(f: NavFile): void; depth: number }) {
  const Icon = fileIcon(file);
  return (
    <li role="treeitem" aria-selected={viewing}>
      <button type="button" data-testid={`nav-file-${file.id}`} onClick={() => onFile(file)} title={file.filename}
        style={{ paddingLeft: `${depth * 14 + 22}px` }}
        className={`flex w-full items-center gap-1.5 rounded py-0.5 pr-2 text-left text-xs transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500 ${viewing ? 'bg-blue-900/40 text-white' : 'text-slate-300 hover:bg-slate-700/60'}`}>
        <Icon aria-hidden className="h-3.5 w-3.5 flex-shrink-0 text-slate-400" />
        <span className="truncate font-mono text-[11px]">{shortName(file.filename)}</span>
      </button>
    </li>
  );
}

function VersionRow({ node, depth, expanded, selected, onToggle, onSelect, onNewIteration }: {
  node: VersionNode<NavFile, TreeRevision>; depth: number; expanded: boolean; selected: boolean;
  onToggle(): void; onSelect(): void; onNewIteration?: () => void;
}) {
  const { rev, state } = node;
  const dead = state.tone === 'dead';
  const Chevron = expanded ? ChevronDown : ChevronRight;
  const Icon = node.minor ? GitBranch : expanded ? FolderOpen : Folder;
  const comment = rev.summary?.split('\n')[0];
  const date = (rev.customer_received_at ?? rev.created_at).slice(0, 10);
  const hasBody = node.files.length > 0 || node.children.length > 0;
  return (
    <div className={`group rounded ${selected ? 'bg-slate-700' : 'hover:bg-slate-700/40'} ${dead && !selected ? 'opacity-60' : ''}`}
      style={{ paddingLeft: `${depth * 14}px` }}>
      <div className="flex items-start gap-1 py-1 pr-1.5">
        <button type="button" onClick={onToggle} aria-label={expanded ? 'Collapse' : 'Expand'} disabled={!hasBody}
          className="mt-0.5 rounded p-0.5 text-slate-400 hover:text-white disabled:invisible focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500">
          <Chevron aria-hidden className="h-3.5 w-3.5" />
        </button>
        <button type="button" onClick={onSelect} data-testid={`nav-rev-${rev.id}`} aria-current={selected || undefined}
          className="min-w-0 flex-1 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500 rounded">
          <span className="flex items-center gap-1.5">
            <Icon aria-hidden className={`h-3.5 w-3.5 flex-shrink-0 ${node.minor ? 'text-sky-400' : 'text-amber-300/80'}`} />
            <span className={`text-sm font-semibold ${selected ? 'text-white' : 'text-slate-100'} ${dead ? 'line-through decoration-slate-500' : ''}`}>
              {nameOf(rev)}
            </span>
            <span data-testid={`nav-state-${rev.id}`} className={`ml-auto whitespace-nowrap rounded-full px-1.5 py-px text-[10px] font-medium ${TONE[state.tone]}`}>
              {state.label}
            </span>
          </span>
          {comment && (
            <span className="mt-0.5 block truncate text-[11px] leading-snug text-slate-400" title={rev.summary ?? undefined}>{comment}</span>
          )}
          <span className="mt-1 flex items-center gap-1">
            {dead ? null : expanded || node.issue === null
              ? SLOTS.map(({ slot }) => <SlotChip key={slot} slot={slot} state={node.slots[slot]} />)
              : <SlotChip slot={node.issue.slot} state={node.slots[node.issue.slot]} />}
            <span className="ml-auto text-[10px] tabular-nums text-slate-500">{formatDate(date)}</span>
          </span>
        </button>
        {onNewIteration && selected && (
          <button type="button" onClick={onNewIteration} title={`New iteration on ${nameOf(rev)}`} aria-label={`New iteration on ${nameOf(rev)}`}
            data-testid={`nav-new-iteration-${rev.id}`}
            className="mt-0.5 rounded p-0.5 text-slate-400 hover:bg-slate-600 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500">
            <Plus aria-hidden className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </div>
  );
}

export default function VersionNav({ revisions, files, activeId, selectedRevisionId, viewingFileId, onSelectRevision, onFile, onNewIteration }: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [collapsed, setCollapsed] = useState<boolean>(() => readStored() ?? false);
  // No stored choice: start folded when the column is narrow.
  useLayoutEffect(() => {
    if (readStored() !== null) return;
    const w = rootRef.current?.parentElement?.clientWidth ?? 0;
    if (w > 0 && w < NARROW_PX) setCollapsed(true);
  }, []);
  const toggleCollapsed = () => setCollapsed((c) => { store(!c); return !c; });

  const pending = useMemo(
    () => new Map(revisions.filter((r) => r.intake_pending).map((r) => [r.id, 'waiting for triage'] as const)),
    [revisions]);
  const tree = useMemo(() => buildVersionTree(revisions, files, { activeId, pending }), [revisions, files, activeId, pending]);

  // Open by default: the selected branch, the active version and anything waiting.
  const defaultOpen = useMemo(() => {
    const open = new Set<number>();
    for (const n of tree) {
      const holdsSelected = n.rev.id === selectedRevisionId || n.children.some((c) => c.rev.id === selectedRevisionId);
      if (holdsSelected || n.rev.id === activeId || n.state.tone === 'waiting') open.add(n.rev.id);
      for (const c of n.children) if (c.rev.id === selectedRevisionId) open.add(c.rev.id);
    }
    return open;
  }, [tree, selectedRevisionId, activeId]);
  const [toggled, setToggled] = useState<Map<number, boolean>>(new Map());
  useEffect(() => setToggled(new Map()), [revisions]);
  const isOpen = (id: number) => toggled.get(id) ?? defaultOpen.has(id);
  const toggle = (id: number) => setToggled((m) => new Map(m).set(id, !isOpen(id)));

  const issues = tree.filter((n) => n.issue).length;

  if (collapsed) {
    return (
      <div ref={rootRef} data-testid="version-nav" data-collapsed="true"
        className="flex w-9 flex-shrink-0 flex-col items-center gap-2 border-r border-slate-700 bg-slate-900/40 py-2">
        <button type="button" onClick={toggleCollapsed} aria-label="Show versions" title="Show versions"
          className="rounded p-1 text-slate-300 hover:bg-slate-700 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500">
          <PanelLeftOpen aria-hidden className="h-4 w-4" />
        </button>
        <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 [writing-mode:vertical-rl]">Versions</span>
        {issues > 0 && (
          <span title={`${issues} version${issues > 1 ? 's' : ''} with missing or outdated files`}
            className="rounded-full bg-amber-900/60 px-1.5 text-[10px] font-semibold tabular-nums text-amber-200">{issues}</span>
        )}
      </div>
    );
  }

  return (
    <div ref={rootRef} data-testid="version-nav" data-collapsed="false"
      className="flex w-72 flex-shrink-0 flex-col border-r border-slate-700 bg-slate-900/40">
      <div className="flex items-center justify-between px-2 py-1.5">
        <h4 className="text-xs font-semibold text-slate-300">Versions</h4>
        <button type="button" onClick={toggleCollapsed} aria-label="Hide versions" title="Hide versions"
          className="rounded p-1 text-slate-400 hover:bg-slate-700 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500">
          <PanelLeftClose aria-hidden className="h-4 w-4" />
        </button>
      </div>
      <ul role="tree" aria-label="Versions" className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-1 pb-2">
        {tree.map((n) => (
          <li key={n.rev.id} role="treeitem" aria-expanded={isOpen(n.rev.id)}>
            <VersionRow node={n} depth={0} expanded={isOpen(n.rev.id)} selected={n.rev.id === selectedRevisionId}
              onToggle={() => toggle(n.rev.id)} onSelect={() => onSelectRevision(n.rev.id)}
              onNewIteration={onNewIteration ? () => onNewIteration(n.rev.id) : undefined} />
            {isOpen(n.rev.id) && (
              <ul role="group">
                {n.files.map((f) => (
                  <FileLeaf key={f.id} file={f} depth={0} viewing={f.id === viewingFileId}
                    onFile={(file) => { onSelectRevision(n.rev.id); onFile(file); }} />
                ))}
                {n.children.map((c) => (
                  <li key={c.rev.id} role="treeitem" aria-expanded={isOpen(c.rev.id)}>
                    <VersionRow node={c} depth={1} expanded={isOpen(c.rev.id)} selected={c.rev.id === selectedRevisionId}
                      onToggle={() => toggle(c.rev.id)} onSelect={() => onSelectRevision(c.rev.id)} />
                    {isOpen(c.rev.id) && (
                      <ul role="group">
                        {c.files.map((f) => (
                          <FileLeaf key={f.id} file={f} depth={1} viewing={f.id === viewingFileId}
                            onFile={(file) => { onSelectRevision(c.rev.id); onFile(file); }} />
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
