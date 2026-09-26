/**
 * The ECR process flow, drawn in full.
 *
 * Not the happy path, the mechanics: the decisions that fork the flow, the
 * gates that refuse to be bypassed, the loops that send work back, the artifacts
 * each stage owes, the tasks each role receives, the two deadlines running
 * alongside it all, the validation-issue branch with its escalation ladder, and
 * the mother-plant side track, and the intake of every new customer index with
 * its engineering-review lane. Sources of truth are docs/ECR_PROCESS_MAP.md
 * (stages, responsibles, build status), docs/CHANGE_MANAGEMENT_FLOW.md (the
 * enforced mechanics) and docs/superpowers/specs/2026-09-25-ecr-costing-to-close.md
 * (offer, timing, deviations, validation issues, P&L, mother plant). An auditor
 * should be able to point at any rule in those documents and find it here.
 *
 * The chart is hand-built SVG: no diagram library, no new dependency, and the
 * geometry stays something we can read and move. Layout discipline: the main
 * path runs down the middle, loops and alternatives leave to the left,
 * outcomes and the issue branch to the right, artifacts and P&L sit in their
 * own far-right gutter, long returns ride dedicated lanes, and the mother-plant
 * side track has its own swimlane at the bottom, so a reader can trace any
 * single concern without crossing another.
 */
import { createContext, useContext, useEffect, useState } from 'react'
import { t } from '../i18n/cmLabels'
import { useAuth } from '../contexts/AuthContext'
import { readStored, writeStored } from '../lib/safeStorage'
import ProcessOverview from '../components/processMap/ProcessOverview'
import {
  OVERVIEW_PRINT_CSS, PROCESS_MAP_CSS, readStoredView, storeView, type ProcessView,
} from '../components/processMap/overviewData'

type BuildState = 'built' | 'in_build' | 'partial' | 'to_build'

/** Border color is the build status: the one thing the chart shows at a glance. */
const STROKE: Record<BuildState, string> = {
  built: '#34d399', in_build: '#38bdf8', partial: '#fbbf24', to_build: '#64748b',
}

const STATE_LABEL: Record<BuildState, string> = {
  built: 'Built', in_build: 'In build', partial: 'Partial', to_build: 'To build',
}

const STATE_TEXT: Record<BuildState, string> = {
  built: 'text-emerald-300', in_build: 'text-sky-300',
  partial: 'text-amber-300', to_build: 'text-slate-400',
}

const LOOP = '#f59e0b'   // anything leaving or re-entering the main path
const LINE = '#64748b'   // the main path
const HARD = '#f87171'   // a gate that cannot be bypassed
const CROSS = '#22d3ee'  // information carried from one stage into another
const MP = '#c084fc'     // the mother-plant side track
const RV = '#2dd4bf'     // the engineering review of a new index (intake)

interface Stage {
  key: string
  name: string
  badge: 'Sales' | 'PM' | 'Team' | 'Customer'
  sub: string
  /** The task kinds this stage puts on somebody's list. */
  task?: string
  state: BuildState
  responsible: string
  artifacts: string
  what: string
}

const STAGES: Stage[] = [
  {
    key: 'intake', name: 'Intake', badge: 'Team', state: 'built',
    sub: 'New customer index, pending triage', task: 'task: triage index',
    responsible: 'Development decides the route (admin via acts-as)',
    artifacts: 'revision intake (source, batch, phase snapshot); pending index (not active); route + reason, audited',
    what: 'Every new customer index (customer package, customer data, upload, a proposal the customer adopted) is captured as an intake; the index stays pending and the active one is unchanged. Development picks the route alone: full ECR (a new change, lead item = the part), attach to an open change, engineering review (light track, lane R) or administrative (active now, reason required). Suggested: review data before series goes to the engineering review, official data or a series part to a full ECR, first data on an RFQ part to administrative. A newer index supersedes a pending one unless a live change already carries it.',
  },
  {
    key: 'captured', name: 'Capture', badge: 'Sales', state: 'built',
    sub: 'Request, attachment, quote-by date', task: 'task: kickoff',
    responsible: 'Sales (can_start_change); PM may start. A change from KTX Weissenburg / Solingen is started by Project Management only',
    artifacts: 'kickoff gate (soft, deviation-overridable); quote deadline; origin (customer, internal, change from KTX Weissenburg / Solingen)',
    what: 'The originator enters the request: project, description, documents, one-line reason, cost carrier, required-by date. No meetings here. A request may also be rejected straight from capture with a recorded reason. A change from KTX Weissenburg (the default) or, rarely, KTX Solingen is started by Project Management only, captured with its reference and SOP date, and runs in its own side track.',
  },
  {
    key: 'scoping', name: 'Scoping', badge: 'PM', state: 'built',
    sub: 'Meeting decides; impacted set locked',
    task: 'tasks: scoping_wrapup · impact_confirm',
    responsible: 'PM convenes; any member records the decision',
    artifacts: 'meeting decision + reason; concerns; impact lock (hard gate)',
    what: 'The team decides proceed, needs info, or reject. Open concerns block proceed; a negative decision resolves them and its reason becomes the rejection reason. A needs-info outcome raises a Sales-accountable task and a tracked question and answer cycle. The impacted set is built and Development-locked: the first PM action, and the one gate no deviation clears.',
  },
  {
    key: 'in_assessment', name: 'Assessment', badge: 'Team', state: 'built',
    sub: 'Verdict, risks, documents per department', task: 'task: assessment',
    responsible: 'Routed departments (Sales exempt)',
    artifacts: 'verdict; risk register; Change PPT / RFQ / customer mails',
    what: 'Each routed department answers the impact checklist and submits a verdict: feasible, feasible with conditions, or not feasible, the last hard-requiring the Change PPT. Risks are a register, not a hold: typed, rated 1 to 3, and severity 3 travels to Sales for the offer. Routing deviations wait for approval; a recall sends the whole assessment back to scoping.',
  },
  {
    key: 'costing', name: 'Costing', badge: 'Team', state: 'built',
    sub: 'Cost lines, lead times, vendor offers', task: 'task: costing_input',
    responsible: 'Departments; PM runs it; PM and Sales see all',
    artifacts: 'cost lines with lead time; vendor quotes + favorite vote; internal hours; weight estimate (compared with the weighed part at validation)',
    what: 'Each department states its internal hours and external positions, an estimate or vendor quotes with document, cost, shipping and lead time, and votes a favorite vendor. A department whose assessment marked nothing impacted owes no costing input. The planned P&L starts here. When costing closes, the cost carrier decides the branch: a customer change goes to the offer, an internal change to internal approval.',
  },
  {
    key: 'quoting', name: 'Offer', badge: 'Sales', state: 'built',
    sub: '1 plan · 2 price · 3 document', task: 'task: create_quote (build the offer)',
    responsible: 'Sales only (Offer tab)',
    artifacts: 'quote plan (rough Gantt); offer draft; offer PDF; sending v1 moves to quoted',
    what: 'Sales builds the offer in three steps. Plan: a rough timeline seeded from costing. Price: cost basis, optional factors, risk weights for the severity-3 risks, changeover (running change or customer pays scrap) and the piece-price effect. Document: detailed CBD or a rough description, free fields, terms, preview and PDF. Sending version 1 moves the change to quoted on its own.',
  },
  {
    key: 'quoted', name: 'Negotiation', badge: 'Sales', state: 'built',
    sub: 'Versions, what changed, 30-day validity',
    task: 'tasks: customer_response · offer_expiring',
    responsible: 'Sales',
    artifacts: 'offer versions with diff; negotiation rounds per version; acceptance (release deadline born)',
    what: 'Negotiation rounds are logged against an offer version; a new version records what changed. Each sent version is valid 30 days from customer receipt. Three ways out: the customer declines and the change ends as rejected, a further round loops back, or the customer accepts a sent, unexpired version (an expired one needs an override reason) with PM and Quality sign-off, and the release deadline is born.',
  },
  {
    key: 'approved', name: 'Approved: timing', badge: 'Team', state: 'built',
    sub: 'Detailed plan, team confirms, baseline',
    task: 'tasks: plan_feedback · timing_validate',
    responsible: 'Sales records acceptance / PM approves internal; then PM + Scheduling + all teams',
    artifacts: 'detailed plan + bank build / scrap plan; team confirmations; baseline; published plan; MS Project / CSV export',
    what: 'The go decision, then timing validation. The quote deadline freezes into a permanent on-time or late fact and the release deadline is born. The detailed plan is seeded from the quote plan, bank build and scrap are planned, and every responsible team confirms or raises a concern at the current plan revision (an edit makes confirmations stale). Timing validated sets the baseline on every block; Sales publishes the plan to the customer. Timing validated is a soft guard on the step into implementation.',
  },
  {
    key: 'in_implementation', name: 'Implementation', badge: 'Team', state: 'built',
    sub: 'Tracker: progress %, actual start / finish',
    task: 'tasks: progress report · plan_deviation',
    responsible: 'Implementing departments + vendors; PM / Sales / lead for dates',
    artifacts: 'tracker; progress reports; deviations locked or escalated; recovery groups from validation issues',
    what: 'Departments track progress and actual dates on their own blocks, report twice a week and book time. After the baseline, dates change only by PM, Sales, lead or admin, and every move is a deviation with a reason: locked when accepted internally, or escalated to the customer through Sales. Open deviations are information, not a gate. A validation issue on a fix route comes back here with a recovery group in the plan.',
  },
  {
    key: 'in_validation', name: 'Validation', badge: 'Team', state: 'partial',
    sub: 'Checks, release checklist, lessons', task: 'tasks: release_check · lessons_step',
    responsible: 'Each department (its own checks); PM',
    artifacts: 'check results; release checklist (13 items); lessons learned; validation issues (in build); weighed part vs estimate with the Sales re-quote task; revision flow (to build)',
    what: 'Tool sampled, measured, cycle time taken, each department on its own checks. A failed check becomes a validation issue: contained, root cause found, and routed by PM or lead to internal rework, supplier rework, design change, customer concession or a follow-up change, with an escalation level from department to management and customer. Release waits for the checklist, the lessons step and no open issue.',
  },
  {
    key: 'released', name: 'Released', badge: 'PM', state: 'built',
    sub: 'Summary, then closed', responsible: 'PM',
    artifacts: 'release; summary plan vs actual; P&L offer vs doing; closure',
    what: 'Released once the checklist is complete, the lessons step is done and no validation issue is open. The summary compares the plan with what happened and the offer with the actual P&L. The PM closes the change.',
  },
]

