import { useEffect } from 'react'
import { useThree } from '@react-three/fiber'

interface CutPlaneProps {
  active: boolean
  axis: 'x' | 'y' | 'z'
  position: number
}

export function CutPlane({ active, axis, position }: CutPlaneProps) {
  const { gl } = useThree()

  useEffect(() => {
    // Enable local clipping on the renderer
    gl.localClippingEnabled = active
  }, [active, gl])

  // This component doesn't render anything visually
  // It just handles the renderer configuration
  // The actual clipping is handled by useCutPlane hook in Model component
  return null
}
