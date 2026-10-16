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
  can_delete?: boolean
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

export const hoursKey = (changeId: number) => ['change', changeId, 'hours'] as const

export const hoursApi = {
  get: (changeId: number) =>
    client.get<HoursState>(`/v1/changes/${changeId}/hours`).then((r) => r.data),
  book: (changeId: number, body: HoursIn) =>
    client.post<HoursState>(`/v1/changes/${changeId}/hours`, body).then((r) => r.data),
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
