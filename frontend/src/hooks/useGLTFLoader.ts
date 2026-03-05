import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
// @ts-ignore - GLTFLoader types are not always properly exported
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'

export interface SceneNode {
  id: string
  name: string
  type: 'group' | 'mesh' | 'light' | 'camera' | 'bone' | 'other'
  object: THREE.Object3D
  children: SceneNode[]
  visible: boolean
}

interface UseGLTFLoaderResult {
  scene: THREE.Group | null
  sceneTree: SceneNode | null
  isLoading: boolean
  error: Error | null
}

interface GLTF {
  scene: THREE.Group
  scenes: THREE.Group[]
  animations: THREE.AnimationClip[]
  asset: any
  parser: any
  userData: any
}

/**
 * Custom React hook for loading glTF/glb 3D models
 * Handles loading, error states, and proper resource cleanup
 * @param url - URL to the glTF/glb file to load
 * @returns Object containing loaded scene, loading state, and error
 */
/**
 * Build a hierarchical tree from a Three.js object and its children
 */
function buildSceneTree(object: THREE.Object3D): SceneNode {
  const type =
    object instanceof THREE.Mesh
      ? 'mesh'
      : object instanceof THREE.Light
        ? 'light'
        : object instanceof THREE.Camera
          ? 'camera'
          : object instanceof THREE.Bone
            ? 'bone'
            : object instanceof THREE.Group
              ? 'group'
              : 'other'

  return {
    id: object.uuid,
    name: object.name || `${type}_${object.id}`,
    type,
    object,
    children: object.children.map(buildSceneTree),
    visible: object.visible
  }
}

export function useGLTFLoader(url: string | null): UseGLTFLoaderResult {
  const [scene, setScene] = useState<THREE.Group | null>(null)
  const [sceneTree, setSceneTree] = useState<SceneNode | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  const loaderRef = useRef<GLTFLoader | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  // Initialize loader once
  useEffect(() => {
    if (!loaderRef.current) {
      loaderRef.current = new GLTFLoader()
    }
  }, [])

  // Load model when URL changes
  useEffect(() => {
    if (!url || !loaderRef.current) {
      setScene(null)
      setSceneTree(null)
      setError(null)
      return
    }

    // Reset state
    setIsLoading(true)
    setSceneTree(null)
    setError(null)

    // Create abort controller for this load attempt
    abortControllerRef.current = new AbortController()
    const signal = abortControllerRef.current.signal

    let isMounted = true

    const loadModel = async () => {
      try {
        // Fetch the glTF file (public endpoint, no auth required)
        const response = await fetch(url, { signal })

        if (!response.ok) {
          throw new Error(`Failed to fetch model: ${response.status} ${response.statusText}`)
        }

        const arrayBuffer = await response.arrayBuffer()

        // Load the glTF using the loader
        loaderRef.current!.parse(
          arrayBuffer,
          '', // baseUrl - not needed since we're using absolute URL
          (gltf: GLTF) => {
            if (!isMounted || signal.aborted) return

            // Extract the scene from the GLTF
            const scene = gltf.scene

            // Center and scale the model
            const bbox = new THREE.Box3().setFromObject(scene)
            const center = bbox.getCenter(new THREE.Vector3())
            const size = bbox.getSize(new THREE.Vector3())

            // Center model at origin
            scene.position.sub(center)

            // Calculate scale to fit in standard size
            const maxDim = Math.max(size.x, size.y, size.z)
            const scale = maxDim > 0 ? 10 / maxDim : 1
            scene.scale.multiplyScalar(scale)

            // Build scene tree
            const tree = buildSceneTree(scene)

            setScene(scene)
            setSceneTree(tree)
            setIsLoading(false)
          },
          (error: ErrorEvent) => {
            if (!isMounted || signal.aborted) return
            console.error('Error parsing glTF:', error)
            setError(new Error(`Failed to parse glTF: ${error instanceof Error ? error.message : 'Unknown error'}`))
            setIsLoading(false)
          }
        )
      } catch (err) {
        if (!isMounted || signal.aborted) return

        if (err instanceof Error) {
          // Ignore abort errors
          if (err.name === 'AbortError') return
          setError(err)
        } else {
          setError(new Error('Unknown error loading model'))
        }
        setIsLoading(false)
      }
    }

    loadModel()

    // Cleanup function
    return () => {
      isMounted = false

      // Abort the fetch if still loading
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }

      // Dispose of Three.js resources
      if (scene) {
        disposeScene(scene)
      }
    }
  }, [url])

  return { scene, sceneTree, isLoading, error }
}

/**
 * Dispose of Three.js resources to prevent memory leaks
 * @param scene - The Three.js scene/group to dispose
 */
function disposeScene(scene: THREE.Group | THREE.Object3D): void {
  scene.traverse((child) => {
    if (child instanceof THREE.Mesh) {
      // Dispose geometry
      if (child.geometry) {
        child.geometry.dispose()
      }

      // Dispose material(s)
      if (child.material) {
        if (Array.isArray(child.material)) {
          child.material.forEach((material) => material.dispose())
        } else {
          child.material.dispose()
        }
      }
    }
  })
}