const RULES = [
  'Scoped views everywhere: a department sees its own input only, at assessment AND costing. PM and Sales see all blocks.',
  'Tasks are mandatory: no accept or claim step; submitting names the owner.',
  'Sales owns the customer: mails tracked on the change and filed into each validation issue; escalations to the customer go through Sales.',
  'Two deadlines, one active: quote-by until quoted (freezes the on-time fact); release-due born at acceptance, internal approval or from the SOP of KTX Weissenburg / Solingen, moved only with an audited reason.',
  'P&L offer vs doing: planned frozen at acceptance, actuals from implementation on (hours, cost entries, issue costs by bearer), compared at release.',
  'The detailed plan leads from approval on: after the baseline every date move is a deviation with a reason.',
  'Release is refused while a validation issue is open; each issue carries an escalation level: L1 department, L2 project, L3 management and customer.',
  'Every decision writes its own audit entry: rejection, reopen, concern, meeting decision, deadline, offer, deviation, issue route and escalation.',
]

const BUILD_ORDER = [
  'Validation issues: raise from a failed check, containment, root cause, route, customer decision, escalation ladder (in build).',
  'Recovery group in the Gantt for a fix route, with the new customer timing when it passes the release deadline (in build).',
  'P&L offer vs doing: actual cost entries, offer-vs-actual table, P&L page columns (in build).',
  'Side track for a change from KTX Weissenburg / Solingen: origin, inform-the-team receipts, scoping to approved with the SOP as release deadline (built).',
  'Weight estimate at costing compared at validation, delta back to Sales as a quote update (built).',
  'Revision intake: every new customer index triaged by Development, engineering review lane, release activates the linked index (built).',
  'Future tool: resource levelling beyond the Gantt planner.',
]

// --- chart geometry -------------------------------------------------------
// Fixed gutters, left to right: the deadline rail, the loop lanes, the left
// column (loops, alternatives, the escalation ladder), the main path, the right
// column (outcomes, the issue branch), two carry lanes, the artifact gutter
// (with the P&L touchpoints) and the P&L line. Every element belongs to
// exactly one of them.
const RAIL = 16            // deadline rail
const LANE_L = 62          // long left-hand returns
const LANE_INT = 80        // the internal-approval path down to Approved
const LX = 100, LW = 210   // left column
const CX0 = 380, CW = 300  // center column (the main path)
const RX = 750, RW = 230   // right column
const LANE_R = 1000        // long right-hand returns
const LANE_R2 = 1022       // second carry lane, so two carries never share a line
const ART_X = 1050, ART_W = 250
const PNL_X = 1314         // the P&L line beside the gutter
const CHART_W = 1344

const NH = 66              // stage box
const DH = 84              // decision diamond
const GH = 46              // gate
const TH = 44              // terminal

const cx = CX0 + CW / 2
const lcx = LX + LW / 2
const rcx = RX + RW / 2

/** The intake row above Capture: every new customer index starts here. */
const INTAKE_Y = 40
const INTAKE_SHIFT = 116

/** Every y on the spine, named: the rest of the chart hangs off these. */
const Y0 = {
  captured: 40, kickoff: 136, scoping: 212, meeting: 308, impactLock: 422,
  assessment: 498, verdict: 594, costing: 708, costGate: 804, carrier: 880,
  quoting: 994, quoted: 1090, fork: 1186, approved: 1300, confirm: 1396,
  timingGate: 1510, publish: 1586, implementation: 1682, dates: 1778,
  validation: 1892, checks: 1988, checklist: 2102, lessons: 2198,
  releaseGate: 2440, released: 2516, closed: 2612,
}
const Y = Object.fromEntries(
  Object.entries(Y0).map(([k, v]) => [k, v + INTAKE_SHIFT]),
) as typeof Y0

const mid = (y: number, h: number) => y + h / 2

/** The validation-issue branch, down the right column from the failed check. */
const IY = {
  raise: mid(Y.checks, DH) - 31, contain: mid(Y.checks, DH) + 51,
  cause: mid(Y.checks, DH) + 133, route: mid(Y.checks, DH) + 215,
  customer: mid(Y.checks, DH) + 329, accepted: mid(Y.checks, DH) + 411,
}
const IH = 62              // issue box

/** The mother-plant swimlane, below the main chart. */
const LANE_Y = Y.closed + TH + 44
const LANE_H = 176
/** The engineering-review swimlane (lane R), below lane M. */
const RLANE_Y = LANE_Y + LANE_H + 24
const RLANE_H = 190
const CHART_H = RLANE_Y + RLANE_H + 20

// --- primitives -----------------------------------------------------------

/** Whether the chart shows the raw task keys ("task: costing_input"). Admins turn it on. */
const TaskKeysContext = createContext(false)

/**
 * A line of raw task keys ("task: costing_input", "tasks: a_b · c_d") versus
 * a line a reader understands ("task: read and understood", "valid 30 days").
 */
const isTaskKey = (s: string) => /^tasks?:/.test(s) && /\b[a-z]+_[a-z_]+\b/.test(s)

function Box({ x, y, w, h, name, sub, task, badge, stroke, dashed, testId }: {
  x: number; y: number; w: number; h: number
  name: string; sub?: string; task?: string; badge?: string
  stroke: string; dashed?: boolean; testId: string
}) {
  const showKeys = useContext(TaskKeysContext)
  const badgeW = badge ? badge.length * 6.8 + 14 : 0
  // Task keys are for admins; everybody else gets the box without that line,
  // and the two remaining lines sit centered.
  const third = task && (!isTaskKey(task) || showKeys) ? task : undefined
  const nameY = third ? y + 23 : sub ? y + h / 2 - 3 : y + h / 2 + 5
  const subY = third ? y + 40 : y + h / 2 + 15
  return (
    <g data-testid={testId}>
      <rect x={x} y={y} width={w} height={h} rx={9} fill="#1e293b"
        stroke={stroke} strokeWidth={1.75}
        strokeDasharray={dashed ? '5 4' : undefined} />
      <text x={x + 12} y={nameY} fill="#e2e8f0"
        fontSize={13.5} fontWeight={600}>{name}</text>
      {sub && <text x={x + 12} y={subY} fill="#94a3b8" fontSize={11}>{sub}</text>}
      {third && (
        <text x={x + 12} y={y + 56} fill={isTaskKey(third) ? '#7c8ca3' : '#94a3b8'} fontSize={11}
          fontFamily={isTaskKey(third) ? 'Geist Mono, ui-monospace, monospace' : undefined}>{third}</text>
      )}
      {badge && (
        <>
          <rect x={x + w - badgeW - 10} y={y + 8} width={badgeW} height={18} rx={9}
            fill="#0f172a" stroke="#475569" strokeWidth={1} />
          <text x={x + w - badgeW / 2 - 10} y={y + 21} fill="#cbd5e1" fontSize={11}
            textAnchor="middle">{badge}</text>
        </>
      )}
    </g>
  )
}

/** A decision. Diamond, because an auditor looks for diamonds. */
function Decision({ y, name, lines, testId, x = CX0, w = CW }: {
  y: number; name: string; lines?: string[]; testId: string; x?: number; w?: number
}) {
  const m = y + DH / 2
  const c = x + w / 2
  return (
    <g data-testid={testId}>
      <polygon points={`${c},${y} ${x + w},${m} ${c},${y + DH} ${x},${m}`}
        fill="#172033" stroke="#a78bfa" strokeWidth={1.75} />
      <text x={c} y={m - (lines?.length ? 6 : -4)} fill="#e9d5ff" fontSize={12.5}
        fontWeight={600} textAnchor="middle">{name}</text>
      {(lines ?? []).map((l, i) => (
        <text key={l} x={c} y={m + 10 + i * 13} fill="#c4b5fd" fontSize={11}
          textAnchor="middle">{l}</text>
      ))}
    </g>
  )
}

/** A gate: clipped-corner shape, red when it cannot be bypassed at all. */
function Gate({ y, name, hard, testId, x = CX0 - 14, w = CW + 28 }: {
  y: number; name: string; hard?: boolean; testId: string; x?: number; w?: number
}) {
  // Wider than the stage boxes and split on ' | ': gate names carry their
  // condition, and one long line collides with the clipped corners.
  const n = 14
  const [title, ...rest] = name.split(' | ')
  const detail = rest.join(', ')
  return (
    <g data-testid={testId}>
      <polygon
        points={`${x + n},${y} ${x + w - n},${y} ${x + w},${y + GH / 2} ${x + w - n},${y + GH} ${x + n},${y + GH} ${x},${y + GH / 2}`}
        fill="#131c2e" stroke={hard ? HARD : '#94a3b8'} strokeWidth={1.75} />
      <text x={x + w / 2} y={y + (detail ? 19 : GH / 2 + 4)}
        fill={hard ? '#fecaca' : '#cbd5e1'}
        fontSize={11} fontWeight={600} textAnchor="middle">{title}</text>
      {detail && (
        <text x={x + w / 2} y={y + 34} fill={hard ? '#fca5a5' : '#94a3b8'}
          fontSize={11} textAnchor="middle">{detail}</text>
      )}
    </g>
  )
}

