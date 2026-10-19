import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CloseSummary from './CloseSummary'
import { hoursApi } from '../../api/hours'
import { changesApi } from '../../api/changes'
import { changeReleaseApi } from '../../api/changeRelease'
import { t } from '../../i18n/cmLabels'

vi.mock('../../api/hours', async (orig) => ({
  ...(await orig<typeof import('../../api/hours')>()),
  hoursApi: { get: vi.fn(), book: vi.fn() },
}))
vi.mock('../../api/changes', () => ({ changesApi: { listConcerns: vi.fn() } }))
vi.mock('../../api/changeRelease', () => ({ changeReleaseApi: { get: vi.fn() } }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const HOURS = {
  change_id: 7, window_open: true, backdate_days: 21, can_coordinate: true,
  total_booked: 34, total_estimate: 40,
  departments: [
    { department_id: 2, department_name: 'Development', estimate_hours: 30, booked_hours: 34, not_booked: false },
    { department_id: 4, department_name: 'Tool Engineer', estimate_hours: 6, booked_hours: 0, not_booked: true },
  ],
  mine: [
    { department_id: 9, department_name: 'Project Manager', estimate_hours: 4, booked_hours: 0,
      prefill_hours: 4, source_label: 'your estimate: 4 h' },
  ],
  bookings: [],
}

const wrap = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <CloseSummary changeId={7} />
  </QueryClientProvider>)

describe('CloseSummary (R37: the close dialog)', () => {
  beforeEach(() => {
    vi.mocked(hoursApi.get).mockResolvedValue(HOURS as never)
    vi.mocked(hoursApi.book).mockResolvedValue(HOURS as never)
    vi.mocked(changesApi.listConcerns).mockResolvedValue([
      { id: 11, kind: 'needs_info', note: 'gate weight', is_open: false, answer_kind: 'assumed',
        assumed_value: '12', assumed_unit: 'g', confirm_by_name: 'Sam Sales', confirm_due: '2026-10-22',
        confirmed_at: null },
      // negative: a confirmed assumption and a Confirmed answer are not open
      { id: 12, kind: 'needs_info', note: 'wall', is_open: false, answer_kind: 'assumed',
        assumed_value: '2', assumed_unit: 'mm', confirmed_at: '2026-10-10T00:00:00' },
      { id: 13, kind: 'needs_info', note: 'rib', is_open: false, answer_kind: 'confirmed' },
    ] as never)
    vi.mocked(changeReleaseApi.get).mockResolvedValue({ checks: [], open_count: 0, can_release: true,
      blockers: [], lessons: { done_at: '2026-10-18', items: [
        { id: 1, title: 'Order the insert early' }, { id: 2, title: 'Gauge first' }] } } as never)
  })
  afterEach(() => { cleanup(); vi.clearAllMocks() })

  it('shows hours booked vs estimate and who has not booked', async () => {
    wrap()
    expect((await screen.findByTestId('close-hours')).textContent)
      .toBe(t('close.hours').replace('{b}', '34 h').replace('{e}', '40 h'))
    expect(screen.getByTestId('close-not-booked').textContent).toContain('Tool Engineer (6 h)')
    expect(screen.getByTestId('close-not-booked').textContent).not.toContain('Development')
  })

  it('lists only the open assumptions, and the lessons', async () => {
    wrap()
    expect((await screen.findByTestId('close-assumption-11')).textContent).toContain('12 g: gate weight')
    expect(screen.getByTestId('close-assumption-11').textContent).toContain('Sam Sales')
    expect(screen.queryByTestId('close-assumption-12')).toBeNull()
    expect(screen.queryByTestId('close-assumption-13')).toBeNull()
    expect((await screen.findByTestId('close-lessons')).textContent)
      .toBe(t('close.lessons').replace('{n}', '2').replace('{x}', 'Order the insert early; Gauge first'))
  })

  it('says so when nothing is assumed and the lessons step is open', async () => {
    vi.mocked(changesApi.listConcerns).mockResolvedValue([] as never)
    vi.mocked(changeReleaseApi.get).mockResolvedValue({ checks: [], open_count: 0, can_release: true,
      blockers: [], lessons: { items: [] } } as never)
    wrap()
    expect((await screen.findByTestId('close-lessons')).textContent).toBe(t('close.lessonsOpen'))
    expect(screen.getByTestId('close-assumptions').textContent).toBe(t('close.noAssumptions'))
  })

  it('prefills the closer\'s hours with the estimate and books it as the estimate', async () => {
    wrap()
    const input = await screen.findByTestId('close-my-hours-input-9') as HTMLInputElement
    expect(input.value).toBe('4')
    expect(screen.getByTestId('close-my-hours-9').textContent).toContain('your estimate: 4 h')
    fireEvent.click(screen.getByTestId('close-my-hours-book-9'))
    await waitFor(() => expect(hoursApi.book).toHaveBeenCalledWith(7,
      expect.objectContaining({ department_id: 9, hours: 4, source: 'estimate' })))
  })

  it('a changed number is booked as typed; nothing to book once the window closed', async () => {
    wrap()
    const input = await screen.findByTestId('close-my-hours-input-9')
    fireEvent.change(input, { target: { value: '5' } })
    fireEvent.click(screen.getByTestId('close-my-hours-book-9'))
    await waitFor(() => expect(hoursApi.book).toHaveBeenCalledWith(7,
      expect.objectContaining({ hours: 5, source: 'typed' })))
    cleanup()
    vi.mocked(hoursApi.get).mockResolvedValue({ ...HOURS, window_open: false } as never)
    wrap()
    await screen.findByTestId('close-hours')
    expect(screen.queryByTestId('close-my-hours-9')).toBeNull()
  })
})
