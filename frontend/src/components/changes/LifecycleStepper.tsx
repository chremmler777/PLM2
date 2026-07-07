import type { ChangeStatus } from '../../types/change'
import { STATUS_LABELS, STATUS_PILL, STATUS_HINTS, OFF_PATH_STATUSES, branchStepOrder } from '../../lib/changeStatus'

export default function LifecycleStepper({
  status,
  customerRelevant,
}: {
  status: ChangeStatus
  customerRelevant?: boolean
}) {
  const offPath = OFF_PATH_STATUSES.includes(status)
  const order = branchStepOrder(customerRelevant)
  const idx = order.indexOf(status)
  return (
    <div className="flex items-center gap-1 text-xs flex-wrap">
      {offPath && (
        <span className={`px-2 py-1 rounded-full font-semibold mr-2 ${STATUS_PILL[status]}`}>
          {STATUS_LABELS[status]}
        </span>
      )}
      {order.map((s, i) => (
        <div key={s} className="flex items-center gap-1">
          <div className="flex flex-col items-center">
            <span
              title={STATUS_HINTS[s]}
              className={`px-2 py-1 rounded-full ${
                offPath ? 'bg-slate-800 text-slate-600'
                : i < idx ? 'bg-emerald-900 text-emerald-200'
                : i === idx ? 'bg-sky-600 text-white'
                : 'bg-slate-800 text-slate-500'}`}>{STATUS_LABELS[s]}</span>
            {!offPath && i === idx && STATUS_HINTS[s] && (
              <span className="text-[10px] text-slate-400">{STATUS_HINTS[s]}</span>
            )}
          </div>
          {i < order.length - 1 && <span className="text-slate-600">→</span>}
        </div>
      ))}
    </div>
  )
}
