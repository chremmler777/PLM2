import type { ChangeConcern, ChecklistItemDef } from '../../types/change'

//: The training fixture: a small, self-contained copy of the world one task
//: needs, rebuilt from scratch for every task and every retry. Nothing in it
//: comes from the live database, and nothing written to it goes back.
//:
//: Ids live far above anything the live system hands out (FIRST_TRAINEE_ID for
//: rows the trainee creates, the SEED range for the fixture's own), so a
//: training id can never be mistaken for a real one, in a log or in the
//: browser's local draft storage.

export const FIRST_TRAINEE_ID = 900_000

export const SEED = {
  project: 800_001,
  partLead: 800_101,
  partSibling: 800_102,
  partBracket: 800_103,
  partTool: 800_104,
  /** A change in capture, waiting for Project Management. */
  changeCaptured: 800_201,
  /** A change in assessment, waiting for the departments' answers. */
  changeInAssessment: 800_202,
  /** The assessment rows on changeInAssessment, one per department. */
  assessmentFor: {
    'Tool Engineer': 800_301,
    Quality: 800_302,
    Scheduling: 800_303,
    Finance: 800_304,
  } as Record<string, number>,
  departments: {
    Sales: 800_401,
    'Project Manager': 800_402,
    'Tool Engineer': 800_403,
    Quality: 800_404,
    Scheduling: 800_405,
    Finance: 800_406,
  } as Record<string, number>,
  pmUser: 800_501,
} as const

export const TRAINEE_NAME = 'You (training)'

export interface SandboxProject {
  id: number
  code: string
  name: string
}

export interface SandboxPart {
  id: number
  part_number: string
  customer_part_number: string | null
  name: string
  item_category: string
}

export interface SandboxChange {
  id: number
  change_number: string
  project_id: number
  title: string
  description: string | null
  reason: string | null
  change_type: string
  priority: 'low' | 'medium' | 'high' | 'critical'
  status: string
  customer_relevant: boolean
  lead_id: number | null
  lead_name: string | null
  raised_by: number
  required_by_date: string | null
  required_by_reason: string | null
  release_due_date: string | null
  release_due_reason: string | null
  deadline_state: 'on_track' | 'at_risk' | 'overdue' | null
  active_deadline: 'quote' | 'release' | null
  impacted_items: { id: number; part_id: number; is_lead: boolean; part_number: string }[]
  assessments: {
    id: number
    department_id: number
    department_name: string
    verdict: string | null
    details: Record<string, unknown> | null
    submitted_at: string | null
  }[]
  attachments: { id: number; filename: string; kind: string }[]
  created_at: string
  updated_at: string
  customer_response: 'pending'
  project_number: string
  project_name: string
  quoted_at: null
  quoted_on_time: null
}

export interface AssessmentSubmission {
  change_id: number
  department_id: number
  verdict: string
  details: Record<string, unknown>
  conditions?: string
  notes?: string
}

export interface SandboxState {
  /** Every request the sandbox answered, in order. */
  calls: { method: string; url: string }[]
  /** Requests no handler covered. Rendered as a red note on the task page. */
  misses: { method: string; url: string }[]
  nextId: number
  projects: SandboxProject[]
  parts: Record<number, SandboxPart[]>
  team: Record<number, { department_id: number; department_name: string;
    responsible: { id: number; name: string } | null }[]>
  changes: SandboxChange[]
  checklist: ChecklistItemDef[]
  riskTypes: { key: string; label_en: string; label_de: string }[]
  concerns: ChangeConcern[]
  /** Server-side assessment drafts, by assessment id. */
  drafts: Record<number, Record<string, unknown>>
  submissions: AssessmentSubmission[]
}

const nowIso = () => new Date().toISOString()

