interface CutPlaneControlsProps {
  axis: 'x' | 'y' | 'z'
  onAxisChange: (axis: 'x' | 'y' | 'z') => void
  position: number
  onPositionChange: (position: number) => void
  onClose: () => void
}

export function CutPlaneControls({
  axis,
  onAxisChange,
  position,
  onPositionChange,
  onClose,
}: CutPlaneControlsProps) {
  return (
    <div className="absolute bottom-4 left-4 bg-slate-800 rounded-lg shadow-lg p-4 w-64 z-20">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-sm font-semibold text-slate-300">Cut Plane</h3>
        <button
          onClick={onClose}
          className="text-slate-400 hover:text-slate-200 text-lg leading-none"
        >
          ✕
        </button>
      </div>

      {/* Axis Selector */}
      <div className="mb-4">
        <label className="block text-xs font-medium text-slate-400 mb-2">Axis</label>
        <div className="flex gap-2">
          {(['x', 'y', 'z'] as const).map((a) => (
            <button
              key={a}
              onClick={() => onAxisChange(a)}
              className={`flex-1 py-1 text-xs font-medium rounded transition-colors ${
                axis === a
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
              }`}
            >
              {a.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Position Slider */}
      <div className="mb-4">
        <label className="block text-xs font-medium text-slate-400 mb-2">
          Position: {position.toFixed(2)}
        </label>
        <input
          type="range"
          min="-1"
          max="1"
          step="0.01"
          value={position}
          onChange={(e) => onPositionChange(parseFloat(e.target.value))}
          className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer"
        />
        <div className="flex justify-between text-xs text-slate-400 mt-1">
          <span>-1</span>
          <span>0</span>
          <span>1</span>
        </div>
      </div>

      {/* Info */}
      <p className="text-xs text-slate-400">
        Drag the slider to adjust the cutting plane position along the {axis.toUpperCase()} axis.
      </p>
    </div>
  )
}
