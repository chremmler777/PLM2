import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DfmFlow from './DfmFlow'
import type { DfmTopicDetail } from '../../api/dfm'
import { makeEntry, relayTopic } from './dfmFixtures'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '/api' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

let current: DfmTopicDetail
function wrap(onOpenPdf = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><DfmFlow partId={7} topicId={1} onOpenPdf={onOpenPdf} /></QueryClientProvider>)
  return onOpenPdf
}
const actionKeys = (id: number) =>
  Array.from(screen.getByTestId(`dfm-entry-${id}`).querySelectorAll('[data-action]')).map((b) => b.getAttribute('data-action'))
const arrows = (id: number) =>
  Array.from(screen.getByTestId(`dfm-row-${id}`).querySelectorAll('[data-testid^="dfm-arrow-"]')).map((a) => ({
    from: a.getAttribute('data-from-lane'), to: a.getAttribute('data-to-lane'), kind: a.getAttribute('data-kind'), dashed: a.getAttribute('data-dashed'),
  }))

describe('DfmFlow', () => {
  beforeEach(() => {
    current = relayTopic()
    clientMocks.get.mockReset(); clientMocks.post.mockReset()
    clientMocks.get.mockImplementation((url: string) =>
      url === '/v1/parts/7/dfm/topics/1' ? Promise.resolve({ data: current }) : Promise.resolve({ data: [] }))
    Element.prototype.scrollIntoView = vi.fn()
  })
  afterEach(() => { cleanup(); vi.useRealTimers() })

  it('renders the full relay as rows in server order, card in the sender lane, arrows to each addressee', async () => {
    wrap()
    const flow = await screen.findByTestId('dfm-flow')
    const cards = Array.from(flow.querySelectorAll('[data-testid^="dfm-entry-"]'))
    expect(cards.map((c) => c.getAttribute('data-testid'))).toEqual(['dfm-entry-1', 'dfm-entry-2', 'dfm-entry-3', 'dfm-entry-4', 'dfm-entry-5'])
    expect(cards.map((c) => c.getAttribute('data-lane'))).toEqual(['0', '1', '2', '1', '0'])
    expect(cards.map((c) => within(c as HTMLElement).getByTestId('dfm-kind-badge').textContent)).toEqual(['Original', 'Forward', 'Answer', 'Answer', 'Question'])
    expect(arrows(1)).toEqual([{ from: '0', to: '1', kind: 'original', dashed: 'false' }])
    expect(arrows(2)).toEqual([{ from: '1', to: '2', kind: 'forward', dashed: 'false' }])
    expect(arrows(3)).toEqual([{ from: '2', to: '1', kind: 'answer', dashed: 'false' }])
    expect(arrows(4)).toEqual([{ from: '1', to: '0', kind: 'answer', dashed: 'false' }])
    expect(arrows(5)).toEqual([{ from: '0', to: '1', kind: 'question', dashed: 'true' }])

    const first = screen.getByTestId('dfm-entry-1')
    expect(first.textContent).toContain('Toolmaker')
    expect(first.textContent).toContain('→ KTX')
    expect(first.textContent).toContain('09-13')
    expect(first.textContent).toContain('CD')
    expect(first.textContent).toContain('DFM rev 1')
    expect(within(first).getByTestId('dfm-status-1').textContent).toContain('Answered by KTX 09-20')
    expect(within(screen.getByTestId('dfm-entry-2')).getByTestId('dfm-status-2').textContent).toContain('Answered by Tier 1 09-18')
    expect(within(screen.getByTestId('dfm-entry-5')).getByTestId('dfm-status-5').textContent).toContain('Waiting on KTX · 1 day')
    expect(screen.getByTestId('dfm-entry-3').textContent).toContain('reply to #2 Forward')
    expect(screen.getByTestId('dfm-entry-4').textContent).toContain('KH')
  })

  it('shows the status strip, per-lane waiting counts and the legend', async () => {
    wrap()
    const strip = await screen.findByTestId('dfm-status-strip')
    expect(strip.textContent).toContain('Waiting on KTX for 1 day: Question #5 from Toolmaker')
    expect(screen.getByTestId('dfm-lane-ktx').getAttribute('data-waiting')).toBe('1')
    expect(screen.getByTestId('dfm-lane-ktx').textContent).toContain('1 waiting')
    expect(screen.getByTestId('dfm-lane-tier1').getAttribute('data-waiting')).toBe('0')
    expect(screen.getByTestId('dfm-legend').textContent).toBe('OriginalForwardAnswerQuestion')
  })

  it('says all answered when nothing waits', async () => {
    current = relayTopic({ waiting_on: [], all_answered: true, next_step: null,
      entries: relayTopic().entries.slice(0, 4) })
    wrap()
    expect((await screen.findByTestId('dfm-status-strip')).textContent).toContain('All answered')
  })

  it('offers only the valid actions per card', async () => {
    wrap()
    await screen.findByTestId('dfm-entry-5')
    expect(actionKeys(1)).toEqual(['update'])
    expect(actionKeys(2)).toEqual(['update'])
    expect(actionKeys(3)).toEqual(['ask-ktx', 'forward-toolmaker', 'update'])
    expect(actionKeys(4)).toEqual(['ask-toolmaker', 'update'])
    expect(actionKeys(5)).toEqual(['answer-ktx', 'forward-tier1', 'update'])
    expect(screen.getByTestId('dfm-action-5-answer-ktx').textContent).toBe('Answer')
    expect(screen.getByTestId('dfm-action-5-forward-tier1').textContent).toBe('Forward to Tier 1')
    expect(screen.getByTestId('dfm-action-4-ask-toolmaker').textContent).toBe('Ask again')
  })

  it('answer action opens the prefilled form and posts kind, reply_to_id and addressed_to', async () => {
    clientMocks.post.mockResolvedValue({ data: makeEntry({ id: 6 }) })
    wrap()
    fireEvent.click(await screen.findByTestId('dfm-action-5-answer-ktx'))
    const form = screen.getByTestId('dfm-entry-form')
    expect(within(form).getByTestId('dfm-step-sentence').textContent).toBe('Answer from KTX to Toolmaker on Question #5')
    fireEvent.click(within(form).getByTestId('dfm-submit'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalled())
    const fd = clientMocks.post.mock.calls[0][1] as FormData
    expect(fd.get('party')).toBe('ktx')
    expect(fd.get('kind')).toBe('answer')
    expect(fd.get('reply_to_id')).toBe('5')
    expect(JSON.parse(fd.get('addressed_to') as string)).toEqual(['toolmaker'])
  })

  it('ask again, forward and update actions prefill their step', async () => {
    wrap()
    fireEvent.click(await screen.findByTestId('dfm-action-4-ask-toolmaker'))
    expect(screen.getByTestId('dfm-step-sentence').textContent).toBe('Question from Toolmaker to KTX on Answer #4')
    fireEvent.click(screen.getByTestId('dfm-action-3-forward-toolmaker'))
    expect(screen.getByTestId('dfm-step-sentence').textContent).toBe('Forward from KTX to Toolmaker of Answer #3')
    fireEvent.click(screen.getByTestId('dfm-action-2-update'))
    expect(screen.getByTestId('dfm-step-sentence').textContent).toBe('Update of Forward #2 from KTX to Tier 1')
    expect(screen.getAllByTestId('dfm-entry-form')).toHaveLength(1)
    fireEvent.click(screen.getByTestId('dfm-new-original'))
    expect(screen.getByTestId('dfm-step-sentence').textContent).toBe('Original from Toolmaker to KTX')
  })

  it('reply link scrolls to and briefly highlights the target', async () => {
    wrap()
    await screen.findByTestId('dfm-entry-5')
    vi.useFakeTimers()
    fireEvent.click(screen.getByTestId('dfm-reply-link-5'))
    const target = screen.getByTestId('dfm-entry-4')
    expect(target.getAttribute('data-highlighted')).toBe('true')
    expect(target.scrollIntoView).toHaveBeenCalled()
    act(() => { vi.advanceTimersByTime(3000) })
    expect(target.getAttribute('data-highlighted')).toBe('false')
  })

  it('opens PDFs in the pane and downloads other files', async () => {
    const onOpenPdf = wrap()
    fireEvent.click(await screen.findByTestId('dfm-file-41'))
    expect(onOpenPdf).toHaveBeenCalledWith({
      fileId: 41, filename: 'dfm_rev1.pdf', kind: 'pdf', revisionName: 'Gate position',
      sourceLabel: 'Original #1 · Toolmaker to KTX', inlineUrl: '/api/v1/parts/7/dfm/files/41/inline',
    })
    const link = screen.getByTestId('dfm-file-42') as HTMLAnchorElement
    expect(link.tagName).toBe('A')
    expect(link.href).toContain('/api/v1/parts/7/dfm/files/42/download')
  })

  it('keeps the lane headers sticky at the top of the flow, first in the scrolling body', async () => {
    wrap()
    await screen.findByTestId('dfm-entry-1')
    const body = screen.getByTestId('dfm-flow-body')
    const header = screen.getByTestId('dfm-lane-headers')
    expect(header.className).toContain('sticky')
    expect(header.className).toContain('top-0')
    expect(body.firstElementChild).toBe(header)
  })

  it('marks an updated message and collapses the earlier version', async () => {
    const es = relayTopic().entries
    es[3] = { ...es[3], id: 6, supersedes_id: 4, history: [{ ...es[3], note: 'accepted, 2 points open' }] }
    current = relayTopic({ entries: es })
    wrap()
    const updated = await screen.findByTestId('dfm-entry-6')
    expect(updated.textContent).toContain('(updated)')
    expect(updated.textContent).not.toContain('accepted, 2 points open')
    fireEvent.click(within(updated).getByTestId('dfm-history-6'))
    expect(updated.textContent).toContain('accepted, 2 points open')
    // the question replies to the earlier version id 4 and still resolves to the current card
    expect(screen.getByTestId('dfm-entry-5').textContent).toContain('reply to #6 Answer')
  })

  it('finishes an open topic', async () => {
    clientMocks.post.mockResolvedValue({ data: relayTopic({ status: 'finished_confirmed' }) })
    wrap()
    fireEvent.click(await screen.findByTestId('dfm-finish'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/7/dfm/topics/1/close'))
  })

  it('renders a finished topic read-only without waiting styling', async () => {
    current = relayTopic({ status: 'finished_confirmed', closed_at: '2026-10-01T09:00:00' })
    clientMocks.post.mockResolvedValue({ data: relayTopic() })
    wrap()
    expect(await screen.findByTestId('dfm-reopen')).toBeTruthy()
    expect(screen.queryByTestId('dfm-finish')).toBeNull()
    expect(screen.queryByTestId('dfm-new-original')).toBeNull()
    expect(screen.getByTestId('dfm-flow').querySelectorAll('[data-action]')).toHaveLength(0)
    expect(arrows(5)[0].dashed).toBe('false')
    expect(screen.getByTestId('dfm-entry-5').textContent).not.toContain('Waiting')
    expect(screen.getByTestId('dfm-status-strip').textContent).toContain('Finished confirmed')
    expect(screen.getByTestId('dfm-lane-ktx').textContent).not.toContain('waiting')
    fireEvent.click(screen.getByTestId('dfm-reopen'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/7/dfm/topics/1/reopen'))
  })

  it('invites the first DFM on an empty topic', async () => {
    current = relayTopic({ entries: [], waiting_on: [], last_step: null, next_step: null, entry_count: 0 })
    wrap()
    expect((await screen.findByTestId('dfm-status-strip')).textContent).toContain('No messages yet')
  })
})
