/**
 * CAD-style orbit about an arbitrary pivot point.
 *
 * OrbitControls always rotates about its `target` and keeps that target in the
 * middle of the screen, so it cannot spin about a point the user clicked
 * without first panning that point to the centre (a visible jump). Instead the
 * camera AND the controls target are rotated together about the pivot: the
 * target stays on the camera's view axis, so OrbitControls stays consistent,
 * and the clicked point stays under the cursor while the part turns around it.
 *
 * Sign conventions match OrbitControls: `yaw` > 0 is dragging left->right,
 * `pitch` > 0 is dragging top->bottom (camera moves toward the "up" pole).
 */
import { Box3, Quaternion, Vector3 } from 'three'
import type { Mesh, Object3D } from 'three'

/**
 * Bounding box of the solid geometry (meshes) only. CAD exports often carry
 * edge / wire / sketch lines (LineSegments) that reach back to the CAD origin
 * (e.g. a backpanel at x = 2.8 m whose edge set also has lines at 0,0,0);
 * counting those puts the "part centre" halfway between the UCS and the part.
 * Falls back to everything when there are no meshes (pure wire models).
 */
export function solidBounds(root: Object3D): Box3 {
  root.updateWorldMatrix(true, true)
  const box = new Box3()
  const tmp = new Box3()
  root.traverse((o) => {
    const mesh = o as Mesh
    if (!mesh.isMesh || !mesh.geometry) return
    if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox()
    const gb = mesh.geometry.boundingBox
    if (!gb || gb.isEmpty()) return
    box.union(tmp.copy(gb).applyMatrix4(mesh.matrixWorld))
  })
  return box.isEmpty() ? new Box3().setFromObject(root) : box
}

/** Keep the camera this far (radians) away from straight up / straight down. */
const POLE_EPS = 1e-3

export interface OrbitResult {
  position: Vector3
  target: Vector3
}

/** Angle (radians) for a pointer move of `pixels`, same scale as OrbitControls (rotateSpeed 1). */
export function dragAngle(pixels: number, viewportHeight: number): number {
  return (2 * Math.PI * pixels) / Math.max(viewportHeight, 1)
}

export function orbitAboutPivot(
  position: Vector3,
  target: Vector3,
  pivot: Vector3,
  up: Vector3,
  yaw: number,
  pitch: number,
): OrbitResult {
  const upN = up.clone().normalize()
  const pos = position.clone().sub(pivot)
  const tgt = target.clone().sub(pivot)

  // Yaw: about the world up axis through the pivot (OrbitControls: theta -= yaw).
  const qYaw = new Quaternion().setFromAxisAngle(upN, -yaw)
  pos.applyQuaternion(qYaw)
  tgt.applyQuaternion(qYaw)

  // Pitch: about the camera's right axis through the pivot (OrbitControls: phi -= pitch),
  // clamped so the view never flips over the pole.
  const offset = pos.clone().sub(tgt) // camera relative to target
  const forward = offset.clone().negate()
  const right = forward.clone().cross(upN)
  if (right.lengthSq() > 1e-12 && offset.lengthSq() > 1e-12) {
    right.normalize()
    const phi = offset.angleTo(upN)
    const minPitch = phi - (Math.PI - POLE_EPS)
    const maxPitch = phi - POLE_EPS
    const p = Math.min(maxPitch, Math.max(minPitch, pitch))
    const qPitch = new Quaternion().setFromAxisAngle(right, -p)
    pos.applyQuaternion(qPitch)
    tgt.applyQuaternion(qPitch)
  }

  return { position: pos.add(pivot), target: tgt.add(pivot) }
}

export interface TrackballResult extends OrbitResult {
  up: Vector3
}

/** Rotation per pixel of drag: half a turn per viewport height (CAD feel; OrbitControls is a full turn). */
export function trackballAngle(pixels: number, viewportHeight: number): number {
  return (Math.PI * pixels) / Math.max(viewportHeight, 1)
}

/**
 * Free (trackball) rotation about a pivot, the way NX / CATIA / Cimatron turn
 * a part: the drag direction on screen decides the axis, there is no fixed
 * "up" axis and no pole, so the part turns on continuously in every direction.
 *
 * The part should follow the cursor: dragging right turns its front to the
 * right. For a screen move m (world, in the view plane) and the direction to
 * the viewer v, the part's rotation axis is v x m; the camera (position, target
 * and its up vector) turns the opposite way about the same axis through the
 * pivot. `dx` > 0 is left->right, `dy` > 0 is top->bottom (screen pixels).
 */
