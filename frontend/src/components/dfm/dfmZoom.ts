/**
 * Zoom for the DFM flow canvas: 50% to 150% in steps of 10, Fit to the
 * container width, compact cards below 75%. The level is remembered per
 * browser through safeStorage, so blocked storage only loses the memory.
 */
import { useCallback, useState } from 'react';
import { readStoredNumber, writeStored } from '../../lib/safeStorage';

export const ZOOM_MIN = 50;
export const ZOOM_MAX = 150;
export const ZOOM_STEP = 10;
export const COMPACT_BELOW = 75;
export const ZOOM_KEY = 'plm2.dfm.zoom';

export const clampZoom = (z: number) => Math.round(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z)));

/** One step in or out, snapping an off-grid level (from Fit) onto the grid. */
export function stepZoom(z: number, dir: 1 | -1): number {
  const snapped = dir > 0 ? Math.floor(z / ZOOM_STEP) * ZOOM_STEP : Math.ceil(z / ZOOM_STEP) * ZOOM_STEP;
  return clampZoom(snapped + dir * ZOOM_STEP);
}

/** The level at which a canvas of canvasWidth fills containerWidth. */
export const fitZoom = (containerWidth: number, canvasWidth: number) =>
  clampZoom(Math.floor((containerWidth / canvasWidth) * 100));

export const isCompact = (z: number) => z < COMPACT_BELOW;

export function useDfmZoom() {
  const [zoom, setRaw] = useState(() => readStoredNumber(ZOOM_KEY, 100, ZOOM_MIN, ZOOM_MAX));
  const setZoom = useCallback((z: number) => {
    const next = clampZoom(z);
    setRaw(next);
    writeStored(ZOOM_KEY, String(next));
  }, []);
  const zoomBy = useCallback((dir: 1 | -1) => {
    setRaw((cur) => {
      const next = stepZoom(cur, dir);
      writeStored(ZOOM_KEY, String(next));
      return next;
    });
  }, []);
  return { zoom, setZoom, zoomBy };
}
