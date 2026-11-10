/**
 * Measuring helpers that stay fast on large CAD meshes (hundreds of thousands
 * of triangles) and measure in the model's own units.
 *
 * - Snapping looks only at the triangle under the cursor (its corners and edge
 *   midpoints), never at the whole mesh on every mouse move.
 * - Snap and hole-search radii are screen pixels converted to world size at
 *   the hit depth, so they behave the same on a clip and on a back panel.
 * - Hole (circle) centres: the mesh's open boundary edges grouped into rim
 *   loops once per geometry (numeric keys, cached); each rim is fitted alone.
 * - Distances are taken in the model's local coordinates: the viewer scales
 *   every model to ~10 units for display, while the converted glb is in mm
 *   (vehicle coordinates), so local units are real millimetres.
 */
import { BufferGeometry, Camera, Matrix4, Object3D, OrthographicCamera, PerspectiveCamera, Vector3 } from 'three'

export type SnapKind = 'surface' | 'vertex' | 'midpoint' | 'center'

/** World size of one screen pixel at `depth` (distance from the camera along the view). */
export function worldPerPixel(camera: Camera, depth: number, viewportHeightPx: number): number {
  const h = Math.max(viewportHeightPx, 1)
  const o = camera as OrthographicCamera
  if (o.isOrthographicCamera) return (o.top - o.bottom) / o.zoom / h
  const p = camera as PerspectiveCamera
  return (2 * Math.max(depth, 0) * Math.tan(((p.fov ?? 50) * Math.PI) / 360)) / h
}

/** Corner or edge midpoint of the hit triangle within `radius` (world) of the hit point, corners first. */
export function snapOnTriangle(
  geometry: BufferGeometry,
  faceIndex: number,
  matrixWorld: Matrix4,
  hit: Vector3,
  radius: number,
): { point: Vector3; kind: SnapKind } | null {
  const pos = geometry.attributes.position
  if (!pos) return null
  const idx = geometry.index
  const ids = [0, 1, 2].map((k) => (idx ? idx.getX(faceIndex * 3 + k) : faceIndex * 3 + k))
  const v = ids.map((i) => new Vector3().fromBufferAttribute(pos, i).applyMatrix4(matrixWorld))
  let best: { point: Vector3; kind: SnapKind } | null = null
  let bestD = radius
  for (const c of v) {
    const d = c.distanceTo(hit)
    if (d < bestD) { bestD = d; best = { point: c.clone(), kind: 'vertex' } }
  }
  if (best) return best
  for (const [a, b] of [[0, 1], [1, 2], [2, 0]]) {
    const m = v[a].clone().add(v[b]).multiplyScalar(0.5)
    const d = m.distanceTo(hit)
    if (d < bestD) { bestD = d; best = { point: m, kind: 'midpoint' } }
  }
  return best
}

const loopCache = new WeakMap<BufferGeometry, Float32Array[]>()

/**
 * Open boundary rims (hole edges, outer outline) of a mesh as separate loops,
 * each a Float32Array of local xyz triplets. Built once per geometry: edges used
 * by one triangle only, grouped by shared vertices (union-find), numeric keys.
 */
export function boundaryLoops(geometry: BufferGeometry): Float32Array[] {
  const cached = loopCache.get(geometry)
  if (cached) return cached
  const pos = geometry.attributes.position
  const idx = geometry.index
  if (!pos || !idx) {
    loopCache.set(geometry, [])
    return []
  }
  const n = pos.count
  const count = new Map<number, number>()
  const key = (a: number, b: number) => (a < b ? a * n + b : b * n + a)
  for (let i = 0; i < idx.count; i += 3) {
    const a = idx.getX(i), b = idx.getX(i + 1), c = idx.getX(i + 2)
    for (const k of [key(a, b), key(b, c), key(c, a)]) count.set(k, (count.get(k) ?? 0) + 1)
  }
  const parent = new Map<number, number>()
  const find = (x: number): number => {
    let r = x
    while (parent.get(r) !== r) r = parent.get(r)!
    let y = x
    while (parent.get(y) !== r) { const nx = parent.get(y)!; parent.set(y, r); y = nx }
    return r
  }
  for (const [k, c] of count) {
    if (c !== 1) continue
    const a = Math.floor(k / n), b = k % n
    if (!parent.has(a)) parent.set(a, a)
    if (!parent.has(b)) parent.set(b, b)
    const ra = find(a), rb = find(b)
    if (ra !== rb) parent.set(ra, rb)
  }
  const groups = new Map<number, number[]>()
  for (const v of parent.keys()) {
    const r = find(v)
    const g = groups.get(r)
    if (g) g.push(v)
    else groups.set(r, [v])
  }
  const loops: Float32Array[] = []
  for (const vs of groups.values()) {
    const arr = new Float32Array(vs.length * 3)
    vs.forEach((v, i) => { arr[i * 3] = pos.getX(v); arr[i * 3 + 1] = pos.getY(v); arr[i * 3 + 2] = pos.getZ(v) })
    loops.push(arr)
  }
  loopCache.set(geometry, loops)
  return loops
}

/**
 * Centre of the round hole rim nearest to the hit point: each rim loop that
 * comes within `radius` of the hit is fitted on its own (all its points), it
 * counts when the points are roughly equidistant from their centroid and lie
 * in the hit plane; the closest such centre wins. Null when no round rim is near.
 */
export function holeCenter(
  loopsLocal: Float32Array[],
  matrixWorld: Matrix4,
  hit: Vector3,
  normal: Vector3,
  radius: number,
  minPoints = 6,
): Vector3 | null {
  let best: Vector3 | null = null
  let bestD = Infinity
  const v = new Vector3()
  for (const loop of loopsLocal) {
    const m = loop.length / 3
    if (m < minPoints) continue
    let near = false
    const pts: Vector3[] = []
    for (let i = 0; i < loop.length; i += 3) {
      v.set(loop[i], loop[i + 1], loop[i + 2]).applyMatrix4(matrixWorld)
      if (v.distanceTo(hit) <= radius) near = true
      pts.push(v.clone())
    }
    if (!near) continue
    const c = pts.reduce((s, p) => s.add(p), new Vector3()).divideScalar(pts.length)
    // flat in the hit plane
    if (pts.some((p) => Math.abs(p.clone().sub(c).dot(normal)) > 0.05 * (p.distanceTo(c) + 1e-9) + 1e-6)) continue
    const ds = pts.map((p) => p.distanceTo(c))
    const avg = ds.reduce((a, b) => a + b, 0) / ds.length
    if (avg <= 0 || avg > radius * 4) continue // not a hole at this zoom (e.g. the part outline)
    const sd = Math.sqrt(ds.reduce((s, d) => s + (d - avg) ** 2, 0) / ds.length)
    if (1 - sd / avg < 0.9) continue
    const d = c.distanceTo(hit)
    if (d < bestD) { bestD = d; best = c }
  }
  return best
}

/** Distance and per-axis distances of two world points, in the model's own units (mm for converted CAD). */
export function modelDistance(model: Object3D, a: Vector3, b: Vector3) {
  model.updateWorldMatrix(true, false)
  const la = model.worldToLocal(a.clone())
  const lb = model.worldToLocal(b.clone())
  return {
    distance: la.distanceTo(lb),
    axis: { x: Math.abs(lb.x - la.x), y: Math.abs(lb.y - la.y), z: Math.abs(lb.z - la.z) },
  }
}
