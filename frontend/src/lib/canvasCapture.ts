/**
 * Reads the three.js canvas into a small image. The frame is rendered right
 * before it is copied (same task), so the WebGL buffer is valid without
 * preserveDrawingBuffer. The grid and the axes helper are hidden for the
 * shot so the picture shows only the part.
 */
import type { Camera, Object3D, Scene, WebGLRenderer } from 'three';

/** Objects with this name are left out of snapshots (the viewer grid). */
export const SNAPSHOT_HIDDEN_NAME = 'snapshot-hidden';
export const THUMBNAIL_MAX_SIDE = 400;
export const THUMBNAIL_MAX_BYTES = 2 * 1024 * 1024;

/** Scale (w, h) down so the long side is at most max; never scales up. */
export function fitWithin(width: number, height: number, max: number): { width: number; height: number } {
  const long = Math.max(width, height);
  if (long <= max || long === 0) return { width, height };
  const k = max / long;
  return { width: Math.max(1, Math.round(width * k)), height: Math.max(1, Math.round(height * k)) };
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
  const size = fitWithin(src.width, src.height, max);
  const out = document.createElement('canvas');
  out.width = size.width;
  out.height = size.height;
  try {
    gl.render(scene, camera);
    const ctx = out.getContext('2d');
    if (!ctx) return null;
    ctx.drawImage(src, 0, 0, size.width, size.height);
  } finally {
    hidden.forEach((o) => { o.visible = true; });
  }
  return encodeThumbnail(out);
}
