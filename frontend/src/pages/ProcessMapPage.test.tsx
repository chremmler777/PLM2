import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import ProcessMapPage from './ProcessMapPage'

// The ten stages of docs/ECR_PROCESS_MAP.md, in order, as the chart names them.
const STAGES: [string, string][] = [
  ['captured', 'Capture'],
  ['scoping', 'Scoping'],
  ['in_assessment', 'Assessment'],
  ['costing', 'Costing'],
  ['quoting', 'Quote Creation'],
  ['quoted', 'Quote & Negotiation'],
  ['approved', 'Approved'],
  ['scheduling', 'Scheduling / Bank Build'],
  ['in_implementation', 'Implementation'],
  ['in_validation', 'Validation'],
  ['released', 'Released'],
]

const wrap = () => render(<MemoryRouter><ProcessMapPage /></MemoryRouter>)

describe('ProcessMapPage', () => {
  afterEach(cleanup)

  it('draws a box per stage in the chart, named and badged', () => {
    wrap()
    const chart = screen.getByTestId('procmap-chart')
    for (const [key, name] of STAGES) {
      const node = screen.getByTestId(`procmap-node-${key}`)
      expect(chart.contains(node)).toBe(true)
      expect(node.textContent).toContain(name)
    }
    expect(screen.getByTestId('procmap-node-quoting').textContent).toContain('Sales')
    expect(screen.getByTestId('procmap-node-scoping').textContent).toContain('PM')
    expect(screen.getByTestId('procmap-node-approved').textContent).toContain('Customer')
  })

  it('runs one arrow from each stage into the next', () => {
    wrap()
    for (const key of [
      'captured-kickoff', 'kickoff-scoping', 'scoping-meeting', 'meeting-impactlock',
      'impactlock-assessment', 'assessment-verdict', 'verdict-costing',
      'costing-costgate', 'costgate-quoting', 'quoting-quoted', 'quoted-fork',
      'fork-approved', 'approved-scheduling', 'scheduling-scrap', 'scrap-publish',
      'publish-implementation', 'implementation-atrisk', 'atrisk-validation',
      'validation-checks', 'checks-released', 'released-closed',
    ]) {
      expect(screen.getByTestId(`procmap-edge-${key}`).getAttribute('marker-end'))
        .toBe('url(#arrow)')
    }
  })

  it('names the real guard on the steps that have one', () => {
    wrap()
    const chart = screen.getByTestId('procmap-chart').textContent ?? ''
    for (const guard of [
      'impact set locked (hard)',
      'all 1st-stage R/A submitted',
      'no open deviation',
      'quoted price set',
      'acceptance + release deadline born',
      'all checks passed',
      'capture complete (soft, deviation-overridable)',
    ]) {
      expect(chart).toContain(guard)
    }
  })

  it('shapes the decisions and the gates as their own symbols', () => {
    wrap()
    for (const d of ['meeting', 'verdict', 'customer', 'scrap', 'atrisk', 'checks']) {
      const node = screen.getByTestId(`procmap-decision-${d}`)
      expect(node.querySelector('polygon')).toBeTruthy()
    }
    // The impact lock is the gate no deviation clears — drawn red and said so.
    const hard = screen.getByTestId('procmap-gate-impact-lock')
    expect(hard.querySelector('polygon')?.getAttribute('stroke')).toBe('#f87171')
    expect(hard.textContent).toContain('no deviation clears it')
    expect(screen.getByTestId('procmap-gate-kickoff')).toBeTruthy()
    expect(screen.getByTestId('procmap-gate-costing').textContent)
      .toContain('every first-stage R/A submitted')
  })

  it('draws the customer-question loop back into scoping', () => {
    wrap()
    expect(screen.getByTestId('procmap-node-obtain-info').textContent).toContain('obtain_info')
    expect(screen.getByTestId('procmap-node-customer-answer').textContent)
      .toContain('info_request → info_response')
    expect(screen.getByTestId('procmap-node-close-question').textContent)
      .toContain('only the asker may withdraw it')
    expect(screen.getByTestId('procmap-loop-needs-info').getAttribute('marker-end'))
      .toBe('url(#arrow-loop)')
  })

  it('keeps every way out of the flow on the chart', () => {
    wrap()
    for (const key of [
      'rejected', 'rejected-not-feasible', 'rejected-declined', 'cancelled', 'closed',
      'on-hold', 'deviation', 'negotiation', 'scrap-quote', 'sales-escalation',
      'escalation', 'progress-report', 'nothing-impacted',
    ]) {
      expect(screen.getByTestId(`procmap-node-${key}`)).toBeTruthy()
    }
    expect(screen.getByTestId('procmap-edge-captured-rejected')).toBeTruthy()
    expect(screen.getByTestId('procmap-node-on-hold').textContent).toContain('parking state')
    // The two loops that send work back where it came from.
    expect(screen.getByTestId('procmap-loop-negotiation')).toBeTruthy()
    expect(screen.getByTestId('procmap-loop-escalation').getAttribute('marker-end'))
      .toBe('url(#arrow-loop)')
    expect(screen.getByTestId('procmap-loop-atrisk')).toBeTruthy()
    expect(screen.getByTestId('procmap-loop-recall')).toBeTruthy()
  })

  it('carries information across stages on its own arrows', () => {
    wrap()
    const risk = screen.getByTestId('procmap-edge-risk-carry')
    expect(risk.getAttribute('marker-end')).toBe('url(#arrow-cross)')
    const fav = screen.getByTestId('procmap-edge-favorite-carry')
    expect(fav.getAttribute('marker-end')).toBe('url(#arrow-cross)')
    expect(screen.getByTestId('procmap-chart').textContent)
      .toContain("favorite vendor → Sales' binding choice")
    expect(screen.getByTestId('procmap-edge-weight-update')).toBeTruthy()
    expect(screen.getByTestId('procmap-edge-pnl-compare')).toBeTruthy()
  })

  it('runs a deadline rail beside the flow', () => {
    wrap()
    const rail = screen.getByTestId('procmap-deadline-rail')
    expect(rail.textContent).toContain('quote-by deadline active')
    expect(rail.textContent).toContain('release-due deadline active')
    expect(screen.getByTestId('procmap-rail-quote')).toBeTruthy()
    expect(screen.getByTestId('procmap-rail-release')).toBeTruthy()
  })

  it('names the task each stage raises and the artifacts it owes', () => {
    wrap()
    expect(screen.getByTestId('procmap-node-captured').textContent).toContain('task: kickoff')
    expect(screen.getByTestId('procmap-node-scoping').textContent)
      .toContain('scoping_wrapup · impact_confirm')
    expect(screen.getByTestId('procmap-node-costing').textContent).toContain('task: costing_input')
    expect(screen.getByTestId('procmap-node-quoting').textContent).toContain('task: create_quote')
    expect(screen.getByTestId('procmap-node-quoted').textContent).toContain('task: customer_response')
    expect(screen.getByTestId('procmap-node-rejected').textContent).toContain('send_rejection')

    expect(screen.getByTestId('procmap-artifacts-assessment').textContent)
      .toContain('Change PPT (per department)')
    expect(screen.getByTestId('procmap-artifacts-costing').textContent)
      .toContain('vendor quotes + ★ favorite vote')
    expect(screen.getByTestId('procmap-artifacts-validation').textContent)
      .toContain('revision bump · actuals P&L')
  })

  it('colours every box by how much of the stage is built', () => {
    wrap()
    const strokeOf = (key: string) =>
      screen.getByTestId(`procmap-node-${key}`).querySelector('rect')?.getAttribute('stroke')
    expect(strokeOf('captured')).toBe('#34d399')   // built
    expect(strokeOf('costing')).toBe('#38bdf8')    // in build
    expect(strokeOf('quoted')).toBe('#fbbf24')     // partial
    expect(strokeOf('scheduling')).toBe('#64748b') // to build
    expect(screen.getByTestId('procmap-status-costing').textContent).toBe('In build')
    expect(screen.getByTestId('procmap-status-quoted').textContent).toBe('Partial')
    expect(screen.getByTestId('procmap-legend').textContent).toContain('To build')
  })

  it('describes every stage under the chart', () => {
    wrap()
    const detail = screen.getByTestId('procmap-detail')
    for (const [key] of STAGES) {
      expect(detail.contains(screen.getByTestId(`procmap-detail-${key}`))).toBe(true)
    }
    const costing = screen.getByTestId('procmap-detail-costing').textContent ?? ''
    expect(costing).toContain('internal effort (assessment time)')
    expect(costing).toContain('In build')
    expect(screen.getByTestId('procmap-detail-in_validation').textContent)
      .toContain('weight is validated against the costing estimate')
  })

  it('keeps the responsibles and the build order in their own blocks', () => {
    wrap()
    expect(screen.getByTestId('procmap-role-in_assessment').textContent)
      .toBe('Routed departments (Sales exempt)')
    expect(screen.getByTestId('procmap-table').querySelectorAll('tbody tr')).toHaveLength(11)
    expect(screen.getByTestId('procmap-rules').querySelectorAll('li')).toHaveLength(7)
    expect(screen.getByTestId('procmap-build-order').querySelectorAll('li')).toHaveLength(7)
  })

  it('reads professionally — no casual phrasing anywhere on the page', () => {
    const { container } = wrap()
    const text = container.textContent ?? ''
    // Substrings, so keep them phrase-shaped — 'management' contains 'nag'.
    for (const casual of [
      'more money', 'no deal', 'ask for additional money', 'maybe', 'a bit of',
    ]) {
      expect(text.toLowerCase()).not.toContain(casual)
    }
    // And the escalation says what it actually is.
    expect(screen.getByTestId('procmap-node-escalation').textContent)
      .toContain('replan timing, renegotiate commercial terms')
  })

  it('says nothing in German', () => {
    const { container } = wrap()
    const text = container.textContent ?? ''
    for (const word of ['Angebot', 'Erfassung', 'Bewertung', 'Umsetzung', 'Prozess']) {
      expect(text).not.toContain(word)
    }
  })
})
