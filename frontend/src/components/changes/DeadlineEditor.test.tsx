import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { DeadlineEditor } from './DeadlineEditor'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'
import type { ChangeRequest } from '../../types/change'

vi.mock('../../api/changes', () => ({
  changesApi: { update: vi.fn().mockResolvedValue({}) },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const change = (over: Partial<ChangeRequest> = {}): ChangeRequest => ({
  id: 7, change_number: 'CR-2026-0007', project_id: 1, title: 'Housing fix',
  change_type: 'tooling', priority: 'medium', status: 'quoted',
  raised_by: 1, customer_response: 'pending', lead_id: 5, lead_name: 'Eva Eng',
  created_at: '2026-07-01T00:00:00', updated_at: '2026-07-01T00:00:00',
  required_by_date: null, required_by_reason: null, deadline_state: null,
  quoted_at: null, quoted_on_time: null, active_deadline: null,
  release_due_date: null, release_due_reason: null, ...over,
} as ChangeRequest)

/** Types a date (any accepted form) into the date field and commits it (blur). */
const typeDate = (container: HTMLElement, ddmmyyyy: string) => {
  const inp = container.querySelector('[data-testid="deadline-form"] input[data-date-input]')!
  fireEvent.change(inp, { target: { value: ddmmyyyy } })
  fireEvent.blur(inp)
}

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}>
    {ui}
  </QueryClientProvider>
)

describe('DeadlineEditor', () => {
  afterEach(() => { cleanup(); vi.mocked(changesApi.update).mockClear() })

  it('sets a first release deadline plainly (no existing commitment to move)', async () => {
    const { container } = render(wrap(<DeadlineEditor change={change({
      release_due_date: null, release_due_reason: null,
    })} kind="release" />))
    fireEvent.click(screen.getByTestId('deadline-edit'))
    typeDate(container, '15 Nov 2026')
    fireEvent.click(screen.getByText(t('deadline.set')))
    await waitFor(() => expect(changesApi.update).toHaveBeenCalledWith(7, {
      release_due_date: '2026-11-15T23:59:59Z', release_due_reason: null,
    }))
  })

  it('defaults to editing required_by_date (quote kind)', async () => {
    const { container } = render(wrap(<DeadlineEditor change={change({ status: 'captured', required_by_date: null })} />))
    fireEvent.click(screen.getByTestId('deadline-edit'))
    typeDate(container, '1 Sep 2026')
    fireEvent.click(screen.getByText(t('deadline.set')))
    await waitFor(() => expect(changesApi.update).toHaveBeenCalledWith(7, {
      required_by_date: '2026-09-01T23:59:59Z', required_by_reason: null,
    }))
  })

  it('keeps the quote date open for plain editing while the change is captured', async () => {
    const { container } = render(wrap(<DeadlineEditor change={change({
      status: 'captured', required_by_date: '2026-09-01T23:59:59', required_by_reason: 'customer ask',
    })} />))
    fireEvent.click(screen.getByTestId('deadline-edit'))
    // No pushback rules at capture: the reason stays optional and prefilled.
    expect((screen.getByTestId('deadline-reason') as HTMLInputElement).value).toBe('customer ask')
    expect((screen.getByTestId('deadline-save') as HTMLButtonElement).disabled).toBe(false)
    typeDate(container, '15 Sep 2026')
    fireEvent.click(screen.getByTestId('deadline-save'))
    await waitFor(() => expect(changesApi.update).toHaveBeenCalledWith(7, {
      required_by_date: '2026-09-15T23:59:59Z', required_by_reason: 'customer ask',
    }))
  })

  it('locks the quote date after capture behind a reasoned pushback', async () => {
    const { container } = render(wrap(<DeadlineEditor change={change({
      status: 'scoping', required_by_date: '2026-09-01T23:59:59', required_by_reason: 'customer ask',
    })} />))
    // Read-only until the pushback is opened: no date input, latest reason shown.
    expect(container.querySelector('[data-testid="deadline-form"]')).toBeNull()
    expect(screen.getByText('customer ask')).toBeTruthy()

    fireEvent.click(screen.getByTestId('deadline-edit'))
    // The pushback says what it moves, in plain words.
    expect(screen.getByText(t('deadline.pushbackTitle'))).toBeTruthy()
    expect(screen.getByText(t('deadline.pushbackWhy'))).toBeTruthy()
    const save = screen.getByTestId('deadline-save') as HTMLButtonElement
    // A date alone is not enough — the reason starts empty and is mandatory.
    expect((screen.getByTestId('deadline-reason') as HTMLTextAreaElement).value).toBe('')
    expect(save.disabled).toBe(true)
    typeDate(container, '5 Oct 2026')
    expect((screen.getByTestId('deadline-save') as HTMLButtonElement).disabled).toBe(true)

    fireEvent.change(screen.getByTestId('deadline-reason'),
      { target: { value: 'tool trial slipped, need 5 Oct' } })
    expect((screen.getByTestId('deadline-save') as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(screen.getByTestId('deadline-save'))
    await waitFor(() => expect(changesApi.update).toHaveBeenCalledWith(7, {
      required_by_date: '2026-10-05T23:59:59Z',
      required_by_reason: 'tool trial slipped, need 5 Oct',
    }))
  })

  it('moves an existing release deadline only with a reason (F-02)', async () => {
    const { container } = render(wrap(<DeadlineEditor change={change({
      status: 'approved', release_due_date: '2026-10-01T23:59:59', release_due_reason: 'PO timing',
    })} kind="release" />))
    expect(screen.getByTestId('deadline-edit').textContent).toBe(t('deadline.move'))
    fireEvent.click(screen.getByTestId('deadline-edit'))
    expect(screen.getByText(t('deadline.moveTitleRelease'))).toBeTruthy()
    // The previous reason is history, not a prefill to submit again.
    expect((screen.getByTestId('deadline-reason') as HTMLTextAreaElement).value).toBe('')
    typeDate(container, '15 Nov 2026')
    expect((screen.getByTestId('deadline-save') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(screen.getByTestId('deadline-reason'), { target: { value: 'customer agreed new SOP' } })
    expect((screen.getByTestId('deadline-save') as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(screen.getByTestId('deadline-save'))
    await waitFor(() => expect(changesApi.update).toHaveBeenCalledWith(7, {
      release_due_date: '2026-11-15T23:59:59Z', release_due_reason: 'customer agreed new SOP',
    }))
  })

  it('shows the date as d MMM yyyy, never the native mm/dd picker', () => {
    const { container } = render(wrap(<DeadlineEditor change={change({
      status: 'captured', required_by_date: '2026-09-01T23:59:59' })} />))
    fireEvent.click(screen.getByTestId('deadline-edit'))
    const inp = container.querySelector('[data-testid="deadline-form"] input') as HTMLInputElement
    expect(inp.value).toBe('1 Sep 2026')
    expect(container.querySelector('input[type="date"]')).toBeNull()
  })

  it('offers no deadline on a change that has ended', () => {
    for (const status of ['rejected', 'closed', 'cancelled'] as const) {
      const { container } = render(wrap(<DeadlineEditor change={change({
        status, required_by_date: '2026-09-01T23:59:59' })} />))
      expect(container.querySelector('[data-testid="deadline-edit"]')).toBeNull()
      expect(container.querySelector('[data-testid="deadline-chip"]')).toBeNull()
      cleanup()
    }
  })

  it('names the quote deadline in its save message', async () => {
    const { toast } = await import('sonner')
    const { container } = render(wrap(<DeadlineEditor change={change({ status: 'captured' })} />))
    fireEvent.click(screen.getByTestId('deadline-edit'))
    typeDate(container, '1 Sep 2026')
    fireEvent.click(screen.getByTestId('deadline-save'))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith(t('deadline.savedQuote')))
  })
})
