/**
 * Thumbnail from the 3D view. Once the viewer reports a rendered model
 * (capture is non-null), a part without a thumbnail gets one automatically,
 * at most once per part per session and silently on failure. "Set as
 * thumbnail" replaces it with the current angle.
 */
import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { apiErrorMessage } from '../../lib/apiError';
import { claimAutoCapture, invalidateThumbnailQueries, uploadThumbnail, type CaptureFn } from '../../lib/thumbnail';

export default function ThumbnailSnapshot({ partId, hasThumbnail, capture, auto }: {
  partId: number;
  hasThumbnail: boolean;
  /** Null until the viewer has loaded and rendered the model. */
  capture: CaptureFn | null;
  /** False when the view is not this part's own geometry (mirror source). */
  auto: boolean;
}) {
  const queryClient = useQueryClient();
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!capture || !auto || hasThumbnail) return;
    if (!claimAutoCapture(partId)) return;
    (async () => {
      try {
        const blob = await capture();
        if (!blob) {
          console.warn('Thumbnail snapshot: nothing captured for part', partId);
          return;
        }
        await uploadThumbnail(partId, blob);
        invalidateThumbnailQueries(queryClient, partId);
      } catch (e) {
        console.warn('Thumbnail snapshot failed for part', partId, e);
      }
    })();
  }, [capture, auto, hasThumbnail, partId, queryClient]);

  if (!capture) return null;

  const setAsThumbnail = async () => {
    setSaving(true);
    try {
      const blob = await capture();
      if (!blob) throw new Error('capture');
      await uploadThumbnail(partId, blob);
      invalidateThumbnailQueries(queryClient, partId);
      toast.success('Thumbnail updated');
    } catch (e) {
      toast.error(apiErrorMessage(e, 'Could not set the thumbnail'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <button
      type="button"
      data-testid="set-thumbnail"
      onClick={setAsThumbnail}
      disabled={saving}
      title="Use the current 3D view as the part's picture"
      className="absolute bottom-2 right-2 z-10 px-2 py-1 rounded bg-slate-700/85 hover:bg-slate-600 text-slate-200 text-xs font-medium disabled:opacity-60"
    >
      {saving ? 'Saving...' : 'Set as thumbnail'}
    </button>
  );
}
