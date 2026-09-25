import {
  SEED,
  checklistAnswers,
  createdChanges,
  findChange,
  type SandboxState,
} from './sandbox/state'

//: The practical tasks, ported from TWOS (frontend/src/training/tasks.ts).
//:
//: Every check asserts on the *outcome* (what the record says afterwards),
//: never on which buttons were pressed, so any legitimate route to the
//: correct record passes. A failed check returns a hint and the trainee
//: retries; retries are unlimited and every one is recorded.
//:
//: The keys are the contract with the server (backend app/services/
//: training.py CURRICULA). They are spelled out again in tasks.test.ts and in
//: backend tests/test_training.py, so a rename is a deliberate change.
//:
//: These are sample tasks proving the mechanism, one or two per role. The
//: final curriculum is written after the UI polish; the format is described
//: at the top of training/manual/chapters.tsx and in TrainingTask below.

/** Which real PLM2 screen the sandbox mounts for a task. */
export type Screen =
  | { kind: 'start-change' }
  | { kind: 'change-status'; changeId: number }
  | { kind: 'assessment'; department: string }

export interface CheckResult {
  passed: boolean
  /** Shown to the trainee on a fail. Names what is missing, never who is wrong. */
  hint?: string
  /** Recorded on the attempt row: what the sandbox held when it was graded. */
  detail?: Record<string, unknown>
}

export interface TrainingTask {
  key: string
  title: string
  /** The brief, in plain working language. What to do, not how. */
  brief: string
  /** Why this is in the check at all. Read once, before starting. */
  why: string
  screen: Screen
  check: (s: SandboxState) => CheckResult
}

const pass = (detail?: Record<string, unknown>): CheckResult => ({ passed: true, detail })
const failWith = (hint: string, detail?: Record<string, unknown>): CheckResult => ({
  passed: false,
  hint,
  detail,
})

// ---------------------------------------------------------------------------
// A checklist row, answered Yes with what has to be done
// ---------------------------------------------------------------------------

function answerRowTask(opts: {
  key: string
  department: string
  rowKey: string
  rowLabel: string
  title: string
  brief: string
  why: string
}): TrainingTask {
  return {
    key: opts.key,
    title: opts.title,
    brief: opts.brief,
    why: opts.why,
    screen: { kind: 'assessment', department: opts.department },
    check: (s) => {
      const { source, impacts } = checklistAnswers(s, opts.department)
      if (source === null) {
        return failWith(
          'Nothing has reached the record yet. Answer the row, then wait until the ' +
            'form says the draft is saved before checking.',
        )
      }
      const row = impacts.find((i) => i.key === opts.rowKey)
      if (!row || !row.answer) {
        return failWith(`The row "${opts.rowLabel}" is still unanswered.`, { source })
      }
      if (row.answer !== 'yes') {
        return failWith(
          `"${opts.rowLabel}" is answered No. Read the brief again: this change does ` +
            'affect it.',
          { answer: row.answer },
        )
      }
      const remark = String(row.remark ?? '').trim()
      if (remark.length < 5) {
        return failWith(
          'The row says Yes but not what has to be done. A Yes without the work ' +
            'behind it cannot be costed or planned.',
          { remark },
        )
      }
      return pass({ source, row: opts.rowKey, remark_length: remark.length })
    },
  }
}

// ---------------------------------------------------------------------------
// Sales
// ---------------------------------------------------------------------------

