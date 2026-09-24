/**
 * ?focus=<field_key> on a part page: scroll to the element carrying
 * data-field-key, ring it for a moment and focus its first control. The
 * worksheet's "Edit" navigates here. Sections load at different times (paint,
 * tool relations), so the lookup retries for up to two seconds.
 */
import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { FIELD_KEY_RE } from '../lib/fieldNotes';

export const FOCUS_PARAM = 'focus';
export const FOCUS_HIGHLIGHT = ['ring-2', 'ring-amber-400', 'ring-offset-2', 'ring-offset-slate-900', 'rounded'];
export const FOCUS_HIGHLIGHT_MS = 2500;
const RETRY_MS = 100;
const RETRIES = 20;

export function focusField(fieldKey: string, doc: Document = document): boolean {
  if (!FIELD_KEY_RE.test(fieldKey)) return false;
  const el = doc.querySelector<HTMLElement>(`[data-field-key="${fieldKey}"]`);
  if (!el) return false;
  el.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
  el.classList.add(...FOCUS_HIGHLIGHT);
  window.setTimeout(() => el.classList.remove(...FOCUS_HIGHLIGHT), FOCUS_HIGHLIGHT_MS);
  const control = el.matches('input, select, textarea, button:not([data-note-marker])')
    ? el
    : el.querySelector<HTMLElement>('input, select, textarea, button:not([data-note-marker])');
  control?.focus();
  return true;
}

export function useFieldFocus(ready: boolean): void {
  const [params] = useSearchParams();
  const key = params.get(FOCUS_PARAM);
  useEffect(() => {
    if (!ready || !key) return;
    let tries = 0;
    let timer = 0;
    const tick = () => {
      if (focusField(key) || ++tries >= RETRIES) return;
      timer = window.setTimeout(tick, RETRY_MS);
    };
    tick();
    return () => window.clearTimeout(timer);
  }, [ready, key]);
}
