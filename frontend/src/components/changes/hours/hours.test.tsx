/** ECR-solid C15: Book hours (UI). */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { hoursApi, type HoursState } from '../../../api/hours'
import BookHoursDialog, { bookBlocked } from './BookHoursDialog'
import HoursCard from './HoursCard'

vi.mock('../../../api/hours', async (orig) => ({
  ...(await orig<typeof import('../../../api/hours')>()),
  hoursApi: { get: vi.fn(), book: vi.fn(), remove: vi.fn() },
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
