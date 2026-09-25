import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import ProcessMapPage from './ProcessMapPage'

const authMock = vi.hoisted(() => ({ current: { role: 'viewer' as string | null } }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => authMock.current }))

// The ten stages of docs/ECR_PROCESS_MAP.md, in order, as the chart names them.
const STAGES: [string, string][] = [
  ['captured', 'Capture'],
  ['scoping', 'Scoping'],
  ['in_assessment', 'Assessment'],
  ['costing', 'Costing'],
  ['quoting', 'Offer'],
  ['quoted', 'Negotiation'],
  ['approved', 'Approved: timing'],
  ['in_implementation', 'Implementation'],
  ['in_validation', 'Validation'],
  ['released', 'Released'],
]

const wrap = () => render(<MemoryRouter><ProcessMapPage /></MemoryRouter>)

describe('ProcessMapPage', () => {
  afterEach(() => {
    cleanup()
    authMock.current = { role: 'viewer' }
    window.localStorage.removeItem('plm2.procmap.taskKeys')
  })

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
    // The open work at approved is the teams' timing confirmation.
    expect(screen.getByTestId('procmap-node-approved').textContent).toContain('Team')
    expect(screen.getByTestId('procmap-node-approved').textContent).not.toContain('Customer')
  })

  it('runs one arrow from each stage into the next', () => {
    wrap()
    for (const key of [
      'captured-kickoff', 'kickoff-scoping', 'scoping-meeting', 'meeting-impactlock',
      'impactlock-assessment', 'assessment-verdict', 'verdict-costing',
      'costing-costgate', 'costgate-carrier', 'carrier-quoting', 'quoting-quoted',
      'quoted-fork', 'fork-approved', 'approved-confirm', 'confirm-timinggate',
      'timinggate-publish', 'publish-implementation', 'implementation-dates',
      'dates-validation', 'validation-checks', 'checks-checklist',
      'checklist-lessons', 'lessons-releasegate', 'releasegate-released',
      'released-closed', 'internal-approved',
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
      'offer v1 sent (auto)',
      'accepted: sent, unexpired version + PM and Quality sign-off',
      'timing validated (soft guard)',
      'work done; open deviations inform, never gate',
      'all checks passed',
      'released (soft guard)',
      'capture complete (soft, deviation-overridable)',
    ]) {
      expect(chart).toContain(guard)
    }
  })

  it('shapes the decisions and the gates as their own symbols', () => {
    wrap()
    for (const d of ['meeting', 'verdict', 'carrier', 'customer', 'confirm', 'dates', 'checks', 'route']) {
      const node = screen.getByTestId(`procmap-decision-${d}`)
      expect(node.querySelector('polygon')).toBeTruthy()
    }
    // The impact lock is the gate no deviation clears: drawn red and said so.
    const hard = screen.getByTestId('procmap-gate-impact-lock')
    expect(hard.querySelector('polygon')?.getAttribute('stroke')).toBe('#f87171')
    expect(hard.textContent).toContain('no deviation clears it')
    expect(screen.getByTestId('procmap-gate-kickoff')).toBeTruthy()
    expect(screen.getByTestId('procmap-gate-costing').textContent)
      .toContain('every first-stage R/A submitted')
    expect(screen.getByTestId('procmap-gate-timing').textContent).toContain('Timing validated')
    expect(screen.getByTestId('procmap-gate-release').textContent)
      .toContain('no open validation issue')
  })

  it('draws the customer-question loop back into scoping', () => {
    authMock.current = { role: 'admin' }
    window.localStorage.setItem('plm2.procmap.taskKeys', 'on')
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
      'on-hold', 'deviation', 'negotiation', 'internal-approval', 'plan-concern',
      'plan-deviation', 'recovery', 'progress-report', 'nothing-impacted',
      'release-checklist', 'lessons',
    ]) {
      expect(screen.getByTestId(`procmap-node-${key}`)).toBeTruthy()
    }
    expect(screen.getByTestId('procmap-edge-captured-rejected')).toBeTruthy()
    expect(screen.getByTestId('procmap-node-on-hold').textContent).toContain('parking state')
    // The loops that send work back where it came from.
    expect(screen.getByTestId('procmap-loop-negotiation')).toBeTruthy()
    expect(screen.getByTestId('procmap-loop-recovery').getAttribute('marker-end'))
      .toBe('url(#arrow-loop)')
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

  it('puts the P&L touchpoints in the artifact gutter: planned, then actual', () => {
    wrap()
    const pnl = (key: string) => screen.getByTestId(`procmap-artifacts-${key}-pnl`).textContent
    expect(pnl('costing')).toContain('P&L planned')
    expect(pnl('approved')).toContain('frozen at acceptance')
    expect(pnl('implementation')).toContain('P&L actual')
    expect(pnl('validation')).toContain('issue costs by bearer')
    expect(pnl('released')).toContain('offer vs doing')
  })

  it('branches a failed check into a validation issue with five routes', () => {
    wrap()
    expect(screen.getByTestId('procmap-edge-checks-issue').getAttribute('marker-end'))
      .toBe('url(#arrow-loop)')
    for (const key of ['raise', 'contain', 'cause', 'customer', 'accepted', 'followup']) {
      expect(screen.getByTestId(`procmap-node-issue-${key}`)).toBeTruthy()
    }
    const chart = screen.getByTestId('procmap-chart').textContent ?? ''
    for (const route of ['internal rework', 'supplier rework', 'design change',
      'route 4: concession', 'route 5: follow-up change']) {
      expect(chart).toContain(route)
    }
    // Routes 1 to 3 go back to implementation with a recovery group in the plan.
    expect(screen.getByTestId('procmap-node-recovery').textContent).toContain('Re-validation VI-n')
    expect(screen.getByTestId('procmap-loop-require-fix')).toBeTruthy()
    expect(screen.getByTestId('procmap-node-issue-customer').textContent).toContain('new_timing')
  })

  it('draws the escalation ladder with its triggers', () => {
    wrap()
    expect(screen.getByTestId('procmap-escalation-l1').textContent).toContain('Department')
    const l2 = screen.getByTestId('procmap-escalation-l2').textContent ?? ''
    expect(l2).toContain('severity 3')
    expect(l2).toContain('no route decided after 2 working days')
    const l3 = screen.getByTestId('procmap-escalation-l3').textContent ?? ''
    expect(l3).toContain('Management + customer')
    expect(l3).toContain('recovery ends after the release date')
  })

  it('runs the mother-plant side track in its own lane, skipping assessment to offer', () => {
    wrap()
    const lane = screen.getByTestId('procmap-mother-plant-lane').textContent ?? ''
    expect(lane).toContain('KTX Weissenburg (WUG)')
    expect(lane).toContain('KTX Solingen')
    expect(lane).toContain('read and understood')
    expect(lane).toContain('release date = their SOP')
    expect(lane).toContain('Never: assessment, costing, offer, quote deadline')
    expect(screen.getByTestId('procmap-mp-gate').querySelector('polygon')?.getAttribute('stroke'))
      .toBe('#f87171')
    expect(screen.getByTestId('procmap-edge-mp-origin').getAttribute('marker-end'))
      .toBe('url(#arrow-mp)')
    expect(screen.getByTestId('procmap-node-mp-join').textContent).toContain('their SOP')
    // The side track is built now.
    expect(screen.getByTestId('procmap-mp-state').textContent).toBe('built')
    expect(lane).not.toContain('to build')
  })

  it('runs a deadline rail beside the flow', () => {
    wrap()
    const rail = screen.getByTestId('procmap-deadline-rail')
    expect(rail.textContent).toContain('quote-by deadline active')
    expect(rail.textContent).toContain('release-due deadline active')
    expect(screen.getByTestId('procmap-rail-quote')).toBeTruthy()
    expect(screen.getByTestId('procmap-rail-release')).toBeTruthy()
  })

  it('keeps task keys off the chart unless an admin turns them on', () => {
    authMock.current = { role: 'viewer' }
    wrap()
    expect(screen.queryByTestId('procmap-task-keys')).toBeNull()
    expect(screen.getByTestId('procmap-node-costing').textContent).not.toContain('costing_input')
    // Detail that is not a task key stays for everybody.
    expect(screen.getByTestId('procmap-mp-inform').textContent).toContain('task: read and understood')
    expect(screen.getByTestId('procmap-node-negotiation').textContent).toContain('valid 30 days from receipt')
    expect(screen.queryByTestId('procmap-sources')).toBeNull()
  })

  it('names the task each stage raises and the artifacts it owes', () => {
    authMock.current = { role: 'admin' }
    window.localStorage.clear()
    wrap()
    fireEvent.click(screen.getByTestId('procmap-task-keys'))
    expect(screen.getByTestId('procmap-sources')).toBeTruthy()
    expect(screen.getByTestId('procmap-node-captured').textContent).toContain('task: kickoff')
    expect(screen.getByTestId('procmap-node-scoping').textContent)
      .toContain('scoping_wrapup · impact_confirm')
    expect(screen.getByTestId('procmap-node-costing').textContent).toContain('task: costing_input')
    expect(screen.getByTestId('procmap-node-quoting').textContent).toContain('task: create_quote')
    expect(screen.getByTestId('procmap-node-quoted').textContent).toContain('customer_response')
    expect(screen.getByTestId('procmap-node-approved').textContent).toContain('plan_feedback')
    expect(screen.getByTestId('procmap-node-in_validation').textContent).toContain('release_check')
    expect(screen.getByTestId('procmap-node-rejected').textContent).toContain('send_rejection')

    expect(screen.getByTestId('procmap-artifacts-assessment').textContent)
      .toContain('Change PPT (per department)')
    expect(screen.getByTestId('procmap-artifacts-costing').textContent)
      .toContain('vendor quotes + ★ favorite vote')
    expect(screen.getByTestId('procmap-artifacts-quoted').textContent)
      .toContain('valid 30 days from receipt')
  })

  it('colours every box by how much of the stage is built', () => {
    wrap()
    const strokeOf = (key: string) =>
      screen.getByTestId(`procmap-node-${key}`).querySelector('rect')?.getAttribute('stroke')
    expect(strokeOf('captured')).toBe('#34d399')   // built
    expect(strokeOf('quoted')).toBe('#34d399')     // built
    // The weight check (estimate at costing, weighing at validation, Sales
    // re-quote task) is built: costing is not partial because of it.
    expect(strokeOf('costing')).toBe('#34d399')
    expect(strokeOf('in_validation')).toBe('#fbbf24')
    expect(screen.getByTestId('procmap-status-costing').textContent).toBe('Built')
    expect(screen.getByTestId('procmap-status-quoting').textContent).toBe('Built')
    expect(screen.getByTestId('procmap-legend').textContent).toContain('To build')
  })

  it('describes every stage under the chart', () => {
    wrap()
    const detail = screen.getByTestId('procmap-detail')
    for (const [key] of STAGES) {
      expect(detail.contains(screen.getByTestId(`procmap-detail-${key}`))).toBe(true)
    }
    const costing = screen.getByTestId('procmap-detail-costing').textContent ?? ''
    expect(costing).toContain('internal hours and external positions')
    expect(costing).toContain('Built')
    expect(costing).toContain('compared with the weighed part at validation')
    expect(screen.getByTestId('procmap-detail-in_validation').textContent)
      .toContain('A failed check becomes a validation issue')
  })

  it('keeps the responsibles and the build order in their own blocks', () => {
    wrap()
    expect(screen.getByTestId('procmap-role-in_assessment').textContent)
      .toBe('Routed departments (Sales exempt)')
    expect(screen.getByTestId('procmap-table').querySelectorAll('tbody tr')).toHaveLength(11)
    expect(screen.getByTestId('procmap-rules').querySelectorAll('li')).toHaveLength(8)
    expect(screen.getByTestId('procmap-build-order').querySelectorAll('li')).toHaveLength(7)
  })

  it('reads professionally, no casual phrasing anywhere on the page', () => {
    const { container } = wrap()
    const text = container.textContent ?? ''
    // Substrings, so keep them phrase-shaped: 'management' contains 'nag'.
    for (const casual of [
      'more money', 'no deal', 'ask for additional money', 'maybe', 'a bit of',
    ]) {
      expect(text.toLowerCase()).not.toContain(casual)
    }
    // No em-dashes anywhere on the page.
    expect(text).not.toContain('\u2014')
  })

  it('says nothing in German', () => {
    const { container } = wrap()
    const text = container.textContent ?? ''
    for (const word of ['Angebot', 'Erfassung', 'Bewertung', 'Umsetzung', 'Prozess']) {
      expect(text).not.toContain(word)
    }
  })

  it('starts with the intake of a new customer index and draws the review lane', () => {
    wrap()
    expect(screen.getByTestId('procmap-node-intake').textContent).toContain('Intake: new customer index')
    expect(screen.getByTestId('procmap-node-intake-review').textContent).toContain('Engineering review')
    expect(screen.getByTestId('procmap-node-intake-admin').textContent).toContain('Active now')
    const lane = screen.getByTestId('procmap-review-lane')
    expect(lane.textContent).toContain('LANE R')
    expect(screen.getByTestId('procmap-rv-decision').textContent).toContain('Any impact?')
    expect(screen.getByTestId('procmap-rv-released').textContent).toContain('Released and closed')
    expect(lane.textContent).toContain('escalates to a full ECR')
    expect(screen.getByTestId('procmap-detail-intake').textContent).toContain('Development picks the route alone')
  })

  describe('overview', () => {
    beforeEach(() => { window.localStorage.clear() })
    afterEach(() => { vi.restoreAllMocks(); window.localStorage.clear() })

    it('opens on the detailed flow and switches to the overview', () => {
      wrap()
      expect(screen.getByTestId('procmap-view-detailed').getAttribute('aria-pressed')).toBe('true')
      expect(screen.getByTestId('procmap-chart')).toBeTruthy()
      expect(screen.queryByTestId('procmap-overview')).toBeNull()
      expect(screen.queryByTestId('procmap-print')).toBeNull()

      fireEvent.click(screen.getByTestId('procmap-view-overview'))
      expect(screen.getByTestId('procmap-view-overview').getAttribute('aria-pressed')).toBe('true')
      expect(screen.queryByTestId('procmap-chart')).toBeNull()
      const stages = screen.getByTestId('procmap-overview-stages')
      const names = Array.from(stages.children).map((li) => (li.textContent ?? '').replace(/\u00AD/g, ''))
      expect(names).toHaveLength(11)
      ;['Intake', 'Capture', 'Scoping', 'Assessment', 'Costing', 'Offer / Approval',
        'Timing', 'Implementation', 'Validation', 'Release', 'Close'].forEach((n, i) => {
        expect(names[i]).toContain(n)
      })
      // Owner, gate and evidence per stage.
      const scoping = screen.getByTestId('procmap-ov-stage-scoping').textContent ?? ''
      expect(scoping).toContain('PM convenes')
      expect(scoping).toContain('kickoff gate')
      expect(scoping).toContain('meeting record with RASIC + cost carrier')
      const assessment = screen.getByTestId('procmap-ov-stage-assessment').textContent ?? ''
      expect(assessment).toContain('HARD impact set locked')
      expect(screen.getByTestId('procmap-ov-stage-costing').textContent)
        .toContain('costing lines with rate snapshot')
      expect(screen.getByTestId('procmap-overview-audit').textContent).toContain('Audit trail on every stage')
      const lanes = screen.getByTestId('procmap-overview-lanes').textContent ?? ''
      expect(lanes).toContain('L1 department, L2 project, L3 management')
      expect(lanes).toContain('Skips assessment, costing, offer')
      expect(lanes).toContain('Revision intake')
      expect(screen.getByTestId('procmap-overview').textContent).not.toContain('\u2014')
    })

    it('remembers the chosen view', () => {
      const first = wrap()
      fireEvent.click(screen.getByTestId('procmap-view-overview'))
      expect(window.localStorage.getItem('plm2.procmap.view')).toBe('overview')
      first.unmount()
      wrap()
      expect(screen.getByTestId('procmap-overview')).toBeTruthy()
      fireEvent.click(screen.getByTestId('procmap-view-detailed'))
      expect(window.localStorage.getItem('plm2.procmap.view')).toBe('detailed')
    })

    it('falls back to the detailed flow when storage throws', () => {
      vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
      wrap()
      expect(screen.getByTestId('procmap-chart')).toBeTruthy()
      // The toggle still works for this visit.
      fireEvent.click(screen.getByTestId('procmap-view-overview'))
      expect(screen.getByTestId('procmap-overview')).toBeTruthy()
    })

    it('jumps from a box to its node in the detailed flow and highlights it', () => {
      window.localStorage.setItem('plm2.procmap.view', 'overview')
      const scroll = vi.fn()
      const original = Element.prototype.scrollIntoView
      Element.prototype.scrollIntoView = scroll
      wrap()
      const box = screen.getByTestId('procmap-ov-stage-assessment')
      expect(box.getAttribute('href')).toBe('#procmap-node-in_assessment')
      fireEvent.click(box)
      const node = screen.getByTestId('procmap-node-in_assessment')
      expect(node.hasAttribute('data-procmap-flash')).toBe(true)
      expect(scroll).toHaveBeenCalled()
      // The jump is a look, not a new preference.
      expect(window.localStorage.getItem('plm2.procmap.view')).toBe('overview')
      Element.prototype.scrollIntoView = original
    })

    it('links every stage and side track to a node that exists in the detailed flow', () => {
      window.localStorage.setItem('plm2.procmap.view', 'overview')
      wrap()
      const links = [
        ...screen.getByTestId('procmap-overview-stages').querySelectorAll('a'),
        ...screen.getByTestId('procmap-overview-lanes').querySelectorAll('a'),
      ].map((a) => a.getAttribute('href')!.slice(1))
      expect(links).toHaveLength(14)
      fireEvent.click(screen.getByTestId('procmap-view-detailed'))
      for (const id of links) expect(screen.getByTestId(id)).toBeTruthy()
    })

    it('prints the overview from its own button', () => {
      window.localStorage.setItem('plm2.procmap.view', 'overview')
      const print = vi.fn()
      vi.stubGlobal('print', print)
      wrap()
      fireEvent.click(screen.getByTestId('procmap-print'))
      expect(print).toHaveBeenCalledOnce()
      vi.unstubAllGlobals()
    })
  })
})
