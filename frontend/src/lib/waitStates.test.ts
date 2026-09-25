import { describe, it, expect } from 'vitest'
import { assessmentProgress, resolveWaitStates, earlyStageWaits, deriveAssessmentState } from './waitStates'
import { t } from '../i18n/cmLabels'

const change = (over: Record<string, unknown> = {}) => ({
  status: 'scoping', customer_relevant: true, blocked_department_ids: [],
  costing_pending_department_ids: [], rejection_sent_at: null, ...over,
}) as never

const concern = (over: Record<string, unknown> = {}) => ({
  id: 1, change_id: 7, kind: 'needs_info', note: 'What is the target price?',
  raised_by: 9, raised_at: '2026-08-01T09:00:00', is_open: true,
  department_id: null, answer_note: null, answered_at: null, ...over,
}) as never

const deptName = (id: number) => ({ 2: 'Development', 4: 'Tool Engineer' }[id] ?? `#${id}`)

const row = (over: Record<string, unknown> = {}) => ({
  department_id: 2, rasic_letter: 'R', status: 'active', stage_order: 1,
  submitted_at: null, verdict: 'pending', ...over,
}) as never

describe('assessmentProgress', () => {
  it('counts a department once, however many rows it left behind', () => {
    // Re-routing and multi-stage routing both leave several rows per department;
    // "3/5" must mean five departments, not five rows.
    const p = assessmentProgress([
      { departmentId: 2, rasic: 'R', submitted: true, dormant: false },
      { departmentId: 2, rasic: 'R', submitted: false, dormant: false },
      { departmentId: 4, rasic: 'A', submitted: false, dormant: false },
    ])
    expect(p).toEqual({ done: 1, total: 2, waiting: [4] })
  })
})

