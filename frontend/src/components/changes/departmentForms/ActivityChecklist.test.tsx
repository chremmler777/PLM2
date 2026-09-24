import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ActivityChecklist, { checklistProgress } from './ActivityChecklist'

const DEFS = [
  { key: 'cycle_time_change', label_de: 'Zykluszeit', label_en: 'Cycle time change', extra: false },
  { key: 'threed_change', label_de: '3D', label_en: '3D change necessary', extra: false },
]
vi.mock('../../../api/changes', () => ({
  changesApi: {
    assessmentChecklist: vi.fn(() => Promise.resolve(DEFS)),
    listConcerns: vi.fn(() => Promise.resolve([])),
  },
}))

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)

describe('checklistProgress', () => {
  it('counts answered keyed rows and names the first open one', () => {
    expect(checklistProgress(DEFS, { impacts: [
      { key: 'threed_change', answer: 'no', impacted: false }] }))
      .toEqual({ answered: 1, total: 2, firstOpen: 'cycle_time_change' })
    expect(checklistProgress(DEFS, { impacts: [
      { key: 'cycle_time_change', answer: 'yes', impacted: true },
      { key: 'threed_change', answer: 'no', impacted: false }] }))
      .toEqual({ answered: 2, total: 2, firstOpen: null })
  })
  it('does not count a legacy tick without an answer', () => {
    expect(checklistProgress(DEFS, { impacts: [
      { key: 'threed_change', impacted: true }] }).answered).toBe(0)
  })
})

describe('ActivityChecklist answers', () => {
  afterEach(cleanup)

  it('starts with nothing selected and no bulk No', async () => {
    render(wrap(<ActivityChecklist departmentId={2} value={{}} onChange={() => {}} />))
    const yes = await screen.findByTestId('check-yes-threed_change')
    expect(yes.getAttribute('aria-pressed')).toBe('false')
    expect(screen.getByTestId('check-no-threed_change').getAttribute('aria-pressed')).toBe('false')
    expect(screen.queryByText(/all no/i)).toBeNull()
  })

  it('No is stored as an answer, not dropped', async () => {
    const onChange = vi.fn()
    render(wrap(<ActivityChecklist departmentId={2} value={{}} onChange={onChange} />))
    fireEvent.click(await screen.findByTestId('check-no-threed_change'))
    expect(onChange).toHaveBeenCalledWith({ impacts: [
      { key: 'threed_change', answer: 'no', impacted: false }] })
  })

  it('Yes marks impacted and opens the remark', async () => {
    const onChange = vi.fn()
    const { rerender } = render(wrap(
      <ActivityChecklist departmentId={2} value={{}} onChange={onChange} />))
    fireEvent.click(await screen.findByTestId('check-yes-threed_change'))
    const next = onChange.mock.calls[0][0]
    expect(next.impacts[0]).toMatchObject({ key: 'threed_change', answer: 'yes', impacted: true })
    rerender(wrap(<ActivityChecklist departmentId={2} value={next} onChange={onChange} />))
    expect(screen.getByTestId('check-remark-threed_change')).toBeTruthy()
  })

  it('switching Yes to No clears the choice', async () => {
    const onChange = vi.fn()
    render(wrap(<ActivityChecklist departmentId={2} onChange={onChange}
      value={{ impacts: [{ key: 'threed_change', answer: 'yes', impacted: true, choice: 'internal' }] }} />))
    fireEvent.click(await screen.findByTestId('check-no-threed_change'))
    const row = onChange.mock.calls[0][0].impacts.find((i: { key: string }) => i.key === 'threed_change')
    expect(row).toEqual({ key: 'threed_change', answer: 'no', impacted: false })
  })

  it('highlights unanswered rows when asked', async () => {
    render(wrap(<ActivityChecklist departmentId={2} highlightOpen onChange={() => {}}
      value={{ impacts: [{ key: 'threed_change', answer: 'no', impacted: false }] }} />))
    await waitFor(() => expect(document.getElementById('check-row-cycle_time_change')
      ?.getAttribute('data-open')).toBe('true'))
    expect(document.getElementById('check-row-threed_change')?.getAttribute('data-open')).toBe('false')
  })

  it('a new free line is answered Yes', async () => {
    const onChange = vi.fn()
    render(wrap(<ActivityChecklist departmentId={2} value={{}} onChange={onChange} />))
    fireEvent.click(await screen.findByTestId('check-add-item'))
    const input = screen.getByTestId('check-free-input-0')
    fireEvent.blur(input, { target: { value: 'Hot runner: zone 3' } })
    expect(onChange).toHaveBeenLastCalledWith({ impacts: [
      { label: 'Hot runner: zone 3', answer: 'yes', impacted: true }] })
  })
})
