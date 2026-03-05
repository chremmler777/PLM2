import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { useThree } from '@react-three/fiber'

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

// Threshold for vertex snapping (in world units)
const VERTEX_SNAP_THRESHOLD = 0.5
// Threshold for circle detection
const CIRCLE_DETECTION_RADIUS = 3.0
const MIN_CIRCLE_POINTS = 6

export function useMeasurement(
  scene: THREE.Group | null,
  enabled: boolean
) {
  const { camera, gl } = useThree()
  const raycasterRef = useRef(new THREE.Raycaster())
  const mouseRef = useRef(new THREE.Vector2())
  const mouseDownRef = useRef<{ x: number; y: number } | null>(null)

  const [result, setResult] = useState<MeasurementResult>({
    point1: null,
    point2: null,
    distance: null,
    unit: 'mm'
  })

  const CLICK_THRESHOLD = 5

  const calculateAxisDistances = (p1: THREE.Vector3, p2: THREE.Vector3) => {
    return {
      x: Math.abs(p2.x - p1.x),
      y: Math.abs(p2.y - p1.y),
      z: Math.abs(p2.z - p1.z)
    }
  }

  // Find nearest vertex to a point within threshold
  const findNearestVertex = (
    mesh: THREE.Mesh,
    point: THREE.Vector3,
    threshold: number
  ): THREE.Vector3 | null => {
    const geometry = mesh.geometry as THREE.BufferGeometry
    const positions = geometry.attributes.position
    if (!positions) return null

    let nearestVertex: THREE.Vector3 | null = null
    let nearestDistance = threshold

    const vertex = new THREE.Vector3()
    for (let i = 0; i < positions.count; i++) {
      vertex.fromBufferAttribute(positions, i)
      // Transform to world coordinates
      vertex.applyMatrix4(mesh.matrixWorld)

      const dist = vertex.distanceTo(point)
      if (dist < nearestDistance) {
        nearestDistance = dist
        nearestVertex = vertex.clone()
      }
    }

    return nearestVertex
  }

  // Find edge midpoint near a point
  const findNearestEdgeMidpoint = (
    mesh: THREE.Mesh,
    point: THREE.Vector3,
    threshold: number
  ): THREE.Vector3 | null => {
    const geometry = mesh.geometry as THREE.BufferGeometry
    const positions = geometry.attributes.position
    const indices = geometry.index
    if (!positions) return null

    let nearestMidpoint: THREE.Vector3 | null = null
    let nearestDistance = threshold

    const processedEdges = new Set<string>()
    const v1 = new THREE.Vector3()
    const v2 = new THREE.Vector3()

    const checkEdge = (i1: number, i2: number) => {
      const edgeKey = i1 < i2 ? `${i1}-${i2}` : `${i2}-${i1}`
      if (processedEdges.has(edgeKey)) return
      processedEdges.add(edgeKey)

      v1.fromBufferAttribute(positions, i1).applyMatrix4(mesh.matrixWorld)
      v2.fromBufferAttribute(positions, i2).applyMatrix4(mesh.matrixWorld)

      const midpoint = new THREE.Vector3().addVectors(v1, v2).multiplyScalar(0.5)
      const dist = midpoint.distanceTo(point)

      if (dist < nearestDistance) {
        nearestDistance = dist
        nearestMidpoint = midpoint
      }
    }

    if (indices) {
      for (let i = 0; i < indices.count; i += 3) {
        const a = indices.array[i]
        const b = indices.array[i + 1]
        const c = indices.array[i + 2]
        checkEdge(a, b)
        checkEdge(b, c)
        checkEdge(c, a)
      }
    }

    return nearestMidpoint
  }

  // Detect circle center from nearby vertices
  const detectCircleCenter = (
    mesh: THREE.Mesh,
    hitPoint: THREE.Vector3,
    hitNormal: THREE.Vector3,
    searchRadius: number
  ): THREE.Vector3 | null => {
    const geometry = mesh.geometry as THREE.BufferGeometry
    const positions = geometry.attributes.position
    const indices = geometry.index
    if (!positions || !indices) return null

    // Find boundary edges (edges that appear only once in the mesh, indicating a hole)
    const edgeCount = new Map<string, number>()
    const edgeVertices = new Map<string, [number, number]>()

    for (let i = 0; i < indices.count; i += 3) {
      const a = indices.array[i]
      const b = indices.array[i + 1]
      const c = indices.array[i + 2]

      const edges = [[a, b], [b, c], [c, a]]
      for (const [i1, i2] of edges) {
        const key = i1 < i2 ? `${i1}-${i2}` : `${i2}-${i1}`
        edgeCount.set(key, (edgeCount.get(key) || 0) + 1)
        edgeVertices.set(key, [i1, i2])
      }
    }

    // Collect boundary edge vertices near the hit point
    const boundaryVertices: THREE.Vector3[] = []
    const vertex = new THREE.Vector3()

    for (const [key, count] of edgeCount) {
      if (count === 1) { // Boundary edge
        const [i1, i2] = edgeVertices.get(key)!

        vertex.fromBufferAttribute(positions, i1).applyMatrix4(mesh.matrixWorld)
        if (vertex.distanceTo(hitPoint) < searchRadius) {
          // Check if roughly coplanar with hit normal
          const toVertex = new THREE.Vector3().subVectors(vertex, hitPoint)
          const dotProduct = Math.abs(toVertex.normalize().dot(hitNormal))
          if (dotProduct < 0.3) { // Roughly perpendicular to normal = on same plane
            boundaryVertices.push(vertex.clone())
          }
        }

        vertex.fromBufferAttribute(positions, i2).applyMatrix4(mesh.matrixWorld)
        if (vertex.distanceTo(hitPoint) < searchRadius) {
          const toVertex = new THREE.Vector3().subVectors(vertex, hitPoint)
          const dotProduct = Math.abs(toVertex.normalize().dot(hitNormal))
          if (dotProduct < 0.3) {
            boundaryVertices.push(vertex.clone())
          }
        }
      }
    }

    if (boundaryVertices.length < MIN_CIRCLE_POINTS) return null

    // Remove duplicates
    const uniqueVertices: THREE.Vector3[] = []
    for (const v of boundaryVertices) {
      let isDuplicate = false
      for (const uv of uniqueVertices) {
        if (v.distanceTo(uv) < 0.01) {
          isDuplicate = true
          break
        }
      }
      if (!isDuplicate) uniqueVertices.push(v)
    }

    if (uniqueVertices.length < MIN_CIRCLE_POINTS) return null

    // Fit circle using centroid method (simple but effective for clean circles)
    // First, find the plane of the vertices
    const centroid = new THREE.Vector3()
    for (const v of uniqueVertices) {
      centroid.add(v)
    }
    centroid.divideScalar(uniqueVertices.length)

    // Check if vertices are roughly equidistant from centroid (circle test)
    const distances = uniqueVertices.map(v => v.distanceTo(centroid))
    const avgDistance = distances.reduce((a, b) => a + b, 0) / distances.length
    const variance = distances.reduce((sum, d) => sum + Math.pow(d - avgDistance, 2), 0) / distances.length
    const stdDev = Math.sqrt(variance)

    // If standard deviation is small relative to average radius, it's likely a circle
    const circleConfidence = 1 - (stdDev / avgDistance)

    if (circleConfidence > 0.85 && avgDistance > 0.1) {
      // Good circle detected, return centroid as center
      return centroid
    }

    return null
  }

  // Get snap point based on intersection
  const getSnapPoint = (
    intersection: THREE.Intersection,
    searchRadius: number = VERTEX_SNAP_THRESHOLD
  ): { point: THREE.Vector3; snapType: SnapType } => {
    const hitPoint = intersection.point.clone()
    const mesh = intersection.object as THREE.Mesh

    if (!(mesh instanceof THREE.Mesh)) {
      return { point: hitPoint, snapType: 'surface' }
    }

    // Try to detect circle center first (highest priority for holes)
    if (intersection.face) {
      const normal = intersection.face.normal.clone().transformDirection(mesh.matrixWorld)
      const circleCenter = detectCircleCenter(mesh, hitPoint, normal, CIRCLE_DETECTION_RADIUS)
      if (circleCenter) {
        return { point: circleCenter, snapType: 'center' }
      }
    }

    // Try vertex snap
    const nearestVertex = findNearestVertex(mesh, hitPoint, searchRadius)
    if (nearestVertex) {
      return { point: nearestVertex, snapType: 'vertex' }
    }

    // Try edge midpoint snap
    const nearestMidpoint = findNearestEdgeMidpoint(mesh, hitPoint, searchRadius)
    if (nearestMidpoint) {
      return { point: nearestMidpoint, snapType: 'midpoint' }
    }

    // Default to surface point
    return { point: hitPoint, snapType: 'surface' }
  }

  useEffect(() => {
    if (!enabled || !scene) return

    const rect = gl.domElement.getBoundingClientRect()

    const handlePointerDown = (event: PointerEvent) => {
      mouseDownRef.current = { x: event.clientX, y: event.clientY }
    }

    const handlePointerMove = (event: PointerEvent) => {
      mouseRef.current.x = ((event.clientX - rect.left) / rect.width) * 2 - 1
      mouseRef.current.y = -((event.clientY - rect.top) / rect.height) * 2 + 1

      raycasterRef.current.setFromCamera(mouseRef.current, camera)
      const intersects = raycasterRef.current.intersectObject(scene, true)

      if (intersects.length > 0) {
        const { point, snapType } = getSnapPoint(intersects[0])
        setResult((prev) => ({
          ...prev,
          hoveredPoint: point,
          hoveredSnapType: snapType
        }))
      }
    }

    const handlePointerUp = (event: PointerEvent) => {
      if (!mouseDownRef.current) return

      const dx = Math.abs(event.clientX - mouseDownRef.current.x)
      const dy = Math.abs(event.clientY - mouseDownRef.current.y)
      const distance = Math.sqrt(dx * dx + dy * dy)

      if (distance > CLICK_THRESHOLD) {
        mouseDownRef.current = null
        return
      }

      mouseRef.current.x = ((event.clientX - rect.left) / rect.width) * 2 - 1
      mouseRef.current.y = -((event.clientY - rect.top) / rect.height) * 2 + 1

      raycasterRef.current.setFromCamera(mouseRef.current, camera)
      const intersects = raycasterRef.current.intersectObject(scene, true)

      if (intersects.length > 0) {
        const { point, snapType } = getSnapPoint(intersects[0])

        setResult((prev) => {
          if (prev.point1 === null) {
            return {
              ...prev,
              point1: { position: point, index: 0, snapType }
            }
          } else if (prev.point2 === null) {
            const distance = prev.point1.position.distanceTo(point)
            const axisDistances = calculateAxisDistances(prev.point1.position, point)

            return {
              point1: prev.point1,
              point2: { position: point, index: 1, snapType },
              distance: distance,
              axisDistances: axisDistances,
              unit: 'mm'
            }
          } else {
            return {
              point1: { position: point, index: 0, snapType },
              point2: null,
              distance: null,
              unit: 'mm'
            }
          }
        })
      }

      mouseDownRef.current = null
    }

    gl.domElement.addEventListener('pointerdown', handlePointerDown)
    gl.domElement.addEventListener('pointerup', handlePointerUp)
    gl.domElement.addEventListener('pointermove', handlePointerMove)
    return () => {
      gl.domElement.removeEventListener('pointerdown', handlePointerDown)
      gl.domElement.removeEventListener('pointerup', handlePointerUp)
      gl.domElement.removeEventListener('pointermove', handlePointerMove)
    }
  }, [enabled, scene, camera, gl])

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
