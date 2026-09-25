/**
 * SearchBox - Global part/project search with debounced dropdown results.
 * ARIA combobox: the input keeps focus, ArrowUp/Down move the highlighted
 * option (aria-activedescendant), Enter opens it, Escape closes the list.
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { Search } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import client from '../api/client';

interface SearchResults {
  parts: {
    id: number;
    part_number: string;
    name: string;
    part_type: string;
    item_category: string;
    project_id: number;
    project_name: string;
  }[];
  projects: { id: number; name: string; code: string }[];
}

export default function SearchBox() {
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  const [open, setOpen] = useState(false);
  // Index into the flattened options (projects, then parts); -1 means none.
  const [active, setActive] = useState(-1);
  const inputId = useId();
  const listId = useId();

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(t);
  }, [query]);

  const { data, isFetching } = useQuery<SearchResults>({
    queryKey: ['search', debounced],
    queryFn: async () => (await client.get(`/v1/search?q=${encodeURIComponent(debounced)}`)).data,
    enabled: debounced.length >= 2,
  });

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const go = (path: string) => {
    setOpen(false);
    setQuery('');
    setActive(-1);
    navigate(path);
  };

  const showPanel = open && debounced.length >= 2;
  const options: { key: string; path: string }[] = [
    ...(data?.projects ?? []).map((p) => ({ key: `proj-${p.id}`, path: `/projects/${p.id}` })),
    ...(data?.parts ?? []).map((part) => ({ key: `part-${part.id}`, path: `/projects/${part.project_id}?part=${part.id}` })),
  ];
  const hasResults = options.length > 0;
  const listVisible = showPanel && hasResults;
  const optionId = (i: number) => `${listId}-opt-${i}`;
  const activeValid = listVisible && active >= 0 && active < options.length;

  // A new result set starts without a highlighted option.
  useEffect(() => { setActive(-1); }, [data, debounced]);

  // Keep the highlighted option in view.
  useEffect(() => {
    if (!activeValid) return;
    document.getElementById(optionId(active))?.scrollIntoView?.({ block: 'nearest' });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, activeValid]);

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    // An IME is composing: Enter/Escape/arrows belong to the candidate window.
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!showPanel) { if (debounced.length >= 2) { e.preventDefault(); setOpen(true); } return; }
      if (!hasResults) return;
      e.preventDefault();
      const n = options.length;
      setActive((i) => (e.key === 'ArrowDown' ? (i + 1) % n : i <= 0 ? n - 1 : i - 1));
    } else if (e.key === 'Enter') {
      if (activeValid) { e.preventDefault(); go(options[active].path); }
    } else if (e.key === 'Escape') {
      if (showPanel) { e.preventDefault(); setOpen(false); setActive(-1); }
      else if (query) { e.preventDefault(); setQuery(''); }
    }
  };

  const status = isFetching && !data
    ? 'Searching…'
    : !hasResults
      ? `No parts or projects match “${debounced}”`
      : `${options.length} result${options.length === 1 ? '' : 's'}`;

  const optionClass = (i: number, extra = '') =>
    `w-full cursor-pointer text-left px-3 py-2 hover:bg-slate-700 border-b border-slate-700 ${i === active ? 'bg-slate-700' : ''} ${extra}`;

  let i = -1;
  return (
    <div ref={containerRef} className="relative">
      <label htmlFor={inputId} className="sr-only">Search parts and projects</label>
      <Search aria-hidden="true" size={15} strokeWidth={2}
        className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
      <input
        id={inputId}
        type="search"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={listVisible}
        aria-controls={listVisible ? listId : undefined}
        aria-activedescendant={activeValid ? optionId(active) : undefined}
        autoComplete="off"
        spellCheck={false}
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => { setOpen(false); setActive(-1); }}
        onKeyDown={onKeyDown}
        placeholder="Search parts and projects…"
        className="w-full bg-slate-900/60 border border-slate-700 rounded-md pl-8 pr-3 py-1.5 text-slate-100 text-sm placeholder-slate-400 hover:border-slate-600"
      />

      {/* Result count / searching / no match, announced without moving focus. */}
      <p role="status" className="sr-only">{showPanel ? status : ''}</p>

      {showPanel && (
        <div onMouseDown={(e) => e.preventDefault()} className="absolute z-50 mt-1 w-72 bg-slate-800 border border-slate-600 rounded-lg shadow-lift max-h-80 overflow-y-auto overscroll-contain">
          {!hasResults ? (
            <p aria-hidden="true" className="px-3 py-2 text-slate-400 text-xs">{status}</p>
          ) : (
            <div id={listId} role="listbox" aria-label="Search results">
              {data!.projects.map((p) => {
                const idx = ++i;
                return (
                  <div
                    role="option"
                    id={optionId(idx)}
                    aria-selected={idx === active}
                    key={`proj-${p.id}`}
                    // Keep focus in the input; the click still navigates.
                    onMouseEnter={() => setActive(idx)}
                    onClick={() => go(`/projects/${p.id}`)}
                    className={optionClass(idx)}
                  >
                    <span className="text-[11px] px-1.5 py-0.5 rounded bg-sky-900/50 text-sky-300 mr-2">Project</span>
                    <span className="text-slate-100 text-sm">{p.name}</span>
                    <span className="text-slate-400 text-xs ml-2 font-mono">{p.code}</span>
                  </div>
                );
              })}
              {data!.parts.map((part) => {
                const idx = ++i;
                return (
                  <div
                    role="option"
                    id={optionId(idx)}
                    aria-selected={idx === active}
                    key={`part-${part.id}`}
                    onMouseEnter={() => setActive(idx)}
                    onClick={() => go(`/projects/${part.project_id}?part=${part.id}`)}
                    className={optionClass(idx, 'last:border-b-0')}
                  >
                    <p className="text-slate-100 text-sm">
                      {part.name}
                      <span className="text-slate-400 text-xs ml-2 font-mono">{part.part_number}</span>
                    </p>
                    <p className="text-slate-500 text-xs">
                      {part.project_name} · {part.item_category !== 'article' ? `${part.item_category.replace(/_/g, ' ')} · ` : ''}
                      {part.part_type.replace(/_/g, ' ')}
                    </p>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