export function trackballAboutPivot(
  position: Vector3,
  target: Vector3,
  up: Vector3,
  pivot: Vector3,
  dx: number,
  dy: number,
  viewportHeight: number,
): TrackballResult {
  const len = Math.hypot(dx, dy)
  if (len === 0) return { position: position.clone(), target: target.clone(), up: up.clone() }
  const toViewer = position.clone().sub(target).normalize()
  const camUp = up.clone().sub(toViewer.clone().multiplyScalar(up.dot(toViewer))).normalize()
  const camRight = camUp.clone().cross(toViewer).normalize()
  const move = camRight.multiplyScalar(dx).add(camUp.clone().multiplyScalar(-dy)).normalize()
  const axis = toViewer.clone().cross(move).normalize()
  const q = new Quaternion().setFromAxisAngle(axis, -trackballAngle(len, viewportHeight))
  return {
    position: position.clone().sub(pivot).applyQuaternion(q).add(pivot),
    target: target.clone().sub(pivot).applyQuaternion(q).add(pivot),
    up: camUp.applyQuaternion(q).normalize(),
  }
}

/** Wheel delta (WheelEvent.deltaY in px) -> zoom factor. Wheel forward / scroll up (deltaY < 0)
 *  zooms in (factor < 1); one notch (100 px) moves about 15 % closer. */
export function wheelFactor(deltaPixels: number): number {
  return Math.exp(deltaPixels * 0.0016)
}

/**
 * CAD-style wheel zoom toward the point under the cursor.
 *
 * The camera moves along the cursor ray (so that point stays under the cursor)
 * by a share of its distance to the point, but never by less than a share of
 * `minDistance`: OrbitControls scales the distance to its target, so steps
 * shrink to nothing near it and the view gets stuck; here it keeps going and
 * may pass through a wall (the near plane cuts it open). The target is
 * re-placed on the view axis at the new distance of the zoom point, so pan
 * speed (which scales with the target distance) fits the zoom level.
 * `factor` < 1 zooms in, > 1 zooms out.
 */
export function zoomTowardPoint(
  position: Vector3,
  target: Vector3,
  point: Vector3,
  factor: number,
  minDistance: number,
): OrbitResult {
  const viewDir = target.clone().sub(position).normalize()
  const toPoint = point.clone().sub(position)
  const dist = toPoint.length()
  if (dist < 1e-12) return { position: position.clone(), target: target.clone() }
  const rayDir = toPoint.clone().divideScalar(dist)
  const step = Math.max(dist, minDistance) * (1 - factor) // > 0 in, < 0 out
  const move = rayDir.multiplyScalar(step)
  const newPos = position.clone().add(move)
  const along = Math.max(point.clone().sub(newPos).dot(viewDir), minDistance)
  return { position: newPos, target: newPos.clone().add(viewDir.multiplyScalar(along)) }
}

/**
 * Parallel-projection (orthographic) wheel zoom about the point under the
 * cursor: the view scale changes, the camera only slides sideways so that
 * point stays on its pixel. Nothing moves toward the part, so nothing can get
 * stuck or cut into it. Returns the new zoom and the sideways shift to add to
 * camera position and target.
 */
export function orthoZoomAbout(
  position: Vector3,
  target: Vector3,
  point: Vector3,
  zoom: number,
  factor: number,
  minZoom = 1e-4,
  maxZoom = 1e6,
): { zoom: number; shift: Vector3 } {
  const newZoom = Math.min(maxZoom, Math.max(minZoom, zoom / factor))
  const viewDir = target.clone().sub(position).normalize()
  const rel = point.clone().sub(position)
  const perp = rel.sub(viewDir.multiplyScalar(rel.dot(viewDir))) // in the view plane
  return { zoom: newZoom, shift: perp.multiplyScalar(1 - zoom / newZoom) }
}

/** Camera up vector for a snapped view direction (camera sits at target + dir): world Y up, except looking straight down / up. */
export function snapUp(dir: Vector3): Vector3 {
  const d = dir.clone().normalize()
  if (Math.abs(d.y) > 0.99) return new Vector3(0, 0, d.y > 0 ? -1 : 1)
  return new Vector3(0, 1, 0)
}
