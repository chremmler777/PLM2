import { CHANGE_STATUS_ORDER, type ChangeStatus } from '../../types/change'
import { STATUS_LABELS, STATUS_PILL, OFF_PATH_STATUSES } from '../../lib/changeStatus'

export default function LifecycleStepper({ status }: { status: ChangeStatus }) {
  const offPath = OFF_PATH_STATUSES.includes(status)
  const idx = CHANGE_STATUS_ORDER.indexOf(status)
  return (
    <div className="flex items-center gap-1 text-xs flex-wrap">
      {offPath && (
        <span className={`px-2 py-1 rounded-full font-semibold mr-2 ${STATUS_PILL[status]}`}>
          {STATUS_LABELS[status]}
        </span>
      )}
      {CHANGE_STATUS_ORDER.map((s, i) => (
        <div key={s} className="flex items-center gap-1">
          <span className={`px-2 py-1 rounded-full ${
            offPath ? 'bg-slate-800 text-slate-600'
            : i < idx ? 'bg-emerald-900 text-emerald-200'
            : i === idx ? 'bg-sky-600 text-white'
            : 'bg-slate-800 text-slate-500'}`}>{STATUS_LABELS[s]}</span>
          {i < CHANGE_STATUS_ORDER.length - 1 && <span className="text-slate-600">→</span>}
        </div>
      ))}
    </div>
  )
}
