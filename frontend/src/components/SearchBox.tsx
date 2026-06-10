/**
 * SearchBox - Global part/project search with debounced dropdown results.
 */
import { useEffect, useRef, useState } from 'react';
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
    navigate(path);
  };

  const hasResults = (data?.parts.length ?? 0) > 0 || (data?.projects.length ?? 0) > 0;

  return (
    <div ref={containerRef} className="relative">
      <input
        type="text"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        placeholder="🔍 Search parts..."
        className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-slate-100 text-sm placeholder-slate-400"
      />

      {open && debounced.length >= 2 && (
        <div className="absolute z-50 mt-1 w-72 bg-slate-700 border border-slate-600 rounded-lg shadow-xl max-h-80 overflow-y-auto">
          {isFetching && !data ? (
            <p className="px-3 py-2 text-slate-400 text-xs">Searching...</p>
          ) : !hasResults ? (
            <p className="px-3 py-2 text-slate-400 text-xs">No results for “{debounced}”</p>
          ) : (
            <>
              {data!.projects.map((p) => (
                <button
                  key={`proj-${p.id}`}
                  onClick={() => go(`/projects/${p.id}`)}
                  className="w-full text-left px-3 py-2 hover:bg-slate-600 border-b border-slate-600/50"
                >
                  <span className="text-xs px-1.5 py-0.5 rounded bg-blue-900/50 text-blue-300 mr-2">project</span>
                  <span className="text-slate-100 text-sm">{p.name}</span>
                  <span className="text-slate-400 text-xs ml-2 font-mono">{p.code}</span>
                </button>
              ))}
              {data!.parts.map((part) => (
                <button
                  key={`part-${part.id}`}
                  onClick={() => go(`/projects/${part.project_id}?part=${part.id}`)}
                  className="w-full text-left px-3 py-2 hover:bg-slate-600 border-b border-slate-600/50 last:border-b-0"
                >
                  <p className="text-slate-100 text-sm">
                    {part.name}
                    <span className="text-slate-400 text-xs ml-2 font-mono">{part.part_number}</span>
                  </p>
                  <p className="text-slate-500 text-xs">
                    {part.project_name} · {part.item_category !== 'article' ? `${part.item_category.replace(/_/g, ' ')} · ` : ''}
                    {part.part_type.replace(/_/g, ' ')}
                  </p>
                </button>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
