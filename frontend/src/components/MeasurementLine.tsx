import * as THREE from 'three'
import { Line, Html } from '@react-three/drei'

interface MeasurementLineProps {
  point1: THREE.Vector3
  point2: THREE.Vector3
  point1SnapType?: string
  point2SnapType?: string
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

export function MeasurementLine({
  point1,
  point2,
  point1SnapType,
  point2SnapType
}: MeasurementLineProps) {
  return (
    <>
      {/* Line between points */}
      <Line
        points={[point1, point2]}
        color="#ff0000"
        lineWidth={2}
        dashed={false}
      />

      {/* Fixed-size marker at point 1 */}
      <Html position={point1} center style={{ pointerEvents: 'none' }}>
        <div
          className="flex items-center justify-center font-bold select-none"
          style={{
            color: '#ff0000',
            textShadow: '0 0 3px black, 0 0 3px black, 0 0 6px white',
            fontSize: '14px'
          }}
        >
          {getSnapSymbol(point1SnapType)}
        </div>
      </Html>

      {/* Fixed-size marker at point 2 */}
      <Html position={point2} center style={{ pointerEvents: 'none' }}>
        <div
          className="flex items-center justify-center font-bold select-none"
          style={{
            color: '#ff0000',
            textShadow: '0 0 3px black, 0 0 3px black, 0 0 6px white',
            fontSize: '14px'
          }}
        >
          {getSnapSymbol(point2SnapType)}
        </div>
      </Html>
    </>
  )
}
