import client from './client'

/** ECR-solid C15: book hours on a change (any open change, until 7 days after close). */
export interface HoursBooking {
  id: number
  department_id: number
  department_name?: string | null
  hours: number
  work_date?: string | null
  source: 'estimate' | 'typed'
  booked_for?: string | null
  activity?: 'coordination' | null
  note?: string | null
  booked_by_name?: string | null
  status_at_booking?: string | null
  booked_by?: number | null
  /** Christoph 2026-11-08: where it counts: 'assessment' (up to the
   *  department's submit), 'costing' (after it, before the offer), else the
   *  change status it was booked in */
  phase?: string | null
  /** the booker, the department (members, manager) or an admin */
  can_delete?: boolean
  can_edit?: boolean
}

export interface HoursDepartment {
  department_id: number
  department_name?: string | null
  estimate_hours?: number | null
  booked_hours: number
  /** an estimate and no booking: "not booked", never 0 */
  not_booked: boolean
}

export interface HoursMine {
  department_id: number
  department_name?: string | null
  estimate_hours?: number | null
  booked_hours: number
  /** what is left of the estimate, for the one prefilled confirm */
  prefill_hours?: number | null
  /** "your estimate: 6 h" */
  source_label?: string | null
  /** A5-04 b: a department with no member here the lead or PM books for. */
  no_member?: boolean
}

export interface HoursState {
  change_id: number
  window_open: boolean
  window_until?: string | null
  backdate_days: number
  can_coordinate: boolean
  departments: HoursDepartment[]
  total_booked: number
  total_estimate: number
  mine: HoursMine[]
  bookings: HoursBooking[]
}

export interface HoursIn {
  department_id: number
  hours: number
  work_date?: string
  booked_for?: string
  coordination?: boolean
  source?: 'estimate' | 'typed'
  note?: string
}

export interface HoursPatch {
  hours?: number
  work_date?: string
  note?: string | null
}

export const hoursKey = (changeId: number) => ['change', changeId, 'hours'] as const

export const hoursApi = {
  get: (changeId: number) =>
    client.get<HoursState>(`/v1/changes/${changeId}/hours`).then((r) => r.data),
  book: (changeId: number, body: HoursIn) =>
    client.post<HoursState>(`/v1/changes/${changeId}/hours`, body).then((r) => r.data),
  /** Christoph 2026-11-08: correct a booking (hours, day worked, note). */
  update: (changeId: number, bookingId: number, body: HoursPatch) =>
    client.patch<HoursState>(`/v1/changes/${changeId}/hours/${bookingId}`, body).then((r) => r.data),
  remove: (changeId: number, bookingId: number) =>
    client.delete<HoursState>(`/v1/changes/${changeId}/hours/${bookingId}`).then((r) => r.data),
}

/** Ask the change page to open the Book hours dialog (from any tab). With
 *  confirm, it opens prefilled with the department's estimate: the one
 *  confirm at the department's last action. */
export const BOOK_HOURS_EVENT = 'plm2:book-hours'
export function requestBookHours(detail: { departmentId?: number; confirm?: boolean } = {}) {
  window.dispatchEvent(new CustomEvent(BOOK_HOURS_EVENT, { detail }))
}

/** Christoph 2026-11-08: open the "Booked hours" correction table (edit or
 *  delete bookings), optionally for one department. */
export const HOURS_CORRECTION_EVENT = 'plm2:hours-correction'
export function requestHoursCorrection(detail: { departmentId?: number } = {}) {
  window.dispatchEvent(new CustomEvent(HOURS_CORRECTION_EVENT, { detail }))
}
