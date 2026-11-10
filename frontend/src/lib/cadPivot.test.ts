// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { BoxGeometry, BufferGeometry, Group, LineSegments, Mesh, OrthographicCamera, PerspectiveCamera, Vector3 } from 'three'
import { dragAngle, orbitAboutPivot, solidBounds, trackballAboutPivot, trackballAngle, wheelFactor, zoomTowardPoint, orthoZoomAbout, snapUp } from './cadPivot'

const UP = new Vector3(0, 1, 0)

function screenPos(cam: PerspectiveCamera | OrthographicCamera, p: Vector3) {
  cam.updateMatrixWorld()
  cam.updateProjectionMatrix()
  return p.clone().project(cam)
}

describe('orbitAboutPivot', () => {
  it('keeps the pivot at the same distance from the camera and the target on the view axis', () => {
    const pos = new Vector3(20, 15, 20)
    const target = new Vector3(0, 0, 0)
    const pivot = new Vector3(3, -1, 2)
    const r = orbitAboutPivot(pos, target, pivot, UP, 0.4, 0.3)
    expect(r.position.distanceTo(pivot)).toBeCloseTo(pos.distanceTo(pivot), 6)
    expect(r.target.distanceTo(pivot)).toBeCloseTo(target.distanceTo(pivot), 6)
    expect(r.position.distanceTo(r.target)).toBeCloseTo(pos.distanceTo(target), 6)
  })

  it('keeps the clicked point fixed on screen (no jump)', () => {
    const cam = new PerspectiveCamera(50, 1.5, 0.1, 1000)
    cam.position.set(20, 15, 20)
    const target = new Vector3(0, 0, 0)
    cam.lookAt(target)
    const pivot = new Vector3(3, -1, 2)
    const before = screenPos(cam, pivot)

    const r = orbitAboutPivot(cam.position, target, pivot, UP, 0.7, -0.25)
    cam.position.copy(r.position)
    cam.lookAt(r.target)
    const after = screenPos(cam, pivot)
    expect(after.x).toBeCloseTo(before.x, 5)
    expect(after.y).toBeCloseTo(before.y, 5)
  })

  it('pivoting at the target is a plain orbit (target unchanged)', () => {
    const pos = new Vector3(10, 5, 0)
    const target = new Vector3(1, 2, 3)
    const r = orbitAboutPivot(pos, target, target.clone(), UP, 1, 0.2)
    expect(r.target.distanceTo(target)).toBeCloseTo(0, 9)
  })

  it('follows OrbitControls direction: positive pitch moves the camera up', () => {
    const pos = new Vector3(0, 0, 10)
    const r = orbitAboutPivot(pos, new Vector3(), new Vector3(), UP, 0, 0.3)
    expect(r.position.y).toBeGreaterThan(0)
  })

  it('never flips over the pole', () => {
    const pos = new Vector3(0, 0, 10)
    const r = orbitAboutPivot(pos, new Vector3(), new Vector3(), UP, 0, 10)
    const offset = r.position.clone().sub(r.target)
    expect(offset.angleTo(UP)).toBeGreaterThan(0)
    expect(r.position.z).toBeGreaterThan(0)
  })
})

describe('solidBounds', () => {
  it('ignores edge lines that reach back to the CAD origin', () => {
    const root = new Group()
    const part = new Mesh(new BoxGeometry(0.1, 0.03, 0.3))
    part.position.set(2.8, -0.16, 0.65)
    root.add(part)
    const edges = new LineSegments(new BufferGeometry().setFromPoints([
      new Vector3(0, 0, 0), new Vector3(2.8, 1.2, 0.8),
    ]))
    root.add(edges)
    const c = solidBounds(root).getCenter(new Vector3())
    expect(c.x).toBeCloseTo(2.8, 6)
    expect(c.y).toBeCloseTo(-0.16, 6)
    expect(c.z).toBeCloseTo(0.65, 6)
  })

  it('falls back to all objects for wire-only models', () => {
    const root = new Group()
    root.add(new LineSegments(new BufferGeometry().setFromPoints([new Vector3(1, 1, 1), new Vector3(3, 3, 3)])))
    expect(solidBounds(root).getCenter(new Vector3()).x).toBeCloseTo(2, 6)
  })
})

describe('dragAngle', () => {
  it('a full viewport height is one turn', () => {
    expect(dragAngle(600, 600)).toBeCloseTo(2 * Math.PI)
  })
})

