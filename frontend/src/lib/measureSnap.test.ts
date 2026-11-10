// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { BufferAttribute, BufferGeometry, Group, Matrix4, OrthographicCamera, PerspectiveCamera, Vector3 } from 'three'
import { boundaryLoops, holeCenter, modelDistance, snapOnTriangle, worldPerPixel } from './measureSnap'

function tri(): BufferGeometry {
  const g = new BufferGeometry()
  g.setAttribute('position', new BufferAttribute(new Float32Array([0, 0, 0, 10, 0, 0, 0, 10, 0]), 3))
  g.setIndex([0, 1, 2])
  return g
}

describe('measureSnap', () => {
  it('measures in model units (mm), not in the scaled display units', () => {
    const model = new Group()
    model.scale.setScalar(10 / 250) // a 250 mm part shown as 10 units
    model.position.set(-3, 1, 0)
    model.updateWorldMatrix(true, true)
    const a = model.localToWorld(new Vector3(1800, -500, 600))
    const b = model.localToWorld(new Vector3(1900, -500, 600))
    const r = modelDistance(model, a, b)
    expect(r.distance).toBeCloseTo(100, 3)
    expect(r.axis.x).toBeCloseTo(100, 3)
  })

  it('snaps to a corner, else an edge midpoint, of the hit triangle within the radius', () => {
    const g = tri()
    const id = new Matrix4()
    expect(snapOnTriangle(g, 0, id, new Vector3(0.3, 0.2, 0), 1)?.kind).toBe('vertex')
    const m = snapOnTriangle(g, 0, id, new Vector3(5, 0.3, 0), 1)
    expect(m?.kind).toBe('midpoint')
    expect(m?.point.x).toBeCloseTo(5)
    expect(snapOnTriangle(g, 0, id, new Vector3(3, 3, 0), 1)).toBeNull()
  })

  it('pixel size: orthographic is fixed by zoom, perspective grows with depth', () => {
    const o = new OrthographicCamera(-400, 400, 300, -300, -10, 10)
    o.zoom = 2
    expect(worldPerPixel(o, 123, 600)).toBeCloseTo(0.5)
    const p = new PerspectiveCamera(30, 1, 0.1, 100)
    expect(worldPerPixel(p, 20, 600)).toBeCloseTo(2 * worldPerPixel(p, 10, 600))
  })

  it('finds a round hole centre from the rim of a flat ring', () => {
    // flat ring: inner rim (hole, r = 2) and outer rim (r = 6), 24 segments
    const seg = 24, pos: number[] = [], index: number[] = []
    for (let i = 0; i < seg; i++) {
      const t = (i / seg) * Math.PI * 2
      pos.push(2 * Math.cos(t), 2 * Math.sin(t), 0, 6 * Math.cos(t), 6 * Math.sin(t), 0)
    }
    for (let i = 0; i < seg; i++) {
      const a = 2 * i, b = 2 * i + 1, c = 2 * ((i + 1) % seg), d = c + 1
      index.push(a, b, c, b, d, c)
    }
    const g = new BufferGeometry()
    g.setAttribute('position', new BufferAttribute(new Float32Array(pos), 3))
    g.setIndex(index)
    const loops = boundaryLoops(g)
    expect(loops.length).toBe(2) // hole rim and outer rim, apart
    const c = holeCenter(loops, new Matrix4(), new Vector3(2.5, 0, 0), new Vector3(0, 0, 1), 1)
    expect(c).not.toBeNull()
    expect(c!.length()).toBeLessThan(1e-5)
    // far from any rim: nothing
    expect(holeCenter(loops, new Matrix4(), new Vector3(4, 0, 0), new Vector3(0, 0, 1), 0.5)).toBeNull()
  })
})