/** A terminal state: stadium shape, the flow stops here. */
function Terminal({ x, y, w, name, sub, task, stroke, testId, dashed }: {
  x: number; y: number; w: number; name: string; sub?: string
  /** A task key, shown only when task keys are on. */
  task?: string
  stroke: string; testId: string; dashed?: boolean
}) {
  const showKeys = useContext(TaskKeysContext)
  const key = task && showKeys ? task : undefined
  return (
    <g data-testid={testId}>
      <rect x={x} y={y} width={w} height={TH} rx={TH / 2} fill="#1e293b"
        stroke={stroke} strokeWidth={1.75} strokeDasharray={dashed ? '5 4' : undefined} />
      <text x={x + w / 2} y={y + (key ? 15 : sub ? 19 : 27)} fill="#e2e8f0" fontSize={12.5}
        fontWeight={600} textAnchor="middle">{name}</text>
      {sub && (
        <text x={x + w / 2} y={y + (key ? 28 : 33)} fill="#94a3b8" fontSize={11}
          textAnchor="middle">{sub}</text>
      )}
      {key && (
        <text x={x + w / 2} y={y + 39} fill="#7c8ca3" fontSize={11}
          fontFamily="Geist Mono, ui-monospace, monospace" textAnchor="middle">{key}</text>
      )}
    </g>
  )
}

const MARKER: Record<string, string> = {
  [LOOP]: 'url(#arrow-loop)', [CROSS]: 'url(#arrow-cross)', [MP]: 'url(#arrow-mp)',
  [HARD]: 'url(#arrow-hard)', [RV]: 'url(#arrow-rv)',
}
const LABEL_FILL: Record<string, string> = {
  [LOOP]: '#fbbf24', [CROSS]: '#67e8f9', [MP]: '#d8b4fe', [HARD]: '#fca5a5', [RV]: '#5eead4',
}

function Edge({ d, testId, color = LINE, dashed, both, label, lx, ly, rot, anchor }: {
  d: string; testId: string; color?: string; dashed?: boolean; both?: boolean
  label?: string; lx?: number; ly?: number
  /** Vertical label, reading bottom to top, centered on (lx, ly). */
  rot?: boolean
  anchor?: 'start' | 'middle' | 'end'
}) {
  const marker = MARKER[color] ?? 'url(#arrow)'
  const textFill = LABEL_FILL[color] ?? '#94a3b8'
  return (
    <g>
      <path data-testid={testId} d={d} fill="none" stroke={color} strokeWidth={1.5}
        strokeDasharray={dashed ? '5 4' : undefined}
        markerEnd={marker} markerStart={both ? marker : undefined} />
      {/* A dark halo keeps the label readable where it crosses lanes and
          outlines: in a chart this dense every label crosses something. */}
      {label && (
        <text x={lx} y={ly} fill={textFill} fontSize={11}
          textAnchor={rot ? 'middle' : anchor}
          transform={rot ? `rotate(-90 ${lx} ${ly})` : undefined}
          stroke="#0b1220" strokeWidth={4} style={{ paintOrder: 'stroke' }}>
          {label}
        </text>
      )}
    </g>
  )
}

const artH = (lines: string[], pnl?: string) => 16 + (lines.length + (pnl ? 1 : 0)) * 14
/** The y of an artifact box's P&L row, where the P&L line picks it up. */
const pnlY = (y: number, lines: string[]) => y + 13 + lines.length * 14

/** What a stage produces, in its own gutter so the path stays readable. The
 *  P&L row, when a stage touches the P&L, is cyan and ticks onto the P&L line. */
function Artifacts({ y, lines, pnl, testId }: {
  y: number; lines: string[]; pnl?: string; testId: string
}) {
  const h = artH(lines, pnl)
  return (
    <g data-testid={testId}>
      <path d={`M ${ART_X} ${y + h / 2} L ${ART_X - 22} ${y + h / 2}`} stroke="#334155"
        strokeWidth={1} strokeDasharray="3 3" fill="none" />
      <rect x={ART_X} y={y} width={ART_W} height={h} rx={7} fill="#0f172a"
        stroke="#334155" strokeWidth={1} />
      {/* A drawn page icon: an emoji here renders as a missing glyph on hosts
          without an emoji font. */}
      <path d={`M ${ART_X + 9} ${y + 8} h 5 l 3 3 v 8 h -8 z`} fill="none"
        stroke="#64748b" strokeWidth={1} />
      {lines.map((l, i) => (
        <text key={l} x={ART_X + (i === 0 ? 22 : 10)} y={y + 17 + i * 14} fill="#94a3b8"
          fontSize={11}>{l}</text>
      ))}
      {pnl && (
        <g data-testid={`${testId}-pnl`}>
          <text x={ART_X + 10} y={y + 17 + lines.length * 14} fill="#67e8f9"
            fontSize={11} fontWeight={600}>{pnl}</text>
          <path d={`M ${ART_X + ART_W} ${pnlY(y, lines)} L ${PNL_X} ${pnlY(y, lines)}`}
            stroke={CROSS} strokeWidth={1} fill="none" />
          <circle cx={PNL_X} cy={pnlY(y, lines)} r={2.5} fill={CROSS} />
        </g>
      )}
    </g>
  )
}

/** A phase outline, drawn behind everything so it groups without boxing in. */
function Phase({ y, h, label, x = CX0 - 30, w = CW + 60, color = '#475569' }: {
  y: number; h: number; label: string; x?: number; w?: number; color?: string
}) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={12}
        fill="#0b1220" stroke="#334155" strokeWidth={1} strokeDasharray="3 5" />
      <text x={x + 8} y={y + 14} fill={color} fontSize={11}
        letterSpacing={1.2}>{label.toUpperCase()}</text>
    </g>
  )
}

/** The two deadlines, as a rail beside the flow: one active at a time. */
function DeadlineRail() {
  const quoteTop = Y.captured, quoteBottom = Y.quoted + NH
  const relTop = Y.approved, relBottom = Y.released + NH
  return (
    <g data-testid="procmap-deadline-rail">
      <rect data-testid="procmap-rail-quote" x={RAIL} y={quoteTop} width={11}
        height={quoteBottom - quoteTop} rx={5} fill="#0c4a6e" stroke="#38bdf8"
        strokeWidth={1} />
      <text x={RAIL - 3} y={(quoteTop + quoteBottom) / 2} fill="#7dd3fc" fontSize={11}
        textAnchor="middle" transform={`rotate(-90 ${RAIL - 3} ${(quoteTop + quoteBottom) / 2})`}>
        quote-by deadline active · capture → quoted (freezes on-time fact) · customer changes only
      </text>
      <rect data-testid="procmap-rail-release" x={RAIL} y={relTop} width={11}
        height={relBottom - relTop} rx={5} fill="#064e3b" stroke="#34d399"
        strokeWidth={1} />
      <text x={RAIL - 3} y={(relTop + relBottom) / 2} fill="#6ee7b7" fontSize={11}
        textAnchor="middle" transform={`rotate(-90 ${RAIL - 3} ${(relTop + relBottom) / 2})`}>
        release-due deadline active · acceptance, internal approval or the SOP from KTX Weissenburg / Solingen → released · moved only by a recorded customer new timing
      </text>
    </g>
  )
}

/** One rung of the escalation ladder: a level, its triggers, who hears of it. */
function Rung({ y, level, title, lines, stroke, testId }: {
  y: number; level: string; title: string; lines: string[]; stroke: string; testId: string
}) {
  const h = RUNG_H(lines.length)
  return (
    <g data-testid={testId}>
      <rect x={LX} y={y} width={RUNG_W} height={h} rx={8} fill="#1e293b" stroke={stroke}
        strokeWidth={1.75} />
      <rect x={LX + 10} y={y + 8} width={26} height={17} rx={8} fill={stroke} />
      <text x={LX + 23} y={y + 20} fill="#0f172a" fontSize={11} fontWeight={700}
        textAnchor="middle">{level}</text>
      <text x={LX + 44} y={y + 21} fill="#e2e8f0" fontSize={12} fontWeight={600}>{title}</text>
      {lines.map((l, i) => (
        <text key={l} x={LX + 10} y={y + 40 + i * 13} fill="#94a3b8" fontSize={11}>{l}</text>
      ))}
    </g>
  )
}

const RUNG_H = (n: number) => 36 + n * 13
/** Wider than the left column: the trigger lines are the content here. */
const RUNG_W = 244
const rungX = LX + RUNG_W / 2
// One trigger per line, short enough for 11 px text in RUNG_W.
const L1_LINES = ['on raise: owner department and', 'PM informed']
const L2_LINES = [
  'auto: severity 3, a fix action overdue',
  'recovery slips past baseline finish',
  'no route decided after 2 working days',
  'PM, change lead, Sales; Sales decides',
  'whether the customer is told',
]
const L3_LINES = [
  'auto: the recovery ends after the',
  'release date, or L2 is not',
  'acknowledged in 2 working days',
  'customer wants a fix on a concession',
  'Sales tells the customer (mail filed)',
  'management notified; for KTX',
  'Weissenburg / Solingen the PM',
  'informs its contact instead',
]
const RUNG = { l1: IY.raise, l2: 0, l3: 0 }
RUNG.l2 = RUNG.l1 + RUNG_H(L1_LINES.length) + 24
RUNG.l3 = RUNG.l2 + RUNG_H(L2_LINES.length) + 24

function EscalationLadder() {
  return (
    <g data-testid="procmap-escalation-ladder">
      <text x={LX} y={RUNG.l1 - 8} fill="#fca5a5" fontSize={11} letterSpacing={1.2}>
        ESCALATION LADDER · PER OPEN ISSUE
      </text>
      <Rung y={RUNG.l1} level="L1" title="Department" lines={L1_LINES} stroke="#94a3b8"
        testId="procmap-escalation-l1" />
      <Edge testId="procmap-edge-l1-l2" color={LOOP}
        d={`M ${rungX} ${RUNG.l1 + RUNG_H(L1_LINES.length)} L ${rungX} ${RUNG.l2}`} />
      <Rung y={RUNG.l2} level="L2" title="Project" lines={L2_LINES} stroke={LOOP}
        testId="procmap-escalation-l2" />
      <Edge testId="procmap-edge-l2-l3" color={HARD}
        d={`M ${rungX} ${RUNG.l2 + RUNG_H(L2_LINES.length)} L ${rungX} ${RUNG.l3}`} />
      <Rung y={RUNG.l3} level="L3" title="Management + customer" lines={L3_LINES}
        stroke={HARD} testId="procmap-escalation-l3" />
      {['each level: audit row, notification and an', 'acknowledge task; manual escalation with a', 'reason; de-escalate only by closing or PM'].map((l, i) => (
        <text key={l} x={LX} y={RUNG.l3 + RUNG_H(L3_LINES.length) + 16 + i * 13}
          fill="#64748b" fontSize={11}>{l}</text>
      ))}
    </g>
  )
}

