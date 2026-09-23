/**
 * Two panes side by side with a draggable splitter. The left width is
 * remembered per browser; minimum widths keep both panes usable. Arrow keys
 * on the focused splitter move it too.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { readStoredNumber, writeStored } from '../../lib/safeStorage';

const MAX_LEFT = 1600;
const KEY_STEP = 16;

interface SplitPaneProps {
  storageKey: string;
  left: ReactNode;
  right: ReactNode;
  /** Hide the right pane and the splitter; the left pane takes the full width. */
  rightHidden?: boolean;
  defaultLeft?: number;
  minLeft?: number;
  minRight?: number;
}

export default function SplitPane({
  storageKey, left, right, rightHidden = false, defaultLeft = 420, minLeft = 280, minRight = 420,
}: SplitPaneProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(() => readStoredNumber(storageKey, defaultLeft, minLeft, MAX_LEFT));
  const drag = useRef<{ startX: number; startWidth: number } | null>(null);

  const clamp = useCallback((w: number) => {
    const total = containerRef.current?.getBoundingClientRect().width ?? 0;
    // A container that has not been laid out (or jsdom) reports 0: only the fixed bounds apply then.
    const max = total > 0 ? Math.max(minLeft, total - minRight) : MAX_LEFT;
    return Math.round(Math.min(max, Math.max(minLeft, w)));
  }, [minLeft, minRight]);

  const commit = useCallback((w: number) => {
    const next = clamp(w);
    setWidth(next);
    writeStored(storageKey, String(next));
  }, [clamp, storageKey]);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!drag.current) return;
      setWidth(clamp(drag.current.startWidth + e.clientX - drag.current.startX));
    };
    const onUp = (e: MouseEvent) => {
      if (!drag.current) return;
      const { startWidth, startX } = drag.current;
      drag.current = null;
      document.body.style.userSelect = '';
      commit(startWidth + e.clientX - startX);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [clamp, commit]);

  return (
    <div ref={containerRef} className="h-full min-h-0 flex" data-testid="split-pane">
      <div
        className={`h-full min-h-0 min-w-0 ${rightHidden ? 'flex-1' : 'flex-shrink-0'}`}
        style={rightHidden ? undefined : { width, minWidth: minLeft, maxWidth: `calc(100% - ${minRight}px)` }}
      >
        {left}
      </div>
      {!rightHidden && (
        <>
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize items list"
            aria-valuenow={width}
            aria-valuemin={minLeft}
            tabIndex={0}
            onMouseDown={(e) => {
              e.preventDefault();
              drag.current = { startX: e.clientX, startWidth: width };
              document.body.style.userSelect = 'none';
            }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                e.preventDefault();
                commit(width + (e.key === 'ArrowRight' ? KEY_STEP : -KEY_STEP));
              }
            }}
            className="w-1.5 flex-shrink-0 cursor-col-resize bg-slate-800 hover:bg-sky-600/60 focus:bg-sky-600/60 focus:outline-none"
          />
          <div className="flex-1 min-w-0 h-full min-h-0">{right}</div>
        </>
      )}
    </div>
  );
}
