/**
 * Publish a draft: valid-from date and a note. The previous version then ends
 * the day before. The date must lie after the latest published version's.
 */
import { useEffect, useState } from 'react'
import { addDaysIso, formatDate, todayIso } from '../../lib/format'

interface Props {
  open: boolean
  version: number
  defaultValidFrom: string | null
  defaultNote: string | null
  /** valid_from of the latest published version, if any. */
  latestValidFrom: string | null
  latestVersion: number | null
  changeCount: number | null
  busy: boolean
  onCancel: () => void
  onPublish: (validFrom: string, note: string) => void
}

export default function PublishDialog({
  open, version, defaultValidFrom, defaultNote, latestValidFrom, latestVersion, changeCount,
  busy, onCancel, onPublish,
}: Props) {
  const minDate = latestValidFrom ? addDaysIso(latestValidFrom, 1) : undefined
  const [validFrom, setValidFrom] = useState('')
  const [note, setNote] = useState('')

  useEffect(() => {
    if (!open) return
    const today = todayIso()
    const start = defaultValidFrom ?? (minDate && minDate > today ? minDate : today)
    setValidFrom(start)
    setNote(defaultNote ?? '')
  }, [open, defaultValidFrom, defaultNote, minDate])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onCancel])

  if (!open) return null
  const tooEarly = !!(minDate && validFrom && validFrom < minDate)
  const endsOn = validFrom ? addDaysIso(validFrom, -1) : null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog"
         aria-modal="true" aria-labelledby="publish-title">
      <div className="w-full max-w-md rounded-xl border border-slate-700 bg-slate-800 shadow-2xl">
        <div className="border-b border-slate-700 px-5 py-4">
          <h2 id="publish-title" className="text-lg font-semibold text-slate-100">
            Publish version {version}
          </h2>
          <p className="mt-1 text-sm text-slate-400">
            Publishing freezes the version. Costing and the P&amp;L use it from the valid-from date on.
          </p>
        </div>
        <div className="space-y-4 px-5 py-4">
          <label className="block">
            <span className="text-xs font-medium uppercase tracking-wide text-slate-400">Valid from</span>
            <input type="date" value={validFrom} min={minDate}
                   onChange={(e) => setValidFrom(e.target.value)}
                   className="mt-1 w-full rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-slate-100 [color-scheme:dark] focus:border-sky-500 focus:outline-none" />
            {tooEarly && (
              <span className="mt-1 block text-xs text-red-300">
                Must be after {formatDate(latestValidFrom)} (version {latestVersion}).
              </span>
            )}
            {!tooEarly && latestVersion !== null && endsOn && (
              <span className="mt-1 block text-xs text-slate-500">
                Version {latestVersion} then ends on {formatDate(endsOn)}.
              </span>
            )}
          </label>
          <label className="block">
            <span className="text-xs font-medium uppercase tracking-wide text-slate-400">Note</span>
            <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3}
                      placeholder="e.g. Budget 2027, wage agreement from 1 January"
                      className="mt-1 w-full rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none" />
          </label>
          {changeCount !== null && (
            <p className="text-sm text-slate-400">
              {changeCount === 0
                ? 'No differences to the previous version.'
                : `${changeCount} ${changeCount === 1 ? 'row differs' : 'rows differ'} from the previous version.`}
            </p>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-700 px-5 py-3">
          <button type="button" onClick={onCancel} disabled={busy}
                  className="rounded-md px-4 py-2 text-sm font-medium text-slate-300 hover:bg-slate-700">
            Cancel
          </button>
          <button type="button" disabled={busy || !validFrom || tooEarly}
                  onClick={() => onPublish(validFrom, note.trim())}
                  className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50">
            {busy ? 'Publishing' : 'Publish'}
          </button>
        </div>
      </div>
    </div>
  )
}
