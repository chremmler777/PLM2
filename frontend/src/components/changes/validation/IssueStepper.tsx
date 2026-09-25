import { Check } from 'lucide-react'
import type { IssueOut } from '../../../types/validationIssue'
import { issueSteps, type StepState } from './issueModel'

/** Read aloud before each step: what the chip's look says. */
const SR: Record<StepState, string> = { done: 'done', current: 'next', todo: 'to do', skipped: 'skipped' }

/**
 * Raised, Contained, Root cause, Route, Fixing, Re-validation, Closed.
 * Done steps are filled with a check; the current step is the next one to
 * do, so it is outlined (dashed) rather than filled: a filled chip would read
 * as already reached.
 */
export default function IssueStepper({ issue }: { issue: IssueOut }) {
  const steps = issueSteps(issue)
  return (
    <ol data-testid={`issue-stepper-${issue.id}`} aria-label={`Progress of issue VI-${issue.number}`}
      className="flex flex-wrap items-center gap-x-1 gap-y-1.5">
      {steps.map((s, i) => (
        <li key={s.key} data-testid={`issue-step-${issue.id}-${s.key}`} data-state={s.state}
          aria-current={s.state === 'current' ? 'step' : undefined}
          title={s.note} className="flex items-center gap-1">
          <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] ${
            s.state === 'done' ? 'bg-emerald-950/50 text-emerald-300'
              : s.state === 'current' ? 'border border-dashed border-sky-500 text-sky-200'
                : s.state === 'skipped' ? 'text-slate-400 line-through'
                  : 'text-slate-400'}`}>
            <span className={`flex h-4 w-4 items-center justify-center rounded-full text-[11px] font-semibold ${
              s.state === 'done' ? 'bg-emerald-600 text-white'
                : s.state === 'current' ? 'border border-sky-500 text-sky-200' : 'bg-slate-700 text-slate-300'}`}>
              {s.state === 'done' ? <Check aria-hidden="true" size={10} strokeWidth={3} /> : i + 1}
            </span>
            <span className="sr-only">{SR[s.state]}:</span>
            {s.label}
            {s.state === 'current' && s.note && <span className="text-sky-300/80">({s.note})</span>}
          </span>
          {i < steps.length - 1 && <span className="h-px w-2 bg-slate-700" aria-hidden />}
        </li>
      ))}
    </ol>
  )
}
