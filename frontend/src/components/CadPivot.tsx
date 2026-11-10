import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { useThree } from '@react-three/fiber'
import { SNAPSHOT_HIDDEN_NAME } from '../lib/canvasCapture'
import { orthoZoomAbout, trackballAboutPivot, wheelFactor, zoomTowardPoint } from '../lib/cadPivot'

const PIVOT_MARKER = 'cad-pivot-marker'
/** Size of the view cube's corner square (CadCamera: margin 70 px around the cube centre). */
const VIEW_CUBE_PX = 140

/** The parts of the drei/three-stdlib OrbitControls instance this component touches. */
interface OrbitLike {
  target: THREE.Vector3
  enableRotate: boolean
  update: () => unknown
}

interface CadPivotProps {
  /** Ref to the drei <OrbitControls> instance. */
  controlsRef: React.MutableRefObject<OrbitLike | null>
  /** Left-drag rotation; off while another tool owns left clicks (measuring). Middle-drag always rotates. */
  enabled: boolean
  /** Pivot when the press hits no part (empty background): the model's bounding-box centre. */
  fallbackPivot: [number, number, number] | null
  /** Pivot marker size in scene units. */
  markerSize?: number
  /** Largest model dimension (scene units): sets the smallest wheel-zoom step. */
  modelSize?: number
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
 * CAD-style rotation: left-drag or middle-drag turns the part freely
 * (trackball: no fixed up axis, no pole, continuous in every direction) about
 * the surface point under the cursor (NX / CATIA / Cimatron behaviour), or
 * about the part centre when the press lands on empty background. The point
 * stays under the cursor, nothing jumps. Pan (right drag, Shift + middle,
 * Ctrl/Shift + left), wheel zoom to cursor and touch stay with OrbitControls.
 */
export function CadPivot({ controlsRef, enabled, fallbackPivot, markerSize = 0.08, modelSize = 10 }: CadPivotProps) {
  const { gl, camera, scene, raycaster } = useThree()
  const [marker, setMarker] = useState<THREE.Vector3 | null>(null)
  const fallbackRef = useRef(fallbackPivot)
  fallbackRef.current = fallbackPivot
  const enabledRef = useRef(enabled)
  enabledRef.current = enabled
  const sizeRef = useRef(modelSize)
  sizeRef.current = modelSize

  useEffect(() => {
    const el = gl.domElement
    let drag: { id: number; x: number; y: number; pivot: THREE.Vector3 } | null = null

    const surfaceHit = (e: MouseEvent): THREE.Vector3 | null => {
      const rect = el.getBoundingClientRect()
      const ndc = new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1,
      )
      raycaster.setFromCamera(ndc, camera)
      const hit = raycaster.intersectObjects(scene.children, true)
        .find((h) => (h.object as THREE.Mesh).isMesh && !isExcluded(h.object) && !isClipped(h, gl.localClippingEnabled))
      return hit ? hit.point.clone() : null
    }

    // CAD wheel zoom: toward the surface under the cursor, never stuck (see zoomTowardPoint).
    const onWheel = (e: WheelEvent) => {
      const controls = controlsRef.current
      if (!controls) return
      e.preventDefault()
      e.stopImmediatePropagation() // OrbitControls' own dolly slows down and stops at its target
      const px = e.deltaY * (e.deltaMode === 1 ? 40 : e.deltaMode === 2 ? 800 : 1)
      if (px === 0) return
      let point = surfaceHit(e)
      if (!point) {
        // Empty background: a point on the cursor ray at the target's depth.
        const depth = controls.target.clone().sub(camera.position).length()
        point = raycaster.ray.at(depth, new THREE.Vector3())
      }
      const ortho = camera as THREE.OrthographicCamera
      if (ortho.isOrthographicCamera) {
        // Parallel projection: scale the view about the cursor point, slide sideways only.
        const z = orthoZoomAbout(camera.position, controls.target, point, ortho.zoom, wheelFactor(px))
        ortho.zoom = z.zoom
        ortho.updateProjectionMatrix()
        camera.position.add(z.shift)
        controls.target.add(z.shift)
      } else {
        const r = zoomTowardPoint(camera.position, controls.target, point, wheelFactor(px), sizeRef.current * 0.05)
        camera.position.copy(r.position)
        controls.target.copy(r.target)
      }
      camera.lookAt(controls.target)
      controls.update()
    }

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
      if (e.pointerType === 'touch') return
      if (e.ctrlKey || e.metaKey || e.shiftKey) return // OrbitControls pans with these
      const left = e.button === 0
      const middle = e.button === 1
      // Bottom-right corner belongs to the view cube (CadCamera).
      const rect = el.getBoundingClientRect()
      if (e.clientX > rect.right - VIEW_CUBE_PX && e.clientY > rect.bottom - VIEW_CUBE_PX) return
      if (!(middle || (left && enabledRef.current))) return
      const pivot = pickPivot(e)
      if (!pivot) return
      // Capture phase on the canvas, before OrbitControls: with rotation off it
      // stays idle on a left press (R3F still gets it: view cube, measuring
      // clicks). A middle press is ours alone (OrbitControls would pan).
      if (middle) {
        e.stopImmediatePropagation()
        e.preventDefault()
      }
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
      const r = trackballAboutPivot(camera.position, controls.target, camera.up, drag.pivot,
        e.clientX - drag.x, e.clientY - drag.y, el.clientHeight)
      drag.x = e.clientX
      drag.y = e.clientY
      camera.position.copy(r.position)
      camera.up.copy(r.up)
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

    // Middle press must not start the browser's auto-scroll.
    const noAutoScroll = (e: MouseEvent) => { if (e.button === 1) e.preventDefault() }

    el.addEventListener('pointerdown', onDown, { capture: true })
    el.addEventListener('mousedown', noAutoScroll)
    el.addEventListener('wheel', onWheel, { capture: true, passive: false })
    return () => {
      el.removeEventListener('wheel', onWheel, { capture: true })
      el.removeEventListener('pointerdown', onDown, { capture: true })
      el.removeEventListener('mousedown', noAutoScroll)
      if (drag) end()
    }
  }, [gl, camera, scene, raycaster, controlsRef])

  if (!marker) return null
  return (
    <mesh name={PIVOT_MARKER} position={marker} renderOrder={999}>
      <sphereGeometry args={[markerSize, 16, 12]} />
      <meshBasicMaterial color="#f97316" depthTest={false} transparent opacity={0.9} />
    </mesh>
  )
}