/** The mother-plant side track: no assessment, no costing, no offer. */
function MotherPlantLane() {
  const y = LANE_Y + 34
  const bw = 190, gw = 214, gap = 22
  const xs = [58, 58 + bw + gap, 58 + 2 * (bw + gap)]
  const gx = xs[2] + bw + gap
  const ax = gx + gw + gap
  const tx = ax + bw + gap
  const m = y + NH / 2
  const arrow = (x1: number, x2: number, key: string) => (
    <Edge key={key} testId={`procmap-edge-mp-${key}`} color={MP}
      d={`M ${x1} ${m} L ${x2} ${m}`} />
  )
  return (
    <g data-testid="procmap-mother-plant-lane">
      <rect x={40} y={LANE_Y} width={PNL_X - 40} height={LANE_H} rx={12}
        fill="#130f1f" stroke={MP} strokeWidth={1} strokeDasharray="6 5" />
      <text x={52} y={LANE_Y + 20} fill="#d8b4fe" fontSize={11} letterSpacing={1.2}
        fontWeight={600}>
        LANE M · SIDE TRACK: Change from KTX Weissenburg / Solingen
      </text>
      <text x={PNL_X - 14} y={LANE_Y + 20} fill={STROKE.built} fontSize={11}
        textAnchor="end" data-testid="procmap-mp-state">built</text>
      <Box x={xs[0]} y={y} w={bw} h={NH} stroke={MP} badge="PM"
        name="Capture" sub="KTX Weissenburg (WUG) default"
        task="or KTX Solingen · ref · SOP" testId="procmap-mp-capture" />
      {arrow(xs[0] + bw, xs[1], 'capture-scoping')}
      <Box x={xs[1]} y={y} w={bw} h={NH} stroke={MP} badge="PM"
        name="Scoping-lite" sub="impacted set, Development lock"
        task="task: impact_confirm" testId="procmap-mp-scoping" />
      {arrow(xs[1] + bw, xs[2], 'scoping-inform')}
      <Box x={xs[2]} y={y} w={bw} h={NH} stroke={MP} badge="Team"
        name="Inform the team" sub="one receipt per department"
        task="task: read and understood" testId="procmap-mp-inform" />
      {arrow(xs[2] + bw, gx, 'inform-gate')}
      <Gate x={gx} w={gw} y={m - GH / 2} hard
        name="Scoping → Approved | impact lock + inform list sent"
        testId="procmap-mp-gate" />
      {arrow(gx + gw, ax, 'gate-approved')}
      <Box x={ax} y={y} w={bw} h={NH} stroke={MP} badge="PM"
        name="Approved" sub="release date = their SOP"
        task="plan: their .xml or SOP" testId="procmap-mp-approved" />
      {arrow(ax + bw, tx, 'approved-main')}
      <Terminal x={tx} y={m - TH / 2} w={PNL_X - 16 - tx} name="Timing onward"
        sub="main path at Approved (M)" stroke={MP} dashed testId="procmap-mp-join" />
      {[
        'Started by Project Management only; other starters see who does it instead of the origin choice.',
        'Never: assessment, costing, offer, quote deadline. Open receipts show in Blocked by as information, not a gate.',
        'Timing as usual (team confirmation, baseline) with an "Inform KTX Weissenburg" (or Solingen) stamp instead of the customer publish. L3 escalation: the PM informs the contact there. P&L: actual local costs only.',
      ].map((l, i) => (
        <text key={l} x={58} y={y + NH + 26 + i * 14} fill="#c4b5fd" fontSize={11}>{l}</text>
      ))}
    </g>
  )
}

/** The engineering review of a new index: lock, answers, activate or escalate. */
function ReviewLane() {
  const y = RLANE_Y + 34
  const bw = 176, gap = 26
  const xs = [58, 58 + bw + gap, 58 + 2 * (bw + gap)]
  const dx = xs[2] + bw + gap, dw = 190
  const tx = dx + dw + gap
  const m = y + NH / 2
  const arrow = (x1: number, x2: number, key: string, label?: string) => (
    <Edge key={key} testId={`procmap-edge-rv-${key}`} color={RV}
      d={`M ${x1} ${m} L ${x2} ${m}`} label={label} lx={x1 + 6} ly={m - 7} />
  )
  return (
    <g data-testid="procmap-review-lane">
      <rect x={40} y={RLANE_Y} width={PNL_X - 40} height={RLANE_H} rx={12}
        fill="#0b1a1a" stroke={RV} strokeWidth={1} strokeDasharray="6 5" />
      <text x={52} y={RLANE_Y + 20} fill="#5eead4" fontSize={11} letterSpacing={1.2}
        fontWeight={600}>
        LANE R · ENGINEERING REVIEW OF A NEW INDEX (origin engineering_review)
      </text>
      <text x={PNL_X - 14} y={RLANE_Y + 20} fill={STROKE.built} fontSize={11}
        textAnchor="end" data-testid="procmap-rv-state">built</text>
      <Box x={xs[0]} y={y} w={bw} h={NH} stroke={RV} badge="Team"
        name="Triage" sub="Development picks the review"
        task="change starts at scoping" testId="procmap-rv-triage" />
      {arrow(xs[0] + bw, xs[1], 'triage-lock')}
      <Box x={xs[1]} y={y} w={bw} h={NH} stroke={RV} badge="Team"
        name="Scoping-lite" sub="Development locks the impact"
        task="task: impact_confirm" testId="procmap-rv-lock" />
      {arrow(xs[1] + bw, xs[2], 'lock-review')}
      <Box x={xs[2]} y={y} w={bw} h={NH} stroke={RV} badge="Team"
        name="Review" sub="serving departments answer"
        task="task: impact or no impact" testId="procmap-rv-review" />
      {arrow(xs[2] + bw, dx, 'review-decision')}
      <Decision x={dx} w={dw} y={m - DH / 2} name="Any impact?"
        lines={['all answered']} testId="procmap-rv-decision" />
      {arrow(dx + dw, tx, 'decision-released', 'no')}
      <Terminal x={tx} y={m - TH / 2} w={PNL_X - 16 - tx} name="Released and closed"
        sub="index activated, no costing, offer or timing" stroke={RV} testId="procmap-rv-released" />
      <Edge testId="procmap-edge-rv-escalate" color={RV}
        d={`M ${dx + dw / 2} ${m + DH / 2} L ${dx + dw / 2} ${m + DH / 2 + 22}`}
        label="yes: Development escalates to a full ECR (audited), main path at Scoping"
        lx={dx + dw / 2 + 8} ly={m + DH / 2 + 16} />
      {[
        'Asked: Development, Packaging Engineer for articles, and the owners of what serves the part (tools: Tool Engineer, stations and EOAT: Manufacturing Engineer, gauges: APQP).',
        'A full ECR or an attached change activates exactly its linked pending index at release; the checklist hints "index updated" and "drawing and 3D data released" from it.',
      ].map((l, i) => (
        <text key={l} x={58} y={y + NH + 46 + i * 14} fill="#99f6e4" fontSize={11}>{l}</text>
      ))}
    </g>
  )
}

