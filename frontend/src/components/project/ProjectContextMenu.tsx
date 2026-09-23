/** Right-click menu on an item row. */
import { useEffect, useRef } from 'react';
import type { ContextMenuState } from './projectTypes';

export default function ProjectContextMenu({
  menu,
  onClose,
  onOpenDetails,
  onViewChangelog,
}: {
  menu: ContextMenuState | null;
  onClose: () => void;
  onOpenDetails: (partId: number) => void;
  onViewChangelog: (partId: number) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menu) return;

    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        onClose();
      }
    }

    function handleEscape(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }

    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [menu, onClose]);

  if (!menu) return null;

  return (
    <div
      ref={containerRef}
      className="fixed z-50 bg-slate-700 border border-slate-600 rounded-lg shadow-lg min-w-max"
      style={{ top: `${menu.y}px`, left: `${menu.x}px` }}
    >
      <button
        onClick={() => {
          onOpenDetails(menu.partId);
          onClose();
        }}
        className="w-full text-left px-4 py-2 text-sm text-slate-200 hover:bg-slate-600"
      >
        Revisions & Lifecycle
      </button>
      <button
        onClick={() => {
          onViewChangelog(menu.partId);
          onClose();
        }}
        className="w-full text-left px-4 py-2 text-sm text-slate-200 hover:bg-slate-600"
      >
        View Changelog
      </button>
    </div>
  );
}