describe('resolveWaitStates', () => {
  it('says nothing when nothing is waiting', () => {
    expect(resolveWaitStates(change(), [], deptName)).toEqual([])
  })

  it('waits on Sales while a customer question is unanswered', () => {
    const [w] = resolveWaitStates(change(), [concern()], deptName)
    expect(w.key).toBe('sales-info-1')
    expect(w.text).toContain('What is the target price?')
    expect(w.tab).toBe('scoping')
  })

  it('waits on review once the answer is in', () => {
    const [w] = resolveWaitStates(change(),
      [concern({ answer_note: '12.50', answered_at: '2026-08-02T00:00:00' })], deptName)
    expect(w.key).toBe('review-1')
    expect(w.text).toContain(t('wait.onReview').split('{x}')[0].trim())
  })

  it('forgets a question that has been settled', () => {
    expect(resolveWaitStates(change(), [concern({ is_open: false })], deptName)).toEqual([])
  })

  it('counts a department-attributed question exactly like a team one', () => {
    // The backend gives Sales the task for any open needs-info flag; the banner
    // must agree, or a task exists that the change page denies.
    const waits = resolveWaitStates(change(), [
      concern({ id: 1, department_id: 6, note: 'packaging dimensions?' }),
      concern({ id: 2, department_id: null, note: 'target price?' }),
    ], deptName)
    expect(waits.map((w) => w.key)).toEqual(['sales-info-1', 'sales-info-2'])
    expect(waits[0].text).toContain('packaging dimensions?')
  })

  it('watches questions at any live status, not only scoping', () => {
    for (const status of ['captured', 'in_assessment', 'costing', 'quoted', 'approved']) {
      const waits = resolveWaitStates(change({ status }), [concern()], deptName)
      expect(waits[0].key).toBe('sales-info-1')
    }
  })

  it('names the departments an open concern is holding, in assessment', () => {
    const waits = resolveWaitStates(
      change({ status: 'in_assessment', blocked_department_ids: [2, 4] }), [], deptName)
    expect(waits[0].key).toBe('blocked-departments')
    expect(waits[0].text).toContain('Development, Tool Engineer')
    // Only while the assessment is the live phase.
    expect(resolveWaitStates(
      change({ status: 'costing', blocked_department_ids: [2] }), [], deptName)).toEqual([])
  })

  it('names the departments still owing cost input, while costing', () => {
    const waits = resolveWaitStates(
      change({ status: 'costing', costing_pending_department_ids: [2, 4] }), [], deptName)
    expect(waits[0].key).toBe('costing-input')
    expect(waits[0].text).toContain('Development, Tool Engineer')
    expect(waits[0].tab).toBe('costing')
    // Only while costing is the live phase.
    expect(resolveWaitStates(
      change({ status: 'quoted', costing_pending_department_ids: [2] }), [], deptName)).toEqual([])
  })

  it('waits on the rejection letter until the customer has been told', () => {
    const waits = resolveWaitStates(change({ status: 'rejected' }), [], deptName)
    expect(waits[0].key).toBe('rejection-letter')
    expect(resolveWaitStates(
      change({ status: 'rejected', rejection_sent_at: '2026-08-04T00:00:00' }), [], deptName)
    ).toEqual([])
    // An internal change owes the customer nothing.
    expect(resolveWaitStates(
      change({ status: 'rejected', customer_relevant: false }), [], deptName)).toEqual([])
  })

  it('waits on Scheduling for the bank-build decision once approved', () => {
    const waits = resolveWaitStates(change({ status: 'approved' }), [], deptName)
    expect(waits.map((w) => w.key)).toEqual(['bank-build'])
    expect(waits[0].text).toBe(t('wait.onBankBuild'))
    expect(waits[0].tab).toBe('timing')
    // Only at approved: earlier the decision is not due, later it is history.
    expect(resolveWaitStates(change({ status: 'quoted' }), [], deptName)).toEqual([])
    expect(resolveWaitStates(
      change({ status: 'in_implementation' }), [], deptName)).toEqual([])
  })

  it('waits on Sales to publish the plan once the mode is set and the timing is validated', () => {
    const waits = resolveWaitStates(
      change({ status: 'approved', bank_build_mode: 'planned_scrap',
        timing_validated_at: '2026-08-09T09:00:00' }), [], deptName)
    expect(waits.map((w) => w.key)).toEqual(['plan-publish'])
    expect(waits[0].text).toBe(t('wait.onPlanPublish'))
    expect(waits[0].tab).toBe('timing')
    // Not validated yet: nothing to publish.
    expect(resolveWaitStates(change({ status: 'approved', bank_build_mode: 'planned_scrap' }),
      [], deptName)).toEqual([])
    // Published: nothing left; and an internal change has nobody to publish to.
    expect(resolveWaitStates(change({
      status: 'approved', bank_build_mode: 'planned_scrap', timing_validated_at: '2026-08-09T09:00:00',
      plan_published_at: '2026-08-10T09:00:00',
    }), [], deptName)).toEqual([])
    expect(resolveWaitStates(change({
      status: 'approved', bank_build_mode: 'running_change', customer_relevant: false,
      timing_validated_at: '2026-08-09T09:00:00',
    }), [], deptName)).toEqual([])
  })

  it('names the teams the timing still waits on at approved', () => {
    const fb = {
      required: [
        { department_name: 'Development', verdict: 'confirmed', stale: false },
        { department_name: 'Tool Engineer', verdict: null, stale: false },
        { department_name: 'Quality', verdict: 'confirmed', stale: true },
      ],
      all_confirmed: false, validated_at: null,
    }
    const waits = resolveWaitStates(change({ status: 'approved', bank_build_mode: 'running_change' }),
      [], deptName, [], {}, null, fb)
    expect(waits.map((w) => w.key)).toEqual(['timing-confirm'])
    expect(waits[0].text).toBe('Timing: waiting on team confirmation: Tool Engineer, Quality')
    expect(waits[0].tab).toBe('timing')
  })

  it('says the timing is not validated once every team confirmed', () => {
    const fb = {
      required: [{ department_name: 'Development', verdict: 'confirmed', stale: false }],
      all_confirmed: true, validated_at: null,
    }
    const waits = resolveWaitStates(change({ status: 'approved', bank_build_mode: 'running_change' }),
      [], deptName, [], {}, null, fb)
    expect(waits.map((w) => w.key)).toEqual(['timing-validate'])
    expect(waits[0].text).toBe('Timing not validated')
    // Validated (per the feedback): the publish wait takes over.
    const after = resolveWaitStates(change({ status: 'approved', bank_build_mode: 'running_change' }),
      [], deptName, [], {}, null, { ...fb, validated_at: '2026-08-09T09:00:00' })
    expect(after.map((w) => w.key)).toEqual(['plan-publish'])
  })

  it('lists the bank-build and timing waits side by side', () => {
    const fb = { required: [{ department_name: 'Scheduling', verdict: 'concern', stale: false }] }
    const waits = resolveWaitStates(change({ status: 'approved' }), [], deptName, [], {}, null, fb)
    expect(waits.map((w) => w.key)).toEqual(['bank-build', 'timing-confirm'])
  })

  it('names the departments the assessment round is still waiting on', () => {
    const waits = resolveWaitStates(
      change({ status: 'in_assessment' }), [], deptName,
      [row({ department_id: 2, status: 'submitted', verdict: 'feasible',
        submitted_at: '2026-08-05T00:00:00' }),
      row({ department_id: 4 })])
    expect(waits[0].key).toBe('assessment-round')
    expect(waits[0].tab).toBe('assessments')
    expect(waits[0].text).toContain('Tool Engineer')
    expect(waits[0].text).toContain('(1/2)')
    // Everyone sees it — it is not gated on membership or role.
    expect(waits[0].text).not.toContain('Development')
  })

  it('says nothing once every department has answered', () => {
    expect(resolveWaitStates(change({ status: 'in_assessment' }), [], deptName,
      [row({ department_id: 2, status: 'submitted', verdict: 'feasible' })])).toEqual([])
  })

  it('only counts the departments that owe an answer', () => {
    // S/C/I are consulted, not on the hook — counting them would make the board
    // look permanently unfinished.
    expect(resolveWaitStates(change({ status: 'in_assessment' }), [], deptName,
      [row({ department_id: 4, rasic_letter: 'C' }),
        row({ department_id: 2, rasic_letter: 'I' })])).toEqual([])
    // Waived and not-yet-started rows owe nothing right now either.
    expect(resolveWaitStates(change({ status: 'in_assessment' }), [], deptName,
      [row({ department_id: 4, status: 'waived' }),
        row({ department_id: 2, status: 'pending' })])).toEqual([])
  })

  it('keeps the assessment line out of every other phase', () => {
    expect(resolveWaitStates(change({ status: 'costing' }), [], deptName,
      [row({ department_id: 4 })])).toEqual([])
  })

  it('counts the departments that owe a progress report, while the work runs', () => {
    const waits = resolveWaitStates(change({ status: 'in_implementation' }), [], deptName, [], {
      state: [
        { department_id: 2, booked_hours: 4, last_report_at: null,
          at_risk_open: false, owes_report: true },
        { department_id: 4, booked_hours: 0, last_report_at: null,
          at_risk_open: false, owes_report: true },
        { department_id: 6, booked_hours: 2, last_report_at: '2026-08-10T09:00:00',
          at_risk_open: false, owes_report: false },
      ],
    })
    expect(waits.map((w) => w.key)).toEqual(['implementation-reports'])
    expect(waits[0].text).toBe(t('wait.onProgressReports').replace('{n}', '2'))
    expect(waits[0].tab).toBe('timing')
  })

  it('keeps the implementation waits out of every other phase', () => {
    const state = [{ department_id: 2, booked_hours: 0, last_report_at: null,
      at_risk_open: true, owes_report: true }]
    expect(resolveWaitStates(change({ status: 'in_validation' }), [], deptName, [], { state }))
      .toEqual([])
  })

  it('waits on Sales while a flagged risk has been taken nowhere', () => {
    const state = [{ department_id: 2, booked_hours: 6, last_report_at: '2026-08-10T09:00:00',
      at_risk_open: true, owes_report: false }]
    const waits = resolveWaitStates(
      change({ status: 'in_implementation' }), [], deptName, [], { state })
    expect(waits.map((w) => w.key)).toEqual(['implementation-escalation'])
    expect(waits[0].text).toBe(t('wait.onRiskEscalation'))
    expect(waits[0].tab).toBe('timing')

    // An open escalation is the answer; a settled one is not.
    expect(resolveWaitStates(change({ status: 'in_implementation' }), [], deptName, [],
      { state, escalations: [{ resolved_at: null }] })).toEqual([])
    expect(resolveWaitStates(change({ status: 'in_implementation' }), [], deptName, [],
      { state, escalations: [{ resolved_at: '2026-08-11T09:00:00' }] })
      .map((w) => w.key)).toEqual(['implementation-escalation'])
  })

  it('says nothing about implementation when nothing is owed and nothing is flagged', () => {
    expect(resolveWaitStates(change({ status: 'in_implementation' }), [], deptName, [], {
      state: [{ department_id: 2, booked_hours: 6, last_report_at: '2026-08-10T09:00:00',
        at_risk_open: false, owes_report: false }],
    })).toEqual([])
    // And nothing at all when the board has not loaded yet.
    expect(resolveWaitStates(change({ status: 'in_implementation' }), [], deptName)).toEqual([])
  })

  it('counts the departments that still owe a validation check', () => {
    const waits = resolveWaitStates(
      change({ status: 'in_validation' }), [], deptName, [], {}, {
        departments: [
          { department_id: 2, checks: [
            { check_key: 'sampled', status: 'passed' },
            { check_key: 'revision_bump', status: 'open' }] },
          { department_id: 4, checks: [{ check_key: 'weight', status: 'failed' }] },
          { department_id: 6, checks: [{ check_key: 'measured', status: 'passed' }] },
        ],
      })
    expect(waits.map((w) => w.key)).toEqual(['validation-checks'])
    expect(waits[0].text).toBe(t('wait.onValidationChecks').replace('{n}', '2'))
    expect(waits[0].tab).toBe('release')
  })

  it('does not wait on a retired validation row', () => {
    const waits = resolveWaitStates(
      change({ status: 'in_validation' }), [], deptName, [], {}, {
        departments: [
          { department_id: 2, checks: [
            { check_key: 'sampled', status: 'passed' },
            { check_key: 'old_check', status: 'open', retired: true }] },
        ],
      })
    expect(waits).toEqual([])
  })

  it('names the unacknowledged weight delta as its own wait, on Sales', () => {
    const state = {
      departments: [{ department_id: 4, checks: [
        { check_key: 'weight', status: 'passed' as const, value: 512 }] }],
      weight_estimate_g: 500, validated_weight_g: 512, weight_delta_g: 12,
    }
    const waits = resolveWaitStates(
      change({ status: 'in_validation' }), [], deptName, [], {}, state)
    expect(waits.map((w) => w.key)).toEqual(['validation-weight-ack'])
    expect(waits[0].text).toBe(t('wait.onWeightAck'))

    // Acknowledged is settled; a delta of zero never was a wait.
    expect(resolveWaitStates(change({ status: 'in_validation' }), [], deptName, [], {},
      { ...state, weight_ack_at: '2026-08-11T09:00:00' })).toEqual([])
    expect(resolveWaitStates(change({ status: 'in_validation' }), [], deptName, [], {},
      { ...state, weight_delta_g: 0 })).toEqual([])
  })

  it('keeps the validation waits out of every other phase, and off an unloaded board', () => {
    const state = {
      departments: [{ department_id: 2, checks: [
        { check_key: 'sampled', status: 'open' as const }] }],
      weight_delta_g: 12,
    }
    expect(resolveWaitStates(
      change({ status: 'in_implementation' }), [], deptName, [], {}, state)).toEqual([])
    expect(resolveWaitStates(change({ status: 'in_validation' }), [], deptName)).toEqual([])
  })

  it('lists every wait at once', () => {
    const waits = resolveWaitStates(
      change({ status: 'in_assessment', blocked_department_ids: [2] }),
      [concern(), concern({ id: 2, note: 'timing?', answer_note: 'Q4',
        answered_at: '2026-08-02T00:00:00' })], deptName)
    expect(waits.map((w) => w.key)).toEqual(['sales-info-1', 'review-2', 'blocked-departments'])
  })
})

