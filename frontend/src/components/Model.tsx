import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { Html } from '@react-three/drei'
import { useGLTFLoader } from '../hooks/useGLTFLoader'
import { useViewMode } from '../hooks/useViewMode'
import { useCutPlane } from '../hooks/useCutPlane'
import { useMeasurement } from '../hooks/useMeasurement'
import { MeasurementLine } from './MeasurementLine'

import { SceneNode } from '../hooks/useGLTFLoader'

import { MeasurementResult } from '../hooks/useMeasurement'

interface ModelProps {
  url: string
  viewMode?: 'solid' | 'wireframe'
  cutPlaneActive?: boolean
  cutPlaneAxis?: 'x' | 'y' | 'z'
  cutPlanePosition?: number
  isMeasuring?: boolean
  onError?: (error: Error) => void
  onLoading?: (isLoading: boolean) => void
  onSceneTreeReady?: (tree: SceneNode) => void
  onMeasurementUpdate?: (result: MeasurementResult) => void
  onClearMeasurement?: () => void
}

export function Model({
  url,
  viewMode = 'solid',
  cutPlaneActive = false,
  cutPlaneAxis = 'y',
  cutPlanePosition = 0,
  isMeasuring = false,
  onError,
  onLoading,
  onSceneTreeReady,
  onMeasurementUpdate,
  onClearMeasurement,
}: ModelProps) {
  const groupRef = useRef<THREE.Group>(null)
  const { scene, sceneTree, isLoading, error } = useGLTFLoader(url)

  // Apply view mode changes
  useViewMode(scene, viewMode)

  // Apply cut plane
  useCutPlane(scene, cutPlaneActive, cutPlaneAxis, cutPlanePosition)

  // Apply measurement tool
  const { result: measurementResult, clearMeasurement } = useMeasurement(scene, isMeasuring)

  // Expose clearMeasurement to parent
  useEffect(() => {
    if (onClearMeasurement) {
      // Store reference for parent to call
      (window as any).__clearMeasurement = clearMeasurement
    }
    return () => {
      delete (window as any).__clearMeasurement
    }
  }, [clearMeasurement, onClearMeasurement])

  // Notify parent when scene tree is ready
  useEffect(() => {
    if (sceneTree) {
      onSceneTreeReady?.(sceneTree)
    }
  }, [sceneTree, onSceneTreeReady])

  // Notify parent of measurement updates
  useEffect(() => {
    onMeasurementUpdate?.(measurementResult)
  }, [measurementResult, onMeasurementUpdate])

  // Notify parent of loading state
  useEffect(() => {
    onLoading?.(isLoading)
  }, [isLoading, onLoading])

  // Notify parent of errors
  useEffect(() => {
    if (error) {
      onError?.(error)
    }
  }, [error, onError])

  // If there's an error or still loading, render nothing
  // Parent component handles error/loading UI
  if (error || !scene) {
    return null
  }

  // Get color based on snap type
  const getSnapColor = (snapType?: string) => {
    switch (snapType) {
      case 'center': return '#00ff00'  // Green for circle center
      case 'vertex': return '#ffff00'  // Yellow for vertex
      case 'midpoint': return '#00ffff' // Cyan for midpoint
      default: return '#ffaa00'  // Orange for surface
    }
  }

  // Get snap indicator symbol
  const getSnapSymbol = (snapType?: string) => {
    switch (snapType) {
      case 'center': return '⊙'
      case 'vertex': return '◆'
      case 'midpoint': return '◇'
      default: return '●'
    }
  }

  return (
    <group ref={groupRef} position={[0, 0, 0]}>
      <primitive object={scene} />

      {/* Hovered point preview - fixed screen size using Html */}
      {isMeasuring && measurementResult.hoveredPoint && !measurementResult.point1 && (
        <Html position={measurementResult.hoveredPoint} center style={{ pointerEvents: 'none' }}>
          <div
            className="flex items-center justify-center text-lg font-bold select-none"
            style={{
              color: getSnapColor(measurementResult.hoveredSnapType),
              textShadow: '0 0 3px black, 0 0 3px black',
              fontSize: '16px'
            }}
          >
            {getSnapSymbol(measurementResult.hoveredSnapType)}
          </div>
        </Html>
      )}

      {/* First point marker - fixed screen size */}
      {measurementResult.point1 && !measurementResult.point2 && (
        <>
          <Html position={measurementResult.point1.position} center style={{ pointerEvents: 'none' }}>
            <div
              className="flex items-center justify-center font-bold select-none"
              style={{
                color: '#ff0000',
                textShadow: '0 0 3px black, 0 0 3px black',
                fontSize: '18px'
              }}
            >
              {getSnapSymbol(measurementResult.point1.snapType)}
            </div>
          </Html>
          {/* Hovered point preview for second point */}
          {measurementResult.hoveredPoint && (
            <Html position={measurementResult.hoveredPoint} center style={{ pointerEvents: 'none' }}>
              <div
                className="flex items-center justify-center font-bold select-none"
                style={{
                  color: getSnapColor(measurementResult.hoveredSnapType),
                  textShadow: '0 0 3px black, 0 0 3px black',
                  fontSize: '16px'
                }}
              >
                {getSnapSymbol(measurementResult.hoveredSnapType)}
              </div>
            </Html>
          )}
        </>
      )}

      {/* Full measurement line - shown when both points are clicked */}
      {measurementResult.point1 &&
        measurementResult.point2 &&
        measurementResult.distance !== null && (
          <MeasurementLine
            point1={measurementResult.point1.position}
            point2={measurementResult.point2.position}
            point1SnapType={measurementResult.point1.snapType}
            point2SnapType={measurementResult.point2.snapType}
          />
        )}
    </group>
  )
}
