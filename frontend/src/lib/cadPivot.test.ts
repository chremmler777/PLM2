// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { BoxGeometry, BufferGeometry, Group, LineSegments, Mesh, PerspectiveCamera, Vector3 } from 'three'
import { dragAngle, orbitAboutPivot, solidBounds } from './cadPivot'

const UP = new Vector3(0, 1, 0)

function screenPos(cam: PerspectiveCamera, p: Vector3) {
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
