/**
 * The DFM archive of a tool (/parts/:id/dfm) or the general tooling DFM of a
 * project (/projects/:id/dfm) in its own browser window. One window name per
 * scope, so a second click reuses (and focuses) the same window.
 */
import { toast } from 'sonner';
import type { DfmScope } from '../../api/dfm';

export const dfmWindowUrl = (scope: DfmScope, topicId: number | null) =>
  `${import.meta.env.BASE_URL}${scope.kind === 'tool' ? 'parts' : 'projects'}/${scope.id}/dfm${topicId !== null ? `?topic=${topicId}` : ''}`;

export const dfmWindowName = (scope: DfmScope) =>
  scope.kind === 'tool' ? `plm2-dfm-${scope.id}` : `plm2-dfm-project-${scope.id}`;

export function openDfmWindow(scope: DfmScope, topicId: number | null): boolean {
  const win = window.open(dfmWindowUrl(scope, topicId), dfmWindowName(scope), 'popup,width=1500,height=950');
  if (!win) {
    toast.error('The browser blocked the new window');
    return false;
  }
  win.focus?.();
  return true;
}
