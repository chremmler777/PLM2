import type { IssueOut } from '../../../types/validationIssue'
import { issueSteps } from './issueModel'

/** Raised, Contained, Root cause, Route, Fixing, Re-validation, Closed. */
export default function IssueStepper({ issue }: { issue: IssueOut }) {
  const steps = issueSteps(issue)
  return (
    <ol data-testid={`issue-stepper-${issue.id}`} className="flex flex-wrap items-center gap-x-1 gap-y-1.5">
      {steps.map((s, i) => (
        <li key={s.key} data-testid={`issue-step-${issue.id}-${s.key}`} data-state={s.state}
          title={s.note} className="flex items-center gap-1">
          <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] ${
            s.state === 'done' ? 'bg-emerald-950/50 text-emerald-300'
              : s.state === 'current' ? 'bg-sky-950/60 text-sky-200 ring-1 ring-sky-700'
                : s.state === 'skipped' ? 'text-slate-600 line-through'
                  : 'text-slate-500'}`}>
            <span className={`flex h-3.5 w-3.5 items-center justify-center rounded-full text-[9px] font-semibold ${
              s.state === 'done' ? 'bg-emerald-600 text-white'
                : s.state === 'current' ? 'bg-sky-500 text-white' : 'bg-slate-700 text-slate-400'}`}>
              {s.state === 'done' ? '✓' : i + 1}
            </span>
            {s.label}
          </span>
          {i < steps.length - 1 && <span className="h-px w-2 bg-slate-700" aria-hidden />}
        </li>
      ))}
    </ol>
  )
}
