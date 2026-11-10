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
