import type { ReactNode } from 'react'
import type { RoleStage } from './uiTokens'

//: Small shared pieces of the Training page, the run page and the handout.

const STAGE: Record<RoleStage, { label: string; pill: string }> = {
  not_started: { label: 'Not started', pill: 'bg-slate-700 text-slate-200' },
  tasks_open: { label: 'Tasks open', pill: 'bg-sky-900 text-sky-200' },
  signed_off: { label: 'Signed off', pill: 'bg-emerald-900 text-emerald-200' },
  retrain_due: { label: 'Re-training due', pill: 'bg-amber-900 text-amber-200' },
}

export function StagePill({ stage }: { stage: RoleStage }) {
  const s = STAGE[stage]
  return (
    <span
      data-testid={`stage-${stage}`}
      className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium ${s.pill}`}
    >
      {s.label}
    </span>
  )
}

const NOTICE_TONES = {
  ok: 'border-emerald-700/50 bg-emerald-950/30 text-emerald-100',
  info: 'border-sky-700/50 bg-sky-950/30 text-sky-100',
  warn: 'border-amber-600/50 bg-amber-950/30 text-amber-100',
} as const

export function Notice({
  tone,
  title,
  children,
}: {
  tone: keyof typeof NOTICE_TONES
  title: string
  children?: ReactNode
}) {
  return (
    <div className={`rounded-lg border px-4 py-3 ${NOTICE_TONES[tone]}`}>
      <div className="text-sm font-semibold">{title}</div>
      {children && <div className="mt-1 text-sm leading-relaxed opacity-90">{children}</div>}
    </div>
  )
}

/**
 * Practice tasks written for a role that the training copy cannot run yet.
 * Listed so the plan is visible; never a button, never part of the record.
 */
export function ComingTasks({ tasks }: { tasks: { key: string; title: string }[] }) {
  if (tasks.length === 0) return null
  return (
    <div data-testid="coming-tasks">
      <div className="mb-1.5 text-[11px] uppercase tracking-wide text-slate-400 print:text-slate-600">
        Coming later
      </div>
      <ul className="space-y-1">
        {tasks.map((t) => (
          <li key={t.key} className="flex items-center gap-2 text-sm">
            <span
              aria-hidden
              className="inline-flex h-4 w-4 shrink-0 rounded-full border border-dashed border-slate-600"
            />
            <span className="text-slate-400 print:text-slate-700">{t.title}</span>
          </li>
        ))}
      </ul>
      <p className="mt-1.5 text-[11px] text-slate-400 print:text-slate-600">
        Not part of the check yet. They join it once the training copy can run them.
      </p>
    </div>
  )
}
