import { useEffect, useRef } from 'react'
import * as THREE from 'three'

export function useViewMode(scene: THREE.Group | null, viewMode: 'solid' | 'wireframe') {
  const originalMaterials = useRef<Map<THREE.Mesh, THREE.Material | THREE.Material[]>>(new Map())

  useEffect(() => {
    if (!scene) return

    scene.traverse((child) => {
      if (child instanceof THREE.Mesh && child.material) {
        // Store original material on first wireframe toggle
        if (viewMode === 'wireframe' && !originalMaterials.current.has(child)) {
          originalMaterials.current.set(child, child.material)
        }

        if (viewMode === 'wireframe') {
          // Apply wireframe material
          child.material = new THREE.MeshBasicMaterial({
            wireframe: true,
            color: 0x00ff00,
            transparent: true,
            opacity: 0.8,
          })
        } else {
          // Restore original material
          const original = originalMaterials.current.get(child)
          if (original) {
            child.material = original
          }
        }
      }
    })
  }, [scene, viewMode])
}