const sales: TrainingTask[] = [
  {
    key: 'sales_start_change',
    title: 'Start a change request',
    screen: { kind: 'start-change' },
    brief:
      'The customer sent a new drawing for the Rear Cladding (TR.807.425) in project ' +
      'T100: the clip tower is reinforced. Start the change request, with the reason ' +
      "from the customer's mail. The PEAK variant (TR.807.426) comes from the same " +
      'tool and changes with it, so it belongs on the same request.',
    why:
      'One change request per tool family keeps one set of assessments and one ' +
      'revision per part. A request without its reason arrives at every department ' +
      'as a question instead of a task.',
    check: (s) => {
      const created = createdChanges(s)
      if (created.length === 0) {
        return failWith('No change request has been started yet.')
      }
      const c = created[created.length - 1]
      const parts = c.impacted_items.map((i) => i.part_id)
      const lead = c.impacted_items.find((i) => i.is_lead)?.part_id
      if (!parts.includes(SEED.partLead)) {
        return failWith(
          'The Rear Cladding (TR.807.425) is not on the request. It is the part the ' +
            'customer changed.',
          { parts },
        )
      }
      if (lead !== SEED.partLead) {
        return failWith(
          'The Rear Cladding should lead the request: it is the part the drawing is for, ' +
            'and the request is named after its lead item.',
          { lead },
        )
      }
      if (!parts.includes(SEED.partSibling)) {
        return failWith(
          'The PEAK variant (TR.807.426) is missing. It comes from the same tool, so it ' +
            'changes on the same request.',
          { parts },
        )
      }
      if ((c.reason ?? '').trim().length < 5) {
        return failWith('The reason is missing or too short to act on.')
      }
      return pass({ change_id: c.id, parts: parts.length })
    },
  },
]

// ---------------------------------------------------------------------------
// Project Management
// ---------------------------------------------------------------------------

const projectManagement: TrainingTask[] = [
  {
    key: 'pm_set_priority',
    title: 'Set priority and the quote deadline',
    screen: { kind: 'change-status', changeId: SEED.changeCaptured },
    brief:
      'CR-TRAIN-0001 (Grille Carrier) was escalated by the customer this morning. Set ' +
      'its priority to High, and give it a quote deadline: the customer expects the ' +
      'quote within two weeks.',
    why:
      'Priority orders everybody\'s task list, and the quote deadline is the date every ' +
      'department is measured against. A change without them waits behind work that ' +
      'is less urgent.',
    check: (s) => {
      const c = findChange(s, SEED.changeCaptured)
      if (!c) return failWith('The change is missing from this exercise. Start the task over.')
      if (c.priority !== 'high') {
        return failWith(
          c.priority === 'critical'
            ? 'Critical is for a stopped line or a safety issue. This one is High.'
            : 'The priority is still ' + c.priority + '.',
          { priority: c.priority },
        )
      }
      if (!c.required_by_date) {
        return failWith('The quote deadline is not set yet.')
      }
      const days = (Date.parse(c.required_by_date) - Date.now()) / 86_400_000
      if (days < 0 || days > 15) {
        return failWith(
          'The quote deadline should fall within the next two weeks.',
          { required_by_date: c.required_by_date },
        )
      }
      return pass({ priority: c.priority, required_by_date: c.required_by_date })
    },
  },
]

// ---------------------------------------------------------------------------
// Engineers
// ---------------------------------------------------------------------------

