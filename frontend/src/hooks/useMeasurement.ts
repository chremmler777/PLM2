import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { useThree } from '@react-three/fiber'
import { boundaryLoops, holeCenter, modelDistance, snapOnTriangle, worldPerPixel } from '../lib/measureSnap'

export type SnapType = 'surface' | 'vertex' | 'midpoint' | 'center'

export interface MeasurementPoint {
  position: THREE.Vector3
  index: number
  snapType?: SnapType
}

export interface MeasurementResult {
  point1: MeasurementPoint | null
  point2: MeasurementPoint | null
  distance: number | null
  axisDistances?: { x: number; y: number; z: number }
  unit: string
  hoveredPoint?: THREE.Vector3
  hoveredSnapType?: SnapType
}

/** Corner / edge-midpoint snap radius, screen pixels. */
const SNAP_PX = 10
/** How far (screen pixels) a click may be from a hole rim to snap to its centre. */
const HOLE_PX = 30

export function useMeasurement(
  scene: THREE.Group | null,
  enabled: boolean
) {
  const { camera, gl } = useThree()
  const raycasterRef = useRef(new THREE.Raycaster())
  const mouseDownRef = useRef<{ x: number; y: number } | null>(null)

  const [result, setResult] = useState<MeasurementResult>({
    point1: null,
    point2: null,
    distance: null,
    unit: 'mm'
  })

  const CLICK_THRESHOLD = 5

  /** Ray from the pointer; the canvas rect is read per event (it moves with scrolling and resizing). */
  const hitAt = (clientX: number, clientY: number): THREE.Intersection | null => {
    if (!scene) return null
    const rect = gl.domElement.getBoundingClientRect()
    const ndc = new THREE.Vector2(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1,
    )
    raycasterRef.current.setFromCamera(ndc, camera)
    const hits = raycasterRef.current.intersectObject(scene, true)
    return hits.find((h) => (h.object as THREE.Mesh).isMesh && h.object.visible) ?? null
  }

  /** Snap for a hit: hole centre (clicks only, needs the cached rims), else corner / edge midpoint of the hit triangle. */
  const snap = (hit: THREE.Intersection, withHoles: boolean): { point: THREE.Vector3; snapType: SnapType } => {
    const mesh = hit.object as THREE.Mesh
    const point = hit.point.clone()
    if (!mesh.isMesh || hit.faceIndex == null) return { point, snapType: 'surface' }
    const depth = point.clone().sub(camera.position).dot(camera.getWorldDirection(new THREE.Vector3()))
    const px = worldPerPixel(camera, depth, gl.domElement.clientHeight)
    const geometry = mesh.geometry as THREE.BufferGeometry
    if (withHoles && hit.face) {
      const normal = hit.face.normal.clone().transformDirection(mesh.matrixWorld)
      const c = holeCenter(boundaryLoops(geometry), mesh.matrixWorld, point, normal, HOLE_PX * px)
      if (c) return { point: c, snapType: 'center' }
    }
    const s = snapOnTriangle(geometry, hit.faceIndex, mesh.matrixWorld, point, SNAP_PX * px)
    return s ? { point: s.point, snapType: s.kind } : { point, snapType: 'surface' }
  }

  useEffect(() => {
    if (!enabled || !scene) return
    const el = gl.domElement
    let frame = 0
    let last: PointerEvent | null = null

    const handlePointerDown = (event: PointerEvent) => {
      mouseDownRef.current = { x: event.clientX, y: event.clientY }
    }

    // Hover: at most one raycast per frame, no whole-mesh loops.
    const hover = () => {
      frame = 0
      const e = last
      if (!e || e.buttons) return // dragging (rotate / pan): no hover work
      const hit = hitAt(e.clientX, e.clientY)
      if (!hit) return
      const { point, snapType } = snap(hit, false)
      setResult((prev) => ({ ...prev, hoveredPoint: point, hoveredSnapType: snapType }))
    }
    const handlePointerMove = (event: PointerEvent) => {
      last = event
      if (!frame) frame = requestAnimationFrame(hover)
    }

    const handlePointerUp = (event: PointerEvent) => {
      if (!mouseDownRef.current || event.button !== 0) return
      const dx = Math.abs(event.clientX - mouseDownRef.current.x)
      const dy = Math.abs(event.clientY - mouseDownRef.current.y)
      mouseDownRef.current = null
      if (Math.sqrt(dx * dx + dy * dy) > CLICK_THRESHOLD) return

      const hit = hitAt(event.clientX, event.clientY)
      if (!hit) return
      const { point, snapType } = snap(hit, true)

      setResult((prev) => {
        if (prev.point1 === null) {
          return { ...prev, point1: { position: point, index: 0, snapType } }
        } else if (prev.point2 === null) {
          // Model units (mm), not the scaled display units.
          const m = modelDistance(scene, prev.point1.position, point)
          return {
            point1: prev.point1,
            point2: { position: point, index: 1, snapType },
            distance: m.distance,
            axisDistances: m.axis,
            unit: 'mm'
          }
        }
        return { point1: { position: point, index: 0, snapType }, point2: null, distance: null, unit: 'mm' }
      })
    }

    el.addEventListener('pointerdown', handlePointerDown)
    el.addEventListener('pointerup', handlePointerUp)
    el.addEventListener('pointermove', handlePointerMove)
    return () => {
      if (frame) cancelAnimationFrame(frame)
      el.removeEventListener('pointerdown', handlePointerDown)
      el.removeEventListener('pointerup', handlePointerUp)
      el.removeEventListener('pointermove', handlePointerMove)
    }
  }, [enabled, scene, camera, gl]) // eslint-disable-line react-hooks/exhaustive-deps

  const clearMeasurement = () => {
    setResult({
      point1: null,
      point2: null,
      distance: null,
      unit: 'mm'
    })
  }

  return { result, clearMeasurement }
}
