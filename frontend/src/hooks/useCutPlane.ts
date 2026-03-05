import { useEffect, useRef } from 'react'
import * as THREE from 'three'

export function useCutPlane(
  scene: THREE.Group | null,
  active: boolean,
  axis: 'x' | 'y' | 'z',
  position: number
) {
  const clippingPlanes = useRef<THREE.Plane[]>([])
  const materialBackups = useRef<Map<THREE.Material, boolean>>(new Map())

  useEffect(() => {
    if (!scene) return

    if (active) {
      // Create clipping plane based on axis
      const normal =
        axis === 'x' ? new THREE.Vector3(1, 0, 0) :
        axis === 'y' ? new THREE.Vector3(0, 1, 0) :
        new THREE.Vector3(0, 0, 1)

      // Get scene bounds to normalize position
      const bbox = new THREE.Box3().setFromObject(scene)
      const size = bbox.getSize(new THREE.Vector3())
      const center = bbox.getCenter(new THREE.Vector3())

      // Convert normalized position (-1 to 1) to world position
      const sizeInAxis =
        axis === 'x' ? size.x :
        axis === 'y' ? size.y :
        size.z

      const centerInAxis =
        axis === 'x' ? center.x :
        axis === 'y' ? center.y :
        center.z

      const worldPosition = centerInAxis + (sizeInAxis / 2) * position
      const plane = new THREE.Plane(normal, -worldPosition)

      clippingPlanes.current = [plane]

      // Apply clipping planes to all materials
      scene.traverse((child) => {
        if (child instanceof THREE.Mesh && child.material) {
          const materials = Array.isArray(child.material) ? child.material : [child.material]

          materials.forEach((material) => {
            // Backup original state
            if (!materialBackups.current.has(material)) {
              materialBackups.current.set(material, material.clippingPlanes ? true : false)
            }

            // Enable clipping on the material
            material.clippingPlanes = clippingPlanes.current
            material.clipIntersection = false
            material.needsUpdate = true
          })
        }
      })
    } else {
      // Disable clipping planes
      scene.traverse((child) => {
        if (child instanceof THREE.Mesh && child.material) {
          const materials = Array.isArray(child.material) ? child.material : [child.material]

          materials.forEach((material) => {
            material.clippingPlanes = []
            material.needsUpdate = true
          })
        }
      })

      clippingPlanes.current = []
      materialBackups.current.clear()
    }
  }, [scene, active, axis, position])

  // Enable local clipping on the renderer (handled by Canvas component)
  // This will be done via useThree() in the CutPlane component
}
