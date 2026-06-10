import { useState, useEffect, useMemo, Suspense, useRef } from 'react'
import * as THREE from 'three'
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
import { API_BASE_URL } from '../api/client'

export interface AssemblyModel {
  id: number  // unique per model (e.g. revision file id)
  url: string
  label: string
}

interface Viewer3DProps {
  fileId: number | null  // Allow null to show "no file" state without unmounting
  viewerUrl?: string | null  // Explicit glTF URL (e.g. revision files); overrides fileId-derived URL
  models?: AssemblyModel[]  // Assembly mode: render multiple models in one scene
  onError?: (error: Error) => void
  onLoad?: () => void
  // Revision tree integration for fullscreen mode
  articleId?: number
  selectedRevisionId?: number | null
  onRevisionSelect?: (revisionId: number) => void
  sourcingType?: string
}

interface BoundingBoxInfo {
  center: [number, number, number]
  size: [number, number, number]
}

interface CameraState {
  position: [number, number, number]
  target: [number, number, number]
  zoom: number
}

export default function Viewer3D({
  fileId,
  viewerUrl,
  models,
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
  const [boundingBox, setBoundingBox] = useState<BoundingBoxInfo | null>(null)

  // Assembly mode state
  const assemblyMode = !!models && models.length > 0
  const modelsKey = models?.map((m) => `${m.id}:${m.url}`).join('|') ?? ''
  const [modelBoxes, setModelBoxes] = useState<Record<number, BoundingBoxInfo>>({})
  const [modelTrees, setModelTrees] = useState<Record<number, SceneNode>>({})
  const [loadedModels, setLoadedModels] = useState<Record<number, boolean>>({})
  const [explodeFactor, setExplodeFactor] = useState(0)

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
    if (assemblyMode) {
      setModelUrl(null)
      return
    }
    const url = viewerUrl ?? (fileId ? `${API_BASE_URL}/v1/parts/files/${fileId}/viewer` : null)
    if (url) {
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
  }, [fileId, viewerUrl, assemblyMode])

  // Reset assembly state whenever the model set changes
  useEffect(() => {
    setModelBoxes({})
    setModelTrees({})
    setLoadedModels({})
    setExplodeFactor(0)
    setBoundingBox(null)
    if (assemblyMode) {
      setLoading(true)
      setError(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelsKey])

  // Assembly: finish loading and fit camera once all models reported in
  useEffect(() => {
    if (!assemblyMode || !models) return
    if (models.every((m) => loadedModels[m.id])) {
      setLoading(false)
    }
    const boxes = models.map((m) => modelBoxes[m.id]).filter(Boolean)
    if (boxes.length === models.length && boxes.length > 0) {
      const min = [Infinity, Infinity, Infinity]
      const max = [-Infinity, -Infinity, -Infinity]
      for (const b of boxes) {
        for (let i = 0; i < 3; i++) {
          min[i] = Math.min(min[i], b.center[i] - b.size[i] / 2)
          max[i] = Math.max(max[i], b.center[i] + b.size[i] / 2)
        }
      }
      setBoundingBox({
        center: [(min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2],
        size: [max[0] - min[0], max[1] - min[1], max[2] - min[2]],
      })
    }
  }, [assemblyMode, models, loadedModels, modelBoxes])

  // Exploded view: push each model away from the assembly center
  const explodeOffsets = useMemo(() => {
    const offsets: Record<number, [number, number, number]> = {}
    if (!assemblyMode || !models || !boundingBox) return offsets
    for (const m of models) {
      const box = modelBoxes[m.id]
      if (!box) continue
      const dir = [
        box.center[0] - boundingBox.center[0],
        box.center[1] - boundingBox.center[1],
        box.center[2] - boundingBox.center[2],
      ]
      const len = Math.hypot(dir[0], dir[1], dir[2])
      // Models stacked at the same center get a small vertical separation instead
      const unit = len > 1e-6 ? dir.map((d) => d / len) : [0, 1, 0]
      const dist = explodeFactor * Math.max(...boundingBox.size) * 0.35 * (len > 1e-6 ? 1 : models.indexOf(m) / Math.max(models.length - 1, 1))
      offsets[m.id] = [unit[0] * dist, unit[1] * dist, unit[2] * dist]
    }
    return offsets
  }, [assemblyMode, models, modelBoxes, boundingBox, explodeFactor])

  // Merged scene tree for assembly mode (one branch per model)
  const assemblyTree = useMemo<SceneNode | null>(() => {
    if (!assemblyMode || !models) return null
    const children = models
      .filter((m) => modelTrees[m.id])
      .map((m) => ({ ...modelTrees[m.id], id: `model-${m.id}`, name: m.label }))
    if (children.length === 0) return null
    return {
      id: 'assembly-root',
      name: 'Assembly',
      type: 'group' as const,
      object: new THREE.Group(),
      children,
      visible: true,
    }
  }, [assemblyMode, models, modelTrees])

  // Fit camera to model's bounding box
  useEffect(() => {
    if (orbitControlsRef.current && boundingBox && !loading) {
      const controls = orbitControlsRef.current
      const camera = controls.object

      if (camera) {
        const { center, size } = boundingBox
        const maxDim = Math.max(size[0], size[1], size[2])
        const fov = camera.fov * (Math.PI / 180) // Convert to radians
        let distance = Math.abs(maxDim / 2 / Math.tan(fov / 2)) * 1.5

        // Set target to model center
        controls.target.set(center[0], center[1], center[2])

        // Position camera to view from diagonal
        const direction = Math.sqrt(2)
        camera.position.set(
          center[0] + distance / direction,
          center[1] + distance / direction,
          center[2] + distance / direction
        )

        // Adjust far plane if needed
        camera.far = distance * 10
        camera.updateProjectionMatrix()
        controls.update()
      }
    }
  }, [boundingBox, loading])

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
              tree={assemblyMode ? assemblyTree : sceneTree}
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
            <p className="text-slate-400 text-sm mt-2">{error.message}</p>
            <button
              onClick={() => {
                setError(null)
                setLoading(true)
              }}
              className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 text-sm"
            >
              Retry
            </button>
          </div>
        ) : modelUrl || assemblyMode ? (
          <Canvas camera={{ position: [15, 15, 15], fov: 50, near: 0.1, far: 1000 }} gl={{ logarithmicDepthBuffer: true }} className="w-full h-full">
            <Suspense fallback={null}>
              {assemblyMode && models ? (
                models.map((m) => (
                  <group key={m.id} position={explodeOffsets[m.id] ?? [0, 0, 0]}>
                    <Model
                      url={m.url}
                      viewMode={viewMode}
                      cutPlaneActive={isCutPlaneActive}
                      cutPlaneAxis={cutPlaneAxis}
                      cutPlanePosition={cutPlanePosition}
                      isMeasuring={isMeasuring}
                      onError={handleModelError}
                      onLoading={(isL) => {
                        if (!isL) setLoadedModels((prev) => ({ ...prev, [m.id]: true }))
                      }}
                      onSceneTreeReady={(tree) => setModelTrees((prev) => ({ ...prev, [m.id]: tree }))}
                      onMeasurementUpdate={setMeasurementResult}
                      onClearMeasurement={() => {}}
                      onBoundingBoxReady={(bbox) => setModelBoxes((prev) => ({ ...prev, [m.id]: bbox }))}
                    />
                  </group>
                ))
              ) : modelUrl ? (
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
                onBoundingBoxReady={setBoundingBox}
              />
              ) : null}
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

      {/* Exploded View Slider (assembly mode with 2+ models) */}
      {assemblyMode && (models?.length ?? 0) > 1 && !loading && (
        <div className="absolute bottom-4 left-4 z-20 bg-white/90 dark:bg-gray-800/90 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 flex items-center gap-2 shadow-lg">
          <span className="text-xs font-medium text-gray-700 dark:text-gray-300" title="Exploded view">💥</span>
          <input
            type="range"
            min="0"
            max="2"
            step="0.05"
            value={explodeFactor}
            onChange={(e) => setExplodeFactor(parseFloat(e.target.value))}
            className="w-32 accent-blue-600"
            title={`Explode: ${Math.round(explodeFactor * 50)}%`}
          />
          {explodeFactor > 0 && (
            <button
              onClick={() => setExplodeFactor(0)}
              className="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
            >
              Reset
            </button>
          )}
        </div>
      )}

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
