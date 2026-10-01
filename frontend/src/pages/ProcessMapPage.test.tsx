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
      'costing-carrier', 'carrier-costgate', 'costgate-quoting', 'quoting-quoted',
      'quoted-fork', 'fork-approved', 'approved-confirm', 'confirm-timinggate',
      'timinggate-implgate', 'implgate-implementation', 'implementation-dates',
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
      'proceed: an R or A department, cost carrier set, no open concern',
      'impact set locked (hard) · soft: impacted items, lead, quote deadline (customer)',
      'soft: all R/A submitted, none not feasible, no routing change pending',
      'Close costing (PM, Sales, lead)',
      'offer v1 sent (auto)',
      'accepted + PM and Quality sign-off (two people), Record approval (hard)',
      'Start implementation',
      'soft: every impacted item has its revision; open deviations do not hold this step',
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
    expect(screen.getByTestId('procmap-gate-kickoff').textContent).toContain('change lead')
    expect(screen.getByTestId('procmap-gate-costing').textContent)
      .toContain('all R/A submitted, none not feasible, no routing change pending')
    const timing = screen.getByTestId('procmap-gate-timing').textContent ?? ''
    expect(timing).toContain('Timing validated')
    expect(timing).toContain('Sales, PM, Scheduling or lead')
    // validate_timing refuses outright (no deviation): drawn red like the impact lock.
    expect(screen.getByTestId('procmap-gate-timing').querySelector('polygon')?.getAttribute('stroke'))
      .toBe('#f87171')
    // The start-implementation condition on it stays soft.
    expect(screen.getByTestId('procmap-gate-implementation').querySelector('polygon')
      ?.getAttribute('stroke')).not.toBe('#f87171')
    const impl = screen.getByTestId('procmap-gate-implementation').textContent ?? ''
    for (const part of ['timing validated (first start)', 'impact confirmed',
      'check workflow per item category', 'D1 Technical release? = Yes']) {
      expect(impl).toContain(part)
    }
    const release = screen.getByTestId('procmap-gate-release').textContent ?? ''
    for (const part of ['checks passed', 'no open validation issue', 'revisions checked',
      'checklist complete', 'lessons done', 'no open plan deviation']) {
      expect(release).toContain(part)
    }
  })

  it('forks on the cost carrier fixed at scoping, before the costing gate', () => {
    wrap()
    expect(screen.getByTestId('procmap-decision-carrier').textContent)
      .toContain('Cost carrier (set at scoping)')
    // The gate closes costing on the customer branch: it sits below the fork.
    const yOf = (id: string) => Number(screen.getByTestId(id).querySelector('polygon')
      ?.getAttribute('points')?.split(/[ ,]/)[1])
    expect(yOf('procmap-gate-costing')).toBeGreaterThan(yOf('procmap-decision-carrier'))
    expect(screen.getByTestId('procmap-node-internal-approval').textContent)
      .toContain('Approve internal costs')
  })

  it('draws the moves back that need a reason', () => {
    wrap()
    const chart = screen.getByTestId('procmap-chart').textContent ?? ''
    for (const [id, text] of [
      ['procmap-loop-reopen-costing', 'reopen costing (reason)'],
      ['procmap-loop-reopen-rejected', 'reopen (reason)'],
      ['procmap-loop-back-to-implementation', 'back to implementation (reason)'],
    ]) {
      expect(screen.getByTestId(id).getAttribute('marker-end')).toBe('url(#arrow-loop)')
      expect(chart).toContain(text)
    }
    // Not feasible holds the change; rejecting is one of three ways on.
    const nf = screen.getByTestId('procmap-node-not-feasible').textContent ?? ''
    expect(nf).toContain('holds costing (soft)')
    expect(nf).toContain('reject · back to scoping · override')
    expect(screen.queryByTestId('procmap-node-rejected-not-feasible')).toBeNull()
    expect(chart).toContain('recall: before work starts, or after not feasible')
    // A declined offer is recorded; rejecting is its own step.
    expect(screen.getByTestId('procmap-node-rejected-declined').textContent)
      .toContain('reject is its own step')
    expect(screen.getByTestId('procmap-node-rejected').textContent)
      .toContain('closes once the letter is sent')
  })

  it('keeps the plan publish and the bank build off the main path', () => {
    wrap()
    expect(screen.getByTestId('procmap-node-bank-build').textContent).toContain('to-do, not a gate')
    expect(screen.getByTestId('procmap-node-publish-plan').textContent).toContain('a stamp')
    // The spine runs from the timing gate through the implementation gate.
    expect(screen.queryByTestId('procmap-edge-publish-implementation')).toBeNull()
    expect(screen.getByTestId('procmap-edge-implgate-implementation')).toBeTruthy()
  })

  it('never claims that open deviations do not gate the release', () => {
    const { container } = wrap()
    const text = container.textContent ?? ''
    expect(text).not.toContain('never gate')
    expect(text).not.toContain('recorded customer new timing')
    expect(screen.getByTestId('procmap-node-plan-deviation').textContent)
      .toContain('open ones hold release')
    expect(screen.getByTestId('procmap-deadline-rail').textContent)
      .toContain('moved only with a reason (audited)')
    expect(screen.getByTestId('procmap-checked').textContent)
      .toContain('Checked against the running system on 1 Oct 2026')
  })

  it('states who decides what as the code does (review 2026-10-01)', () => {
    const { container } = wrap()
    const rules = screen.getByTestId('procmap-rules').textContent ?? ''
    // Four eyes: transition / routing deviations and issue routes, not plan deviations.
    expect(rules).toContain('a transition or routing deviation is decided by somebody other than its proposer')
    expect(rules).toContain('Plan (date) deviations have no four-eyes rule')
    expect(rules).not.toContain('whoever proposes a deviation or raises a validation issue does not decide it')
    // Dates after the baseline: Scheduling moves them too; deciding stays with PM, Sales, lead, admin.
    expect(rules).toContain('PM, Sales, Scheduling, the lead or an admin move dates')
    expect(screen.getByTestId('procmap-decision-dates').textContent).toContain('Scheduling')
    // The release hold is soft, and the P&L freezes at the go decision.
    expect(rules).toContain('holds the release (soft: an approved deviation releases anyway)')
    expect(rules).toContain("the PM's internal cost approval")
    const text = container.textContent ?? ''
    expect(text).not.toContain('Sales only')
    expect(text).not.toContain('any member records the decision')
    expect(text).not.toContain('admin via acts-as')
    expect(text).not.toContain('in build')
    expect(text).not.toContain('FS into SOP')
    expect(screen.getByTestId('procmap-role-quoting').textContent)
      .toContain('Sales, the change lead or an admin')
    expect(screen.getByTestId('procmap-role-scoping').textContent)
      .toContain('the change lead, Project Management or an admin')
    // Escalation: the acknowledge task starts at L2; L3 flags the customer errand.
    expect(screen.getByTestId('procmap-escalation-ladder').textContent)
      .toContain('L3 also an acknowledge task')
    expect(screen.getByTestId('procmap-escalation-l3').textContent).toContain('inform the customer (Sales)')
    // The quote deadline freezes when quoted, not at approval.
    expect(screen.getByTestId('procmap-detail-approved').textContent)
      .toContain('froze into its permanent on-time or late fact when the offer was sent')
    // Capture: internal is a form choice again (F-04, 2026-10-01).
    expect(screen.getByTestId('procmap-detail-captured').textContent)
      .toContain('internal change (the plant pays, no quote, no quote deadline)')
    expect(screen.getByTestId('procmap-detail-captured').textContent).not.toContain('not offered')
    // Risks: every open risk becomes an optional offer row.
    expect(screen.getByTestId('procmap-chart').textContent).toContain('open risks → optional rows on the offer')
  })

  it('cancels only before release: a released change closes', () => {
    wrap()
    const edge = screen.getByTestId('procmap-edge-cancelled')
    // Leaves the release gate (still in validation), never the Released box.
    const startY = Number((edge.getAttribute('d') ?? '').split(/\s+/)[2])
    const releasedY = Number(screen.getByTestId('procmap-node-released').querySelector('rect')?.getAttribute('y'))
    expect(startY).toBeLessThan(releasedY)
    expect(screen.getByTestId('procmap-node-cancelled').textContent).toContain('not after release')
  })

  it('draws the customer-question loop back into scoping', () => {
    authMock.current = { role: 'admin' }
    window.localStorage.setItem('plm2.procmap.taskKeys', 'on')
    wrap()
    expect(screen.getByTestId('procmap-node-obtain-info').textContent).toContain('obtain_info')
    expect(screen.getByTestId('procmap-node-customer-answer').textContent)
      .toContain('info_request → info_response')
    expect(screen.getByTestId('procmap-node-close-question').textContent)
      .toContain('the asker or PM settles it')
    expect(screen.getByTestId('procmap-loop-needs-info').getAttribute('marker-end'))
      .toBe('url(#arrow-loop)')
  })

  it('keeps every way out of the flow on the chart', () => {
    wrap()
    for (const key of [
      'rejected', 'not-feasible', 'rejected-declined', 'cancelled', 'closed',
      'on-hold', 'deviation', 'negotiation', 'internal-approval', 'plan-concern',
      'plan-deviation', 'recovery', 'progress-report', 'nothing-impacted',
      'release-checklist', 'lessons', 'bank-build', 'publish-plan',
    ]) {
      expect(screen.getByTestId(`procmap-node-${key}`)).toBeTruthy()
    }
    expect(screen.getByTestId('procmap-edge-captured-rejected')).toBeTruthy()
    expect(screen.getByTestId('procmap-node-on-hold').textContent).toContain('resumes only where it left off')
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
    expect(pnl('approved')).toContain('frozen at the go decision')
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
    expect(l3).toContain('recovery ends after the')
    expect(l3).toContain('release date, or L2 is not')
  })

  it('runs the mother-plant side track in its own lane, skipping assessment to offer', () => {
    wrap()
    const lane = screen.getByTestId('procmap-mother-plant-lane').textContent ?? ''
    expect(lane).toContain('KTX Weissenburg (WUG)')
    expect(lane).toContain('KTX Solingen')
    expect(lane).toContain('read and understood')
    expect(lane).toContain('release date = their SOP')
    expect(lane).toContain('Never: assessment, costing, offer, quote deadline')
    expect(lane).toContain('Started by Project Management only')
    expect(screen.getByTestId('procmap-node-mp-origin').textContent).toContain('PM starts it')
    expect(screen.getByTestId('procmap-node-mp-origin').textContent).toContain('skips assessment, costing, offer')
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
      .toContain('A failed check offers to raise a validation issue, and a person raises it')
  })

  it('keeps the responsibles and the build order in their own blocks', () => {
    wrap()
    expect(screen.getByTestId('procmap-role-in_assessment').textContent)
      .toBe('Routed departments (Sales exempt)')
    // Who starts a change: Sales (PM may too); the mother-plant origin is PM only.
    const capture = screen.getByTestId('procmap-role-captured').textContent ?? ''
    expect(capture).toContain('Sales (can_start_change); PM may start')
    expect(capture).toContain('KTX Weissenburg / Solingen is started by Project Management only')
    expect(screen.getByTestId('procmap-table').querySelectorAll('tbody tr')).toHaveLength(11)
    expect(screen.getByTestId('procmap-rules').querySelectorAll('li')).toHaveLength(12)
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
    expect(lane.textContent).toContain('or without one when it gives a note')
    // Development owns the intake and the review lane, not "the team".
    expect(screen.getByTestId('procmap-node-intake').textContent).toContain('Development')
    for (const id of ['procmap-rv-triage', 'procmap-rv-lock', 'procmap-rv-review']) {
      expect(screen.getByTestId(id).textContent).toContain('Development')
      expect(screen.getByTestId(id).textContent).not.toContain('Team')
    }
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
      expect(scoping).toContain('change lead')
      const assessment = screen.getByTestId('procmap-ov-stage-assessment').textContent ?? ''
      expect(assessment).toContain('HARD impact set locked')
      expect(assessment).toContain('cost carrier set')
      // One gate per path into Timing: customer, internal, Weissenburg / Solingen.
      const timing = screen.getByTestId('procmap-ov-stage-timing').textContent ?? ''
      expect(timing).toContain('PM + Quality sign-off (two people)')
      expect(timing).toContain('internal: PM approved costs + release deadline')
      expect(timing).toContain('SOP date')
      expect(screen.getByTestId('procmap-ov-stage-release').textContent).toContain('plan deviation')
      expect(screen.getByTestId('procmap-overview').textContent).not.toContain('never gate')
      expect(screen.getByTestId('procmap-ov-stage-costing').textContent)
        .toContain('costing lines with rate snapshot')
      expect(screen.getByTestId('procmap-overview-audit').textContent).toContain('Audit trail on every stage')
      const lanes = screen.getByTestId('procmap-overview-lanes').textContent ?? ''
      expect(lanes).toContain('L1 department, L2 project, L3 management')
      expect(lanes).toContain('Skips assessment, costing, offer')
      expect(lanes).toContain('Started by Project Management only')
      expect(lanes).toContain('PM captures: ref + SOP')
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
