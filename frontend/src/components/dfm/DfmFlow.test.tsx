import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DfmFlow from './DfmFlow'
import { projectScope, toolScope, type DfmScope, type DfmTopicDetail } from '../../api/dfm'
import { makeEntry, relayTopic } from './dfmFixtures'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '/api' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

let current: DfmTopicDetail
function wrap(onOpenPdf = vi.fn(), extra: { onBack?: () => void; onPopOut?: () => void; scope?: DfmScope; autoOpenForm?: boolean } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}>
    <DfmFlow scope={extra.scope ?? toolScope(7)} topicId={1} onOpenPdf={onOpenPdf} onBack={extra.onBack ?? vi.fn()}
      onPopOut={extra.onPopOut} autoOpenForm={extra.autoOpenForm} />
  </QueryClientProvider>)
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
    clientMocks.get.mockReset(); clientMocks.post.mockReset(); clientMocks.patch.mockReset(); clientMocks.delete.mockReset()
    clientMocks.get.mockImplementation((url: string) =>
      url === '/v1/parts/7/dfm/topics/1' ? Promise.resolve({ data: current }) : Promise.resolve({ data: [] }))
    Element.prototype.scrollIntoView = vi.fn()
    localStorage.clear()
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
    expect(first.textContent).toContain('CD')
    expect(first.textContent).toContain('DFM rev 1')
    expect(within(first).getByTestId('dfm-status-1').textContent).toContain('Answered by KTX 09-20')
    expect(within(screen.getByTestId('dfm-entry-2')).getByTestId('dfm-status-2').textContent).toContain('Answered by Tier 1 09-18')
    expect(within(screen.getByTestId('dfm-entry-5')).getByTestId('dfm-status-5').textContent).toContain('Waiting on KTX · 1 day')
    expect(screen.getByTestId('dfm-entry-3').textContent).toContain('reply to #2 Forward')
    expect(screen.getByTestId('dfm-entry-4').textContent).toContain('KH')
  })

  it('draws each arrow to a marker on the receiver lane with a kind label, dashed while waiting', async () => {
    wrap()
    await screen.findByTestId('dfm-entry-5')
    const a1 = screen.getByTestId('dfm-arrow-1-ktx')
    expect(a1.getAttribute('data-direction')).toBe('right')
    expect(a1.style.left).toContain('16.6667%')
    expect(within(a1).getByTestId('dfm-kind-label').textContent).toBe('Original')
    const m1 = screen.getByTestId('dfm-marker-1-ktx')
    expect(m1.style.left).toBe('50%')
    expect(screen.getByTestId('dfm-arrow-3-ktx').getAttribute('data-direction')).toBe('left')
    expect(screen.getByTestId('dfm-arrow-5-ktx').className).toContain('border-dashed')
    expect(screen.getByTestId('dfm-arrow-4-toolmaker').className).toContain('border-solid')
  })

  it('puts a day divider in the date column whenever the date changes', async () => {
    wrap()
    const body = await screen.findByTestId('dfm-flow-body')
    await screen.findByTestId('dfm-entry-5')
    const order = Array.from(body.querySelectorAll('[data-testid^="dfm-day-"], [data-testid^="dfm-row-"]')).map((n) => n.getAttribute('data-testid'))
    expect(order).toEqual(['dfm-day-2026-09-13', 'dfm-row-1', 'dfm-day-2026-09-15', 'dfm-row-2', 'dfm-day-2026-09-18', 'dfm-row-3',
      'dfm-day-2026-09-20', 'dfm-row-4', 'dfm-day-2026-09-22', 'dfm-row-5'])
    expect(screen.getByTestId('dfm-day-2026-09-13').textContent).toContain('13 Sep')
  })

  it('shows one header row: breadcrumb back to the archive, status, actions, zoom, pop-out', async () => {
    const onBack = vi.fn()
    const onPopOut = vi.fn()
    wrap(vi.fn(), { onBack, onPopOut })
    const crumb = await screen.findByTestId('dfm-breadcrumb')
    expect(crumb.textContent).toBe('DFM archive/Gate position')
    fireEvent.click(screen.getByTestId('dfm-breadcrumb-archive'))
    expect(onBack).toHaveBeenCalled()
    fireEvent.click(screen.getByTestId('dfm-popout'))
    expect(onPopOut).toHaveBeenCalled()
    expect(screen.getByTestId('dfm-topic-status').textContent).toBe('Open')
  })

  it('hides Open in window when the flow already is in its own window', async () => {
    wrap()
    await screen.findByTestId('dfm-breadcrumb')
    expect(screen.queryByTestId('dfm-popout')).toBeNull()
  })

  it('zooms with the controls and ctrl+wheel, remembered in storage', async () => {
    wrap()
    await screen.findByTestId('dfm-entry-5')
    const level = screen.getByTestId('dfm-zoom-level')
    expect(level.textContent).toBe('100%')
    fireEvent.click(screen.getByTestId('dfm-zoom-in'))
    expect(level.textContent).toBe('110%')
    expect(screen.getByTestId('dfm-flow-body').getAttribute('data-zoom')).toBe('110')
    fireEvent.click(screen.getByTestId('dfm-zoom-out'))
    fireEvent.click(screen.getByTestId('dfm-zoom-out'))
    expect(level.textContent).toBe('90%')
    expect(localStorage.getItem('plm2.dfm.zoom')).toBe('90')
    fireEvent.wheel(screen.getByTestId('dfm-flow-viewport'), { deltaY: -100, ctrlKey: true })
    expect(level.textContent).toBe('100%')
    fireEvent.wheel(screen.getByTestId('dfm-flow-viewport'), { deltaY: 100 })
    expect(level.textContent).toBe('100%')
    // jsdom has no layout: the container reads 0 wide, so Fit lands on the floor
    fireEvent.click(screen.getByTestId('dfm-zoom-fit'))
    expect(level.textContent).toBe('50%')
  })

  it('shows compact cards below 75%, with the actions behind a small menu', async () => {
    localStorage.setItem('plm2.dfm.zoom', '70')
    wrap()
    const card = await screen.findByTestId('dfm-entry-5')
    expect(card.getAttribute('data-compact')).toBe('true')
    expect(card.textContent).not.toContain('and the rib?')
    expect(card.textContent).toContain('Question')
    expect(card.textContent).toContain('09-22')
    expect(card.textContent).toContain('Waiting on KTX')
    expect(screen.queryByTestId('dfm-action-5-answer-ktx')).toBeNull()
    fireEvent.click(within(card).getByTestId('dfm-menu-5'))
    fireEvent.click(screen.getByTestId('dfm-action-5-answer-ktx'))
    expect(screen.getByTestId('dfm-step-sentence').textContent).toBe('Answer from KTX to Toolmaker on Question #5')
    fireEvent.click(screen.getByTestId('dfm-zoom-in'))
    expect(screen.getByTestId('dfm-entry-5').getAttribute('data-compact')).toBe('false')
    expect(screen.getByTestId('dfm-entry-5').textContent).toContain('and the rib?')
  })

  it('shows the status strip, per-lane waiting counts and the legend', async () => {
    wrap()
    const strip = await screen.findByTestId('dfm-status-strip')
    expect(strip.textContent).toContain('Waiting on KTX for 1 day: Question #5 from Toolmaker')
    expect(within(strip).getByTestId('dfm-waiting-ktx').textContent).toBe('KTX1 · 1 day')
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
    fireEvent.change(within(form).getByTestId('dfm-files-input'), { target: { files: [new File([new Uint8Array([1])], 'dfm_rev2.pptx')] } })
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

  it('finishes an open topic only after a confirmation that names the waiting messages', async () => {
    clientMocks.post.mockResolvedValue({ data: relayTopic({ status: 'finished_confirmed' }) })
    wrap()
    fireEvent.click(await screen.findByTestId('dfm-finish'))
    expect(clientMocks.post).not.toHaveBeenCalled()
    const dialog = await screen.findByTestId('dfm-finish-confirm')
    expect(dialog.textContent).toContain('1 message still waits for an answer')
    fireEvent.click(within(dialog).getByTestId('confirm-ok'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/7/dfm/topics/1/close'))
  })

  it('cancelling the finish confirmation keeps the topic open', async () => {
    wrap()
    fireEvent.click(await screen.findByTestId('dfm-finish'))
    fireEvent.click(within(await screen.findByTestId('dfm-finish-confirm')).getByText('Cancel'))
    await waitFor(() => expect(screen.queryByTestId('dfm-finish-confirm')).toBeNull())
    expect(clientMocks.post).not.toHaveBeenCalled()
  })

  it('disables Finish confirmed on a topic without messages, with a reason', async () => {
    current = relayTopic({ entries: [], waiting_on: [], last_step: null, next_step: null, entry_count: 0 })
    wrap()
    const btn = await screen.findByTestId('dfm-finish') as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(btn.title).toBe('Record at least one message before finishing the topic')
    // + New DFM stays the primary action.
    expect(screen.getByTestId('dfm-new-original').className).toContain('bg-blue-600')
    expect(btn.className).not.toContain('bg-emerald')
  })

  it('disables Finish confirmed while a step form is open, so a chosen file is never thrown away', async () => {
    wrap()
    fireEvent.click(await screen.findByTestId('dfm-new-original'))
    const btn = screen.getByTestId('dfm-finish') as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(btn.title).toBe('Record or cancel the open step first')
  })

  it('shows Delete only when the topic can be deleted, confirms, deletes and goes back', async () => {
    wrap()
    await screen.findByTestId('dfm-flow')
    expect(screen.queryByTestId('dfm-delete-topic')).toBeNull()
    cleanup()
    current = relayTopic({ entries: [], waiting_on: [], last_step: null, next_step: null, entry_count: 0, can_delete: true })
    clientMocks.delete.mockResolvedValue({ status: 204 })
    const onBack = vi.fn()
    wrap(vi.fn(), { onBack })
    fireEvent.click(await screen.findByTestId('dfm-delete-topic'))
    expect(clientMocks.delete).not.toHaveBeenCalled()
    fireEvent.click(within(await screen.findByTestId('dfm-delete-confirm')).getByTestId('confirm-ok'))
    await waitFor(() => expect(clientMocks.delete).toHaveBeenCalledWith('/v1/parts/7/dfm/topics/1'))
    await waitFor(() => expect(onBack).toHaveBeenCalled())
  })

  it('deletes a topic with messages only with a reason', async () => {
    current = relayTopic({ can_delete: true, can_edit: true })
    clientMocks.delete.mockResolvedValue({ status: 204 })
    const onBack = vi.fn()
    wrap(vi.fn(), { onBack })
    fireEvent.click(await screen.findByTestId('dfm-delete-topic'))
    const dialog = await screen.findByTestId('dfm-delete-confirm')
    expect(dialog.textContent).toContain('5 messages')
    fireEvent.change(within(dialog).getByTestId('dfm-delete-reason'), { target: { value: 'Opened on the wrong tool' } })
    fireEvent.click(within(dialog).getByTestId('confirm-ok'))
    await waitFor(() => expect(clientMocks.delete).toHaveBeenCalledWith('/v1/parts/7/dfm/topics/1',
      { data: { reason: 'Opened on the wrong tool' } }))
    await waitFor(() => expect(onBack).toHaveBeenCalled())
  })

  it('is view only without tool rights: no step, finish, rename or delete', async () => {
    current = relayTopic({ can_edit: false, can_delete: false })
    wrap()
    await screen.findByTestId('dfm-flow')
    expect(screen.getByTestId('dfm-view-only')).toBeTruthy()
    for (const id of ['dfm-new-original', 'dfm-finish', 'dfm-reopen', 'dfm-rename', 'dfm-delete-topic']) {
      expect(screen.queryByTestId(id)).toBeNull()
    }
    expect(actionKeys(5)).toEqual([])
  })

  it('renames the topic inline', async () => {
    clientMocks.patch.mockResolvedValue({ data: relayTopic({ title: 'DFM rev 1' }) })
    wrap()
    fireEvent.click(await screen.findByTestId('dfm-rename'))
    const input = screen.getByTestId('dfm-rename-input') as HTMLInputElement
    expect(input.value).toBe('Gate position')
    fireEvent.change(input, { target: { value: 'DFM rev 1' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/parts/7/dfm/topics/1', { title: 'DFM rev 1' }))
    await waitFor(() => expect(screen.queryByTestId('dfm-rename-input')).toBeNull())
  })

  it('cancels a rename with Escape without saving', async () => {
    wrap()
    fireEvent.click(await screen.findByTestId('dfm-rename'))
    fireEvent.keyDown(screen.getByTestId('dfm-rename-input'), { key: 'Escape' })
    expect(screen.queryByTestId('dfm-rename-input')).toBeNull()
    expect(clientMocks.patch).not.toHaveBeenCalled()
  })

  it('opens the first-step form right away for a topic just created', async () => {
    current = relayTopic({ entries: [], waiting_on: [], last_step: null, next_step: null, entry_count: 0 })
    wrap(vi.fn(), { autoOpenForm: true })
    const form = await screen.findByTestId('dfm-entry-form')
    expect(form.getAttribute('data-kind')).toBe('original')
  })

  it('reads the topic from the project for the general tooling DFM', async () => {
    clientMocks.get.mockImplementation((url: string) =>
      url === '/v1/projects/35/dfm/topics/1' ? Promise.resolve({ data: current }) : Promise.resolve({ data: [] }))
    wrap(vi.fn(), { scope: projectScope(35) })
    await screen.findByTestId('dfm-flow-viewport')
    expect(screen.getByTestId('dfm-breadcrumb-archive').textContent).toBe('General tooling DFM')
    expect(screen.getByTestId('dfm-file-42').getAttribute('href')).toBe('/api/v1/projects/35/dfm/files/42/download')
  })

  it('renders a finished topic read-only without waiting styling', async () => {
    current = relayTopic({ status: 'finished_confirmed', closed_at: '2026-10-01T09:00:00', closed_by_name: 'Karl Huber' })
    clientMocks.post.mockResolvedValue({ data: relayTopic() })
    wrap()
    expect(await screen.findByTestId('dfm-reopen')).toBeTruthy()
    expect(screen.queryByTestId('dfm-finish')).toBeNull()
    expect(screen.queryByTestId('dfm-new-original')).toBeNull()
    expect(screen.getByTestId('dfm-flow').querySelectorAll('[data-action]')).toHaveLength(0)
    expect(arrows(5)[0].dashed).toBe('false')
    expect(screen.getByTestId('dfm-entry-5').textContent).not.toContain('Waiting')
    expect(screen.getByTestId('dfm-status-strip').textContent).toContain('Finished confirmed on 1 Oct 2026 by Karl Huber. Reopen to add messages.')
    expect(screen.getByTestId('dfm-lane-ktx').textContent).not.toContain('waiting')
    fireEvent.click(screen.getByTestId('dfm-reopen'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/7/dfm/topics/1/reopen'))
  })

  it('invites the first DFM on an empty topic', async () => {
    current = relayTopic({ entries: [], waiting_on: [], last_step: null, next_step: null, entry_count: 0 })
    wrap()
    expect((await screen.findByTestId('dfm-status-strip')).textContent).toContain('No messages yet')
  })

  it('toggles the topic body between the flow and its audit log', async () => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/7/dfm/topics/1') return Promise.resolve({ data: current })
      if (url === '/v1/parts/7/dfm/audit') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })
    wrap()
    await screen.findByTestId('dfm-flow-viewport')
    expect(screen.queryByTestId('dfm-topic-audit-log')).toBeNull()
    fireEvent.click(screen.getByTestId('dfm-audit-toggle'))
    expect(await screen.findByTestId('dfm-topic-audit-log')).toBeTruthy()
    expect(screen.queryByTestId('dfm-flow-viewport')).toBeNull()
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/parts/7/dfm/audit', expect.objectContaining({ params: expect.objectContaining({ topic_id: 1 }) }))
    fireEvent.click(screen.getByTestId('dfm-audit-toggle'))
    expect(await screen.findByTestId('dfm-flow-viewport')).toBeTruthy()
  })

  it('jumping from the audit log switches back to the flow and highlights the message', async () => {
    const auditEvents = [
      { id: 90, at: '2026-09-24T09:00:00', action: 'entry_recorded', actor: { id: 2, name: 'Engineer' },
        topic: { id: 1, title: 'Gate position' }, entry: { id: 2, kind: 'forward', party: 'ktx' }, file: null,
        details: { kind: 'forward', party: 'ktx', addressed_to: ['tier1'] } },
    ]
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/7/dfm/topics/1') return Promise.resolve({ data: current })
      if (url === '/v1/parts/7/dfm/audit') return Promise.resolve({ data: auditEvents })
      return Promise.resolve({ data: [] })
    })
    wrap()
    await screen.findByTestId('dfm-flow-viewport')
    fireEvent.click(screen.getByTestId('dfm-audit-toggle'))
    const jumpBtn = await screen.findByTestId('dfm-audit-jump-2')
    fireEvent.click(jumpBtn)
    expect(await screen.findByTestId('dfm-flow-viewport')).toBeTruthy()
    await waitFor(() => expect(screen.getByTestId('dfm-entry-2').getAttribute('data-highlighted')).toBe('true'))
  })
})
