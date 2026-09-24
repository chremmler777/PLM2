/**
 * The DFM archive of a tool in its own browser window. One window name per
 * tool, so a second click reuses (and focuses) the same window.
 */
import { toast } from 'sonner';

export const dfmWindowUrl = (partId: number, topicId: number | null) =>
  `${import.meta.env.BASE_URL}parts/${partId}/dfm${topicId !== null ? `?topic=${topicId}` : ''}`;

export function openDfmWindow(partId: number, topicId: number | null): boolean {
  const win = window.open(dfmWindowUrl(partId, topicId), `plm2-dfm-${partId}`, 'popup,width=1500,height=950');
  if (!win) {
    toast.error('The browser blocked the new window');
    return false;
  }
  win.focus?.();
  return true;
}
