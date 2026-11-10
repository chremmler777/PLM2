import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { useThree } from '@react-three/fiber'
import { SNAPSHOT_HIDDEN_NAME } from '../lib/canvasCapture'
import { dragAngle, orbitAboutPivot } from '../lib/cadPivot'

const PIVOT_MARKER = 'cad-pivot-marker'

/** The parts of the drei/three-stdlib OrbitControls instance this component touches. */
interface OrbitLike {
  target: THREE.Vector3
  enableRotate: boolean
  update: () => unknown
}

interface CadPivotProps {
  /** Ref to the drei <OrbitControls> instance. */
  controlsRef: React.MutableRefObject<OrbitLike | null>
  /** Off while another tool owns left clicks (measuring). */
  enabled: boolean
  /** Pivot when the press hits no part (empty background): the model's bounding-box centre. */
  fallbackPivot: [number, number, number] | null
  /** Pivot marker size in scene units. */
  markerSize?: number
}

/** True when the object or one of its parents is hidden or a helper we never pivot on. */
function isExcluded(obj: THREE.Object3D | null): boolean {
  for (let o = obj; o; o = o.parent) {
    if (!o.visible || o.name === SNAPSHOT_HIDDEN_NAME || o.name === PIVOT_MARKER) return true
  }
  return false
}

/** True when the hit lies in the half a cut plane has clipped away (invisible). */
function isClipped(hit: THREE.Intersection, localClipping: boolean): boolean {
  if (!localClipping) return false
  const mat = (hit.object as THREE.Mesh).material
  const mats = Array.isArray(mat) ? mat : [mat]
  return mats.some((m) => m?.clippingPlanes?.some((p: THREE.Plane) => p.distanceToPoint(hit.point) < 0))
}

/**
 * CAD-style rotation: a left-drag spins the view about the surface point under
 * the cursor (NX / CATIA / SolidWorks behaviour), or about the part centre
 * when the press lands on empty background. The point stays under the cursor,
 * nothing jumps. Pan (right drag), zoom (wheel) and touch gestures stay with
 * OrbitControls. Ctrl/Shift + left drag keep OrbitControls' pan.
 */
export function CadPivot({ controlsRef, enabled, fallbackPivot, markerSize = 0.08 }: CadPivotProps) {
  const { gl, camera, scene, raycaster } = useThree()
  const [marker, setMarker] = useState<THREE.Vector3 | null>(null)
  const fallbackRef = useRef(fallbackPivot)
  fallbackRef.current = fallbackPivot

  useEffect(() => {
    if (!enabled) return
    const el = gl.domElement
    let drag: { id: number; x: number; y: number; pivot: THREE.Vector3 } | null = null

    const pickPivot = (e: PointerEvent): THREE.Vector3 | null => {
      const rect = el.getBoundingClientRect()
      const ndc = new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1,
      )
      raycaster.setFromCamera(ndc, camera)
      const hits = raycaster.intersectObjects(scene.children, true)
      const hit = hits.find((h) => (h.object as THREE.Mesh).isMesh && !isExcluded(h.object)
        && !isClipped(h, gl.localClippingEnabled))
      if (hit) return hit.point.clone()
      const fb = fallbackRef.current
      return fb ? new THREE.Vector3(...fb) : null
    }

    const onDown = (e: PointerEvent) => {
      const controls = controlsRef.current
      if (!controls || drag) return
      if (e.button !== 0 || e.pointerType === 'touch') return
      if (e.ctrlKey || e.metaKey || e.shiftKey) return // OrbitControls pans with these
      const pivot = pickPivot(e)
      if (!pivot) return
      // Runs in the capture phase, before OrbitControls' own pointerdown, so
      // OrbitControls sees rotation disabled and stays idle for this drag.
      controls.enableRotate = false
      drag = { id: e.pointerId, x: e.clientX, y: e.clientY, pivot }
      setMarker(pivot)
      window.addEventListener('pointermove', onMove)
      window.addEventListener('pointerup', onUp)
      window.addEventListener('pointercancel', onUp)
    }

    const onMove = (e: PointerEvent) => {
      const controls = controlsRef.current
      if (!drag || e.pointerId !== drag.id || !controls) return
      const h = el.clientHeight
      const yaw = dragAngle(e.clientX - drag.x, h)
      const pitch = dragAngle(e.clientY - drag.y, h)
      drag.x = e.clientX
      drag.y = e.clientY
      const r = orbitAboutPivot(camera.position, controls.target, drag.pivot, camera.up, yaw, pitch)
      camera.position.copy(r.position)
      controls.target.copy(r.target)
      camera.lookAt(controls.target)
      controls.update()
    }

    const onUp = (e: PointerEvent) => {
      if (!drag || e.pointerId !== drag.id) return
      end()
    }

    const end = () => {
      drag = null
      setMarker(null)
      if (controlsRef.current) controlsRef.current.enableRotate = true
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
    }

    el.addEventListener('pointerdown', onDown, { capture: true })
    return () => {
      el.removeEventListener('pointerdown', onDown, { capture: true })
      if (drag) end()
    }
  }, [enabled, gl, camera, scene, raycaster, controlsRef])

  if (!marker) return null
  return (
    <mesh name={PIVOT_MARKER} position={marker} renderOrder={999}>
      <sphereGeometry args={[markerSize, 16, 12]} />
      <meshBasicMaterial color="#f97316" depthTest={false} transparent opacity={0.9} />
    </mesh>
  )
}
