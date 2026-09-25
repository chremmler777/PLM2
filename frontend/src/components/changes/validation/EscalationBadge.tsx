import type { EscalationLevel } from '../../../types/validationIssue'
import { LEVEL } from './issueModel'

/** "Level 2 (project)", "L2" when compact: slate for the department, amber for the project, rose for management and customer. */
export default function EscalationBadge({ level, compact = false, unacknowledged = false }: {
  level?: EscalationLevel | null
  compact?: boolean
  /** A pending acknowledgement pulses the dot, quietly (level 2 and 3 only). */
  unacknowledged?: boolean
}) {
  if (!level) return null
  const l = LEVEL[level]
  // Level 1 is the department's own business: nobody acknowledges it.
  const pulse = unacknowledged && level >= 2
  return (
    <span data-testid={`escalation-badge-l${level}`}
      title={`Escalation level ${level}: ${l.who}${pulse ? ', not acknowledged yet' : ''}`}
      className={`inline-flex items-center gap-1.5 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${l.chip}`}>
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${l.dot} ${pulse ? 'motion-safe:animate-pulse' : ''}`}
        data-testid={pulse ? 'escalation-dot-pulse' : undefined} />
      {compact ? l.label : `Level ${level} (${l.who.toLowerCase()})`}
    </span>
  )
}