describe('trackballAboutPivot (free CAD rotation)', () => {
  const H = 800

  function apply(cam: PerspectiveCamera, target: Vector3, pivot: Vector3, dx: number, dy: number) {
    const r = trackballAboutPivot(cam.position, target, cam.up, pivot, dx, dy, H)
    cam.position.copy(r.position)
    cam.up.copy(r.up)
    target.copy(r.target)
    cam.lookAt(target)
  }

  it('keeps the grabbed point fixed on screen', () => {
    const cam = new PerspectiveCamera(50, 1.5, 0.1, 1000)
    cam.position.set(20, 15, 20)
    const target = new Vector3()
    cam.lookAt(target)
    const pivot = new Vector3(3, -1, 2)
    const before = screenPos(cam, pivot)
    apply(cam, target, pivot, 120, -70)
    const after = screenPos(cam, pivot)
    expect(after.x).toBeCloseTo(before.x, 5)
    expect(after.y).toBeCloseTo(before.y, 5)
  })

  it('turns on continuously over the top: no pole, a full vertical turn comes back', () => {
    const cam = new PerspectiveCamera(50, 1, 0.1, 1000)
    cam.position.set(0, 0, 30)
    const target = new Vector3()
    cam.lookAt(target)
    const start = cam.position.clone()
    const heights: number[] = []
    // 2 viewport heights = 2 x 180 deg, in small steps like a real drag
    for (let i = 0; i < 160; i++) {
      apply(cam, target, new Vector3(), 0, (2 * H) / 160)
      heights.push(cam.position.y)
    }
    // passed straight over the top and under the bottom (an orbit would stop near the pole)
    expect(Math.max(...heights)).toBeCloseTo(30, 3)
    expect(Math.min(...heights)).toBeCloseTo(-30, 3)
    expect(cam.position.distanceTo(start)).toBeLessThan(1e-6)
  })

  it('drags right -> the part front moves right (camera goes left)', () => {
    const cam = new PerspectiveCamera(50, 1, 0.1, 1000)
    cam.position.set(0, 0, 30)
    const target = new Vector3()
    cam.lookAt(target)
    apply(cam, target, new Vector3(), 50, 0)
    expect(cam.position.x).toBeLessThan(0)
  })

  it('half a turn per viewport height', () => {
    expect(trackballAngle(H, H)).toBeCloseTo(Math.PI)
  })
})

describe('zoomTowardPoint (CAD wheel zoom)', () => {
  it('keeps the point under the cursor on the same pixel', () => {
    const cam = new PerspectiveCamera(50, 1.5, 0.01, 1000)
    cam.position.set(20, 15, 20)
    const target = new Vector3()
    cam.lookAt(target)
    const p = new Vector3(2, 1, -1)
    const before = screenPos(cam, p)
    const r = zoomTowardPoint(cam.position, target, p, wheelFactor(-100), 0.1)
    cam.position.copy(r.position)
    cam.lookAt(r.target)
    const after = screenPos(cam, p)
    expect(after.x).toBeCloseTo(before.x, 5)
    expect(after.y).toBeCloseTo(before.y, 5)
  })

  it('never gets stuck: close to the point it still moves by the minimum step and passes it', () => {
    let pos = new Vector3(0, 0, 10)
    let target = new Vector3()
    const p = new Vector3()
    for (let i = 0; i < 200; i++) {
      const r = zoomTowardPoint(pos, target, p, wheelFactor(-100), 0.5)
      pos = r.position
      target = r.target
    }
    expect(pos.z).toBeLessThan(0) // went through the point instead of creeping toward it
  })

  it('zooming out by the inverse factor comes back', () => {
    const pos = new Vector3(0, 0, 10)
    const target = new Vector3()
    const p = new Vector3(1, 0, 0)
    const inn = zoomTowardPoint(pos, target, p, 0.8, 0.01)
    const out = zoomTowardPoint(inn.position, inn.target, p, 1 / 0.8, 0.01)
    expect(out.position.distanceTo(p)).toBeGreaterThan(inn.position.distanceTo(p))
  })
})

describe('orthoZoomAbout (parallel projection)', () => {
  it('keeps the point under the cursor on the same pixel while the scale changes', () => {
    const cam = new OrthographicCamera(-400, 400, 300, -300, -1000, 1000)
    cam.position.set(10, 8, 10)
    const target = new Vector3()
    cam.lookAt(target)
    cam.zoom = 40
    const p = new Vector3(1.5, 0.5, -2)
    const before = screenPos(cam, p)
    const r = orthoZoomAbout(cam.position, target, p, cam.zoom, wheelFactor(-100))
    cam.zoom = r.zoom
    cam.position.add(r.shift)
    target.add(r.shift)
    cam.lookAt(target)
    const after = screenPos(cam, p)
    expect(r.zoom).toBeGreaterThan(40)
    expect(after.x).toBeCloseTo(before.x, 5)
    expect(after.y).toBeCloseTo(before.y, 5)
  })
})

describe('snapUp', () => {
  it('is world Y for side views and Z for top / bottom', () => {
    expect(snapUp(new Vector3(0, 0, 1)).toArray()).toEqual([0, 1, 0])
    expect(snapUp(new Vector3(0, 1, 0)).toArray()).toEqual([0, 0, -1])
    expect(snapUp(new Vector3(0, -1, 0)).toArray()).toEqual([0, 0, 1])
  })
})

describe('wheelFactor', () => {
  it('scroll up (negative deltaY) zooms in, scroll down zooms out', () => {
    expect(wheelFactor(-100)).toBeLessThan(1)
    expect(wheelFactor(100)).toBeGreaterThan(1)
  })
})
