/**
 * BOM workspace of one gauge, assembly station or EOAT, opened on its own from the
 * equipment card. Left: the project's articles and tools, searchable. Right: what the
 * equipment takes in (with an amount) or checks, and the tools it serves. A row is
 * dragged across or added with its button; "Add all shown" takes a filtered set in one
 * go, for stations with many parts. The card owns the data and the mutations; this
 * only shows them large enough to work in.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Plus, Search, X } from 'lucide-react';
import { shortName } from '../../lib/partDisplay';
import type { Part } from './projectTypes';

export interface EquipmentRelation {
  id: number;
  relation_type: string;
  direction: 'outgoing' | 'incoming';
  other_part_id: number;
  other_part_number: string;
  other_part_name: string;
  other_item_category: string;
  other_customer_part_number?: string | null;
  quantity?: number | null;
}

interface RowsProps {
  articles: EquipmentRelation[];
  isGauge: boolean;
  editable: boolean;
  busy?: boolean;
  /** Opens the article; left out where leaving the screen would lose the place. */
  onOpenPart?(partId: number): void;
  onQuantity(rel: EquipmentRelation, raw: string, reset: () => void): void;
  onRemove(relationId: number): void;
}

/** The parts of an equipment BOM: customer number first, amount (not for gauges), remove. */
export function BomRows({ articles, isGauge, editable, busy = false, onOpenPart, onQuantity, onRemove }: RowsProps) {
  return (
    <ul className="divide-y divide-slate-700 rounded border border-slate-700">
      {articles.map((a) => {
        const text = (
          <>
            <span className="font-mono text-slate-100">{a.other_customer_part_number || a.other_part_number}</span>
            <span className="text-slate-200"> {shortName(a.other_part_name, null, a.other_customer_part_number)}</span>
            {a.other_customer_part_number && (
              <span className="block font-mono text-xs text-slate-400">{a.other_part_number}</span>
            )}
          </>
        );
        return (
          <li key={a.id} className="flex items-center gap-3 px-3 py-2 text-sm">
            {onOpenPart ? (
              <button type="button" onClick={() => onOpenPart(a.other_part_id)} className="flex-1 min-w-0 text-left hover:text-sky-300">
                {text}
              </button>
            ) : (
              <div className="flex-1 min-w-0">{text}</div>
            )}
            {!isGauge && (
              <label className="flex flex-shrink-0 items-center gap-1.5 text-xs text-slate-400">
                Amount
                <input
                  key={`${a.id}-${a.quantity}`}
                  type="number" min="0.001" step="any"
                  aria-label={`Amount of ${a.other_part_number}`}
                  defaultValue={a.quantity ?? ''}
                  disabled={!editable}
                  onFocus={(e) => e.currentTarget.select()}
                  onBlur={(e) => { const el = e.currentTarget; onQuantity(a, el.value, () => { el.value = String(a.quantity ?? ''); }); }}
                  onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); }}
                  className="w-20 bg-slate-700 border border-slate-600 rounded px-2 py-1 text-right text-slate-100 text-sm tabular-nums focus:border-sky-400 focus:outline-none disabled:opacity-60"
                />
              </label>
            )}
            {editable && (
              <button type="button" aria-label={`Remove article ${a.other_part_number}`}
                onClick={() => onRemove(a.id)} disabled={busy}
                className="flex-shrink-0 rounded p-1 text-slate-400 hover:bg-slate-700 hover:text-red-300">
                <X size={14} aria-hidden="true" />
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export interface EquipmentBomProps {
  part: Part;
  parts: Part[];
  kindLabel: string;
  tools: EquipmentRelation[];
  articles: EquipmentRelation[];
  isGauge: boolean;
  busy: boolean;
  onAdd(others: Part[], relationType: 'serves' | 'article'): void;
  onRemove(relationId: number): void;
  onQuantity(rel: EquipmentRelation, raw: string, reset: () => void): void;
  onClose(): void;
}

type Source = 'article' | 'tool';

export default function EquipmentBom({
  part, parts, kindLabel, tools, articles, isGauge, busy, onAdd, onRemove, onQuantity, onClose,
}: EquipmentBomProps) {
  const [source, setSource] = useState<Source>('article');
  const [search, setSearch] = useState('');
  const [draggingId, setDraggingId] = useState<number | null>(null);
  const [over, setOver] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    searchRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const linkedIds = useMemo(
    () => new Set((source === 'tool' ? tools : articles).map((r) => r.other_part_id)),
    [source, tools, articles],
  );
  const candidates = useMemo(() => {
    const words = search.toLowerCase().split(/\s+/).filter(Boolean);
    return parts.filter((p) => {
      if (p.item_category !== source || p.obsolete_at || p.id === part.id) return false;
      const hay = `${p.customer_part_number ?? ''} ${p.part_number} ${p.name}`.toLowerCase();
      return words.every((w) => hay.includes(w));
    });
  }, [parts, source, search, part.id]);
  const open = candidates.filter((p) => !linkedIds.has(p.id));
  const total = parts.filter((p) => p.item_category === source && !p.obsolete_at && p.id !== part.id).length;

  const add = (others: Part[]) => { if (others.length) onAdd(others, source === 'tool' ? 'serves' : 'article'); };
  const dragged = draggingId === null ? undefined : parts.find((p) => p.id === draggingId);
  const acceptsDrop = !!dragged && !linkedIds.has(dragged.id);

  const articleWord = isGauge ? 'checked' : 'taken in';
  const title = `BOM of ${part.part_number}`;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title} data-testid="equipment-bom"
        onClick={(e) => e.stopPropagation()}
        className="flex h-full max-h-[900px] w-full max-w-6xl flex-col rounded-lg border border-slate-700 bg-slate-800">
        <header className="flex flex-shrink-0 items-center justify-between gap-3 border-b border-slate-700 px-5 py-3">
          <h2 className="min-w-0 truncate text-base font-semibold text-slate-100">
            BOM of <span className="font-mono">{part.part_number}</span> {part.name}
            <span className="ml-2 text-sm font-normal text-slate-400">{kindLabel}</span>
          </h2>
          <button type="button" onClick={onClose}
            className="flex-shrink-0 rounded bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-500">
            Done
          </button>
        </header>

        <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          {/* Source: what the project has */}
          <div className="flex min-h-0 flex-col border-b border-slate-700 md:border-b-0 md:border-r">
            <div className="flex-shrink-0 space-y-2 px-4 py-3">
              <div role="tablist" aria-label="What to add" className="inline-flex rounded border border-slate-600 p-0.5 text-xs font-medium">
                {(['article', 'tool'] as const).map((s) => (
                  <button key={s} type="button" role="tab" aria-selected={source === s}
                    onClick={() => { setSource(s); setSearch(''); }}
                    className={`rounded px-3 py-1 ${source === s ? 'bg-slate-600 text-slate-100' : 'text-slate-400 hover:text-slate-200'}`}>
                    {s === 'article' ? 'Articles' : 'Tools'}
                  </button>
                ))}
              </div>
              <div className="relative">
                <Search size={14} aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                <input ref={searchRef} type="search" value={search} onChange={(e) => setSearch(e.target.value)}
                  aria-label={source === 'article' ? 'Search articles' : 'Search tools'}
                  placeholder="Number or name"
                  className="w-full rounded border border-slate-600 bg-slate-700 py-1.5 pl-8 pr-3 text-sm text-slate-100 placeholder:text-slate-400 focus:border-sky-400 focus:outline-none" />
              </div>
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span>{candidates.length} of {total} {source === 'article' ? 'articles' : 'tools'}</span>
                {open.length > 1 && (
                  <button type="button" onClick={() => add(open)} disabled={busy}
                    className="rounded px-2 py-0.5 font-medium text-sky-300 hover:bg-slate-700 disabled:text-slate-500">
                    Add all {open.length} shown
                  </button>
                )}
              </div>
            </div>
            <ul data-testid="bom-source" className="min-h-0 flex-1 overflow-y-auto border-t border-slate-700">
              {candidates.length === 0 && (
                <li className="px-4 py-6 text-sm text-slate-400">
                  {total === 0
                    ? `This project has no ${source === 'article' ? 'articles' : 'tools'} yet. Add them in the item list first.`
                    : 'Nothing matches the search.'}
                </li>
              )}
              {candidates.map((p) => {
                const linked = linkedIds.has(p.id);
                return (
                  <li key={p.id}
                    draggable={!linked}
                    onDragStart={(e) => { e.dataTransfer.effectAllowed = 'copy'; e.dataTransfer.setData('text/plain', p.part_number); setDraggingId(p.id); }}
                    onDragEnd={() => { setDraggingId(null); setOver(false); }}
                    className={`flex items-center gap-2 border-b border-slate-700/60 px-4 py-2 text-sm ${
                      linked ? 'opacity-50' : 'cursor-grab hover:bg-slate-700/50 active:cursor-grabbing'
                    }`}>
                    <div className="min-w-0 flex-1">
                      <p className="truncate">
                        <span className="font-mono text-slate-100">{p.customer_part_number || p.part_number}</span>
                        <span className="text-slate-200"> {shortName(p.name, null, p.customer_part_number)}</span>
                      </p>
                      {p.customer_part_number && <p className="truncate font-mono text-xs text-slate-400">{p.part_number}</p>}
                    </div>
                    {linked ? (
                      <span className="flex-shrink-0 text-xs text-slate-400">in BOM</span>
                    ) : (
                      <button type="button" aria-label={`Add ${p.part_number}`} onClick={() => add([p])} disabled={busy}
                        className="flex-shrink-0 rounded border border-slate-600 p-1 text-slate-300 hover:border-sky-400 hover:text-sky-300 disabled:opacity-50">
                        <Plus size={14} aria-hidden="true" />
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>

          {/* Target: the BOM itself */}
          <div
            data-testid="bom-drop"
            onDragOver={(e) => { if (acceptsDrop) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; setOver(true); } }}
            onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(false); }}
            onDrop={(e) => { e.preventDefault(); setOver(false); if (acceptsDrop && dragged) add([dragged]); setDraggingId(null); }}
            className={`min-h-0 space-y-5 overflow-y-auto px-5 py-4 transition-colors ${
              over ? 'bg-emerald-900/25 outline outline-2 -outline-offset-4 outline-emerald-500' : dragged ? 'bg-slate-700/30' : ''
            }`}>
            <section data-testid="bom-articles">
              <h3 className="mb-2 flex items-baseline gap-2 text-sm font-semibold text-slate-100">
                Articles {articleWord}
                <span className="text-xs font-normal text-slate-400 tabular-nums">{articles.length}</span>
              </h3>
              {articles.length === 0 ? (
                <p className="rounded border border-dashed border-slate-600 px-4 py-8 text-center text-sm text-slate-400">
                  Drag articles from the left into this area, or use the + on a row.
                </p>
              ) : (
                <BomRows articles={articles} isGauge={isGauge} editable busy={busy} onQuantity={onQuantity} onRemove={onRemove} />
              )}
            </section>

            <section data-testid="bom-tools">
              <h3 className="mb-2 flex items-baseline gap-2 text-sm font-semibold text-slate-100">
                Serves tools
                <span className="text-xs font-normal text-slate-400 tabular-nums">{tools.length}</span>
              </h3>
              {tools.length === 0 ? (
                <p className="text-sm text-slate-400">
                  {isGauge ? 'No tool: assembly gauge.' : 'No tool: assembly operation.'} Switch the left list to Tools to add one.
                </p>
              ) : (
                <ul className="divide-y divide-slate-700 rounded border border-slate-700">
                  {tools.map((t) => (
                    <li key={t.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                      <div className="min-w-0 flex-1">
                        <span className="font-mono text-slate-100">{t.other_part_number}</span>
                        <span className="text-slate-200"> {t.other_part_name}</span>
                      </div>
                      <button type="button" aria-label={`Remove tool ${t.other_part_number}`}
                        onClick={() => onRemove(t.id)} disabled={busy}
                        className="flex-shrink-0 rounded p-1 text-slate-400 hover:bg-slate-700 hover:text-red-300">
                        <X size={14} aria-hidden="true" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}
