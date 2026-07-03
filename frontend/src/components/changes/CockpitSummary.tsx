import type { ChangeDetail, Gate, GateKey } from '../../types/change'
import { STATUS_LABELS, STATUS_PILL, NEXT_STATUS, OFF_PATH_STATUSES, GATE_TARGET_STATUS } from '../../lib/changeStatus'
import { t } from '../../i18n/cmLabels'
import { DeadlineChip } from './DeadlineChip'

interface Props {
  change: ChangeDetail
  gates: Gate[]
  pendingDeviations: number
  impl?: { ready_to_go: boolean } | undefined
  onAdvance: (to: string) => void
  advancing: boolean
  /** Called with the gate's key when the user clicks a gate row — the page
      jumps to where the gate is decided (D1 tab). */
  onResolveGate?: (gateKey: GateKey) => void
  /** Called when the user clicks the impact-confirmation blocker row — the
      page jumps to the Impacted tab so it can be resolved in place. */
  onShowImpact?: () => void
}

export default function CockpitSummary({ change, gates, pendingDeviations, impl, onAdvance, advancing, onResolveGate, onShowImpact }: Props) {
  const next = NEXT_STATUS[change.status] ?? []
  const openGates = gates.filter((g) => g.decision !== 'yes')
  // A gate only blocks when it guards a transition that's currently available —
  // gates seeded 'na' but guarding a later transition are just "outstanding later".
  const blockingGates = openGates.filter((g) => next.includes(GATE_TARGET_STATUS[g.gate_key]))
  const laterGates = openGates.filter((g) => !next.includes(GATE_TARGET_STATUS[g.gate_key]))
  const overdue = change.assessments.filter((a) => a.overdue).length
  const unclaimed = change.assessments.filter(
    (a) => a.status === 'active' && a.owner_id === null).length
  // Task 18: kickoff (approved -> in_implementation) is soft-guarded on R&D's
  // impact confirmation; surface it as a blocker only once it is the live gate.
  const impactUnconfirmed = change.status === 'approved' && !change.impact_confirmed_at
  const blockers = blockingGates.length + (pendingDeviations > 0 ? 1 : 0)
    + (overdue > 0 ? 1 : 0) + (impactUnconfirmed ? 1 : 0)
  const offPath = OFF_PATH_STATUSES.includes(change.status)

  const gateRow = (g: Gate, blocking: boolean) => {
    const label = (
      <>
        {blocking && '⚠ '}{t('cockpit.gate')} {t('gate.' + g.gate_key)}:{' '}
        <span className="uppercase">{g.decision}</span>
      </>
    )
    return (
      <li key={g.gate_key} className={blocking ? 'text-amber-300' : 'text-slate-400'}>
        {onResolveGate ? (
          <button type="button"
            className="text-left hover:underline decoration-dotted underline-offset-2"
            onClick={() => onResolveGate(g.gate_key)}
            title={t('cockpit.resolveGate')}>
            {label} <span className="text-xs opacity-70">→ D1</span>
          </button>
        ) : label}
      </li>
    )
  }

  return (
    <div className="grid md:grid-cols-3 gap-3 my-4">
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
        <h3 className="text-xs uppercase tracking-wide text-slate-500 mb-2">{t('cockpit.where')}</h3>
        <span className={`px-2.5 py-1 rounded-full text-sm font-semibold ${STATUS_PILL[change.status]}`}>
          {STATUS_LABELS[change.status]}
        </span>
        {' '}
        <DeadlineChip date={change.required_by_date} state={change.deadline_state} />
        <p className="mt-3 text-sm text-slate-300">
          {t('cockpit.lead')}: <span className="text-slate-100">{change.lead_name ?? '—'}</span>
        </p>
        <p className="mt-1 text-xs text-slate-500">
          {new Date(change.created_at).toLocaleDateString()} → {new Date(change.updated_at).toLocaleDateString()}
        </p>
      </div>

      <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
        <h3 className="text-xs uppercase tracking-wide text-slate-500 mb-2">{t('cockpit.blocking')}</h3>
        {blockers === 0 && unclaimed === 0 ? (
          <>
            <p className="text-sm text-emerald-400">✓ {t('cockpit.nothingBlocking')}</p>
            {laterGates.length > 0 && (
              <ul className="space-y-1.5 text-sm mt-2">
                {laterGates.map((g) => gateRow(g, false))}
              </ul>
            )}
          </>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {blockingGates.map((g) => gateRow(g, true))}
            {pendingDeviations > 0 && (
              <li className="text-amber-300">⚠ {t('cockpit.pendingDeviations')}: {pendingDeviations}</li>
            )}
            {overdue > 0 && (
              <li className="text-red-400">⚠ {t('cockpit.overdueAssessments')}: {overdue}</li>
            )}
            {impactUnconfirmed && (
              <li className="text-amber-300">
                {onShowImpact ? (
                  <button type="button"
                    className="text-left hover:underline decoration-dotted underline-offset-2"
                    onClick={onShowImpact}>
                    ⚠ {t('impact.pending')} <span className="text-xs opacity-70">→ {t('impact.title')}</span>
                  </button>
                ) : <>⚠ {t('impact.pending')}</>}
              </li>
            )}
            {unclaimed > 0 && (
              <li className="text-slate-400">{t('cockpit.unclaimed')}: {unclaimed}</li>
            )}
            {laterGates.map((g) => gateRow(g, false))}
          </ul>
        )}
      </div>

      <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
        <h3 className="text-xs uppercase tracking-wide text-slate-500 mb-2">{t('cockpit.next')}</h3>
        {impl?.ready_to_go && (
          <span className="inline-block mb-2 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-900 text-emerald-200">
            ✓ {t('impl.readyToGo')}
          </span>
        )}
        {offPath || next.length === 0 ? (
          <p className="text-sm text-slate-400">{STATUS_LABELS[change.status]}</p>
        ) : (
          <div className="flex flex-col gap-2">
            <button
              className="bg-sky-600 hover:bg-sky-500 text-white font-semibold px-4 py-2 rounded-lg text-sm disabled:opacity-50"
              disabled={advancing}
              onClick={() => onAdvance(next[0])}>
              → {STATUS_LABELS[next[0]]}
            </button>
            {next.slice(1).map((to) => (
              <button key={to}
                className="border border-slate-600 text-slate-300 hover:bg-slate-700 px-4 py-2 rounded-lg text-sm disabled:opacity-50"
                disabled={advancing}
                onClick={() => onAdvance(to)}>
                → {STATUS_LABELS[to]}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
