import type { Issue } from '../../../types/changePlan'

interface Props {
  errors: Issue[]
  warnings: Issue[]
  /** Row number of a task, for "#4" references. */
  rowNo: Map<number, number>
  onFocusTask: (taskId: number) => void
}

/** The plan's errors and warnings; an issue tied to a task jumps to it. */
export default function ValidationList({ errors, warnings, rowNo, onFocusTask }: Props) {
  if (errors.length + warnings.length === 0) {
    return <p className="text-xs text-emerald-300" data-testid="gantt-validation-list">No issues. The plan is consistent.</p>
  }
  const item = (i: Issue, level: 'error' | 'warning', k: number) => {
    const dot = level === 'error' ? 'bg-red-400' : 'bg-amber-400'
    const text = (
      <>
        <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
        <span className="text-slate-200">{i.message}</span>
        {i.task_id != null && rowNo.has(i.task_id) && (
          <span className="shrink-0 text-slate-500">#{rowNo.get(i.task_id)}</span>
        )}
      </>
    )
    return (
      <li key={`${level}-${i.code}-${i.task_id ?? 'plan'}-${k}`}>
        {i.task_id != null ? (
          <button type="button" onClick={() => onFocusTask(i.task_id!)}
            className="flex w-full items-start gap-2 rounded px-2 py-1 text-left hover:bg-slate-800"
            aria-label={`Show task for: ${i.message}`}>
            {text}
          </button>
        ) : (
          <div className="flex items-start gap-2 px-2 py-1">{text}</div>
        )}
      </li>
    )
  }
  return (
    <ul className="space-y-0.5 text-xs" data-testid="gantt-validation-list">
      {errors.map((i, k) => item(i, 'error', k))}
      {warnings.map((i, k) => item(i, 'warning', k))}
    </ul>
  )
}
