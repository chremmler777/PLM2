import { useState, useRef, useCallback, useEffect } from 'react'
import { SnapType } from '../hooks/useMeasurement'

interface MeasurementReadoutProps {
  distance: number
  axisDistances?: { x: number; y: number; z: number }
  point1SnapType?: SnapType
  point2SnapType?: SnapType
  onClear?: () => void
}

const getSnapLabel = (snapType?: SnapType): string => {
  switch (snapType) {
    case 'center': return '⊙ Center'
    case 'vertex': return '◆ Vertex'
    case 'midpoint': return '◇ Midpoint'
    default: return '● Surface'
  }
}

const getSnapColor = (snapType?: SnapType): string => {
  switch (snapType) {
    case 'center': return 'text-green-600 dark:text-green-400'
    case 'vertex': return 'text-yellow-600 dark:text-yellow-400'
    case 'midpoint': return 'text-cyan-600 dark:text-cyan-400'
    default: return 'text-orange-600 dark:text-orange-400'
  }
}

export function MeasurementReadout({
  distance,
  axisDistances,
  point1SnapType,
  point2SnapType,
  onClear,
}: MeasurementReadoutProps) {
  const [position, setPosition] = useState({ x: 16, y: 16 }) // bottom-left default
  const [isDragging, setIsDragging] = useState(false)
  const dragOffset = useRef({ x: 0, y: 0 })

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    // Only drag from header area
    if ((e.target as HTMLElement).closest('button')) return

    setIsDragging(true)
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    dragOffset.current = {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top
    }
    e.preventDefault()
  }, [])

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!isDragging) return

    const newX = e.clientX - dragOffset.current.x
    const newY = window.innerHeight - e.clientY - (300 - dragOffset.current.y) // Convert to bottom-based

    // Keep within viewport bounds
    const clampedX = Math.max(0, Math.min(newX, window.innerWidth - 256))
    const clampedY = Math.max(0, Math.min(newY, window.innerHeight - 100))

    setPosition({ x: clampedX, y: clampedY })
  }, [isDragging])

  const handleMouseUp = useCallback(() => {
    setIsDragging(false)
  }, [])

  // Add/remove global mouse listeners for dragging
  useEffect(() => {
    if (isDragging) {
      window.addEventListener('mousemove', handleMouseMove)
      window.addEventListener('mouseup', handleMouseUp)
      return () => {
        window.removeEventListener('mousemove', handleMouseMove)
        window.removeEventListener('mouseup', handleMouseUp)
      }
    }
  }, [isDragging, handleMouseMove, handleMouseUp])

  return (
    <div
      className={`fixed bg-white dark:bg-gray-800 rounded-lg shadow-xl border-2 border-red-600 dark:border-red-500 w-64 z-30 font-mono ${isDragging ? 'cursor-grabbing' : ''}`}
      style={{
        left: position.x,
        bottom: position.y,
      }}
      onMouseDown={handleMouseDown}
      onMouseMove={isDragging ? (e) => handleMouseMove(e.nativeEvent) : undefined}
      onMouseUp={handleMouseUp}
      onMouseLeave={isDragging ? handleMouseUp : undefined}
    >
      {/* Draggable header */}
      <div className={`flex items-center justify-between p-3 pb-2 cursor-grab ${isDragging ? 'cursor-grabbing' : ''}`}>
        <div className="text-sm font-bold text-red-600 dark:text-red-400 flex items-center gap-2">
          <span className="text-gray-400 text-xs">⋮⋮</span>
          MEASUREMENT
        </div>
        {onClear && (
          <button
            onClick={onClear}
            className="px-2 py-1 text-xs bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 rounded text-gray-700 dark:text-gray-300 transition-colors"
            title="Clear measurement and start new"
          >
            ✕ Clear
          </button>
        )}
      </div>

      <div className="px-3 pb-3">
        <div className="border-t border-gray-300 dark:border-gray-700 pt-2 mb-2">
          <div className="text-xs space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-gray-600 dark:text-gray-400">Point 1:</span>
              <span className={`font-medium ${getSnapColor(point1SnapType)}`}>
                {getSnapLabel(point1SnapType)}
              </span>
            </div>
            <div className="text-center text-gray-400">↓</div>
            <div className="flex items-center justify-between">
              <span className="text-gray-600 dark:text-gray-400">Point 2:</span>
              <span className={`font-medium ${getSnapColor(point2SnapType)}`}>
                {getSnapLabel(point2SnapType)}
              </span>
            </div>
          </div>
        </div>

        <div className="bg-red-50 dark:bg-red-900/20 rounded p-2 mb-2">
          <div className="text-xs text-gray-600 dark:text-gray-400">Total Distance</div>
          <div className="text-2xl font-bold text-red-600 dark:text-red-400">{distance.toFixed(2)} mm</div>
        </div>

        {axisDistances && (
          <div className="bg-gray-50 dark:bg-gray-700 rounded p-2 text-xs space-y-1">
            <div className="font-bold text-gray-700 dark:text-gray-300 mb-1">Axis Breakdown:</div>
            <div className="flex justify-between text-gray-700 dark:text-gray-300">
              <span>X:</span>
              <span className="font-mono font-bold">{axisDistances.x.toFixed(2)} mm</span>
            </div>
            <div className="flex justify-between text-gray-700 dark:text-gray-300">
              <span>Y:</span>
              <span className="font-mono font-bold">{axisDistances.y.toFixed(2)} mm</span>
            </div>
            <div className="flex justify-between text-gray-700 dark:text-gray-300">
              <span>Z:</span>
              <span className="font-mono font-bold">{axisDistances.z.toFixed(2)} mm</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
