/**
 * Data, storage and styles for the one-page overview of the Process Flow
 * (ProcessOverview.tsx). Kept apart so the component file only exports
 * components.
 */

export type ProcessView = 'detailed' | 'overview'

export const VIEW_STORAGE_KEY = 'plm2.procmap.view'

/** The remembered view; Detailed whenever storage is missing or unreadable. */
export function readStoredView(): ProcessView {
  try {
    return window.localStorage.getItem(VIEW_STORAGE_KEY) === 'overview' ? 'overview' : 'detailed'
  } catch {
    return 'detailed'
  }
}

export function storeView(view: ProcessView) {
  try {
    window.localStorage.setItem(VIEW_STORAGE_KEY, view)
  } catch {
    // Private window or blocked storage: the choice lasts for this visit only.
  }
}

export interface Gate { text: string; hard?: boolean; soft?: boolean }

export interface OverviewStage {
  key: string
  name: string
  owner: string
  gates: Gate[]
  evidence: string[]
  /** data-testid of the matching node in the detailed flow. */
  target: string
}

export const OVERVIEW_STAGES: OverviewStage[] = [
  {
    key: 'intake', name: 'Intake', owner: 'Development', target: 'procmap-node-intake',
    gates: [{ text: 'every new customer index lands here' }],
    evidence: ['revision intake', 'pending index', 'route + reason'],
  },
  {
    key: 'capture', name: 'Capture', owner: 'Sales (PM may start)', target: 'procmap-node-captured',
    gates: [{ text: 'triage route: full ECR or attach' }],
    evidence: ['request + attachment', 'quote-by date', 'origin, cost carrier'],
  },
  {
    key: 'scoping', name: 'Scoping', owner: 'PM convenes', target: 'procmap-node-scoping',
    gates: [{ text: 'kickoff gate: description, attachment, quote deadline, change lead', soft: true }],
    evidence: ['meeting record with RASIC + cost carrier', 'decision + reason', 'concerns'],
  },
  {
    key: 'assessment', name: 'Assessment', owner: 'Routed departments', target: 'procmap-node-in_assessment',
    gates: [
      { text: 'impact set locked', hard: true },
      { text: 'proceed: R or A named, cost carrier set, no open concern' },
      { text: 'impacted items, lead, quote deadline', soft: true },
    ],
    evidence: ['department verdicts', 'impact checklist', 'risks (severity 1 to 3)', 'Change PPT'],
  },
  {
    key: 'costing', name: 'Costing', owner: 'Departments, PM runs', target: 'procmap-node-costing',
    gates: [{ text: 'all R/A submitted, none not feasible, no routing change pending', soft: true }],
    evidence: ['costing lines with rate snapshot', 'vendor quotes + favorite', 'P&L planned'],
  },
  {
    key: 'offer', name: 'Offer / Approval', owner: 'Sales; PM if internal', target: 'procmap-node-quoting',
    gates: [
      { text: 'cost carrier (set at scoping) picks the offer or internal approval' },
      { text: 'customer: Close costing, same checks again', soft: true },
    ],
    evidence: ['offer versions (PDF)', 'what changed per version', 'acceptance or internal approval'],
  },
  {
    key: 'timing', name: 'Timing', owner: 'PM, Scheduling, all teams', target: 'procmap-node-approved',
    gates: [
      { text: 'customer: accepted offer, PM + Quality sign-off (two people)', hard: true },
      { text: 'internal: PM approved costs + release deadline', hard: true },
      { text: 'Weissenburg / Solingen: impact locked, team informed, SOP date', hard: true },
    ],
    evidence: ['detailed plan', 'baseline + team confirmations', 'bank build decision, published plan (not gates)'],
  },
  {
    key: 'implementation', name: 'Implemen\u00ADtation', owner: 'Implementing departments', target: 'procmap-node-in_implementation',
    gates: [{ text: 'timing validated, impact confirmed, check workflows, D1 Technical release? = Yes', soft: true }],
    evidence: ['tracker + progress reports', 'deviations, locked or escalated', 'P&L actual'],
  },
  {
    key: 'validation', name: 'Validation', owner: 'Each department, PM', target: 'procmap-node-in_validation',
    gates: [{ text: 'every impacted item has its revision', soft: true }],
    evidence: ['checks: measured, cycle time, weight', 'validation issues'],
  },
  {
    key: 'release', name: 'Release', owner: 'PM', target: 'procmap-node-released',
    gates: [{ text: 'checks passed, revisions checked, checklist, lessons, no open validation issue or plan deviation', soft: true }],
    evidence: ['release checklist (16 items)', 'lessons learned', 'plan vs actual, P&L'],
  },
  {
    key: 'close', name: 'Close', owner: 'PM', target: 'procmap-node-closed',
    gates: [{ text: 'released' }],
    evidence: ['closure', 'linked index activated'],
  },
]