describe('resolveWaitStates: deviations and release blockers', () => {
  const deptName = (id: number) => `#${id}`
  it('names open plan deviations as information while the work runs', () => {
    const waits = resolveWaitStates(change({ status: 'in_implementation' }), [], deptName, [], {}, null, null,
      { openPlanDeviations: 2 })
    expect(waits).toEqual([expect.objectContaining({ key: 'plan-deviations', info: true, tab: 'timing' })])
    expect(waits[0].text).toContain('2 plan deviations')
  })
  it('lists the release guard reasons at validation, once each', () => {
    const waits = resolveWaitStates(change({ status: 'in_validation' }), [], deptName, [], {}, null, null, {
      openPlanDeviations: 1,
      releaseBlockers: ['Not ready to go: 2 revisions open', 'Lessons learned step not done',
        '1 plan deviation still open: lock or escalate them first'],
    })
    expect(waits.map((w) => w.text)).toEqual(['Not ready to go: 2 revisions open', 'Lessons learned step not done',
      '1 plan deviation still open: lock or escalate them first'])
    expect(waits.every((w) => !w.info)).toBe(true)
    expect(waits[2].tab).toBe('timing')
  })
})

describe('earlyStageWaits (spec §16)', () => {
  const base = { status: 'in_assessment' as const, lead_id: 5 }
  it('takes the backend rows, replacing the client assessment line and skipping duplicates', () => {
    const out = earlyStageWaits(base,
      [{ key: 'assessment-round', text: 'client line', tab: 'assessments' },
        { key: 'sales-info-3', text: 'Waiting on Sales: X', tab: 'scoping' }],
      [{ kind: 'assessment_waiting', text: 'Assessment: waiting on Development (1/2)', target_tab: 'assessments' },
        { kind: 'waiting_on_sales_answer', text: 'Waiting on Sales to answer 1 question(s)', target_tab: 'scoping' },
        { kind: 'not_feasible', text: 'Tool Engineer: not feasible (Change PPT)', department_id: 27, target_tab: 'assessments' },
        { kind: 'no_lead', text: 'No lead assigned', target_tab: 'overview' }])
    expect(out.map((w) => w.key)).toEqual(['sales-info-3', 'assessment-round', 'not_feasible-27', 'no_lead'])
    expect(out.find((w) => w.key === 'assessment-round')!.text).toContain('Development')
    expect(out.find((w) => w.key === 'no_lead')!.tab).toBeUndefined()
  })
  it('derives no lead, open cancel votes, not feasible and scope rows without stage-state', () => {
    const out = earlyStageWaits({ ...base, lead_id: null, scope_changed_after_quote: true, scope_offer_version: 2 }, [], undefined, {
      concerns: [{ id: 1, kind: 'reject_proposal', is_open: true, raised_by: 3, raised_by_name: 'Ann' } as never],
      assessments: [{ department_id: 27, verdict: 'not_feasible', stage_order: 1, rasic_letter: 'R', has_change_ppt: false }],
      departmentName: () => 'Tool Engineer',
    })
    expect(out.map((w) => w.text)).toEqual([
      'No lead assigned',
      '1 open cancel vote from Ann',
      'Tool Engineer: not feasible (no Change PPT)',
      'Offer v2 no longer covers the scope: new offer version or approved deviation',
    ])
  })
})

describe('deriveAssessmentState', () => {
  it('counts first-stage R/A rows only', () => {
    const a = deriveAssessmentState([
      { id: 1, department_id: 1, rasic_letter: 'R', status: 'submitted', submitted_at: 'x', verdict: 'feasible', stage_order: 1 },
      { id: 2, department_id: 2, rasic_letter: 'A', status: 'active', submitted_at: null, verdict: 'pending', stage_order: 1 },
      { id: 3, department_id: 3, rasic_letter: 'C', status: 'active', submitted_at: null, verdict: 'pending', stage_order: 1 },
      { id: 4, department_id: 4, rasic_letter: 'R', status: 'active', submitted_at: null, verdict: 'pending', stage_order: 2 },
    ] as never, (id) => `D${id}`)!
    expect(a.total).toBe(2)
    expect(a.waiting_on.map((d) => d.department_name)).toEqual(['D2'])
    expect(a.all_submitted).toBe(false)
    expect(a.verdicts.map((v) => v.verdict)).toEqual(['feasible'])
  })
})
