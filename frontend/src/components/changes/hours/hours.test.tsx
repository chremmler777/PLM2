/** ECR-solid C15: Book hours (UI). */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { hoursApi, type HoursState } from '../../../api/hours'
import BookHoursDialog, { bookBlocked } from './BookHoursDialog'
import HoursCard from './HoursCard'
import BookingsDialog, { editBlocked, phaseLabel } from './BookingsDialog'
import { invalidateCosting } from '../../../lib/invalidateCosting'

vi.mock('../../../api/hours', async (orig) => ({
  ...(await orig<typeof import('../../../api/hours')>()),
  hoursApi: { get: vi.fn(), book: vi.fn(), remove: vi.fn(), update: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const state = (over: Partial<HoursState> = {}): HoursState => ({
  change_id: 7, window_open: true, window_until: null, backdate_days: 21, can_coordinate: false,
  departments: [
    { department_id: 2, department_name: 'Development', estimate_hours: 6, booked_hours: 0, not_booked: true },
    { department_id: 4, department_name: 'Tool Engineer', estimate_hours: 10, booked_hours: 4, not_booked: false },
  ],
  total_booked: 4, total_estimate: 16,
  mine: [{ department_id: 2, department_name: 'Development', estimate_hours: 6, booked_hours: 0,
    prefill_hours: 6, source_label: 'your estimate: 6 h' }],
  bookings: [], ...over,
})
const wrap = (ui: React.ReactElement) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)

afterEach(cleanup)
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(hoursApi.get).mockResolvedValue(state())
  vi.mocked(hoursApi.book).mockResolvedValue(state())
})

describe('bookBlocked', () => {
  it('NEGATIVE: no department, zero hours, more than a day, the future, older than 21 days', () => {
    expect(bookBlocked(null, '2', '2026-10-15', '2026-10-15')).not.toBeNull()
    expect(bookBlocked(2, '0', '2026-10-15', '2026-10-15')).not.toBeNull()
    expect(bookBlocked(2, '25', '2026-10-15', '2026-10-15')).not.toBeNull()
    expect(bookBlocked(2, '2', '2026-10-16', '2026-10-15')).not.toBeNull()
    expect(bookBlocked(2, '2', '2026-09-23', '2026-10-15')).not.toBeNull()
    expect(bookBlocked(2, '2', '2026-09-24', '2026-10-15')).toBeNull()
  })
})

describe('BookHoursDialog', () => {
  it('the confirm comes prefilled with the estimate and books it as a confirmed estimate', async () => {
    wrap(<BookHoursDialog changeId={7} open onClose={() => {}} confirm initialDepartmentId={2}
      departments={[{ id: 2, name: 'Development' }]} myDepartmentIds={[2]} />)
    await waitFor(() => expect((screen.getByTestId('book-hours-hours') as HTMLInputElement).value).toBe('6'))
    expect(screen.getByTestId('book-hours-source').textContent).toBe('your estimate: 6 h')
    fireEvent.click(screen.getByText('Book'))
    await waitFor(() => expect(hoursApi.book).toHaveBeenCalled())
    expect(vi.mocked(hoursApi.book).mock.calls[0][1]).toMatchObject({ department_id: 2, hours: 6, source: 'estimate' })
  })
  it('a changed number is typed, not a confirmed estimate', async () => {
    wrap(<BookHoursDialog changeId={7} open onClose={() => {}} confirm initialDepartmentId={2}
      departments={[{ id: 2, name: 'Development' }]} myDepartmentIds={[2]} />)
    await waitFor(() => expect((screen.getByTestId('book-hours-hours') as HTMLInputElement).value).toBe('6'))
    fireEvent.change(screen.getByTestId('book-hours-hours'), { target: { value: '4.5' } })
    fireEvent.click(screen.getByText('Book'))
    await waitFor(() => expect(hoursApi.book).toHaveBeenCalled())
    expect(vi.mocked(hoursApi.book).mock.calls[0][1]).toMatchObject({ hours: 4.5, source: 'typed' })
  })
  it('NEGATIVE: only my departments are offered; coordination only for the lead', async () => {
    wrap(<BookHoursDialog changeId={7} open onClose={() => {}}
      departments={[{ id: 2, name: 'Development' }, { id: 4, name: 'Tool Engineer' }]} myDepartmentIds={[2]} />)
    await waitFor(() => expect(hoursApi.get).toHaveBeenCalled())
    const opts = [...(screen.getByTestId('book-hours-dept') as HTMLSelectElement).options].map((o) => o.text)
    expect(opts).not.toContain('Tool Engineer')
    expect(screen.queryByTestId('book-hours-coordination')).toBeNull()
  })
  it('A5-04: the lead books for a department with no member here, worded', async () => {
    vi.mocked(hoursApi.get).mockResolvedValue(state({
      mine: [{ department_id: 4, department_name: 'Tool Engineer', estimate_hours: 10, booked_hours: 4,
        prefill_hours: 6, no_member: true,
        source_label: 'Tool Engineer has no member here: Holmes coordinates; its estimate: 10 h, 4 h booked' }],
    }))
    wrap(<BookHoursDialog changeId={7} open onClose={() => {}}
      departments={[{ id: 2, name: 'Development' }, { id: 4, name: 'Tool Engineer' }]} myDepartmentIds={[2]} />)
    await waitFor(() => expect([...(screen.getByTestId('book-hours-dept') as HTMLSelectElement).options]
      .map((o) => o.text)).toContain('Tool Engineer'))
    fireEvent.change(screen.getByTestId('book-hours-dept'), { target: { value: '4' } })
    expect(screen.getByTestId('book-hours-source').textContent).toContain('Holmes coordinates')
  })
})

describe('HoursCard', () => {
  it('names the department with an estimate and no booking', async () => {
    wrap(<HoursCard changeId={7} canBook />)
    await waitFor(() => expect(screen.getByTestId('hours-card')).toBeTruthy())
    expect(screen.getByTestId('hours-not-booked-2').textContent).toBe('not booked')
    expect(screen.queryByTestId('hours-not-booked-4')).toBeNull()
    expect(screen.getByTestId('hours-total').textContent).toBe('4 h booked of 16 h estimated')
  })
  it('NEGATIVE: no Book button once the window closed', async () => {
    vi.mocked(hoursApi.get).mockResolvedValue(state({ window_open: false }))
    wrap(<HoursCard changeId={7} canBook />)
    await waitFor(() => expect(screen.getByTestId('hours-card')).toBeTruthy())
    expect(screen.queryByTestId('hours-book')).toBeNull()
  })
})

// Christoph 2026-11-08: correct booked hours (edit / delete) in a table
const booking = (id: number, over: Partial<HoursState['bookings'][number]> = {}) => ({
  id, department_id: 2, department_name: 'Development', hours: 3, work_date: '2026-11-02',
  source: 'typed' as const, booked_by_name: 'Apurva', note: 'first look', phase: 'assessment',
  can_edit: true, can_delete: true, ...over,
})

describe('BookingsDialog', () => {
  const withBookings = () => vi.mocked(hoursApi.get).mockResolvedValue(state({ bookings: [
    booking(11), booking(12, { hours: 2, phase: 'costing', booked_by_name: 'Holmes', note: null }),
    booking(13, { department_id: 4, department_name: 'Tool Engineer', can_edit: false, can_delete: false }),
  ] }))
  it('lists the department\'s bookings with date, person, hours, phase, note and their sum', async () => {
    withBookings()
    wrap(<BookingsDialog changeId={7} open onClose={() => {}} departmentId={2}
      departments={[{ id: 2, name: 'Development' }]} />)
    await waitFor(() => expect(screen.getByTestId('booking-row-11')).toBeTruthy())
    expect(screen.queryByTestId('booking-row-13')).toBeNull()
    expect(screen.getByTestId('booking-row-12').textContent).toContain('Costing')
    expect(screen.getByTestId('booking-row-11').textContent).toContain('Assessment')
    expect(screen.getByTestId('bookings-sum').textContent).toBe('Total: 5 h')
  })
  it('edits hours and note inline, sends only what changed and refreshes the costing', async () => {
    withBookings()
    vi.mocked(hoursApi.update).mockResolvedValue(state())
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const spy = vi.spyOn(qc, 'invalidateQueries')
    render(<QueryClientProvider client={qc}><BookingsDialog changeId={7} open onClose={() => {}}
      departmentId={2} departments={[{ id: 2, name: 'Development' }]} /></QueryClientProvider>)
    await waitFor(() => expect(screen.getByTestId('booking-edit-11')).toBeTruthy())
    fireEvent.click(screen.getByTestId('booking-edit-11'))
    fireEvent.change(screen.getByTestId('booking-hours-11'), { target: { value: '2.5' } })
    fireEvent.change(screen.getByTestId('booking-note-11'), { target: { value: 'corrected' } })
    fireEvent.click(screen.getByTestId('booking-save-11'))
    await waitFor(() => expect(hoursApi.update).toHaveBeenCalled())
    expect(vi.mocked(hoursApi.update).mock.calls[0]).toEqual([7, 11, { hours: 2.5, note: 'corrected' }])
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['costing-positions', 7] }))
  })
  it('delete asks in an inline row first, then deletes', async () => {
    withBookings()
    vi.mocked(hoursApi.remove).mockResolvedValue(state())
    wrap(<BookingsDialog changeId={7} open onClose={() => {}} departmentId={2}
      departments={[{ id: 2, name: 'Development' }]} />)
    await waitFor(() => expect(screen.getByTestId('booking-delete-12')).toBeTruthy())
    fireEvent.click(screen.getByTestId('booking-delete-12'))
    expect(hoursApi.remove).not.toHaveBeenCalled()
    expect(screen.getByTestId('booking-confirm-12').textContent).toContain('Delete 2 h')
    fireEvent.click(screen.getByTestId('booking-delete-yes-12'))
    await waitFor(() => expect(hoursApi.remove).toHaveBeenCalledWith(7, 12))
  })
  it('NEGATIVE: a booking that is not mine to correct is read only; a closed window allows nothing', async () => {
    withBookings()
    wrap(<BookingsDialog changeId={7} open onClose={() => {}} departmentId={4}
      departments={[{ id: 4, name: 'Tool Engineer' }]} />)
    await waitFor(() => expect(screen.getByTestId('booking-row-13')).toBeTruthy())
    expect(screen.queryByTestId('booking-edit-13')).toBeNull()
    expect(screen.queryByTestId('booking-delete-13')).toBeNull()
    cleanup()
    vi.mocked(hoursApi.get).mockResolvedValue(state({ window_open: false, bookings: [booking(11)] }))
    wrap(<BookingsDialog changeId={7} open onClose={() => {}} departmentId={2}
      departments={[{ id: 2, name: 'Development' }]} />)
    await waitFor(() => expect(screen.getByTestId('booking-row-11')).toBeTruthy())
    expect(screen.queryByTestId('booking-edit-11')).toBeNull()
  })
  it('NEGATIVE: editBlocked refuses 0, more than a day, a new date in the future or too old', () => {
    expect(editBlocked('0', '2026-11-02', '2026-11-02', '2026-11-08')).not.toBeNull()
    expect(editBlocked('25', '2026-11-02', '2026-11-02', '2026-11-08')).not.toBeNull()
    expect(editBlocked('2', '2026-11-09', '2026-11-02', '2026-11-08')).not.toBeNull()
    expect(editBlocked('2', '2026-10-01', '2026-11-02', '2026-11-08')).not.toBeNull()
    // an old date that is not changed stays allowed
    expect(editBlocked('2', '2026-10-01', '2026-10-01', '2026-11-08')).toBeNull()
  })
  it('phase words', () => {
    expect(phaseLabel({ phase: 'costing', activity: null })).toBe('Costing')
    expect(phaseLabel({ phase: 'assessment', activity: 'coordination' })).toBe('Assessment, coordination')
  })
})

describe('invalidateCosting', () => {
  it('refreshes the lines, the summation, the change (finalize check, waits, hours) and the actions', () => {
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    invalidateCosting(qc, 7)
    const keys = spy.mock.calls.map((c) => JSON.stringify((c[0] as { queryKey: unknown }).queryKey))
    for (const k of [['costing-positions', 7], ['change-summation', 7], ['change', 7], ['change-my-actions', 7]]) {
      expect(keys).toContain(JSON.stringify(k))
    }
  })
})