function daysFromNow(n: number): string {
  const d = new Date()
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

//: A short checklist on purpose, with the live system's own keys: the full
//: list is thirteen rows and the exercise is about answering one properly,
//: not about clicking through thirteen.
const CHECKLIST: ChecklistItemDef[] = [
  { key: 'threed_change', label_en: '3D change necessary', label_de: '3D-Änderung notwendig', extra: false },
  { key: 'modification_internal', label_en: 'Internal modification', label_de: 'Interne Änderung', extra: false },
  { key: 'bank_build_needed', label_en: 'Bank build needed', label_de: 'Vorproduktion (Bank Build) nötig', extra: false },
  { key: 'dimensional_risk', label_en: 'Dimensional risk', label_de: 'Maßliches Risiko', extra: false },
  { key: 'work_instruction_update', label_en: 'Work instruction update', label_de: 'Arbeitsanweisung aktualisieren', extra: false },
]

function change(over: Partial<SandboxChange> & Pick<SandboxChange, 'id' | 'change_number' | 'title'>): SandboxChange {
  return {
    project_id: SEED.project,
    description: null,
    reason: null,
    change_type: 'physical_part',
    priority: 'medium',
    status: 'captured',
    customer_relevant: true,
    lead_id: SEED.pmUser,
    lead_name: 'P. Manager',
    raised_by: SEED.pmUser,
    required_by_date: null,
    required_by_reason: null,
    release_due_date: null,
    release_due_reason: null,
    deadline_state: null,
    active_deadline: 'quote',
    impacted_items: [],
    assessments: [],
    attachments: [],
    created_at: nowIso(),
    updated_at: nowIso(),
    customer_response: 'pending',
    project_number: 'T100',
    project_name: 'Training Atlas',
    quoted_at: null,
    quoted_on_time: null,
    ...over,
  }
}

export function createSandbox(): SandboxState {
  //: A half-answered checklist is kept in this browser's local storage, keyed
  //: by change and department. Each task starts from the fixture, never from
  //: where the last attempt left off, so the fixture's keys are cleared here.
  clearSeedDrafts()

  const inAssessment = change({
    id: SEED.changeInAssessment,
    change_number: 'CR-TRAIN-0002',
    title: '20-9001-001-0 - TR.807.425 - Rear Cladding (training)',
    status: 'in_assessment',
    reason: 'Customer asks for a reinforced clip tower (training copy).',
    required_by_date: `${daysFromNow(10)}T23:59:59Z`,
    deadline_state: 'on_track',
    impacted_items: [{ id: 800_601, part_id: SEED.partLead, is_lead: true, part_number: '20-9001-001-0' }],
    assessments: Object.entries(SEED.assessmentFor).map(([name, id]) => ({
      id,
      department_id: SEED.departments[name],
      department_name: name,
      verdict: null,
      details: null,
      submitted_at: null,
    })),
  })

  return {
    calls: [],
    misses: [],
    nextId: FIRST_TRAINEE_ID,
    projects: [{ id: SEED.project, code: 'T100', name: 'Training Atlas' }],
    parts: {
      [SEED.project]: [
        { id: SEED.partLead, part_number: '20-9001-001-0', customer_part_number: 'TR.807.425', name: 'Rear Cladding', item_category: 'article' },
        { id: SEED.partSibling, part_number: '20-9001-002-0', customer_part_number: 'TR.807.426', name: 'Rear Cladding PEAK', item_category: 'article' },
        { id: SEED.partBracket, part_number: '10-9002-001-0', customer_part_number: 'TR.853.653', name: 'Grille Carrier', item_category: 'article' },
        { id: SEED.partTool, part_number: '9001', customer_part_number: null, name: 'Rear Cladding mold', item_category: 'tool' },
      ],
    },
    team: {
      [SEED.project]: [
        { department_id: SEED.departments['Project Manager'], department_name: 'Project Manager',
          responsible: { id: SEED.pmUser, name: 'P. Manager' } },
      ],
    },
    changes: [
      change({
        id: SEED.changeCaptured,
        change_number: 'CR-TRAIN-0001',
        title: '10-9002-001-0 - TR.853.653 - Grille Carrier (training)',
        status: 'captured',
        reason: 'Customer escalated a fit issue at the grille (training copy).',
        impacted_items: [{ id: 800_602, part_id: SEED.partBracket, is_lead: true, part_number: '10-9002-001-0' }],
      }),
      inAssessment,
    ],
    checklist: CHECKLIST,
    riskTypes: [
      { key: 'timing', label_en: 'Timing', label_de: 'Termin' },
      { key: 'quality', label_en: 'Quality', label_de: 'Qualität' },
      { key: 'cost', label_en: 'Cost', label_de: 'Kosten' },
    ],
    concerns: [],
    drafts: {},
    submissions: [],
  }
}

export function clearSeedDrafts(): void {
  try {
    for (const deptId of Object.values(SEED.departments)) {
      window.localStorage.removeItem(`cm-assessment-draft:${SEED.changeInAssessment}:${deptId}`)
    }
  } catch {
    // Storage off: nothing was kept, nothing to clear.
  }
}

export function findChange(s: SandboxState, id: number): SandboxChange | undefined {
  return s.changes.find((c) => c.id === id)
}

/** Changes the trainee created in this attempt. */
export function createdChanges(s: SandboxState): SandboxChange[] {
  return s.changes.filter((c) => c.id >= FIRST_TRAINEE_ID)
}

/** The checklist answers the department saved or submitted, latest first. */
export function checklistAnswers(
  s: SandboxState,
  department: string,
): { source: 'submitted' | 'draft' | null; impacts: Record<string, unknown>[] } {
  const deptId = SEED.departments[department]
  const submitted = [...s.submissions]
    .reverse()
    .find((x) => x.change_id === SEED.changeInAssessment && x.department_id === deptId)
  if (submitted) return { source: 'submitted', impacts: impactsIn(submitted.details) }
  const draft = s.drafts[SEED.assessmentFor[department]]
  if (draft) {
    const details = (draft as { details?: Record<string, unknown> }).details ?? {}
    return { source: 'draft', impacts: impactsIn(details) }
  }
  return { source: null, impacts: [] }
}

function impactsIn(details: Record<string, unknown> | null | undefined): Record<string, unknown>[] {
  return details && Array.isArray(details.impacts) ? (details.impacts as Record<string, unknown>[]) : []
}
