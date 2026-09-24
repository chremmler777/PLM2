/**
 * FieldNoteMarker - a dot coloured by the field's flag and a speech bubble
 * count of its comments, next to any value. Click opens the thread popover.
 * The same (part, field) key is used in the worksheet and on the article,
 * tool and paint pages, so a flag set in one place shows in the other.
 */
import { useLayoutEffect, useRef, useState } from 'react';
import type { FieldNoteSummary } from '../../api/fieldNotes';
import { FLAG_DOT, FLAG_LABELS, popoverPosition } from '../../lib/fieldNotes';
import FieldNotePopover from './FieldNotePopover';

export interface FieldNoteMarkerProps {
  partId: number;
  fieldKey: string;
  label: string;
  note?: FieldNoteSummary;
  /** The part's project: the popover then shows the field's history from the worksheet audit log. */
  projectId?: number | null;
  /** Controlled open state (the worksheet's "Comment" menu item); omit for self-managed. */
  open?: boolean;
  onOpenChange?(open: boolean): void;
  /** Hidden until hover or focus while the field has no comment and no flag (worksheet cells). */
  quietWhenEmpty?: boolean;
}

export default function FieldNoteMarker({
  partId, fieldKey, label, note, projectId = null, open, onOpenChange, quietWhenEmpty = false,
}: FieldNoteMarkerProps) {
  const button = useRef<HTMLButtonElement>(null);
  const [ownOpen, setOwnOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  const isOpen = open ?? ownOpen;
  const setOpen = (next: boolean) => {
    if (open === undefined) setOwnOpen(next);
    onOpenChange?.(next);
  };

  useLayoutEffect(() => {
    if (!isOpen || !button.current) return;
    setPosition(popoverPosition(button.current.getBoundingClientRect(), { width: window.innerWidth, height: window.innerHeight }));
  }, [isOpen]);

  const flag = note?.flag_status ?? null;
  const count = note?.comment_count ?? 0;
  const empty = !flag && count === 0;
  const title = [flag ? FLAG_LABELS[flag] : null, count ? `${count} comment${count === 1 ? '' : 's'}` : null]
    .filter(Boolean).join(', ') || 'Comment or flag';

  return (
    <>
      <button
        ref={button}
        type="button"
        data-note-marker=""
        data-testid={`note-marker-${fieldKey}`}
        aria-label={`Comments and flag: ${label}`}
        aria-expanded={isOpen}
        title={title}
        onClick={(e) => { e.stopPropagation(); setOpen(!isOpen); }}
        className={`inline-flex items-center gap-0.5 align-middle ml-1 text-[10px] leading-none text-slate-400 hover:text-slate-100 ${
          quietWhenEmpty && empty && !isOpen ? 'opacity-0 group-hover:opacity-100 focus:opacity-100' : ''
        }`}
      >
        <span data-testid={`note-dot-${fieldKey}`} className={`inline-block w-2 h-2 rounded-full ${flag ? FLAG_DOT[flag] : 'border border-slate-500'}`} />
        {count > 0 && (
          <span data-testid={`note-count-${fieldKey}`} className="inline-flex items-center gap-px">
            <svg aria-hidden="true" viewBox="0 0 16 16" className="w-3 h-3" fill="currentColor"><path d="M2 3h12v8H6l-3 3v-3H2z" /></svg>
            {count}
          </span>
        )}
      </button>
      {isOpen && position && (
        <FieldNotePopover partId={partId} fieldKey={fieldKey} label={label} projectId={projectId} position={position}
          onClose={() => setOpen(false)} />
      )}
    </>
  );
}
