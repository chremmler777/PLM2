import type { EscalationLevel } from '../../../types/validationIssue'
import { LEVEL } from './issueModel'

/** "L2 Project": slate for the department, amber for the project, rose for management and customer. */
export default function EscalationBadge({ level, compact = false, unacknowledged = false }: {
  level?: EscalationLevel | null
  compact?: boolean
  /** A pending acknowledgement pulses the dot, quietly. */
  unacknowledged?: boolean
}) {
  if (!level) return null
  const l = LEVEL[level]
  return (
    <span data-testid={`escalation-badge-l${level}`}
      title={`Escalation level ${level}: ${l.who}${unacknowledged ? ', not acknowledged yet' : ''}`}
      className={`inline-flex items-center gap-1.5 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${l.chip}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${l.dot} ${unacknowledged ? 'animate-pulse' : ''}`} />
      {compact ? l.label : `${l.label} ${l.who}`}
    </span>
  )
}