export interface Lane {
  key: string
  name: string
  joins: string
  steps: string[]
  note: string
  tone: string
  target: string
}

export const OVERVIEW_LANES: Lane[] = [
  {
    key: 'issues', name: 'Validation issues', joins: 'from Validation', tone: 'amber',
    target: 'procmap-node-issue-raise',
    steps: ['failed check: raise VI-n', 'containment', 'root cause', 'route (PM or lead, 4-eyes)'],
    note: 'Routes: internal rework, supplier rework, design change (back to Implementation with a recovery group), customer concession, follow-up change. Escalation L1 department, L2 project, L3 management + customer. Release waits while one is open.',
  },
  {
    key: 'mother-plant', name: 'Change from KTX Weissenburg / Solingen', joins: 'rejoins at Timing', tone: 'purple',
    target: 'procmap-mother-plant-lane',
    steps: ['PM captures: ref + SOP', 'scoping-lite: impact lock', 'inform the team: receipts', 'approved: release date = their SOP'],
    note: 'Started by Project Management only. Skips assessment, costing, offer and the quote deadline: from scoping straight to approved, then bank-build planning and implementation. Hard gate: impact locked, the team informed and the SOP date set. Timing confirmed by the informed departments and Scheduling.',
  },
  {
    key: 'revision', name: 'Revision intake', joins: 'from Intake', tone: 'teal',
    target: 'procmap-review-lane',
    steps: ['Development triage', 'engineering review: scoping-lite', 'serving departments answer', 'any impact?'],
    note: 'Triage routes: full ECR, attach to an open change, engineering review, administrative (reason required). Owner: Development. No impact: released, index activated. Impact (or a note without one): Development escalates to a full ECR at Scoping.',
  },
]

export const LANE_TONE: Record<string, { border: string; text: string }> = {
  amber: { border: 'border-amber-400/50', text: 'text-amber-300' },
  purple: { border: 'border-purple-400/50', text: 'text-purple-300' },
  teal: { border: 'border-teal-400/50', text: 'text-teal-300' },
}

/** 11 columns: the deadline bars span the stages they are active in. */
export const COLS = 'repeat(11, minmax(0, 1fr))'

/** Scoped styles: the jump highlight on screen and the one-page print sheet. */
export const PROCESS_MAP_CSS = `
[data-procmap-flash] > rect:first-child,
[data-procmap-flash] > polygon:first-child {
  stroke: #facc15 !important;
  stroke-width: 4 !important;
  animation: procmap-flash 0.7s ease-in-out 3;
}
@keyframes procmap-flash { 50% { stroke-opacity: 0.25; } }
@media (prefers-reduced-motion: reduce) {
  [data-procmap-flash] > rect:first-child,
  [data-procmap-flash] > polygon:first-child { animation: none; }
}
`

export const OVERVIEW_PRINT_CSS = `
@media print {
  @page { size: A4 landscape; margin: 8mm; }
  html, body { background: #fff !important; }
  /* Keep only the sheet: every branch that does not lead to it goes. */
  body *:not(:has(#procmap-overview)):not(#procmap-overview):not(#procmap-overview *) {
    display: none !important;
  }
  *:has(#procmap-overview) {
    display: block !important; position: static !important;
    height: auto !important; min-height: 0 !important; max-width: none !important;
    overflow: visible !important; margin: 0 !important; padding: 0 !important;
    background: #fff !important; border: 0 !important;
  }
  .procmap-noprint { display: none !important; }
  #procmap-overview {
    width: 100% !important; min-width: 0 !important; margin: 0 !important;
    padding: 0 !important; border: 0 !important; background: #fff !important;
    font-size: 9px !important;
  }
  #procmap-overview * {
    color: #000 !important; background: transparent !important;
    border-color: #000 !important; box-shadow: none !important;
  }
  #procmap-overview .ov-soft { border-color: #9ca3af !important; }
  #procmap-overview .ov-muted { color: #374151 !important; }
  #procmap-overview .ov-bar { background: #e5e7eb !important; }
  #procmap-overview .ov-hard { border-width: 1.5px !important; font-weight: 700 !important; }
  #procmap-overview a { text-decoration: none !important; }
  #procmap-overview section, #procmap-overview a { break-inside: avoid; }
}
`
