import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ActivityChecklist, {
  checklistItemLabel, checklistProgress, earlierAnswers, missingDocuments, casesOf, refToNos, restToNo,
  riskKeyOf, saysWhat, verdictEvidence,
} from './ActivityChecklist'
// ActivityChecklist reads the viewer (who may delete assessment documents).
vi.mock('../../../contexts/AuthContext', () => ({ useAuth: () => ({ userId: 5, isAdmin: false }) }))

const DEFS = [
  { key: 'cycle_time_change', label_de: 'Zykluszeit', label_en: 'Cycle time change', extra: false },
  { key: 'threed_change', label_de: '3D', label_en: '3D change necessary', extra: false },
]
const ARTICLE = { key: 'article_design_update', label_de: 'A', label_en: 'Article design update',
  extra: true, choices: [
    { value: 'internal', label_de: 'Intern', label_en: 'Internal' },
    { value: 'customer_given', label_de: 'Kundenvorgabe', label_en: 'Customer given' }] }
const assessmentChecklist = vi.fn(() => Promise.resolve(DEFS as unknown[]))
const listConcerns = vi.fn(() => Promise.resolve([] as unknown[]))
vi.mock('../../../api/changes', () => ({
  changesApi: {
    assessmentChecklist: () => assessmentChecklist(),
    listConcerns: () => listConcerns(),
    riskTypes: vi.fn(() => Promise.resolve({ items: [{ key: 'fill_issue', label_en: 'Fill issue' }] })),
    raiseConcern: vi.fn(),
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

describe('ActivityChecklist choices', () => {
  afterEach(cleanup)
  it('renders object choices by their label and stores the value (crash fix)', async () => {
    assessmentChecklist.mockResolvedValueOnce([ARTICLE])
    const onChange = vi.fn()
    render(wrap(<ActivityChecklist departmentId={4} onChange={onChange}
      value={{ impacts: [{ key: 'article_design_update', answer: 'yes', impacted: true }] }} />))
    expect(await screen.findByText('Customer given')).toBeTruthy()
    fireEvent.click(screen.getByTestId('check-choice-article_design_update-customer_given'))
    expect(onChange).toHaveBeenLastCalledWith({ impacts: [expect.objectContaining({
      key: 'article_design_update', choice: 'customer_given' })] })
  })
})

describe('ActivityChecklist risk flag', () => {
  afterEach(cleanup)
  const answeredNo = { impacts: [{ key: 'threed_change', answer: 'yes', impacted: true }] }

  it('offers ⚑ on a Yes row only: never on an open row or a No row (spec §16)', async () => {
    render(wrap(<ActivityChecklist departmentId={4} changeId={5} onChange={() => {}}
      value={{ impacts: [
        { key: 'threed_change', answer: 'yes', impacted: true },
        { key: 'visual_risk', answer: 'no', impacted: false },
      ] }} />))
    expect(await screen.findByTestId('check-flag-threed_change')).toBeTruthy()
    expect(screen.queryByTestId('check-flag-cycle_time_change')).toBeNull()
    expect(screen.queryByTestId('check-flag-visual_risk')).toBeNull()
  })

  it('opens the pre-filled form from ⚑', async () => {
    render(wrap(<ActivityChecklist departmentId={4} changeId={5} onChange={() => {}}
      value={{ impacts: [{ key: 'threed_change', answer: 'yes', impacted: true, remark: 'gate moves' }] }} />))
    fireEvent.click(await screen.findByTestId('check-flag-threed_change'))
    expect((screen.getByTestId('check-risk-note') as HTMLTextAreaElement).value)
      .toBe('3D change necessary: gate moves')
  })

  it('lists the row\'s open risks under it and still offers ⚑ for another', async () => {
    listConcerns.mockResolvedValueOnce([
      { id: 9, kind: 'risk', is_open: true, department_id: 4, checklist_key: 'threed_change',
        severity: 3, risk_type: 'fill_issue', note: 'gate moves' },
      { id: 10, kind: 'risk', is_open: false, department_id: 4, checklist_key: 'threed_change',
        severity: 1, risk_type: 'timing', note: 'old one' }])
    render(wrap(<ActivityChecklist departmentId={4} changeId={5} value={answeredNo} onChange={() => {}} />))
    const item = await screen.findByTestId('check-risk-9')
    await waitFor(() => expect(item.textContent).toContain('Fill issue'))
    expect(item.textContent).toContain('3')
    expect(item.textContent).toContain('gate moves')
    expect(screen.queryByTestId('check-risk-10')).toBeNull()
    expect(screen.getByTestId('check-flag-threed_change')).toBeTruthy()
  })

  it('jumps to the risk card when a listed risk is clicked', async () => {
    const card = document.createElement('div')
    card.id = 'concern-card-9'
    const scroll = vi.fn()
    card.scrollIntoView = scroll
    document.body.appendChild(card)
    listConcerns.mockResolvedValueOnce([{ id: 9, kind: 'risk', is_open: true, department_id: 4,
      checklist_key: 'threed_change', severity: 3, note: 'gate moves' }])
    render(wrap(<ActivityChecklist departmentId={4} changeId={5} value={answeredNo} onChange={() => {}} />))
    fireEvent.click(await screen.findByTestId('check-risk-9'))
    expect(scroll).toHaveBeenCalled()
    card.remove()
  })

  it("ignores another department's risk on the same key", async () => {
    listConcerns.mockResolvedValueOnce([{ id: 9, kind: 'risk', is_open: true, department_id: 7,
      checklist_key: 'threed_change', severity: 2 }])
    render(wrap(<ActivityChecklist departmentId={4} changeId={5} value={answeredNo} onChange={() => {}} />))
    expect(await screen.findByTestId('check-flag-threed_change')).toBeTruthy()
    expect(screen.queryByTestId('check-risk-9')).toBeNull()
  })

  it('a long free line gets a key capped at 120 chars', () => {
    expect(riskKeyOf(`free:${'L'.repeat(200)}`)).toHaveLength(120)
    expect(riskKeyOf('free:Hot runner: zone 3')).toBe('free:Hot runner: zone 3')
  })
})

describe('ActivityChecklist Rest → No marks', () => {
  afterEach(cleanup)

  it('a row changed by hand is no longer marked as bulk', async () => {
    const onChange = vi.fn()
    render(wrap(<ActivityChecklist departmentId={2} onChange={onChange}
      value={{ impacts: [{ key: 'threed_change', answer: 'no', impacted: false, bulk: true }] }} />))
    fireEvent.click(await screen.findByTestId('check-yes-threed_change'))
    const row = onChange.mock.calls[0][0].impacts.find((i: { key: string }) => i.key === 'threed_change')
    expect(row).toEqual({ key: 'threed_change', answer: 'yes', impacted: true })
  })
})

describe('ActivityChecklist earlier checklist items', () => {
  afterEach(cleanup)
  // Stored answers to keys the served checklist no longer lists.
  const EARLIER = [
    { key: 'scrap_increase', answer: 'yes' as const, impacted: true, remark: 'more purge' },
    { key: 'visual_risk', answer: 'no' as const, impacted: false },
    { key: 'retired_key_x', impacted: true },
  ]

  it('shows them read-only under "Earlier checklist items", named', async () => {
    render(wrap(<ActivityChecklist departmentId={2} value={{ impacts: EARLIER }} onChange={() => {}} />))
    const box = await screen.findByTestId('check-earlier')
    expect(box.textContent).toContain('Earlier checklist items')
    expect(screen.getByTestId('check-earlier-scrap_increase').textContent).toContain('Scrap increase')
    expect(screen.getByTestId('check-earlier-scrap_increase').textContent).toContain('more purge')
    expect(screen.getByTestId('check-earlier-visual_risk').textContent).toContain('Visual risk')
    expect(screen.getByTestId('check-earlier-retired_key_x').textContent).toContain('Retired key x')
    // Read-only: no Yes/No buttons for them.
    expect(screen.queryByTestId('check-yes-scrap_increase')).toBeNull()
  })

  it('keeps them unchanged when a served row is answered', async () => {
    const onChange = vi.fn()
    render(wrap(<ActivityChecklist departmentId={2} value={{ impacts: EARLIER }} onChange={onChange} />))
    await screen.findByTestId('check-earlier')
    fireEvent.click(screen.getByTestId('check-no-threed_change'))
    const sent = onChange.mock.calls[0][0].impacts
    for (const e of EARLIER) expect(sent).toContainEqual(e)
    expect(sent).toContainEqual({ key: 'threed_change', answer: 'no', impacted: false })
  })

  it('restToNo leaves them as stored', () => {
    const out = restToNo(DEFS, { impacts: EARLIER }).impacts as unknown[]
    for (const e of EARLIER) expect(out).toContainEqual(e)
    expect(out).toHaveLength(EARLIER.length + DEFS.length)
  })

  it('earlierAnswers and checklistItemLabel', () => {
    expect(earlierAnswers(DEFS, { impacts: [...EARLIER, { key: 'threed_change', answer: 'no', impacted: false }] })
      .map((i) => i.key)).toEqual(['scrap_increase', 'visual_risk', 'retired_key_x'])
    expect(checklistItemLabel({ key: 'scrap_increase' }, DEFS, 'de')).toBe('Ausschusserhöhung')
    expect(checklistItemLabel({ key: 'threed_change' }, DEFS)).toBe('3D change necessary')
    expect(checklistItemLabel({ label: 'Free line' }, DEFS)).toBe('Free line')
  })
})

describe('missingDocuments', () => {
  const EXT = { key: 'modification_external', label_de: 'E', label_en: 'External modification (supplier)',
    extra: false, requires_documents: [
      { kind: 'change_ppt' as const, label_de: 'P', label_en: 'Change presentation', extensions: ['.pptx'] },
      { kind: 'rfq' as const, label_de: 'R', label_en: 'Change RFQ', extensions: ['.pdf'] }] }
  const yes = { impacts: [{ key: 'modification_external', answer: 'yes', impacted: true }] }

  it('owes both documents on a Yes, only what is not filed, nothing on a No', () => {
    expect(missingDocuments([EXT], yes, []).map((m) => m.doc.kind)).toEqual(['change_ppt', 'rfq'])
    expect(missingDocuments([EXT], yes, [{ kind: 'rfq' }]).map((m) => m.doc.kind)).toEqual(['change_ppt'])
    expect(missingDocuments([EXT], yes, [{ kind: 'rfq' }, { kind: 'change_ppt' }])).toEqual([])
    expect(missingDocuments([EXT], yes, [{ kind: 'general' }]).length).toBe(2)
    expect(missingDocuments([EXT], { impacts: [{ key: 'modification_external', answer: 'no',
      impacted: false }] }, [])).toEqual([])
    expect(missingDocuments([...DEFS, EXT], {}, [])).toEqual([])
  })
})

describe('verdict evidence (spec §4)', () => {
  it('says nothing with ok / checked, something with a ref or a number and unit', () => {
    expect(saysWhat('ok')).toBe(false)
    expect(saysWhat('checked')).toBe(false)
    expect(saysWhat('asdfg')).toBe(false)
    expect(saysWhat('DRW-4471 rev C')).toBe(true)
    expect(saysWhat('+0.4s')).toBe(true)
  })

  it('impact no owes a reference per No row; one ref fills the rest', () => {
    const value = { impacts: [
      { key: 'cycle_time_change', answer: 'no', impacted: false },
      { key: 'threed_change', answer: 'no', impacted: false, ref: 'DRW-1 rev A' }] }
    expect(verdictEvidence(DEFS, value)).toEqual({ impact: 'no', missing: ['Cycle time change'] })
    expect(verdictEvidence(DEFS, refToNos(value, 'CL-12 row 4')).missing).toEqual([])
    // the row that had its own ref keeps it
    const kept = (refToNos(value, 'CL-12 row 4').impacts as { ref?: string }[])[1].ref
    expect(kept).toBe('DRW-1 rev A')
  })

  it('impact yes owes what changes per Yes, not refs on the No rows', () => {
    const value = { impacts: [
      { key: 'cycle_time_change', answer: 'yes', impacted: true, remark: 'ok' },
      { key: 'threed_change', answer: 'no', impacted: false }] }
    expect(verdictEvidence(DEFS, value)).toEqual({ impact: 'yes', missing: ['Cycle time change'] })
    // 6f23cb8f (YES_NEEDS_NUMBER off): a few words that say what changes are enough
    ;(value.impacts[0] as { remark: string }).remark = 'Update Q Instruction'
    expect(verdictEvidence(DEFS, value).missing).toEqual([])
    ;(value.impacts[0] as { remark: string }).remark = 'cycle +0.4 s, trial TR-22'
    expect(verdictEvidence(DEFS, value).missing).toEqual([])
  })
})

describe('modification cases (2026-11-08)', () => {
  const def = { key: 'modification_external', label_de: 'x', label_en: 'External modification (supplier)',
    extra: false,
    requires_documents: [{ kind: 'change_ppt', label_de: 'p', label_en: 'Change presentation', extensions: ['.pptx'] },
      { kind: 'rfq', label_de: 'r', label_en: 'Change RFQ', extensions: ['.pdf'] }],
    case_documents: [{ kind: 'change_ppt', label_de: 'p', label_en: 'Change presentation', extensions: ['.pptx'] },
      { kind: 'rfq', label_de: 'r', label_en: 'Change RFQ', extensions: ['.pdf'] }] }
  const value = { impacts: [{ key: 'modification_external', answer: 'yes', impacted: true,
    cases: [{ id: 'cA', text: 'Insert LH' }, { id: 'cB', text: 'Insert RH' }] }] }
  it('owes the documents per case, not once per row', () => {
    const filedA = [{ kind: 'change_ppt', case_ref: 'cA' }, { kind: 'rfq', case_ref: 'cA' }]
    // case B still owes both, although the kinds are filed (for A)
    expect(missingDocuments([def] as never, value, filedA as never).map((m) => m.doc.kind))
      .toEqual(['change_ppt', 'rfq'])
    const all = [...filedA, { kind: 'change_ppt', case_ref: 'cB' }, { kind: 'rfq', case_ref: 'cB' }]
    expect(missingDocuments([def] as never, value, all as never)).toEqual([])
  })
  it('reads plain-text cases of the first version', () => {
    expect(casesOf({ key: 'modification_external', impacted: true, cases: ['Insert LH'] }).map((c) => c.text))
      .toEqual(['Insert LH'])
  })
})
