/**
 * Reads the three.js canvas into a small image. The frame is rendered right
 * before it is copied (same task), so the WebGL buffer is valid without
 * preserveDrawingBuffer. The grid and the axes helper are hidden for the
 * shot so the picture shows only the part, and the frame is cropped to a
 * square around the part so it fills the thumbnail instead of sitting small
 * in the middle of the wide viewer.
 */
import type { Camera, Object3D, Scene, WebGLRenderer } from 'three';

/** Objects with this name are left out of snapshots (the viewer grid). */
export const SNAPSHOT_HIDDEN_NAME = 'snapshot-hidden';
export const THUMBNAIL_MAX_SIDE = 400;
export const THUMBNAIL_MAX_BYTES = 2 * 1024 * 1024;

/** Channel difference from the background that counts as part, not anti-aliasing noise. */
const BACKGROUND_TOLERANCE = 12;
/** Space around the part, as a share of its long side, on each edge. */
export const THUMBNAIL_MARGIN = 0.08;

export interface Bounds { x0: number; y0: number; x1: number; y1: number }

/** Inclusive pixel box of everything that differs from the background (the
 *  top-left pixel's colour), or null when the frame shows nothing. */
export function contentBounds(data: Uint8ClampedArray, width: number, height: number,
  tolerance = BACKGROUND_TOLERANCE): Bounds | null {
  const [r, g, b] = [data[0], data[1], data[2]];
  let x0 = width, y0 = height, x1 = -1, y1 = -1;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      if (Math.abs(data[i] - r) > tolerance || Math.abs(data[i + 1] - g) > tolerance
        || Math.abs(data[i + 2] - b) > tolerance) {
        if (x < x0) x0 = x;
        if (x > x1) x1 = x;
        if (y < y0) y0 = y;
        if (y > y1) y1 = y;
      }
    }
  }
  return x1 < 0 ? null : { x0, y0, x1, y1 };
}

/** Square around the bounds with `margin` of the long side on each edge,
 *  centred on the part. It may reach past the frame; the caller fills that
 *  with the background. */
export function squareCrop(bounds: Bounds, margin = THUMBNAIL_MARGIN):
  { x: number; y: number; side: number } {
  const w = bounds.x1 - bounds.x0 + 1;
  const h = bounds.y1 - bounds.y0 + 1;
  const side = Math.round(Math.max(w, h) * (1 + 2 * margin));
  const cx = bounds.x0 + w / 2;
  const cy = bounds.y0 + h / 2;
  return { x: Math.round(cx - side / 2), y: Math.round(cy - side / 2), side };
}

function toBlob(canvas: HTMLCanvasElement, type: string, quality?: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob((b) => resolve(b), type, quality));
}

/** WEBP where the browser can encode it, else PNG; null when over the size cap. */
export async function encodeThumbnail(canvas: HTMLCanvasElement): Promise<Blob | null> {
  const webp = await toBlob(canvas, 'image/webp', 0.9);
  const blob = webp && webp.type === 'image/webp' ? webp : await toBlob(canvas, 'image/png');
  if (!blob || blob.size > THUMBNAIL_MAX_BYTES) return null;
  return blob;
}

export async function captureFrame(gl: WebGLRenderer, scene: Scene, camera: Camera, max = THUMBNAIL_MAX_SIDE): Promise<Blob | null> {
  const hidden: Object3D[] = [];
  scene.traverse((o) => {
    if (o.visible && (o.name === SNAPSHOT_HIDDEN_NAME || o.type === 'AxesHelper')) {
      o.visible = false;
      hidden.push(o);
    }
  });
  const src = gl.domElement;
  const out = document.createElement('canvas');
  try {
    gl.render(scene, camera);
    // Full-size copy first: the part's pixels are found there, then cut out.
    const full = document.createElement('canvas');
    full.width = src.width;
    full.height = src.height;
    const fctx = full.getContext('2d');
    const ctx = out.getContext('2d');
    if (!fctx || !ctx) return null;
    fctx.drawImage(src, 0, 0);
    const data = fctx.getImageData(0, 0, full.width, full.height).data;
    const bounds = contentBounds(data, full.width, full.height);
    if (!bounds) return null;
    const crop = squareCrop(bounds);
    const side = Math.min(crop.side, max);
    out.width = side;
    out.height = side;
    ctx.fillStyle = `rgb(${data[0]}, ${data[1]}, ${data[2]})`;
    ctx.fillRect(0, 0, side, side);
    ctx.drawImage(full, crop.x, crop.y, crop.side, crop.side, 0, 0, side, side);
  } finally {
    hidden.forEach((o) => { o.visible = true; });
  }
  return encodeThumbnail(out);
}