const engineering: TrainingTask[] = [
  answerRowTask({
    key: 'eng_answer_checklist_row',
    department: 'Tool Engineer',
    rowKey: 'modification_internal',
    rowLabel: 'Internal modification',
    title: 'Answer a checklist row',
    brief:
      'CR-TRAIN-0002 is waiting for the Tool Engineer assessment. The reinforced clip ' +
      'tower means the mold is modified in house. Answer the row "Internal ' +
      'modification" and say what has to be done.',
    why:
      'Every row is answered Yes or No, and a Yes carries the work behind it. That ' +
      'line is what costing prices and what the plan schedules.',
  }),
  {
    key: 'eng_submit_assessment',
    title: 'Submit the assessment',
    screen: { kind: 'assessment', department: 'Tool Engineer' },
    brief:
      'Finish the Tool Engineer assessment on CR-TRAIN-0002: the internal modification ' +
      'is needed (say what), nothing else on the list is affected. The change is ' +
      'feasible. Submit it.',
    why:
      'A department that has not submitted holds the whole change in assessment. ' +
      '"Rest to No" answers the untouched rows in one step, and reviewers can see it ' +
      'was used.',
    check: (s) => {
      const deptId = SEED.departments['Tool Engineer']
      const sub = [...s.submissions].reverse().find((x) => x.department_id === deptId)
      if (!sub) {
        return failWith('The assessment has not been submitted yet.')
      }
      if (!sub.verdict.startsWith('feasible')) {
        return failWith('The verdict should say the change is feasible.', { verdict: sub.verdict })
      }
      const impacts = Array.isArray(sub.details.impacts)
        ? (sub.details.impacts as { key?: string; answer?: string; remark?: string }[])
        : []
      const mod = impacts.find((i) => i.key === 'modification_internal')
      if (mod?.answer !== 'yes' || (mod.remark ?? '').trim().length < 5) {
        return failWith(
          '"Internal modification" should be Yes, with what has to be done.',
          { answer: mod?.answer },
        )
      }
      const extraYes = impacts.filter((i) => i.key !== 'modification_internal' && i.answer === 'yes')
      if (extraYes.length > 0) {
        return failWith(
          'More rows say Yes than the brief describes. Only the internal modification ' +
            'is affected.',
          { extra: extraYes.map((i) => i.key) },
        )
      }
      return pass({ verdict: sub.verdict, rows: impacts.length })
    },
  },
]

// ---------------------------------------------------------------------------
// Scheduling, Quality, Finance
// ---------------------------------------------------------------------------

const scheduling: TrainingTask[] = [
  answerRowTask({
    key: 'sch_answer_checklist_row',
    department: 'Scheduling',
    rowKey: 'cycle_time_change',
    rowLabel: 'Cycle time change',
    title: 'Answer a checklist row',
    brief:
      'CR-TRAIN-0002 is waiting for the Scheduling assessment. The reinforced clip ' +
      'tower adds cooling time to every shot. Answer the row "Cycle time change" and ' +
      'say what it means for the press plan.',
    why:
      'A longer cycle is lost press capacity. Said here, it reaches the plan; found ' +
      'after release, it is a shortage.',
  }),
]

const quality: TrainingTask[] = [
  answerRowTask({
    key: 'qa_answer_checklist_row',
    department: 'Quality',
    rowKey: 'dimensional_risk',
    rowLabel: 'Dimensional risk',
    title: 'Answer a checklist row',
    brief:
      'CR-TRAIN-0002 is waiting for the Quality assessment. The clip tower moves the ' +
      'mating surface to the bumper. Answer the row "Dimensional risk" and say what ' +
      'has to be checked.',
    why:
      'A risk named at assessment becomes a check in the plan. A risk nobody wrote ' +
      'down becomes a complaint.',
  }),
]

const finance: TrainingTask[] = [
  answerRowTask({
    key: 'fin_answer_checklist_row',
    department: 'Finance',
    rowKey: 'modification_internal',
    rowLabel: 'Internal modification',
    title: 'Answer a checklist row',
    brief:
      'CR-TRAIN-0002 is waiting for the Finance assessment. The mold is modified in ' +
      'house, which is toolshop time charged to the change. Answer the row "Internal ' +
      'modification" and say how it is to be booked.',
    why:
      'Internal hours are money the customer is asked to pay. Booked against the ' +
      'change, they appear in its P&L; booked nowhere, they are lost.',
  }),
]

export const TASKS_BY_ROLE: Record<string, TrainingTask[]> = {
  project_management: projectManagement,
  sales,
  engineering,
  scheduling,
  quality,
  finance,
}

export const TASKS: Record<string, TrainingTask> = Object.fromEntries(
  Object.values(TASKS_BY_ROLE)
    .flat()
    .map((t) => [t.key, t]),
)

/**
 * The runtime half of the contract with the server: the keys it asks for that
 * this build cannot score. A curriculum with any of them must not start;
 * grading a screen that never loaded would produce a record that says
 * something untrue.
 */
export function assertCurriculumCovered(keys: string[]): string[] {
  return keys.filter((k) => !(k in TASKS))
}
