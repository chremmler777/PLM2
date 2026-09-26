/**
 * Publish a draft: valid-from date and a note. The previous version then ends
 * the day before. The date must lie after the latest published version's; a
 * date in the past needs an explicit confirmation. A change is priced with
 * the version valid on the day it was created, and lines keep the rate they
 * were costed with; backdating prices the changes created since that date
 * where a line has no rate yet, and the hours booked since then
 * (costing_rates.change_pricing_date / booking_pricing_date).
 */
import { useEffect, useId, useState } from 'react'
import Dialog from '../common/Dialog'
import Button from '../common/Button'
import DateInput from '../gantt/DateInput'
import { addDaysIso, formatCalendarDate, todayIso } from '../../lib/format'

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
  onPublish: (validFrom: string, note: string, confirmBackdated: boolean) => void
}

export default function PublishDialog({
  open, version, defaultValidFrom, defaultNote, latestValidFrom, latestVersion, changeCount,
  busy, onCancel, onPublish,
}: Props) {
  const minDate = latestValidFrom ? addDaysIso(latestValidFrom, 1) : undefined
  const [validFrom, setValidFrom] = useState('')
  const [note, setNote] = useState('')
  const [backdatedOk, setBackdatedOk] = useState(false)
  const dateId = useId()
  const noteId = useId()

  useEffect(() => {
    if (!open) return
    const today = todayIso()
    const start = defaultValidFrom ?? (minDate && minDate > today ? minDate : today)
    setValidFrom(start)
    setNote(defaultNote ?? '')
    setBackdatedOk(false)
  }, [open, defaultValidFrom, defaultNote, minDate])

  const tooEarly = !!(minDate && validFrom && validFrom < minDate)
  const backdated = !!validFrom && validFrom < todayIso()
  const endsOn = validFrom ? addDaysIso(validFrom, -1) : null
  const blocked = busy || !validFrom || tooEarly || (backdated && !backdatedOk)

  return (
    <Dialog open={open} onClose={onCancel} busy={busy} closeOnBackdrop={false} size="md"
      title={`Publish version ${version}`}
      description={<>Publishing freezes the version. Changes created from the valid-from date on are priced with it; changes created before keep their rates.</>}
      footer={(
        <>
          <Button onClick={onCancel} disabled={busy}>Cancel</Button>
          <Button variant="primary" disabled={blocked} loading={busy}
            onClick={() => onPublish(validFrom, note.trim(), backdated)}>
            Publish
          </Button>
        </>
      )}>
      <div className="space-y-4">
        <div>
          <label htmlFor={dateId} className="text-xs font-medium uppercase tracking-wide text-slate-400">Valid from</label>
          {/* The hints below follow the date while it is typed, not only on blur. */}
          <DateInput id={dateId} value={validFrom} min={minDate} aria-label="Valid from" required commitOnChange
            onChange={(iso) => { setValidFrom(iso); setBackdatedOk(false) }}
            className="mt-1 w-full rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-slate-100 focus:border-sky-500 focus:outline-none" />
          {tooEarly && (
            <span className="mt-1 block text-xs text-red-300">
              Must be after {formatCalendarDate(latestValidFrom)} (version {latestVersion}).
            </span>
          )}
          {!tooEarly && latestVersion !== null && endsOn && (
            <span data-testid="publish-ends-on" className="mt-1 block text-xs text-slate-400">
              Version {latestVersion} then ends on {formatCalendarDate(endsOn)}.
            </span>
          )}
        </div>
        {backdated && !tooEarly && (
          <div data-testid="publish-backdated" className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
            <p>
              {formatCalendarDate(validFrom)} lies in the past. Changes created since then are priced with this
              version where a line has no rate yet, and so are the hours booked since then. Lines already priced
              keep the rate they were costed with.
            </p>
            <label className="mt-2 flex items-center gap-2">
              <input type="checkbox" checked={backdatedOk} onChange={(e) => setBackdatedOk(e.target.checked)}
                className="h-4 w-4 accent-amber-500" />
              <span>Publish backdated anyway</span>
            </label>
          </div>
        )}
        <div>
          <label htmlFor={noteId} className="text-xs font-medium uppercase tracking-wide text-slate-400">Note</label>
          <textarea id={noteId} value={note} onChange={(e) => setNote(e.target.value)} rows={3}
            placeholder="e.g. Budget 2027, wage agreement from 1 January"
            className="mt-1 w-full rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-sky-500 focus:outline-none" />
        </div>
        {changeCount !== null && (
          <p className="text-sm text-slate-400">
            {changeCount === 0
              ? 'No differences to the previous version.'
              : `${changeCount} ${changeCount === 1 ? 'row differs' : 'rows differ'} from the previous version.`}
          </p>
        )}
      </div>
    </Dialog>
  )
}
