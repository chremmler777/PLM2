/**
 * The weekly meeting: Start meeting (PM); while it runs, how many lines are
 * not touched yet (the server's marks) and Close meeting; after it, Send
 * minutes once (with a confirmation), then "Minutes sent <date>". Everyone
 * sees when the last meeting was.
 */
import { useState } from 'react'
import { lopApi } from '../../api/lop'
import { shortDay } from '../../lib/lop'
import type { LopMeetingDetail, LopProjectResponse } from '../../types/lop'
import ConfirmDialog from '../common/ConfirmDialog'
import { btnSm } from '../common/buttonStyles'
import { InlineError } from './lopUi'
import { lopErrorMessage, useLopWrite } from './useLopWrite'

/** The buttons, for the toolbar (PM only). */
export function MeetingButtons({ projectId, data, detail }: {
  projectId: number; data: LopProjectResponse; detail: LopMeetingDetail | undefined
}) {
  const [confirm, setConfirm] = useState(false)
  const meeting = data.meeting
  const closedMeetingId = meeting && !meeting.open ? meeting.id : null
  const start = useLopWrite(projectId, () => lopApi.startMeeting(projectId), { fallback: 'The meeting could not be started.' })
  const close = useLopWrite(projectId, () => lopApi.closeMeeting(meeting!.id), { fallback: 'The meeting could not be closed.' })
  const minutes = useLopWrite(projectId, () => lopApi.sendMinutes(closedMeetingId!),
    { fallback: 'The minutes could not be sent.', refreshPdb: false })
  if (!data.can_manage) return null
  const thisDetail = detail && detail.id === closedMeetingId ? detail : undefined
  const sent = thisDetail?.minutes_sent_at
  const canSend = closedMeetingId != null && !!thisDetail?.closed_at && !sent
  return (
    <>
      {meeting?.open ? (
        <button type="button" className={btnSm.secondary} disabled={close.pending} onClick={() => close.run(undefined)}>Close meeting</button>
      ) : (
        <button type="button" className={btnSm.secondary} disabled={start.pending} onClick={() => start.run(undefined)}>Start meeting</button>
      )}
      {closedMeetingId != null && (sent ? (
        <span className="text-xs text-slate-400">Minutes sent {shortDay(sent)}</span>
      ) : (
        <button type="button" className={btnSm.secondary} disabled={!canSend || minutes.pending} onClick={() => setConfirm(true)}>
          Send minutes
        </button>
      ))}
      {(start.error || close.error) && <span className="basis-full"><InlineError>{start.error ?? close.error}</InlineError></span>}
      <ConfirmDialog
        open={confirm}
        title="Send minutes"
        body={`Send the minutes to the project team? Meeting of ${shortDay(meeting?.held_on)}; this is sent once.`}
        confirmLabel="Send minutes"
        errorFallback="The minutes could not be sent."
        onConfirm={() => minutes.runAsync(undefined)}
        onClose={() => setConfirm(false)}
      />
    </>
  )
}

/** The line under the toolbar: meeting running and its untouched counter, or the last meeting. */
export function MeetingStatus({ data, detail, detailError }: {
  data: LopProjectResponse; detail: LopMeetingDetail | undefined; detailError: unknown
}) {
  const meeting = data.meeting
  if (meeting?.open) {
    const marks = detail && detail.id === meeting.id ? detail.marks : null
    const untouched = marks ? marks.filter((m) => m.mark === 'none').length : null
    return (
      <p className="mb-2 text-xs text-slate-300">
        Meeting running since {shortDay(meeting.held_on)} ·{' '}
        <span data-testid="untouched-count"
          className={untouched == null ? 'text-slate-400' : untouched > 0 ? 'font-medium text-amber-300' : 'text-emerald-300'}>
          {untouched == null
            ? (detailError ? `marks could not be read: ${lopErrorMessage(detailError, 'no answer')}` : 'reading marks…')
            : untouched === 0 ? 'every line touched'
              : `${untouched} ${untouched === 1 ? 'line' : 'lines'} not touched yet`}
        </span>
      </p>
    )
  }
  if (!data.last_meeting) return <p className="mb-2 text-xs text-slate-400">No meeting held yet.</p>
  return (
    <p className="mb-2 text-xs text-slate-400">
      Last meeting {shortDay(data.last_meeting)}
      {data.untouched > 0 && <> · <span className="text-amber-300">{data.untouched} {data.untouched === 1 ? 'line was' : 'lines were'} not touched</span></>}
    </p>
  )
}
