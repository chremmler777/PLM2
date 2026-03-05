import { useState, useEffect, Suspense, useRef } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, Grid } from '@react-three/drei'
import { Model } from './Model'
import ViewerToolbar from './ViewerToolbar'
import { CutPlane } from './CutPlane'
import { CutPlaneControls } from './CutPlaneControls'
import { ObjectTree } from './ObjectTree'
import { MeasurementReadout } from './MeasurementReadout'
import { SceneNode } from '../hooks/useGLTFLoader'
import { useTheme } from '../contexts/ThemeContext'

interface Viewer3DProps {
  fileId: number | null  // Allow null to show "no file" state without unmounting
  onError?: (error: Error) => void
  onLoad?: () => void
  // Revision tree integration for fullscreen mode
  articleId?: number
  selectedRevisionId?: number | null
  onRevisionSelect?: (revisionId: number) => void
  sourcingType?: string
}

interface CameraState {
  position: [number, number, number]
  target: [number, number, number]
  zoom: number
}

export default function Viewer3D({
  fileId,
  onError,
  onLoad,
  articleId,
  selectedRevisionId,
  onRevisionSelect,
  sourcingType
}: Viewer3DProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const orbitControlsRef = useRef<any>(null)
  const { resolvedTheme } = useTheme()

  // Model state
  const [modelUrl, setModelUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)

  // Viewer state
  const [showGrid, setShowGrid] = useState(true)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [viewMode, setViewMode] = useState<'solid' | 'wireframe'>('solid')
  const [isMeasuring, setIsMeasuring] = useState(false)
  const [isCutPlaneActive, setIsCutPlaneActive] = useState(false)
  const [cutPlaneAxis, setCutPlaneAxis] = useState<'x' | 'y' | 'z'>('y')
  const [cutPlanePosition, setCutPlanePosition] = useState(0)

  // Object tree state
  const [sceneTree, setSceneTree] = useState<SceneNode | null>(null)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [showObjectTree, setShowObjectTree] = useState(true)

  // Measurement state
  const [measurementResult, setMeasurementResult] = useState<any>(null)

  // Camera state preservation
  const cameraStateRef = useRef<CameraState | null>(null)

  // Load preferences from localStorage
  useEffect(() => {
    try {
      const savedPrefs = localStorage.getItem('viewer3d_prefs')
      if (savedPrefs) {
        const prefs = JSON.parse(savedPrefs)
        if (prefs.viewMode) setViewMode(prefs.viewMode)
        if (prefs.showGrid !== undefined) setShowGrid(prefs.showGrid)
        if (prefs.showObjectTree !== undefined) setShowObjectTree(prefs.showObjectTree)
      }
    } catch (e) {
      console.warn('Failed to load viewer preferences:', e)
    }
  }, [])

  // Save preferences to localStorage whenever they change
  useEffect(() => {
    try {
      const prefs = {
        viewMode,
        showGrid,
        showObjectTree
      }
      localStorage.setItem('viewer3d_prefs', JSON.stringify(prefs))
    } catch (e) {
      console.warn('Failed to save viewer preferences:', e)
    }
  }, [viewMode, showGrid, showObjectTree])

  useEffect(() => {
    if (fileId) {
      // Set the model URL
      const url = `http://localhost:8000/api/files/${fileId}/viewer`
      setModelUrl(url)
      // Keep loading=true until Model component notifies it's done
      setLoading(true)
      setError(null)
    } else {
      // No file selected
      setModelUrl(null)
      setLoading(false)
      setError(null)
    }
  }, [fileId])

  // Restore camera state when file changes and controls are available
  useEffect(() => {
    if (orbitControlsRef.current && cameraStateRef.current) {
      const { position, target, zoom } = cameraStateRef.current
      const controls = orbitControlsRef.current
      const camera = controls.getCamera?.() || controls.object?.parent?.children?.[0]

      if (camera) {
        camera.position.set(...position)
        controls.target.set(...target)
        camera.zoom = zoom
        camera.updateProjectionMatrix?.()
        controls.update?.()
      }
    }
  }, [fileId])

  // Handle model loading completion
  const handleModelLoading = (isLoading: boolean) => {
    setLoading(isLoading)
    if (!isLoading && onLoad) {
      onLoad()
    }
  }

  // Handle model errors
  const handleModelError = (err: Error) => {
    setError(err)
    setLoading(false)
    onError?.(err)
  }

  // Handle fullscreen toggle
  const toggleFullscreen = () => {
    if (!document.fullscreenElement && containerRef.current) {
      containerRef.current.requestFullscreen().catch((err) => {
        console.error('Failed to enter fullscreen:', err)
      })
    } else {
      document.exitFullscreen().catch((err) => {
        console.error('Failed to exit fullscreen:', err)
      })
    }
  }

  // Handle node selection from object tree
  const handleNodeSelect = (node: SceneNode) => {
    setSelectedNodeId(node.id)
  }

  // Handle visibility toggle from object tree
  const handleToggleVisibility = (node: SceneNode) => {
    // Visibility is handled in the ObjectTree component
    // This is just a callback for any additional logic needed
  }

  // Listen for fullscreen changes
  useEffect(() => {
    const handleFullscreenChange = () => {
      const isNowFullscreen = !!document.fullscreenElement
      setIsFullscreen(isNowFullscreen)
      // Clear measurement when exiting fullscreen
      if (!isNowFullscreen) {
        setIsMeasuring(false)
        setMeasurementResult(null)
        setIsCutPlaneActive(false)
      }
    }
    document.addEventListener('fullscreenchange', handleFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange)
  }, [])

  // Handle keyboard shortcuts
  useEffect(() => {
    const handleKeydown = (e: KeyboardEvent) => {
      // Only handle shortcuts when not typing in an input
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return

      switch (e.key.toLowerCase()) {
        case 'f':
          // Fullscreen (F key)
          e.preventDefault()
          toggleFullscreen()
          break
        case 'escape':
          // Close tools (Escape key)
          setIsMeasuring(false)
          setIsCutPlaneActive(false)
          break
        case 'g':
          // Toggle grid (G key)
          setShowGrid(!showGrid)
          break
        case 'm':
          // Toggle measurement (M key)
          setIsMeasuring(!isMeasuring)
          break
        case 'c':
          // Toggle cut plane (C key)
          setIsCutPlaneActive(!isCutPlaneActive)
          break
        case 's':
          // Solid view (S key)
          if (!e.ctrlKey && !e.metaKey) {
            e.preventDefault()
            setViewMode('solid')
          }
          break
        case 'w':
          // Wireframe view (W key)
          if (!e.ctrlKey && !e.metaKey) {
            e.preventDefault()
            setViewMode('wireframe')
          }
          break
      }
    }
    window.addEventListener('keydown', handleKeydown)
    return () => window.removeEventListener('keydown', handleKeydown)
  }, [showGrid, isMeasuring, isCutPlaneActive])

  // Reset view - will be used by toolbar
  const handleResetView = () => {
    // This will be handled by passing a ref to OrbitControls
    // For now, just a placeholder
    console.log('Reset view clicked')
  }

  return (
    <div ref={containerRef} className="w-full h-full flex flex-col relative">
      {/* Loading Overlay - shown on top of Canvas while loading */}
      {loading && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-gray-50 dark:bg-gray-900 rounded-lg">
          <div className="text-center">
            <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
            <p className="text-gray-600 dark:text-gray-400 mt-4">Loading 3D model...</p>
          </div>
        </div>
      )}

      {/* Toolbar */}
      <ViewerToolbar
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        showGrid={showGrid}
        onShowGridChange={setShowGrid}
        isFullscreen={isFullscreen}
        onFullscreenToggle={toggleFullscreen}
        isMeasuring={isMeasuring}
        onMeasureToggle={() => setIsMeasuring(!isMeasuring)}
        isCutPlaneActive={isCutPlaneActive}
        onCutPlaneToggle={() => setIsCutPlaneActive(!isCutPlaneActive)}
        onResetView={handleResetView}
      />

      {/* Main Content Area with Sidebar and Canvas */}
      <div className="flex-1 flex overflow-hidden">
        {/* Object Tree Sidebar - only shown in fullscreen mode */}
        {showObjectTree && isFullscreen && (
          <div className="w-64 border-r border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-sm overflow-hidden flex flex-col">
            <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Scene Objects</h3>
              <button
                onClick={() => setShowObjectTree(false)}
                className="text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 text-lg"
              >
                ✕
              </button>
            </div>
            <ObjectTree
              tree={sceneTree}
              onSelectNode={handleNodeSelect}
              onToggleVisibility={handleToggleVisibility}
              selectedNodeId={selectedNodeId}
            />
          </div>
        )}

        {/* Sidebar Toggle Button - only shown in fullscreen mode */}
        {!showObjectTree && isFullscreen && (
          <button
            onClick={() => setShowObjectTree(true)}
            className="w-12 flex items-center justify-center border-r border-gray-300 dark:border-gray-700 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
            title="Show object tree"
          >
            <span className="text-lg">📦</span>
          </button>
        )}

      {/* 3D Canvas, Error, or No File Message */}
      <div className="flex-1 flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        {error ? (
          <div className="text-center">
            <p className="text-red-600 dark:text-red-400 font-semibold">Error loading 3D model</p>
            <p className="text-red-500 dark:text-red-400 text-sm mt-2">{error.message}</p>
            <button
              onClick={() => {
                setError(null)
                setLoading(true)
              }}
              className="mt-4 px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 text-sm"
            >
              Retry
            </button>
          </div>
        ) : modelUrl ? (
          <Canvas camera={{ position: [15, 15, 15], fov: 50, near: 0.1, far: 1000 }} gl={{ logarithmicDepthBuffer: true }} className="w-full h-full">
            <Suspense fallback={null}>
              <Model
                url={modelUrl}
                viewMode={viewMode}
                cutPlaneActive={isCutPlaneActive}
                cutPlaneAxis={cutPlaneAxis}
                cutPlanePosition={cutPlanePosition}
                isMeasuring={isMeasuring}
                onError={handleModelError}
                onLoading={handleModelLoading}
                onSceneTreeReady={setSceneTree}
                onMeasurementUpdate={setMeasurementResult}
                onClearMeasurement={() => {}}
              />
              <CutPlane
                active={isCutPlaneActive}
                axis={cutPlaneAxis}
                position={cutPlanePosition}
              />
              <OrbitControls
                ref={orbitControlsRef}
                autoRotate={false}
                enableDamping={true}
                dampingFactor={0.05}
                zoomToCursor={true}
                onChange={() => {
                  // Save camera state on change
                  if (orbitControlsRef.current) {
                    const camera = orbitControlsRef.current.object
                    cameraStateRef.current = {
                      position: [camera.position.x, camera.position.y, camera.position.z] as [number, number, number],
                      target: [orbitControlsRef.current.target.x, orbitControlsRef.current.target.y, orbitControlsRef.current.target.z] as [number, number, number],
                      zoom: camera.zoom
                    }
                  }
                }}
              />

              {/* Lighting */}
              <ambientLight intensity={0.6} />
              <directionalLight position={[10, 20, 10]} intensity={0.8} />
              <directionalLight position={[-10, -10, -10]} intensity={0.3} />

              {/* Helpers */}
              {showGrid && (
                <Grid
                  args={[30, 30]}
                  cellSize={1}
                  cellColor={resolvedTheme === 'dark' ? '#1f2937' : '#e5e7eb'}
                  sectionSize={5}
                  sectionColor={resolvedTheme === 'dark' ? '#374151' : '#9ca3af'}
                  fadeDistance={100}
                  fadeStrength={1}
                />
              )}
              <axesHelper args={[5]} />

              {/* Background */}
              <color attach="background" args={[resolvedTheme === 'dark' ? '#0f172a' : '#f9fafb']} />
            </Suspense>
          </Canvas>
        ) : (
          <div className="text-center text-gray-500 dark:text-gray-400">
            <p className="font-medium">No 3D file available</p>
            <p className="text-sm mt-1">Select a revision with a CAD file to view</p>
          </div>
        )}
      </div>
      </div>

      {/* Cut Plane Controls */}
      {isCutPlaneActive && (
        <CutPlaneControls
          axis={cutPlaneAxis}
          onAxisChange={setCutPlaneAxis}
          position={cutPlanePosition}
          onPositionChange={setCutPlanePosition}
          onClose={() => setIsCutPlaneActive(false)}
        />
      )}

      {/* Measurement Mode Indicator */}
      {isMeasuring && (
        <div className="absolute top-4 right-4 bg-blue-600 text-white px-4 py-2 rounded-lg shadow-lg text-sm font-medium z-20 animate-pulse">
          📏 Click first point to start measuring
        </div>
      )}

      {/* Measurement Readout Window */}
      {isMeasuring && measurementResult?.point1 && measurementResult?.point2 && measurementResult?.distance !== null && (
        <MeasurementReadout
          distance={measurementResult.distance}
          axisDistances={measurementResult.axisDistances}
          point1SnapType={measurementResult.point1.snapType}
          point2SnapType={measurementResult.point2.snapType}
          onClear={() => {
            // Call the clearMeasurement function exposed by Model
            if ((window as any).__clearMeasurement) {
              (window as any).__clearMeasurement()
            }
          }}
        />
      )}
    </div>
  )
}
