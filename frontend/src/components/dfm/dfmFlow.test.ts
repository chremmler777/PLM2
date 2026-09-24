import { describe, it, expect } from 'vitest'
import {
  arrowSpan, cardActions, cardLane, currentIds, dayLabel, entryDay, flowRows, formatDays, initials, laneCenterPct,
  lastStepText, newOriginalStep, nextStepText, PARTY_STYLE, shortDate, sourceLabel, stepSentence, waitingSummary,
} from './dfmFlow'
import { makeEntry, relayEntries, relaySummary } from './dfmFixtures'

const keys = (id: number) => { const es = relayEntries(); return cardActions(es.find((e) => e.id === id)!, es).map((a) => a.key) }

describe('dfmFlow helpers', () => {
  it('initials, short dates and days', () => {
    expect(initials('Christoph Demmler')).toBe('CD')
    expect(initials('karl')).toBe('K')
    expect(initials(null)).toBe('?')
    expect(shortDate('2026-09-24')).toBe('09-24')
    expect(shortDate('2026-09-24T10:00:00')).toBe('09-24')
    expect(formatDays(0)).toBe('today')
    expect(formatDays(1)).toBe('1 day')
    expect(formatDays(4)).toBe('4 days')
  })

  it('places cards on the sender lane and arrows from the card edge to the receiver lane line', () => {
    expect(laneCenterPct(0)).toBeCloseTo(16.667, 2)
    expect(laneCenterPct(2)).toBeCloseTo(83.333, 2)
    expect(cardLane(makeEntry({ party: 'tier1' }))).toBe(2)
    const right = arrowSpan(0, 1)
    expect(right.direction).toBe('right')
    // leaves the right edge of the card centred on lane 0, stops short of the marker on lane 1
    expect(right.left).toBe('calc(16.6667% + min(150px, 16.6667% - 12px))')
    expect(right.width).toBe('calc(33.3333% - min(150px, 16.6667% - 12px) - 6px)')
    expect(right.markerPct).toBeCloseTo(50, 2)
    const left = arrowSpan(2, 1)
    expect(left.direction).toBe('left')
    // starts just right of the marker on lane 1 and runs to the left edge of the card on lane 2
    expect(left.left).toBe('calc(50% + 6px)')
    expect(left.width).toBe('calc(33.3333% - min(150px, 16.6667% - 12px) - 6px)')
    expect(left.markerPct).toBeCloseTo(50, 2)
    expect(arrowSpan(0, 2).width).toBe('calc(66.6667% - min(150px, 16.6667% - 12px) - 6px)')
  })

  it('splits the timeline into day dividers when the date changes', () => {
    const es = [
      makeEntry({ id: 1, sent_at: '2026-09-13' }),
      makeEntry({ id: 2, sent_at: '2026-09-13' }),
      makeEntry({ id: 3, sent_at: null, recorded_at: '2026-09-15T10:00:00' }),
      makeEntry({ id: 4, sent_at: '2026-09-15' }),
      makeEntry({ id: 5, sent_at: '2026-09-18' }),
    ]
    expect(entryDay(es[2])).toBe('2026-09-15')
    expect(flowRows(es).map((r) => (r.type === 'day' ? `day ${r.date}` : `#${r.entry.id}`)))
      .toEqual(['day 2026-09-13', '#1', '#2', 'day 2026-09-15', '#3', '#4', 'day 2026-09-18', '#5'])
    expect(flowRows([])).toEqual([])
    expect(dayLabel('2026-09-13')).toEqual({ day: '13', month: 'Sep', year: '2026' })
    expect(dayLabel('2026-01-02T08:00:00')).toEqual({ day: '2', month: 'Jan', year: '2026' })
  })

  it('offers only valid actions per card in the relay', () => {
    // original toolmaker to KTX: KTX already answered, KTX can still forward? no, already forwarded to Tier 1
    expect(keys(1)).toEqual(['update'])
    // forward KTX to Tier 1: answered by Tier 1
    expect(keys(2)).toEqual(['update'])
    // answer Tier 1 to KTX: KTX may ask again or pass it on to the toolmaker
    expect(keys(3)).toEqual(['ask-ktx', 'forward-toolmaker', 'update'])
    // answer KTX to toolmaker: toolmaker may ask again
    expect(keys(4)).toEqual(['ask-toolmaker', 'update'])
    // question toolmaker to KTX, waiting: KTX answers or forwards to Tier 1
    expect(keys(5)).toEqual(['answer-ktx', 'forward-tier1', 'update'])
  })

  it('offers one answer per waiting addressee, and a forward only for KTX mail', () => {
    const e = makeEntry({ id: 9, party: 'ktx', addressed_to: ['toolmaker', 'tier1'], awaiting: [{ party: 'toolmaker', days: 2 }, { party: 'tier1', days: 2 }] })
    const acts = cardActions(e, [e])
    expect(acts.map((a) => a.key)).toEqual(['answer-toolmaker', 'answer-tier1', 'update'])
    expect(acts[0].label).toBe('Answer as Toolmaker')
    expect(acts[0].step).toMatchObject({ kind: 'answer', from: 'toolmaker', to: ['ktx'], lockedTo: ['ktx'], replyTo: { id: 9, kind: 'original' } })
  })

  it('builds prefilled steps', () => {
    const es = relayEntries()
    const [ask] = cardActions(es[3], es)
    expect(ask.label).toBe('Ask again')
    expect(ask.step).toMatchObject({ kind: 'question', from: 'toolmaker', fromEditable: false, to: ['ktx'], lockedTo: ['ktx'], allowedTo: ['ktx', 'tier1'], replyTo: { id: 4, kind: 'answer' }, supersedes: null, anchorId: 4 })
    const fwd = cardActions(es[4], es)[1]
    expect(fwd.label).toBe('Forward to Tier 1')
    expect(fwd.step).toMatchObject({ kind: 'forward', from: 'ktx', to: ['tier1'], allowedTo: ['tier1'], replyTo: { id: 5, kind: 'question' } })
    const upd = cardActions(es[3], es).slice(-1)[0]
    expect(upd.step).toMatchObject({ kind: 'answer', from: 'ktx', to: ['toolmaker'], lockedTo: ['toolmaker'], replyTo: { id: 1, kind: 'original' }, supersedes: { id: 4, kind: 'answer' } })
    expect(newOriginalStep()).toMatchObject({ kind: 'original', fromEditable: true, replyTo: null, supersedes: null })
  })

  it('states a step in words', () => {
    const es = relayEntries()
    const answer = cardActions(es[4], es)[0].step
    expect(stepSentence(answer, 'ktx', ['toolmaker'])).toBe('Answer from KTX to Toolmaker on Question #5')
    expect(stepSentence(cardActions(es[4], es)[1].step, 'ktx', ['tier1'])).toBe('Forward from KTX to Tier 1 of Question #5')
    expect(stepSentence(newOriginalStep(), 'toolmaker', ['ktx'])).toBe('Original from Toolmaker to KTX')
    expect(stepSentence(cardActions(es[3], es).slice(-1)[0].step, 'ktx', ['toolmaker'])).toBe('Update of Answer #4 from KTX to Toolmaker')
  })

  it('maps superseded ids to the current message', () => {
    const cur = makeEntry({ id: 7, history: [makeEntry({ id: 6 }) as never] })
    const m = currentIds([cur])
    expect(m.get(6)).toBe(7)
    expect(m.get(7)).toBe(7)
  })

  it('words the next step, waiting summary and last step', () => {
    expect(nextStepText({ entry_id: 3, kind: 'forward', from: 'ktx', to: 'tier1', days: 4 })).toBe('Waiting on Tier 1 for 4 days: Forward #3 from KTX')
    expect(nextStepText({ entry_id: 3, kind: 'forward', from: 'ktx', to: 'tier1', days: 0 })).toBe('Waiting on Tier 1 since today: Forward #3 from KTX')
    expect(waitingSummary(relaySummary())).toBe('waiting on KTX · 1 d')
    expect(waitingSummary(relaySummary({ waiting_on: [{ party: 'tier1', count: 2, oldest_days: 4 }] }))).toBe('waiting on Tier 1 (2) · 4 d')
    expect(waitingSummary(relaySummary({ waiting_on: [], all_answered: true }))).toBe('all answered')
    expect(waitingSummary(relaySummary({ status: 'finished_confirmed' }))).toBeNull()
    expect(lastStepText(relaySummary().last_step!)).toBe('Question Toolmaker → KTX 09-22')
  })

  it('describes an entry for the document pane title, sender first', () => {
    expect(sourceLabel(makeEntry({ id: 8, kind: 'answer', party: 'ktx', addressed_to: ['toolmaker'] })))
      .toBe('Answer #8 · KTX to Toolmaker')
    expect(sourceLabel(makeEntry({ id: 1, kind: 'original', party: 'toolmaker', addressed_to: ['ktx'] })))
      .toBe('Original #1 · Toolmaker to KTX')
  })

  it('gives every party a distinct sender colour', () => {
    expect(PARTY_STYLE.toolmaker.text).not.toBe(PARTY_STYLE.ktx.text)
    expect(PARTY_STYLE.ktx.text).not.toBe(PARTY_STYLE.tier1.text)
    expect(PARTY_STYLE.toolmaker.text).not.toBe(PARTY_STYLE.tier1.text)
  })
})
