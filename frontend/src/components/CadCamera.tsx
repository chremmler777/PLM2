import { useEffect, useImperativeHandle, useRef, forwardRef } from 'react'
import * as THREE from 'three'
import { useFrame, useThree } from '@react-three/fiber'
import { GizmoHelper, GizmoViewcube } from '@react-three/drei'
import { snapUp } from '../lib/cadPivot'

export type Projection = 'ortho' | 'persp'

/** Perspective lens: a normal lens, not the wide 50 deg that made parts look distorted. */
export const PERSP_FOV = 30

interface ControlsLike {
  target: THREE.Vector3
  object: THREE.Camera
  update: () => unknown
}

export interface CadCameraHandle {
  /** Snap to a view direction (camera at target + dir), upright, animated. */
  snapTo: (dir: THREE.Vector3) => void
}

interface CadCameraProps {
  projection: Projection
  controlsRef: React.MutableRefObject<ControlsLike | null>
  /** Largest model dimension: sets the parallel camera's clip range. */
  modelSize: number
  /** View cube in the corner (off while snapshots must stay clean is not needed: it is a separate HUD scene). */
  showCube?: boolean
}

/**
 * CAD camera: parallel (orthographic) projection by default, perspective on
 * request, switched without a jump (same pose, same apparent size), plus a
 * view cube that snaps to faces / edges / corners. drei's own cube animation
 * is not used: it resets the camera's up vector and assumes the world origin,
 * which fights the free trackball rotation.
 */
export const CadCamera = forwardRef<CadCameraHandle, CadCameraProps>(function CadCamera(
  { projection, controlsRef, modelSize, showCube = true }, ref,
) {
  const set = useThree((s) => s.set)
  const size = useThree((s) => s.size)
  const camera = useThree((s) => s.camera)
  const pendingTarget = useRef<THREE.Vector3 | null>(null)
  const anim = useRef<{ q0: THREE.Quaternion; q1: THREE.Quaternion; t: number; dist: number } | null>(null)

  // Switch projection, keeping pose and apparent size.
  useEffect(() => {
    const isOrtho = (camera as THREE.OrthographicCamera).isOrthographicCamera === true
    if ((projection === 'ortho') === isOrtho) return
    const controls = controlsRef.current
    const target = controls ? controls.target.clone() : new THREE.Vector3()
    const dist = Math.max(camera.position.distanceTo(target), 1e-6)
    const viewDir = target.clone().sub(camera.position).normalize()
    let next: THREE.Camera
    if (projection === 'ortho') {
      const p = camera as THREE.PerspectiveCamera
      const visibleH = 2 * dist * Math.tan((p.fov * Math.PI) / 360)
      const o = new THREE.OrthographicCamera(-size.width / 2, size.width / 2, size.height / 2, -size.height / 2,
        -modelSize * 50, modelSize * 50 + dist * 10)
      o.zoom = size.height / Math.max(visibleH, 1e-9)
      o.position.copy(camera.position)
      next = o
    } else {
      const o = camera as THREE.OrthographicCamera
      const visibleH = (o.top - o.bottom) / o.zoom
      const d = visibleH / (2 * Math.tan((PERSP_FOV * Math.PI) / 360))
      const p = new THREE.PerspectiveCamera(PERSP_FOV, size.width / Math.max(size.height, 1),
        Math.max(d / 1000, 1e-5), d * 20 + modelSize * 10)
      p.position.copy(target).sub(viewDir.multiplyScalar(d))
      next = p
    }
    next.up.copy(camera.up)
    next.lookAt(target)
    ;(next as THREE.PerspectiveCamera).updateProjectionMatrix?.()
    pendingTarget.current = target
    set({ camera: next as THREE.PerspectiveCamera })
  }, [projection]) // eslint-disable-line react-hooks/exhaustive-deps

  // OrbitControls is rebuilt for the new camera with target (0,0,0): give it back the old target.
  useFrame(() => {
    const controls = controlsRef.current
    if (pendingTarget.current && controls && controls.object === camera) {
      controls.target.copy(pendingTarget.current)
      camera.lookAt(controls.target)
      controls.update()
      pendingTarget.current = null
    }
    const a = anim.current
    if (!a || !controls) return
    a.t = Math.min(1, a.t + 1 / 14) // about a quarter second at 60 fps
    const k = a.t * a.t * (3 - 2 * a.t)
    const q = a.q0.clone().slerp(a.q1, k)
    const back = new THREE.Vector3(0, 0, 1).applyQuaternion(q)
    camera.position.copy(controls.target).add(back.multiplyScalar(a.dist))
    camera.up.set(0, 1, 0).applyQuaternion(q)
    camera.quaternion.copy(q)
    controls.update()
    if (a.t >= 1) anim.current = null
  })

  const snapRef = useRef<(dir: THREE.Vector3) => void>(() => {})
  snapRef.current = (dir) => {
    const controls = controlsRef.current
    if (!controls) return
    const d = dir.clone().normalize()
    const dist = camera.position.distanceTo(controls.target)
    const m = new THREE.Matrix4().lookAt(d.clone().multiplyScalar(dist), new THREE.Vector3(), snapUp(d))
    anim.current = { q0: camera.quaternion.clone(), q1: new THREE.Quaternion().setFromRotationMatrix(m), t: 0, dist }
  }

  useImperativeHandle(ref, () => ({ snapTo: (dir) => snapRef.current(dir) }), [])

  if (!showCube) return null
  return (
    <GizmoHelper alignment="bottom-right" margin={[70, 70]}>
      <GizmoViewcube
        color="#e2e8f0"
        textColor="#0f172a"
        strokeColor="#475569"
        hoverColor="#f97316"
        opacity={0.95}
        onClick={(e) => {
          e.stopPropagation()
          const obj = e.object as THREE.Object3D
          const dir = obj.position.lengthSq() > 1e-9
            ? obj.position.clone()
            : e.face?.normal?.clone() ?? new THREE.Vector3(0, 0, 1)
          snapRef.current(dir)
          return null
        }}
      />
    </GizmoHelper>
  )
})