// Scaled to the page width, the page itself scrolls: a nested two-axis
// scrollbox hid two thirds of the chart and clipped the artifact gutter
// mid-word. Expanded, the chart takes the whole window at natural size.
function Flowchart({ expanded, onToggle }: { expanded: boolean; onToggle: () => void }) {
  const spine = (from: number, fh: number, to: number, key: string, guard?: string) => (
    <Edge key={key} testId={`procmap-edge-${key}`}
      d={`M ${cx} ${from + fh} L ${cx} ${to}`}
      label={guard} lx={cx + 8} ly={from + fh + (to - from - fh) / 2 + 4} />
  )
  const routeMid = mid(IY.route, DH)
  const recoveryMid = mid(Y.implementation, NH)
  const pnlTop = pnlY(Y.costing, ART.costing)
  const pnlBottom = pnlY(Y.released, ART.released)
  return (
    <div className={expanded
      ? 'fixed inset-0 z-[100] overflow-auto bg-slate-950 p-4'
      : 'relative overflow-x-auto rounded-lg border border-slate-700 bg-slate-900/60 p-2'}
      data-testid={expanded ? 'procmap-overlay' : 'procmap-frame'}>
      <button type="button" data-testid="procmap-expand"
        onClick={onToggle}
        className={`${expanded ? 'fixed top-3 right-5' : 'absolute top-3 right-3'} z-10 rounded border border-slate-600 bg-slate-800/90 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-700`}>
        {expanded ? 'Close (Esc)' : 'Full window'}
      </button>
      <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`}
        style={expanded
          ? { width: CHART_W, height: CHART_H, margin: '0 auto', display: 'block' }
          : { width: '100%', height: 'auto', minWidth: 1000 }}
        role="img" aria-label="ECR process flow" data-testid="procmap-chart">
        <defs>
          {([['arrow', LINE], ['arrow-loop', LOOP], ['arrow-cross', CROSS],
            ['arrow-mp', MP], ['arrow-hard', HARD], ['arrow-rv', RV]] as const).map(([id, fill]) => (
            <marker key={id} id={id} viewBox="0 0 10 10" refX="9" refY="5"
              markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill={fill} />
            </marker>
          ))}
        </defs>

        <Phase y={INTAKE_Y - 20} h={NH + 36} label="Intake" color="#2dd4bf" />
        <Phase y={Y.captured - 20} h={(Y.kickoff + GH + 16) - (Y.captured - 20)} label="Capture" />
        <Phase y={Y.scoping - 20} h={(Y.impactLock + GH + 16) - (Y.scoping - 20)} label="Scoping" />
        <Phase y={Y.assessment - 20} h={(Y.verdict + DH + 16) - (Y.assessment - 20)} label="Assessment" />
        <Phase y={Y.costing - 20} h={(Y.carrier + DH + 16) - (Y.costing - 20)} label="Costing" />
        <Phase y={Y.quoting - 20} h={(Y.fork + DH + 16) - (Y.quoting - 20)} label="Offer & negotiation" />
        <Phase y={Y.approved - 20} h={(Y.publish + NH + 16) - (Y.approved - 20)} label="Approved: timing" />
        <Phase y={Y.implementation - 20} h={(Y.dates + DH + 16) - (Y.implementation - 20)} label="Implementation" />
        <Phase y={Y.validation - 20} h={(Y.releaseGate + GH + 16) - (Y.validation - 20)} label="Validation & release" />
        <Phase y={Y.released - 20} h={(Y.closed + TH + 16) - (Y.released - 20)} label="Close-out" />
        <Phase x={RX - 12} w={RW + 24} y={IY.raise - 26}
          h={(IY.accepted + TH + 12) - (IY.raise - 26)}
          label="Validation issue VI-n · in build" color="#7dd3fc" />

        <DeadlineRail />

        {/* --- intake: every new customer index, triaged by Development ---- */}
        <Box x={CX0} y={INTAKE_Y} w={CW} h={NH} stroke={STROKE.built} badge="Team"
          name="Intake: new customer index" sub="pending, active index unchanged"
          task="task: triage index (Development)" testId="procmap-node-intake" />
        <Edge testId="procmap-edge-intake-captured"
          d={`M ${cx} ${INTAKE_Y + NH} L ${cx} ${Y.captured}`}
          label="full ECR, or attach to an open change" lx={cx + 8} ly={INTAKE_Y + NH + 30} />
        <Edge testId="procmap-edge-intake-review" color={RV}
          d={`M ${CX0} ${mid(INTAKE_Y, NH)} L ${LX + LW} ${mid(INTAKE_Y, NH)}`}
          label="review" lx={LX + LW + 8} ly={mid(INTAKE_Y, NH) - 7} />
        <Box x={LX} y={INTAKE_Y} w={LW} h={NH} stroke={RV} dashed
          name="Engineering review" sub="continues in lane R, below"
          task="E levels before series" testId="procmap-node-intake-review" />
        <Edge testId="procmap-edge-intake-admin" color={RV}
          d={`M ${CX0 + CW} ${mid(INTAKE_Y, NH)} L ${RX + 20} ${mid(INTAKE_Y, NH)}`}
          label="administrative" lx={CX0 + CW + 8} ly={mid(INTAKE_Y, NH) - 7} />
        <Terminal x={RX + 20} y={mid(INTAKE_Y, NH) - TH / 2} w={RW - 20} name="Active now"
          sub="reason required, audited" stroke={RV} testId="procmap-node-intake-admin" />

        {/* --- the main path, each step carrying the condition it must meet --- */}
        {spine(Y.captured, NH, Y.kickoff, 'captured-kickoff')}
        {spine(Y.kickoff, GH, Y.scoping, 'kickoff-scoping', 'capture complete (soft, deviation-overridable)')}
        {spine(Y.scoping, NH, Y.meeting, 'scoping-meeting')}
        {spine(Y.meeting, DH, Y.impactLock, 'meeting-impactlock', 'proceed decision, no open concern')}
        {spine(Y.impactLock, GH, Y.assessment, 'impactlock-assessment', 'impact set locked (hard)')}
        {spine(Y.assessment, NH, Y.verdict, 'assessment-verdict')}
        {spine(Y.verdict, DH, Y.costing, 'verdict-costing', 'no open deviation')}
        {spine(Y.costing, NH, Y.costGate, 'costing-costgate')}
        {spine(Y.costGate, GH, Y.carrier, 'costgate-carrier', 'all 1st-stage R/A submitted')}
        {spine(Y.carrier, DH, Y.quoting, 'carrier-quoting', 'customer change')}
        {spine(Y.quoting, NH, Y.quoted, 'quoting-quoted', 'offer v1 sent (auto)')}
        {spine(Y.quoted, NH, Y.fork, 'quoted-fork')}
        {spine(Y.fork, DH, Y.approved, 'fork-approved', 'accepted: sent, unexpired version + PM and Quality sign-off')}
        {spine(Y.approved, NH, Y.confirm, 'approved-confirm')}
        {spine(Y.confirm, DH, Y.timingGate, 'confirm-timinggate', 'all teams confirmed at this revision')}
        {spine(Y.timingGate, GH, Y.publish, 'timinggate-publish', 'baseline set')}
        {spine(Y.publish, NH, Y.implementation, 'publish-implementation', 'timing validated (soft guard)')}
        {spine(Y.implementation, NH, Y.dates, 'implementation-dates')}
        {spine(Y.dates, DH, Y.validation, 'dates-validation', 'work done; open deviations inform, never gate')}
        {spine(Y.validation, NH, Y.checks, 'validation-checks')}
        {spine(Y.checks, DH, Y.checklist, 'checks-checklist', 'all checks passed')}
        {spine(Y.checklist, NH, Y.lessons, 'checklist-lessons', 'every item done, or n/a with a note')}
        {spine(Y.lessons, NH, Y.releaseGate, 'lessons-releasegate', 'lessons step done')}
        {spine(Y.releaseGate, GH, Y.released, 'releasegate-released', 'released (soft guard)')}
        {spine(Y.released, NH, Y.closed, 'released-closed', 'PM closes')}

        {/* --- capture: straight to rejected, or off to the mother plant -- */}
        <Edge testId="procmap-edge-captured-rejected" color={LOOP}
          d={`M ${CX0 + CW} ${mid(Y.captured, NH)} L ${rcx} ${mid(Y.captured, NH)} L ${rcx} ${Y.meeting + 20}`}
          label="reject at capture (reason recorded)" lx={CX0 + CW + 10} ly={mid(Y.captured, NH) - 8} />
        <Edge testId="procmap-edge-mp-origin" color={MP}
          d={`M ${CX0} ${mid(Y.captured, NH)} L ${LX + LW} ${mid(Y.captured, NH)}`}
          label="origin" lx={LX + LW + 8} ly={mid(Y.captured, NH) - 7} />
        <Box x={LX} y={Y.captured} w={LW} h={NH} stroke={MP} dashed
          name="KTX Weissenburg / Solingen" sub="PM starts it; lane M, below"
          task="skips assessment, costing, offer" testId="procmap-node-mp-origin" />

        {/* --- scoping: the meeting decides ----------------------------- */}
        <Edge testId="procmap-edge-meeting-rejected" color={LOOP}
          d={`M ${CX0 + CW} ${mid(Y.meeting, DH)} L ${RX} ${mid(Y.meeting, DH)}`}
          label="reject" lx={CX0 + CW + 8} ly={mid(Y.meeting, DH) - 7} />
        <Terminal x={RX} y={Y.meeting + 20} w={RW} name="Rejected"
          sub="reason + rejection letter" task="task: send_rejection" stroke={LOOP}
          testId="procmap-node-rejected" />

        {/* The needs-info loop: one tracked question, one owner, one answer. */}
        <Edge testId="procmap-edge-meeting-obtaininfo" color={LOOP}
          d={`M ${CX0} ${mid(Y.meeting, DH)} L ${LX + LW} ${mid(Y.meeting, DH)}`}
          label="needs info" lx={LX + LW + 6} ly={mid(Y.meeting, DH) - 7} />
        <Box x={LX} y={Y.meeting - 30} w={LW} h={62} stroke={LOOP} badge="Sales"
          name="Obtain information" sub="the question goes to the customer"
          task="task: obtain_info" testId="procmap-node-obtain-info" />
        <Edge testId="procmap-edge-obtaininfo-answer" color={LOOP}
          d={`M ${lcx} ${Y.meeting + 32} L ${lcx} ${Y.meeting + 40}`} />
        <Box x={LX} y={Y.meeting + 40} w={LW} h={62} stroke={LOOP} badge="Customer"
          name="Customer answers" sub="info_request → info_response"
          testId="procmap-node-customer-answer" />
        <Edge testId="procmap-edge-answer-close" color={LOOP}
          d={`M ${lcx} ${Y.meeting + 102} L ${lcx} ${Y.meeting + 110}`} />
        <Box x={LX} y={Y.meeting + 110} w={LW} h={62} stroke={LOOP} badge="Team"
          name="Close the question" sub="only the asker may withdraw it"
          task="task: close_question" testId="procmap-node-close-question" />
        <Edge testId="procmap-loop-needs-info" color={LOOP} dashed
          d={`M ${LX} ${Y.meeting + 141} L ${LANE_L} ${Y.meeting + 141} L ${LANE_L} ${mid(Y.scoping, NH)} L ${CX0} ${mid(Y.scoping, NH)}`}
          label="follow-up meeting" lx={LANE_L + 6} ly={mid(Y.scoping, NH) - 8} />

        {/* --- the two gates before assessment -------------------------- */}
        <Gate y={Y.kickoff} name="Kickoff gate | description, attachment, quote-by date"
          testId="procmap-gate-kickoff" />
        <Gate y={Y.impactLock} hard
          name="HARD GATE | impacted set Development-locked (no deviation clears it)"
          testId="procmap-gate-impact-lock" />

        {/* --- assessment: register, deviation, recall, not feasible ---- */}
        <Edge testId="procmap-edge-assessment-risks"
          d={`M ${CX0 + CW} ${mid(Y.assessment, NH)} L ${RX} ${mid(Y.assessment, NH)}`} />
        <Box x={RX} y={Y.assessment} w={RW} h={NH} stroke="#94a3b8" badge="Team"
          name="Risk register" sub="typed risks, severity 1 to 3"
          testId="procmap-node-risk-register" />
        <Edge testId="procmap-edge-risk-carry" color={CROSS} dashed
          d={`M ${RX + RW} ${mid(Y.assessment, NH)} L ${LANE_R} ${mid(Y.assessment, NH)} L ${LANE_R} ${mid(Y.quoting, NH) - 12} L ${CX0 + CW} ${mid(Y.quoting, NH) - 12}`}
          label="severity 3 → risk weights on the offer" lx={LANE_R - 8} ly={mid(Y.quoting, NH) - 18}
          anchor="end" />

        <Edge testId="procmap-edge-assessment-deviation" color={LOOP} both dashed
          d={`M ${LX + LW} ${mid(Y.assessment, NH)} L ${CX0} ${mid(Y.assessment, NH)}`} />
        <Box x={LX} y={Y.assessment} w={LW} h={NH} stroke={LOOP} badge="PM"
          name="Routing deviation" sub="pending approval blocks the stage"
          testId="procmap-node-deviation" />
        {/* Leaves through the bottom edge: the deviation box owns the same
            vertical band, and a straight left exit would cut through it. */}
        <Edge testId="procmap-loop-recall" color={LOOP} dashed
          d={`M ${CX0 + 24} ${Y.assessment + NH} L ${CX0 + 24} ${Y.assessment + NH + 14} L ${LANE_L - 24} ${Y.assessment + NH + 14} L ${LANE_L - 24} ${Y.scoping + 52} L ${CX0} ${Y.scoping + 52}`}
          label="recall to scoping (teardown)" lx={LANE_L - 18} ly={Y.scoping + 46} />

        <Edge testId="procmap-edge-verdict-notfeasible" color={LOOP}
          d={`M ${CX0 + CW} ${mid(Y.verdict, DH)} L ${RX} ${mid(Y.verdict, DH)}`}
          label="not feasible" lx={CX0 + CW + 8} ly={mid(Y.verdict, DH) - 7} />
        <Terminal x={RX} y={mid(Y.verdict, DH) - TH / 2} w={RW} name="Rejected: not feasible"
          sub="Change PPT required before the verdict" stroke={LOOP}
          testId="procmap-node-rejected-not-feasible" />

        {/* --- on hold: the parking state ------------------------------- */}
        <Box x={LX} y={Y.costing} w={LW} h={NH} stroke="#94a3b8" dashed
          name="On hold" sub="parking state, reversible"
          testId="procmap-node-on-hold" />
        <Edge testId="procmap-edge-onhold" color={LOOP} dashed both
          d={`M ${LX + LW} ${mid(Y.costing, NH)} L ${CX0} ${mid(Y.costing, NH)}`}
          label="from any active stage" lx={LX + 4} ly={Y.costing - 8} />

        {/* --- costing -------------------------------------------------- */}
        <Edge testId="procmap-edge-costing-positions"
          d={`M ${CX0 + CW} ${mid(Y.costing, NH)} L ${RX} ${mid(Y.costing, NH)}`} />
        <Box x={RX} y={Y.costing} w={RW} h={NH} stroke="#94a3b8" badge="Team"
          name="Positions + vendor offers" sub="★ favorite drives the figures"
          testId="procmap-node-cost-positions" />
        <Edge testId="procmap-edge-favorite-carry" color={CROSS} dashed
          d={`M ${RX + RW} ${mid(Y.costing, NH) + 12} L ${LANE_R2} ${mid(Y.costing, NH) + 12} L ${LANE_R2} ${mid(Y.quoting, NH) + 14} L ${CX0 + CW} ${mid(Y.quoting, NH) + 14}`}
          label="favorite vendor → Sales' binding choice" lx={LANE_R2 - 8} ly={mid(Y.quoting, NH) + 28}
          anchor="end" />
        <Box x={LX} y={Y.costGate - 8} w={LW} h={62} stroke="#94a3b8" dashed
          name="Nothing impacted" sub="no costing task, owes nothing"
          testId="procmap-node-nothing-impacted" />
        <Edge testId="procmap-edge-nothing-impacted" dashed
          d={`M ${LX + LW} ${Y.costGate + 23} L ${CX0 + 16} ${Y.costGate + 23}`}
          label="skips" lx={LX + LW + 8} ly={Y.costGate + 16} />
        <Gate y={Y.costGate} name="Costing gate | every first-stage R/A submitted"
          testId="procmap-gate-costing" />

        {/* --- the cost carrier forks: offer, or internal approval ------ */}
        <Decision y={Y.carrier} name="Cost carrier?"
          lines={['customer change · internal change']} testId="procmap-decision-carrier" />
        <Edge testId="procmap-edge-carrier-internal"
          d={`M ${CX0} ${mid(Y.carrier, DH)} L ${LX + LW} ${mid(Y.carrier, DH)}`}
          label="internal" lx={LX + LW + 8} ly={mid(Y.carrier, DH) - 7} />
        <Box x={LX} y={mid(Y.carrier, DH) - 31} w={LW} h={62} stroke={STROKE.built} badge="PM"
          name="Internal approval" sub="Offer tab reads Approval"
          task="quote plan kept · no offer" testId="procmap-node-internal-approval" />
        {/* Rides its own lane left of the column, past the negotiation loop,
            and enters Approved above the mother-plant join. */}
        <Edge testId="procmap-edge-internal-approved"
          d={`M ${LX} ${mid(Y.carrier, DH)} L ${LANE_INT} ${mid(Y.carrier, DH)} L ${LANE_INT} ${Y.approved + 14} L ${CX0} ${Y.approved + 14}`}
          label="approved + release deadline born" lx={LX + 6} ly={Y.approved + 8} />

        {/* --- offer, negotiation, go-ahead ----------------------------- */}
        <Decision y={Y.fork} name="Customer decision"
          lines={['declined · further round · accepted']} testId="procmap-decision-customer" />
        <Edge testId="procmap-edge-fork-negotiation" color={LOOP}
          d={`M ${CX0} ${mid(Y.fork, DH)} L ${LX + LW} ${mid(Y.fork, DH)}`}
          label="further round" lx={LX + LW + 6} ly={mid(Y.fork, DH) - 7} />
        <Box x={LX} y={mid(Y.fork, DH) - 31} w={LW} h={62} stroke={LOOP} badge="Sales"
          name="Negotiation round" sub="new version: what changed"
          task="valid 30 days from receipt" testId="procmap-node-negotiation" />
        <Edge testId="procmap-loop-negotiation" color={LOOP} dashed
          d={`M ${lcx} ${mid(Y.fork, DH) - 31} L ${lcx} ${mid(Y.quoted, NH)} L ${CX0} ${mid(Y.quoted, NH)}`} />
        <Edge testId="procmap-edge-fork-declined" color={LOOP}
          d={`M ${CX0 + CW} ${mid(Y.fork, DH)} L ${RX} ${mid(Y.fork, DH)}`}
          label="declined" lx={CX0 + CW + 8} ly={mid(Y.fork, DH) - 7} />
        <Terminal x={RX} y={mid(Y.fork, DH) - TH / 2} w={RW} name="Rejected: declined"
          sub="customer informed, change closed" stroke={LOOP}
          testId="procmap-node-rejected-declined" />

        {/* --- approved: timing validation ------------------------------ */}
        <Edge testId="procmap-edge-approved-deadline"
          d={`M ${CX0 + CW} ${mid(Y.approved, NH)} L ${RX} ${mid(Y.approved, NH)}`} />
        <Box x={RX} y={Y.approved} w={RW} h={NH} stroke="#34d399"
          name="Release deadline born" sub="mandatory; quote date freezes on-time fact"
          testId="procmap-node-release-deadline" />
        <Box x={LX} y={Y.approved + 30} w={LW} h={48} stroke={MP} dashed
          name="From lane M" sub="release date = their SOP"
          testId="procmap-node-mp-join" />
        <Edge testId="procmap-edge-mp-join" color={MP}
          d={`M ${LX + LW} ${Y.approved + 54} L ${CX0} ${Y.approved + 54}`} />
        <Decision y={Y.confirm} name="Every team confirmed?"
          lines={['at the current plan revision']} testId="procmap-decision-confirm" />
        <Edge testId="procmap-edge-confirm-concern" color={LOOP} dashed both
          d={`M ${CX0 + CW} ${mid(Y.confirm, DH)} L ${RX} ${mid(Y.confirm, DH)}`}
          label="concern" lx={CX0 + CW + 8} ly={mid(Y.confirm, DH) - 7} />
        <Box x={RX} y={mid(Y.confirm, DH) - 31} w={RW} h={62} stroke={LOOP} badge="Team"
          name="Concern raised" sub="plan revised, revision bumps"
          task="confirmations go stale" testId="procmap-node-plan-concern" />
        <Gate y={Y.timingGate}
          name="Timing validated | baseline set, all teams confirmed, no errors or idea blocks"
          testId="procmap-gate-timing" />
        <Box x={CX0} y={Y.publish} w={CW} h={NH} stroke={STROKE.built} badge="Sales"
          name="Publish the plan" sub="to the customer; MS Project / CSV export"
          task="KTX Weissenburg / Solingen: Inform stamp instead" testId="procmap-node-publish-plan" />

        {/* --- implementation: tracker, deviations, recovery ------------ */}
        <Box x={LX} y={Y.implementation} w={LW} h={NH} stroke="#94a3b8" badge="Team"
          name="Progress report" sub="2x per week; time booking"
          task="own blocks: progress, actuals" testId="procmap-node-progress-report" />
        <Edge testId="procmap-edge-progress" dashed both
          d={`M ${LX + LW} ${mid(Y.implementation, NH)} L ${CX0} ${mid(Y.implementation, NH)}`} />
        <Box x={RX} y={Y.implementation} w={RW} h={NH} stroke={LOOP} badge="PM"
          name="Recovery group" sub="fix blocks + Re-validation VI-n"
          task="FS into SOP, pushes the plan" testId="procmap-node-recovery" />
        <Edge testId="procmap-edge-recovery-implementation" color={LOOP}
          d={`M ${RX} ${recoveryMid} L ${CX0 + CW} ${recoveryMid}`} />
        <Edge testId="procmap-edge-recovery-deviation" color={CROSS} dashed
          d={`M ${rcx} ${Y.implementation + NH} L ${rcx} ${mid(Y.dates, DH) - 31}`}
          label="after baseline: deviations" lx={rcx - 8} ly={Y.implementation + NH + 24}
          anchor="end" />
        <Decision y={Y.dates} name="Dates held?"
          lines={['moved only by PM, Sales, lead']} testId="procmap-decision-dates" />
        <Edge testId="procmap-edge-dates-deviation" color={LOOP} both dashed
          d={`M ${CX0 + CW} ${mid(Y.dates, DH)} L ${RX} ${mid(Y.dates, DH)}`}
          label="moved" lx={CX0 + CW + 8} ly={mid(Y.dates, DH) - 7} />
        <Box x={RX} y={mid(Y.dates, DH) - 31} w={RW} h={62} stroke={LOOP} badge="PM"
          name="Deviation" sub="reason, slip, finish impact"
          task="lock · escalate via Sales" testId="procmap-node-plan-deviation" />

        {/* --- validation: weight delta, checks, the issue branch ------- */}
        <Edge testId="procmap-edge-weight-update" color={CROSS}
          d={`M ${CX0 + CW} ${mid(Y.validation, NH)} L ${RX} ${mid(Y.validation, NH)}`}
          label="weight delta" lx={CX0 + CW + 6} ly={mid(Y.validation, NH) - 7} />
        <Box x={RX} y={Y.validation} w={RW} h={NH} stroke={CROSS} badge="Sales"
          name="Quote update" sub="validated weight → additional cost"
          task="task: update_quote" testId="procmap-node-weight-update" />
        <Decision y={Y.checks} name="Checks passed?"
          lines={['sampled · measured · cycle time · revision']}
          testId="procmap-decision-checks" />
        <Edge testId="procmap-edge-checks-issue" color={LOOP}
          d={`M ${CX0 + CW} ${mid(Y.checks, DH)} L ${RX} ${mid(Y.checks, DH)}`}
          label="failed" lx={CX0 + CW + 8} ly={mid(Y.checks, DH) - 7} />
        <Box x={CX0} y={Y.checklist} w={CW} h={NH} stroke={STROKE.built} badge="Team"
          name="Release checklist" sub="13 items, each owned by a department"
          task="task: release_check" testId="procmap-node-release-checklist" />
        <Box x={CX0} y={Y.lessons} w={CW} h={NH} stroke={STROKE.built} badge="PM"
          name="Lessons learned" sub="at least one lesson, or a reason for none"
          task="task: lessons_step" testId="procmap-node-lessons" />
        <Gate y={Y.releaseGate}
          name="Release gate (soft) | checklist complete, lessons done, no open validation issue"
          testId="procmap-gate-release" />

        {/* The issue, step by step: raised, contained, cause, route. */}
        <Box x={RX} y={IY.raise} w={RW} h={IH} stroke={LOOP} badge="Team"
          name="Raise issue VI-n" sub="severity 1 to 3, owner, failed check"
          task="escalation L1 starts" testId="procmap-node-issue-raise" />
        <Edge testId="procmap-edge-issue-raise-contain" color={LOOP}
          d={`M ${rcx} ${IY.raise + IH} L ${rcx} ${IY.contain}`} />
        <Box x={RX} y={IY.contain} w={RW} h={IH} stroke={LOOP} badge="Team"
          name="Containment" sub="hold parts, protect bank, old state"
          task="before the route at severity 3" testId="procmap-node-issue-contain" />
        <Edge testId="procmap-edge-issue-contain-cause" color={LOOP}
          d={`M ${rcx} ${IY.contain + IH} L ${rcx} ${IY.cause}`} />
        <Box x={RX} y={IY.cause} w={RW} h={IH} stroke={LOOP} badge="Team"
          name="Root cause" sub="required before any route"
          task="concession may leave it open" testId="procmap-node-issue-cause" />
        <Edge testId="procmap-edge-issue-cause-route" color={LOOP}
          d={`M ${rcx} ${IY.cause + IH} L ${rcx} ${IY.route}`} />
        <Decision x={RX} w={RW} y={IY.route} name="Route decision"
          lines={['PM or lead · 4-eyes · reason']} testId="procmap-decision-route" />

        {/* Routes 1 to 3: back to implementation with a recovery group. */}
        <Edge testId="procmap-loop-recovery" color={LOOP} dashed
          d={`M ${RX + RW} ${routeMid} L ${LANE_R} ${routeMid} L ${LANE_R} ${recoveryMid} L ${RX + RW} ${recoveryMid}`}
          label="routes 1 to 3: internal rework · supplier rework · design change → back to implementation"
          lx={LANE_R + 12} ly={(routeMid + recoveryMid) / 2} rot />
        {/* Route 5: a follow-up change carries the work; the issue is transferred. */}
        <Edge testId="procmap-edge-route-followup" color={LOOP}
          d={`M ${RX + RW} ${routeMid} L ${ART_X + 120} ${routeMid} L ${ART_X + 120} ${IY.customer}`}
          label="route 5: follow-up change" lx={LANE_R + 26} ly={routeMid - 7} />
        <Box x={ART_X} y={IY.customer} w={240} h={IH} stroke={LOOP} badge="PM"
          name="Follow-up change" sub="new ECR at Capture, same project"
          task="issue transferred: not open" testId="procmap-node-issue-followup" />
        {/* Route 4: the customer accepts the deviation, on the record. */}
        <Edge testId="procmap-edge-route-concession" color={LOOP}
          d={`M ${rcx} ${IY.route + DH} L ${rcx} ${IY.customer}`}
          label="route 4: concession" lx={rcx - 8} ly={IY.route + DH + 19} anchor="end" />
        <Box x={RX} y={IY.customer} w={RW} h={IH} stroke={LOOP} badge="Sales"
          name="Customer decision" sub="accept needs the customer mail"
          task="require_fix · new_timing" testId="procmap-node-issue-customer" />
        <Edge testId="procmap-loop-require-fix" color={LOOP} dashed
          d={`M ${RX + RW} ${mid(IY.customer, IH)} L ${RX + RW + 10} ${mid(IY.customer, IH)} L ${RX + RW + 10} ${routeMid + 20} L ${rcx + RW / 2 * (1 - 20 / (DH / 2))} ${routeMid + 20}`}
          label="require fix: route reopens" lx={RX + RW + 16} ly={routeMid + 52} />
        <Edge testId="procmap-edge-issue-accepted" color={LOOP}
          d={`M ${rcx} ${IY.customer + IH} L ${rcx} ${IY.accepted}`}
          label="accept + mail filed" lx={rcx + 8} ly={IY.customer + IH + 14} />
        <Terminal x={RX} y={IY.accepted} w={RW} name="Issue accepted"
          sub="concession, end date optional" stroke={LOOP}
          testId="procmap-node-issue-accepted" />
        <Edge testId="procmap-edge-issue-settled" color={LOOP} dashed
          d={`M ${RX} ${mid(IY.accepted, TH)} L ${CX0 + CW + 14} ${mid(Y.releaseGate, GH)}`}
          label="settled" lx={CX0 + CW + 18} ly={mid(Y.releaseGate, GH) - 7} />

        <EscalationLadder />

        {/* --- terminal states ------------------------------------------ */}
        <Terminal x={CX0 + 60} y={Y.closed} w={CW - 120} name="Closed"
          stroke={STROKE.built} testId="procmap-node-closed" />
        <Edge testId="procmap-edge-cancelled" color={LOOP} dashed
          d={`M ${CX0 + CW} ${mid(Y.released, NH)} L ${RX} ${mid(Y.released, NH)}`}
          label="cancel" lx={CX0 + CW + 8} ly={mid(Y.released, NH) - 7} />
        <Terminal x={RX} y={mid(Y.released, NH) - TH / 2} w={RW} name="Canceled"
          sub="irreversible, from any active stage" stroke="#f87171"
          testId="procmap-node-cancelled" />

        {/* --- what each stage owes, in its own gutter ------------------ */}
        {ARTIFACTS.map((a) => (
          <Artifacts key={a.key} y={a.y} lines={a.lines} pnl={a.pnl}
            testId={`procmap-artifacts-${a.key}`} />
        ))}
        {/* The P&L line: planned frozen at acceptance, actuals from
            implementation on, compared at release. */}
        <Edge testId="procmap-edge-pnl-compare" color={CROSS} dashed
          d={`M ${PNL_X} ${pnlTop} L ${PNL_X} ${pnlBottom}`} />
        <text x={PNL_X + 14} y={(pnlTop + pnlBottom) / 2} fill="#67e8f9" fontSize={11}
          textAnchor="middle" transform={`rotate(-90 ${PNL_X + 14} ${(pnlTop + pnlBottom) / 2})`}>
          P&amp;L offer vs doing · planned at costing, frozen at acceptance · actual from implementation · compared at release
        </text>

        {/* --- the stages themselves, drawn last so they sit on top ----- */}
        {STAGES.filter((s) => s.key !== 'released' && s.key !== 'intake').map((s) => (
          // Stage keys carry the status vocabulary ("in_assessment"); the
          // coordinate map speaks plain names ("assessment"): strip the prefix
          // or the box lands at NaN and stacks over Capture.
          <Box key={s.key} x={CX0}
            y={Y[s.key.replace(/^in_/, '') as keyof typeof Y]} w={CW} h={NH}
            name={s.name} sub={s.sub} task={s.task} badge={s.badge}
            stroke={STROKE[s.state]} testId={`procmap-node-${s.key}`} />
        ))}
        <Box x={CX0} y={Y.released} w={CW} h={NH} name="Released"
          sub="summary: plan vs actual, P&L" badge="PM" stroke={STROKE.built}
          testId="procmap-node-released" />

        <Decision y={Y.meeting} name="Scoping meeting"
          lines={['proceed · needs info · reject']} testId="procmap-decision-meeting" />
        <Decision y={Y.verdict} name="Verdicts in?"
          lines={['feasible · with conditions · not feasible']}
          testId="procmap-decision-verdict" />

        <MotherPlantLane />
        <ReviewLane />
      </svg>
    </div>
  )
}

const ART = {
  costing: ['cost lines, lead time on every line', 'vendor quotes + ★ favorite vote', 'internal hours · weight estimate'],
  released: ['summary: plan vs actual', 'closure'],
}

const ARTIFACTS: { key: string; y: number; lines: string[]; pnl?: string }[] = [
  { key: 'captured', y: Y.captured, lines: ['request + description', 'at least one attachment', 'quote-by date (customer changes)'] },
  { key: 'scoping', y: Y.scoping, lines: ['meeting decision + reason', 'concern rows', 'customer letters / questions'] },
  { key: 'assessment', y: Y.assessment, lines: ['Change PPT (per department)', 'RFQ (external modification)', 'customer mails (change level)'] },
  { key: 'costing', y: Y.costing, lines: ART.costing, pnl: 'P&L planned starts here' },
  { key: 'quoting', y: Y.quoting, lines: ['quote plan (rough Gantt)', 'price: basis, factors, risk weights', 'changeover · piece-price effect', 'offer PDF (v1 sent = quoted)'] },
  { key: 'quoted', y: Y.quoted, lines: ['offer versions + what changed', 'valid 30 days from receipt', 'negotiation rounds per version', 'expired: override reason'] },
  { key: 'approved', y: Y.approved, lines: ['detailed plan + bank build / scrap', 'team confirmations per revision', 'baseline · published plan', 'MS Project XML / CSV'], pnl: 'P&L planned frozen at acceptance' },
  { key: 'implementation', y: Y.implementation, lines: ['tracker: progress %, actual dates', 'progress reports (2x per week)', 'deviations: locked / escalated'], pnl: 'P&L actual: hours x rate, cost entries' },
  { key: 'validation', y: Y.validation, lines: ['measurements + cycle time', 'weight delta → quote update', 'release checklist · lessons learned'], pnl: 'P&L actual + issue costs by bearer' },
  { key: 'issue', y: IY.raise, lines: ['VI-n: containment, cause, route', 'fix actions · evidence', 'customer mails filed on the issue', 'escalation rows L1 to L3'] },
  { key: 'released', y: Y.released, lines: ART.released, pnl: 'P&L offer vs doing: margin, slip' },
]

const KEYS_KEY = 'plm2.procmap.taskKeys'

/** The signed-in role, or null outside an AuthProvider (tests, previews). */
function useRole(): string | null {
  try {
    return useAuth().role ?? null
  } catch {
    return null
  }
}

export default function ProcessMapPage() {
  const isAdmin = useRole() === 'admin'
  const [keysOn, setKeysOn] = useState(() => readStored(KEYS_KEY) === 'on')
  const showKeys = isAdmin && keysOn
  const toggleKeys = () => {
    const next = !keysOn
    setKeysOn(next)
    writeStored(KEYS_KEY, next ? 'on' : 'off')
  }
  const [expanded, setExpanded] = useState(false)
  // Detailed is the default; the overview is remembered once chosen.
  const [view, setView] = useState<ProcessView>(readStoredView)
  // A box on the overview names a node in the detailed flow to show.
  const [jumpTo, setJumpTo] = useState<string | null>(null)
  const choose = (v: ProcessView) => { setView(v); storeView(v) }
  // Not remembered: the jump is a look at one node, the chosen view stays.
  const jump = (target: string) => { setView('detailed'); setJumpTo(target) }
  useEffect(() => {
    if (view !== 'detailed' || !jumpTo) return
    const el = document.querySelector(`[data-testid="${jumpTo}"]`)
    setJumpTo(null)
    if (!el) return
    el.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
    el.setAttribute('data-procmap-flash', '')
    const timer = window.setTimeout(() => el.removeAttribute('data-procmap-flash'), 2400)
    return () => window.clearTimeout(timer)
  }, [view, jumpTo])
  // Escape leaves the full-window chart, like any overlay.
  useEffect(() => {
    if (!expanded) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setExpanded(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])
  return (
    <div className={`${view === 'detailed' ? 'max-w-[88rem]' : 'max-w-6xl'} mx-auto p-6 space-y-4`}>
      <h1 className="text-2xl font-semibold text-slate-100">{t('procmap.title')}</h1>

      <style>{PROCESS_MAP_CSS}</style>
      <div className="procmap-noprint flex flex-wrap items-center justify-between gap-3">
        <div role="group" aria-label="View" data-testid="procmap-view-toggle"
          className="inline-flex rounded-md border border-slate-600 bg-slate-800 p-0.5 text-xs">
          {(['detailed', 'overview'] as const).map((v) => (
            <button key={v} type="button" aria-pressed={view === v}
              data-testid={`procmap-view-${v}`} onClick={() => choose(v)}
              className={`rounded px-3 py-1 ${view === v
                ? 'bg-slate-600 text-slate-50 font-medium'
                : 'text-slate-300 hover:bg-slate-700'}`}>
              {v === 'detailed' ? 'Detailed' : 'Overview'}
            </button>
          ))}
        </div>
        {view === 'overview' && (
          <button type="button" data-testid="procmap-print" onClick={() => window.print()}
            className="rounded-md border border-slate-600 bg-slate-800 px-3 py-1 text-xs text-slate-200 hover:bg-slate-700">
            Print overview
          </button>
        )}
        {view === 'detailed' && isAdmin && (
          <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-slate-300">
            <input type="checkbox" data-testid="procmap-task-keys" checked={keysOn} onChange={toggleKeys}
              className="h-3.5 w-3.5 rounded border-slate-600 accent-sky-500" />
            Show task keys
          </label>
        )}
      </div>

      {view === 'overview' ? (
        <>
          <style>{OVERVIEW_PRINT_CSS}</style>
          <ProcessOverview onJump={jump} />
        </>
      ) : (
      <>
      <TaskKeysContext.Provider value={showKeys}>
        <Flowchart expanded={expanded} onToggle={() => setExpanded((v) => !v)} />
      </TaskKeysContext.Provider>

      <p data-testid="procmap-legend"
        className="text-xs text-slate-400 flex flex-wrap gap-x-4 gap-y-1">
        {(Object.keys(STATE_LABEL) as BuildState[]).map((s) => (
          <span key={s} className="inline-flex items-center gap-1.5">
            <span aria-hidden className="inline-block w-3 h-0 border-t-2 rounded"
              style={{ borderColor: STROKE[s] }} />
            <span className={STATE_TEXT[s]}>{STATE_LABEL[s]}</span>
          </span>
        ))}
        <span className="text-slate-400">Box = stage · diamond = decision · hexagon = gate (red = unbypassable) · stadium = terminal state.</span>
        <span className="text-amber-300/80">Amber = the flow leaving or re-entering the main path, incl. the validation-issue branch.</span>
        <span className="text-cyan-300/80">Cyan = information carried into a later stage, and the P&amp;L line.</span>
        <span className="text-purple-300/80">Purple dashed = the side track for a change from KTX Weissenburg / Solingen (lane M).</span>
        <span className="text-teal-300/80">Teal = the intake of a new customer index and its engineering review (lane R).</span>
        <span className="text-slate-400">Badge = who owns it{showKeys ? ' · mono line = the task raised' : ''} · right gutter = what the stage produces · left rail = which deadline is active.</span>
      </p>

      <section data-testid="procmap-detail" className="space-y-2">
        <h2 className="text-sm font-semibold text-slate-200">Stage by stage</h2>
        {STAGES.map((s, i) => (
          <div key={s.key} data-testid={`procmap-detail-${s.key}`}
            className="rounded border border-slate-700 bg-slate-800/50 px-3 py-2">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="text-slate-500 text-xs tabular-nums">{i + 1}</span>
              <span className="text-slate-100 text-sm font-medium">{s.name}</span>
              <span className="rounded border border-slate-600 px-1.5 py-0 text-[11px] leading-tight text-slate-300">
                {s.badge}
              </span>
              <span className="text-xs text-slate-400">{s.responsible}</span>
              <span className={`ml-auto text-[11px] font-semibold ${STATE_TEXT[s.state]}`}>
                {STATE_LABEL[s.state]}
              </span>
            </div>
            <p className="text-xs text-slate-300 mt-1">{s.what}</p>
            <p className="text-[11px] text-slate-400 mt-0.5">
              <span className="uppercase tracking-wide">Artifacts / gates</span>: {s.artifacts}
            </p>
          </div>
        ))}
      </section>

      <div className="overflow-x-auto rounded-lg border border-slate-700">
        <table className="w-full text-xs" data-testid="procmap-table">
          <thead className="bg-slate-800 text-slate-400 text-left">
            <tr>
              <th className="px-3 py-2">#</th>
              <th className="px-3 py-2">Stage</th>
              <th className="px-3 py-2">Responsible</th>
              <th className="px-3 py-2">Artifacts / gates</th>
              <th className="px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {STAGES.map((s, i) => (
              <tr key={s.key} data-testid={`procmap-row-${s.key}`}
                className="border-t border-slate-800">
                <td className="px-3 py-2 text-slate-500 tabular-nums">{i + 1}</td>
                <td className="px-3 py-2 text-slate-200">{s.name}</td>
                <td className="px-3 py-2 text-slate-300" data-testid={`procmap-role-${s.key}`}>
                  {s.responsible}
                </td>
                <td className="px-3 py-2 text-slate-400">{s.artifacts}</td>
                <td className={`px-3 py-2 font-medium ${STATE_TEXT[s.state]}`}
                  data-testid={`procmap-status-${s.key}`}>
                  {STATE_LABEL[s.state]}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <section data-testid="procmap-rules">
          <h2 className="text-sm font-semibold text-slate-200 mb-1.5">Cross-cutting rules</h2>
          <ul className="space-y-1 text-xs text-slate-400">
            {RULES.map((rule) => (
              <li key={rule} className="flex gap-2">
                <span aria-hidden className="text-slate-600">•</span>
                <span>{rule}</span>
              </li>
            ))}
          </ul>
        </section>

        <section data-testid="procmap-build-order">
          <h2 className="text-sm font-semibold text-slate-200 mb-1.5">Build order</h2>
          <ol className="space-y-1 text-xs text-slate-400">
            {BUILD_ORDER.map((step, i) => (
              <li key={step} className="flex gap-2">
                <span className="text-slate-500 tabular-nums flex-shrink-0">{i + 1}.</span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        </section>
      </div>

      {showKeys && (
        <p data-testid="procmap-sources" className="text-[11px] text-slate-400">
          Source of truth: <span className="font-mono">docs/ECR_PROCESS_MAP.md</span> (stages, status),
          {' '}<span className="font-mono">docs/CHANGE_MANAGEMENT_FLOW.md</span> (enforced mechanics)
          and the ECR costing-to-close spec (<span className="font-mono">docs/superpowers/specs</span>).
        </p>
      )}
      </>
      )}
    </div>
  )
}
