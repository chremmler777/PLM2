import { describe, expect, it, vi } from 'vitest'
import type { AxiosRequestConfig } from 'axios'
import { createTrainingAdapter } from './sandbox/adapter'
import { createSandbox, SEED, type SandboxState } from './sandbox/state'
import { assertCurriculumCovered, TASKS, TASKS_BY_ROLE } from './tasks'

//: Every check driven through the real adapter with the payloads the real
//: screens send (ported from TWOS tasks.test.ts). The one property that
//: matters most: no task passes against an untouched sandbox.

//: Spelled out literally, like backend tests/test_training.py: a rename on one
//: side must be a deliberate two-file change.
const EXPECTED: Record<string, string[]> = {
  project_management: ['pm_set_priority'],
  sales: ['sales_start_change'],
  engineering: ['eng_answer_checklist_row', 'eng_submit_assessment'],
  scheduling: ['sch_answer_checklist_row'],
  quality: ['qa_answer_checklist_row'],
  finance: ['fin_answer_checklist_row'],
}

async function send(s: SandboxState, method: string, url: string, data?: unknown) {
  const adapter = createTrainingAdapter(s, vi.fn() as never)
  const config: AxiosRequestConfig = { method, url, data: data === undefined ? undefined : JSON.stringify(data) }
  return (await adapter(config)).data as Record<string, unknown>
}

const inTwoWeeks = () => {
  const d = new Date()
  d.setDate(d.getDate() + 10)
  return `${d.toISOString().slice(0, 10)}T23:59:59Z`
}

/** What ActivityChecklist + AssessmentSubmitForm put in details, row by row. */
function impacts(yes: Record<string, string>, restNo = false) {
  const rows: Record<string, unknown>[] = Object.entries(yes).map(([key, remark]) => ({
    key, answer: 'yes', impacted: true, remark,
  }))
  if (restNo) {
    for (const d of createSandbox().checklist) {
      if (!(d.key in yes)) rows.push({ key: d.key, answer: 'no', impacted: false, bulk: true })
    }
  }
  return { impacts: rows }
}

async function saveDraft(s: SandboxState, department: string, details: Record<string, unknown>) {
  const aid = SEED.assessmentFor[department]
  await send(s, 'put', `/v1/changes/${SEED.changeInAssessment}/assessments/${aid}/draft`, {
    draft: { details, verdict: '', conditions: '', notes: '' },
  })
}

describe('the curriculum', () => {
  it('matches the server contract', () => {
    expect(Object.fromEntries(
      Object.entries(TASKS_BY_ROLE).map(([r, ts]) => [r, ts.map((t) => t.key)]))).toEqual(EXPECTED)
  })

  it('asks no role for more than five tasks', () => {
    for (const ts of Object.values(TASKS_BY_ROLE)) {
      expect(ts.length).toBeGreaterThan(0)
      expect(ts.length).toBeLessThanOrEqual(5)
    }
  })

  it('names the keys this build cannot score', () => {
    expect(assertCurriculumCovered(['sales_start_change', 'nope'])).toEqual(['nope'])
  })

  it('passes no task against an untouched sandbox', () => {
    for (const task of Object.values(TASKS)) {
      const r = task.check(createSandbox())
      expect(r.passed, task.key).toBe(false)
      expect(r.hint, task.key).toBeTruthy()
    }
  })

  it('uses no em-dash in anything the trainee reads', () => {
    for (const t of Object.values(TASKS)) {
      expect(`${t.title} ${t.brief} ${t.why}`).not.toMatch(/\u2014/)
    }
  })
})

describe('sales_start_change', () => {
  const task = TASKS.sales_start_change
  const body = (ids: number[], reason = 'Customer drawing: reinforced clip tower') => ({
    project_id: SEED.project, title: 'x', change_type: 'physical_part', reason,
    customer_relevant: true, impacted_part_ids: ids, lead_part_id: ids[0], title_auto: true,
  })

  it('passes with both parts, the cladding leading', async () => {
    const s = createSandbox()
    await send(s, 'post', '/v1/changes', body([SEED.partLead, SEED.partSibling]))
    expect(task.check(s).passed).toBe(true)
  })

  it('fails without the PEAK variant, or with the wrong lead', async () => {
    let s = createSandbox()
    await send(s, 'post', '/v1/changes', body([SEED.partLead]))
    expect(task.check(s).hint).toMatch(/PEAK/)
    s = createSandbox()
    await send(s, 'post', '/v1/changes', body([SEED.partSibling, SEED.partLead]))
    expect(task.check(s).hint).toMatch(/lead/)
  })
})

describe('pm_set_priority', () => {
  const task = TASKS.pm_set_priority
  const url = `/v1/changes/${SEED.changeCaptured}`

  it('passes with High and a deadline within two weeks', async () => {
    const s = createSandbox()
    await send(s, 'patch', url, { priority: 'high' })
    expect(task.check(s).hint).toMatch(/deadline/)
    await send(s, 'patch', url, { required_by_date: inTwoWeeks(), required_by_reason: null })
    expect(task.check(s).passed).toBe(true)
  })

  it('does not take Critical for High', async () => {
    const s = createSandbox()
    await send(s, 'patch', url, { priority: 'critical', required_by_date: inTwoWeeks() })
    expect(task.check(s).hint).toMatch(/Critical/)
  })
})

describe('checklist rows', () => {
  const cases: [string, string, string][] = [
    ['eng_answer_checklist_row', 'Tool Engineer', 'modification_internal'],
    ['sch_answer_checklist_row', 'Scheduling', 'bank_build_needed'],
    ['qa_answer_checklist_row', 'Quality', 'dimensional_risk'],
    ['fin_answer_checklist_row', 'Finance', 'modification_internal'],
  ]
  it.each(cases)('%s passes on a saved Yes with the work named', async (key, dept, row) => {
    const s = createSandbox()
    await saveDraft(s, dept, impacts({ [row]: 'Modify the clip tower insert' }))
    expect(TASKS[key].check(s).passed).toBe(true)
  })

  it.each(cases)('%s fails on a Yes with no remark, and on a No', async (key, dept, row) => {
    let s = createSandbox()
    await saveDraft(s, dept, impacts({ [row]: '' }))
    expect(TASKS[key].check(s).hint).toMatch(/what has to be done/)
    s = createSandbox()
    await saveDraft(s, dept, { impacts: [{ key: row, answer: 'no', impacted: false }] })
    expect(TASKS[key].check(s).hint).toMatch(/No/)
  })

  it('does not count another department\'s answer', async () => {
    const s = createSandbox()
    await saveDraft(s, 'Quality', impacts({ modification_internal: 'Modify the insert' }))
    expect(TASKS.eng_answer_checklist_row.check(s).passed).toBe(false)
  })
})

describe('eng_submit_assessment', () => {
  const task = TASKS.eng_submit_assessment
  const dept = SEED.departments['Tool Engineer']
  const url = `/v1/changes/${SEED.changeInAssessment}/assessments`

  it('passes on a feasible submit with only the modification answered Yes', async () => {
    const s = createSandbox()
    await send(s, 'post', url, { department_id: dept, verdict: 'feasible',
      details: impacts({ modification_internal: 'Modify the clip tower insert' }, true) })
    expect(task.check(s).passed).toBe(true)
  })

  it('fails when more rows say Yes than the brief describes', async () => {
    const s = createSandbox()
    await send(s, 'post', url, { department_id: dept, verdict: 'feasible',
      details: impacts({ modification_internal: 'Modify the insert', threed_change: 'CAD' }, true) })
    expect(task.check(s).hint).toMatch(/More rows/)
  })
})
