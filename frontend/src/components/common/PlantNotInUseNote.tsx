/**
 * A quiet amber hint next to a plant that is not in use yet (lib/plantNotInUse:
 * Mexico (Silao) for now). Informational only: nothing is hidden or blocked.
 * Renders nothing when none of the plants given is on the list.
 */
import { Info } from 'lucide-react'
import { plantNotInUseText, plantsNotInUse, type PlantKeys } from '../../lib/plantNotInUse'

export default function PlantNotInUseNote({ plants, className = '' }: {
  plants: readonly (PlantKeys | null | undefined)[]
  className?: string
}) {
  const hits = plantsNotInUse(plants)
  if (hits.length === 0) return null
  return (
    <p role="note" data-testid="plant-not-in-use"
      className={`flex items-start gap-1.5 text-xs leading-snug text-amber-200/80 ${className}`}>
      <Info aria-hidden="true" size={13} className="mt-px shrink-0 text-amber-300/80" />
      <span>{hits.map(plantNotInUseText).join(' ')}</span>
    </p>
  )
}
