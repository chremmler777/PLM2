
interface ViewerToolbarProps {
  viewMode: 'solid' | 'wireframe'
  onViewModeChange: (mode: 'solid' | 'wireframe') => void
  showGrid: boolean
  onShowGridChange: (show: boolean) => void
  isFullscreen: boolean
  onFullscreenToggle: () => void
  isMeasuring: boolean
  onMeasureToggle: () => void
  isCutPlaneActive: boolean
  onCutPlaneToggle: () => void
  onResetView: () => void
}

export default function ViewerToolbar({
  viewMode,
  onViewModeChange,
  showGrid,
  onShowGridChange,
  isFullscreen,
  onFullscreenToggle,
  isMeasuring,
  onMeasureToggle,
  isCutPlaneActive,
  onCutPlaneToggle,
  onResetView,
}: ViewerToolbarProps) {
  return (
    <div className="bg-gray-100 dark:bg-gray-800 px-3 py-2 flex items-center gap-2 border-b border-gray-200 dark:border-gray-700 flex-wrap">
      {/* View Mode Toggle */}
      <div className="flex gap-1 border-r border-gray-300 dark:border-gray-700 pr-3">
        <button
          onClick={() => onViewModeChange('solid')}
          className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
            viewMode === 'solid'
              ? 'bg-blue-600 text-white'
              : 'bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-gray-600'
          }`}
          title="Solid view"
        >
          Solid
        </button>
        <button
          onClick={() => onViewModeChange('wireframe')}
          className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
            viewMode === 'wireframe'
              ? 'bg-blue-600 text-white'
              : 'bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-gray-600'
          }`}
          title="Wireframe view"
        >
          Wireframe
        </button>
      </div>

      {/* Grid Toggle */}
      <label className="flex items-center gap-1 cursor-pointer text-xs border-r border-gray-300 dark:border-gray-700 pr-3">
        <input
          type="checkbox"
          checked={showGrid}
          onChange={(e) => onShowGridChange(e.target.checked)}
          className="w-3 h-3"
        />
        <span className="text-gray-600 dark:text-gray-400">Grid</span>
      </label>

      {/* Measure Button */}
      <button
        onClick={onMeasureToggle}
        className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
          isMeasuring
            ? 'bg-green-600 text-white'
            : 'bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-gray-600'
        }`}
        title="Point-to-point measurement (click two points)"
      >
        📏 Measure
      </button>

      {/* Cut Plane Button */}
      <button
        onClick={onCutPlaneToggle}
        className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
          isCutPlaneActive
            ? 'bg-orange-600 text-white'
            : 'bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-gray-600'
        }`}
        title="Cut plane / cross-section"
      >
        ✂️ Cut
      </button>

      {/* Reset View Button */}
      <button
        onClick={onResetView}
        className="px-3 py-1 text-xs font-medium rounded bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-gray-600 transition-colors border-r border-gray-300 dark:border-gray-700 pr-3"
        title="Reset camera to home position"
      >
        🏠 Reset
      </button>

      {/* Fullscreen Button */}
      <button
        onClick={onFullscreenToggle}
        className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
          isFullscreen
            ? 'bg-blue-600 text-white'
            : 'bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-gray-600'
        }`}
        title="Toggle fullscreen (F)"
      >
        {isFullscreen ? '⛔ Exit' : '⛶ Fullscreen'}
      </button>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Instructions */}
      <div className="text-xs text-gray-500 dark:text-gray-400 max-w-xs">
        <span title="Mouse Controls: Left drag = rotate, Scroll = zoom, Right drag = pan">
          🖱️ Left: rotate • Scroll: zoom • Right: pan
        </span>
        <span className="mx-2">|</span>
        <span title="Keyboard Shortcuts: F=fullscreen, S=solid, W=wireframe, G=grid, M=measure, C=cut, Esc=close">
          ⌨️ F/S/W/G/M/C/Esc
        </span>
      </div>
    </div>
  )
}
