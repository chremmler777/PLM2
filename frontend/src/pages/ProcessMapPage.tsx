/**
 * The ECR process flow, drawn in full.
 *
 * Not the happy path — the mechanics: the decisions that fork the flow, the
 * gates that refuse to be bypassed, the loops that send work back, the artifacts
 * each stage owes, the tasks each role receives, and the two deadlines running
 * alongside it all. Sources of truth are docs/ECR_PROCESS_MAP.md (stages,
 * responsibles, build status) and docs/CHANGE_MANAGEMENT_FLOW.md (the enforced
 * mechanics). An auditor should be able to point at any rule in those documents
 * and find it here.
 *
 * The chart is hand-built SVG: no diagram library, no new dependency, and the
 * geometry stays something we can read and move. Layout discipline — the main
 * path runs down the middle, loops leave to the left, outcomes and carries to
 * the right, artifacts sit in their own far-right gutter, and long returns ride
 * dedicated lanes, so a reader can trace any single concern without crossing
 * another.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { t } from '../i18n/cmLabels'

type BuildState = 'built' | 'in_build' | 'partial' | 'to_build'

/** Border colour is the build status — the one thing the chart shows at a glance. */
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
    key: 'captured', name: 'Capture', badge: 'Sales', state: 'built',
    sub: 'Request, attachment, quote-by date', task: 'task: kickoff',
    responsible: 'Sales (can_start_change)',
    artifacts: 'kickoff gate (soft, deviation-overridable); quote deadline',
    what: 'The originator enters the request: project, description, documents, one-line reason, cost carrier, required-by date. No meetings here. A request may also be rejected straight from capture with a recorded reason — requiring the scoping hop would demand a full capture for a change that is already ending.',
  },
  {
    key: 'scoping', name: 'Scoping', badge: 'PM', state: 'built',
    sub: 'Meeting decides; impacted set locked',
    task: 'tasks: scoping_wrapup · impact_confirm',
    responsible: 'PM convenes; any member records the decision',
    artifacts: 'meeting decision + reason; concerns; impact lock (hard gate)',
    what: 'The team decides proceed, needs info, or reject. Open concerns block proceed; a negative decision resolves them and its reason becomes the rejection reason. A needs-info outcome raises a Sales-accountable task and a tracked question/answer cycle. The impacted set is built and Development-locked — the first PM action, and the one gate no deviation clears.',
  },
  {
    key: 'in_assessment', name: 'Assessment', badge: 'Team', state: 'built',
    sub: 'Verdict, risks, documents per department', task: 'task: assessment',
    responsible: 'Routed departments (Sales exempt)',
    artifacts: 'verdict; risk register; Change PPT / RFQ / customer mails',
    what: 'Each routed department answers the impact checklist and submits a verdict: feasible, feasible with conditions, or not feasible — the last hard-requires the Change PPT. Risks are a register, not a hold: typed, rated 1 to 3, and severity 3 travels to Sales for the offer. Routing deviations wait for approval; a recall sends the whole assessment back to scoping.',
  },
  {
    key: 'costing', name: 'Costing', badge: 'Team', state: 'in_build',
    sub: 'Positions, vendor offers, lead times', task: 'task: costing_input',
    responsible: 'Departments; PM and Sales see all',
    artifacts: 'tagged positions; vendor quotes + favorite vote; lead times; weight estimate (to build)',
    what: 'Each department states its internal effort (assessment time), its estimated implementation support, and external positions — an estimate or vendor quotes, one row per vendor with document, cost, shipping and lead time, and the department votes a favorite. A department whose assessment marked nothing impacted owes no costing input. The planned P&L starts here.',
  },
  {
    key: 'quoting', name: 'Quote Creation', badge: 'Sales', state: 'in_build',
    sub: 'Sales only; wrap-up per department', task: 'task: create_quote',
    responsible: 'Sales only',
    artifacts: 'per-department wrap-up; quoted price',
    what: 'Costing closes the inputs and Sales sees every department wrapped up — lines, lifecycle, positions with the favorite vendor, and the severity-3 risks carried over from assessment. Sales prices it. The implementation-timeline builder (parallel and serial sequencing) is a future tool.',
  },
  {
    key: 'quoted', name: 'Quote & Negotiation', badge: 'Sales', state: 'partial',
    sub: 'Submitted, negotiated to a final result', task: 'task: customer_response',
    responsible: 'Sales',
    artifacts: 'negotiation record; final price; go-ahead (acceptance built, loop to build)',
    what: 'The quote goes to the customer and negotiation runs until there is a final result. Three ways out: the customer declines and the change ends as rejected, a further round loops back, or the customer accepts — and acceptance cannot be recorded without the release deadline.',
  },
  {
    key: 'approved', name: 'Approved', badge: 'Customer', state: 'built',
    sub: 'Acceptance / internal approval; release date born',
    responsible: 'Sales records acceptance; PM approves internal costs',
    artifacts: 'customer acceptance or internal approval; release deadline (mandatory)',
    what: 'The go decision. The quote deadline freezes into a permanent on-time or late fact and the release deadline is born mandatorily — the API refuses the acceptance or the internal approval without it. From here the release date is the active one.',
  },
  {
    key: 'scheduling', name: 'Scheduling / Bank Build', badge: 'Team', state: 'to_build',
    sub: 'Bank-build plan; scrap decision; published',
    responsible: 'Scheduling (+ Sales publishes)',
    artifacts: 'bank-build plan; scrap decision + scrap quote; published plan',
    what: 'The real bank-build plan, which only exists once acceptance fixed the downtime start and the confirmed lead times. Running change or planned scrap is decided here — the customer bears the scrap cost, so scrapping requires an additional quote. Sales publishes the plan; samplings and blocked machines hang off this timeline, and it leads everything downstream.',
  },
  {
    key: 'in_implementation', name: 'Implementation', badge: 'Team', state: 'to_build',
    sub: 'Time booking; progress 2×/week; at-risk flags',
    responsible: 'Implementing departments + vendors',
    artifacts: 'progress reports; risk flags; escalation records',
    what: 'ECN revisions are spawned and the work is done, with per-department time tracking. A progress report at least twice a week carries an at-risk flag; a flagged report puts Sales on the hook to escalate, to the customer or internally. Samplings happen per the scheduling timeline.',
  },
  {
    key: 'in_validation', name: 'Validation', badge: 'Team', state: 'to_build',
    sub: 'Sampled, measured, weight + revision checked',
    responsible: 'Each department (its own checks)',
    artifacts: 'check completion; weight delta → quote update; revision bump; actuals P&L',
    what: 'Tool sampled, measured, cycle time taken. The weight is validated against the costing estimate and the delta returns to Sales as a quote update. Revision levels are increased per the customer statement and validated as correctly implemented. The second P&L — time actually spent and additional costs — closes the loop against the plan.',
  },
  {
    key: 'released', name: 'Released', badge: 'PM', state: 'built',
    sub: 'Implemented, then closed out', responsible: 'PM',
    artifacts: 'release; closure',
    what: 'All checks passed means implemented and released, then wrapped up as closed. Checks not passed means escalation with PM and Sales — replanned timing and, where warranted, renegotiated commercial terms — and the work returns to implementation.',
  },
]

const RULES = [
  'Scoped views everywhere: a department sees its own input only — at assessment AND costing. PM and Sales see all blocks.',
  'Tasks are mandatory — no accept or claim step; submitting names the owner.',
  'Sales owns the customer: mails tracked on the change; escalations to the customer go through Sales.',
  'Two deadlines, one active: quote-by until quoted (freezes the on-time fact), release-due born at acceptance and never cleared.',
  'P&L twice: planned at costing and quoting, actuals at validation — the delta is the learning.',
  'The scheduling timeline is the leader from stage 7 on: samplings, blocked machines, department work and escalation all hang off it.',
  'Every decision writes its own audit entry — rejection, reopen, concern raised or withdrawn, meeting decision, deadline pushback.',
]

const BUILD_ORDER = [
  'Finish in flight: costing positions + vendor quotes; the quoting stage.',
  'Weight estimate at costing — Tool Engineer states the part weight, carried to validation.',
  'Negotiation loop at quoted — entries (date, channel, result), final result, Sales go-ahead.',
  'Scheduling block — bank-build plan, running-change vs planned-scrap with scrap quote, published stamp.',
  'Implementation tracking — time booking, twice-weekly progress with at-risk flag, Sales escalation records.',
  'Validation checks — per-department checklist, weight validation with quote delta, revision bump, actuals P&L.',
  'Future tool: the Sales timeline builder — placeholder until then.',
]

// --- chart geometry -------------------------------------------------------
// Fixed gutters, left to right: the deadline rail, the loop lane, the loop
// column, the main path, the outcome column, two carry lanes, and the artifact
// gutter. Every element belongs to exactly one of them.
const RAIL = 16            // deadline rail
const LANE_L = 62          // long left-hand returns
const LX = 100, LW = 210   // left column (loops)
const CX0 = 380, CW = 300  // centre column (the main path)
const RX = 750, RW = 230   // right column (outcomes)
const LANE_R = 1000        // long right-hand returns
const LANE_R2 = 1022       // second carry lane, so two carries never share a line
const ART_X = 1050, ART_W = 250
const CHART_W = 1320

const NH = 66              // stage box
const DH = 84              // decision diamond
const GH = 46              // gate
const TH = 44              // terminal

const cx = CX0 + CW / 2
const lcx = LX + LW / 2
const rcx = RX + RW / 2

/** Every y on the spine, named — the rest of the chart hangs off these. */
const Y = {
  captured: 40, kickoff: 136, scoping: 212, meeting: 308, impactLock: 422,
  assessment: 498, verdict: 594, costing: 708, costGate: 804, quoting: 880,
  quoted: 976, fork: 1072, approved: 1186, scheduling: 1282, scrap: 1378,
  publish: 1492, implementation: 1588, atRisk: 1684, validation: 1798,
  checks: 1894, released: 2008, closed: 2104,
}
const CHART_H = Y.closed + TH + 30

const mid = (y: number, h: number) => y + h / 2

// --- primitives -----------------------------------------------------------

function Box({ x, y, w, h, name, sub, task, badge, stroke, dashed, testId }: {
  x: number; y: number; w: number; h: number
  name: string; sub?: string; task?: string; badge?: string
  stroke: string; dashed?: boolean; testId: string
}) {
  const badgeW = badge ? badge.length * 6.2 + 14 : 0
  return (
    <g data-testid={testId}>
      <rect x={x} y={y} width={w} height={h} rx={9} fill="#1e293b"
        stroke={stroke} strokeWidth={1.75}
        strokeDasharray={dashed ? '5 4' : undefined} />
      <text x={x + 12} y={y + (sub ? 23 : h / 2 + 5)} fill="#e2e8f0"
        fontSize={13.5} fontWeight={600}>{name}</text>
      {sub && <text x={x + 12} y={y + 40} fill="#94a3b8" fontSize={10}>{sub}</text>}
      {task && (
        <text x={x + 12} y={y + 56} fill="#64748b" fontSize={9}
          fontFamily="ui-monospace, monospace">{task}</text>
      )}
      {badge && (
        <>
          <rect x={x + w - badgeW - 10} y={y + 8} width={badgeW} height={17} rx={8}
            fill="#0f172a" stroke="#475569" strokeWidth={1} />
          <text x={x + w - badgeW / 2 - 10} y={y + 20} fill="#cbd5e1" fontSize={10}
            textAnchor="middle">{badge}</text>
        </>
      )}
    </g>
  )
}

/** A decision. Diamond, because an auditor looks for diamonds. */
function Decision({ y, name, lines, testId }: {
  y: number; name: string; lines?: string[]; testId: string
}) {
  const m = y + DH / 2
  return (
    <g data-testid={testId}>
      <polygon points={`${cx},${y} ${CX0 + CW},${m} ${cx},${y + DH} ${CX0},${m}`}
        fill="#172033" stroke="#a78bfa" strokeWidth={1.75} />
      <text x={cx} y={m - (lines?.length ? 6 : -4)} fill="#e9d5ff" fontSize={12.5}
        fontWeight={600} textAnchor="middle">{name}</text>
      {(lines ?? []).map((l, i) => (
        <text key={l} x={cx} y={m + 9 + i * 12} fill="#c4b5fd" fontSize={10}
          textAnchor="middle">{l}</text>
      ))}
    </g>
  )
}

/** A gate: clipped-corner shape, red when it cannot be bypassed at all. */
function Gate({ y, name, hard, testId }: {
  y: number; name: string; hard?: boolean; testId: string
}) {
  // Wider than the stage boxes and split on the em-dash: gate names carry
  // their condition, and one long line collides with the clipped corners.
  const x = CX0 - 14, w = CW + 28, n = 14
  const [title, ...rest] = name.split(' — ')
  const detail = rest.join(' — ')
  return (
    <g data-testid={testId}>
      <polygon
        points={`${x + n},${y} ${x + w - n},${y} ${x + w},${y + GH / 2} ${x + w - n},${y + GH} ${x + n},${y + GH} ${x},${y + GH / 2}`}
        fill="#131c2e" stroke={hard ? HARD : '#94a3b8'} strokeWidth={1.75} />
      <text x={x + w / 2} y={y + (detail ? 19 : GH / 2 + 4)}
        fill={hard ? '#fecaca' : '#cbd5e1'}
        fontSize={10.5} fontWeight={600} textAnchor="middle">{title}</text>
      {detail && (
        <text x={x + w / 2} y={y + 34} fill={hard ? '#fca5a5' : '#94a3b8'}
          fontSize={9.5} textAnchor="middle">{detail}</text>
      )}
    </g>
  )
}

/** A terminal state: stadium shape, the flow stops here. */
function Terminal({ x, y, w, name, sub, stroke, testId }: {
  x: number; y: number; w: number; name: string; sub?: string
  stroke: string; testId: string
}) {
  return (
    <g data-testid={testId}>
      <rect x={x} y={y} width={w} height={TH} rx={TH / 2} fill="#1e293b"
        stroke={stroke} strokeWidth={1.75} />
      <text x={x + w / 2} y={y + (sub ? 19 : 27)} fill="#e2e8f0" fontSize={12.5}
        fontWeight={600} textAnchor="middle">{name}</text>
      {sub && (
        <text x={x + w / 2} y={y + 33} fill="#94a3b8" fontSize={9.5}
          textAnchor="middle">{sub}</text>
      )}
    </g>
  )
}

function Edge({ d, testId, color = LINE, dashed, both, label, lx, ly }: {
  d: string; testId: string; color?: string; dashed?: boolean; both?: boolean
  label?: string; lx?: number; ly?: number
}) {
  const marker = color === LOOP ? 'url(#arrow-loop)'
    : color === CROSS ? 'url(#arrow-cross)' : 'url(#arrow)'
  const textFill = color === LOOP ? '#fbbf24' : color === CROSS ? '#67e8f9' : '#94a3b8'
  return (
    <g>
      <path data-testid={testId} d={d} fill="none" stroke={color} strokeWidth={1.5}
        strokeDasharray={dashed ? '5 4' : undefined}
        markerEnd={marker} markerStart={both ? marker : undefined} />
      {/* A dark halo keeps the label readable where it crosses lanes and
          outlines — in a chart this dense every label crosses something. */}
      {label && (
        <text x={lx} y={ly} fill={textFill} fontSize={10}
          stroke="#0b1220" strokeWidth={4} style={{ paintOrder: 'stroke' }}>
          {label}
        </text>
      )}
    </g>
  )
}

/** What a stage produces, in its own gutter so the path stays readable. */
function Artifacts({ y, lines, testId }: { y: number; lines: string[]; testId: string }) {
  const h = 16 + lines.length * 13
  return (
    <g data-testid={testId}>
      <path d={`M ${ART_X} ${y + h / 2} L ${ART_X - 22} ${y + h / 2}`} stroke="#334155"
        strokeWidth={1} strokeDasharray="3 3" fill="none" />
      <rect x={ART_X} y={y} width={ART_W} height={h} rx={7} fill="#0f172a"
        stroke="#334155" strokeWidth={1} />
      {lines.map((l, i) => (
        <text key={l} x={ART_X + 10} y={y + 17 + i * 13} fill="#94a3b8" fontSize={9.5}>
          {i === 0 ? `📄 ${l}` : l}
        </text>
      ))}
    </g>
  )
}

/** A phase outline, drawn behind everything so it groups without boxing in. */
function Phase({ y, h, label }: { y: number; h: number; label: string }) {
  return (
    <g>
      <rect x={CX0 - 30} y={y} width={CW + 60} height={h} rx={12}
        fill="#0b1220" stroke="#334155" strokeWidth={1} strokeDasharray="3 5" />
      <text x={CX0 - 22} y={y + 14} fill="#475569" fontSize={10}
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
        quote-by deadline active · capture → quoted (freezes on-time fact)
      </text>
      <rect data-testid="procmap-rail-release" x={RAIL} y={relTop} width={11}
        height={relBottom - relTop} rx={5} fill="#064e3b" stroke="#34d399"
        strokeWidth={1} />
      <text x={RAIL - 3} y={(relTop + relBottom) / 2} fill="#6ee7b7" fontSize={11}
        textAnchor="middle" transform={`rotate(-90 ${RAIL - 3} ${(relTop + relBottom) / 2})`}>
        release-due deadline active · acceptance → released
      </text>
    </g>
  )
}

// Scaled to the page width, the page itself scrolls — a nested two-axis
// scrollbox hid two thirds of the chart and clipped the artifact gutter
// mid-word. Expanded, the chart takes the whole window at natural size.
function Flowchart({ expanded, onToggle }: { expanded: boolean; onToggle: () => void }) {
  const spine = (from: number, fh: number, to: number, key: string, guard?: string) => (
    <Edge key={key} testId={`procmap-edge-${key}`}
      d={`M ${cx} ${from + fh} L ${cx} ${to}`}
      label={guard} lx={cx + 8} ly={from + fh + (to - from - fh) / 2 + 4} />
  )
  return (
    <div className={expanded
      ? 'fixed inset-0 z-[100] overflow-auto bg-slate-950 p-4'
      : 'relative overflow-x-auto rounded-lg border border-slate-700 bg-slate-900/60 p-2'}
      data-testid={expanded ? 'procmap-overlay' : 'procmap-frame'}>
      <button type="button" data-testid="procmap-expand"
        onClick={onToggle}
        className={`${expanded ? 'fixed top-3 right-5' : 'absolute top-3 right-3'} z-10 rounded border border-slate-600 bg-slate-800/90 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-700`}>
        {expanded ? '✕ Close' : '⛶ Full window'}
      </button>
      <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`}
        style={expanded
          ? { width: CHART_W, height: CHART_H, margin: '0 auto', display: 'block' }
          : { width: '100%', height: 'auto', minWidth: 1000 }}
        role="img" aria-label="ECR process flow" data-testid="procmap-chart">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill={LINE} />
          </marker>
          <marker id="arrow-loop" viewBox="0 0 10 10" refX="9" refY="5"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill={LOOP} />
          </marker>
          <marker id="arrow-cross" viewBox="0 0 10 10" refX="9" refY="5"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill={CROSS} />
          </marker>
        </defs>

        <Phase y={Y.captured - 20} h={(Y.kickoff + GH + 16) - (Y.captured - 20)} label="Capture" />
        <Phase y={Y.scoping - 20} h={(Y.impactLock + GH + 16) - (Y.scoping - 20)} label="Scoping" />
        <Phase y={Y.assessment - 20} h={(Y.verdict + DH + 16) - (Y.assessment - 20)} label="Assessment" />
        <Phase y={Y.costing - 20} h={(Y.costGate + GH + 16) - (Y.costing - 20)} label="Costing" />
        <Phase y={Y.quoting - 20} h={(Y.approved + NH + 16) - (Y.quoting - 20)} label="Quote & go-ahead" />
        <Phase y={Y.scheduling - 20} h={(Y.publish + NH + 16) - (Y.scheduling - 20)} label="Scheduling" />
        <Phase y={Y.implementation - 20} h={(Y.atRisk + DH + 16) - (Y.implementation - 20)} label="Implementation" />
        <Phase y={Y.validation - 20} h={(Y.checks + DH + 16) - (Y.validation - 20)} label="Validation" />
        <Phase y={Y.released - 20} h={(Y.closed + TH + 16) - (Y.released - 20)} label="Close-out" />

        <DeadlineRail />

        {/* --- the main path, each step carrying the condition it must meet --- */}
        {spine(Y.captured, NH, Y.kickoff, 'captured-kickoff')}
        {spine(Y.kickoff, GH, Y.scoping, 'kickoff-scoping', 'capture complete (soft, deviation-overridable)')}
        {spine(Y.scoping, NH, Y.meeting, 'scoping-meeting')}
        {spine(Y.meeting, DH, Y.impactLock, 'meeting-impactlock', 'proceed decision, no open concern')}
        {spine(Y.impactLock, GH, Y.assessment, 'impactlock-assessment', 'impact set locked (hard)')}
        {spine(Y.assessment, NH, Y.verdict, 'assessment-verdict')}
        {spine(Y.verdict, DH, Y.costing, 'verdict-costing', 'no open deviation')}
        {spine(Y.costing, NH, Y.costGate, 'costing-costgate')}
        {spine(Y.costGate, GH, Y.quoting, 'costgate-quoting', 'all 1st-stage R/A submitted')}
        {spine(Y.quoting, NH, Y.quoted, 'quoting-quoted', 'quoted price set')}
        {spine(Y.quoted, NH, Y.fork, 'quoted-fork')}
        {spine(Y.fork, DH, Y.approved, 'fork-approved', 'acceptance + release deadline born')}
        {spine(Y.approved, NH, Y.scheduling, 'approved-scheduling', 'release date active')}
        {spine(Y.scheduling, NH, Y.scrap, 'scheduling-scrap')}
        {spine(Y.scrap, DH, Y.publish, 'scrap-publish', 'plan agreed')}
        {spine(Y.publish, NH, Y.implementation, 'publish-implementation', 'plan published to the customer')}
        {spine(Y.implementation, NH, Y.atRisk, 'implementation-atrisk')}
        {spine(Y.atRisk, DH, Y.validation, 'atrisk-validation', 'on plan')}
        {spine(Y.validation, NH, Y.checks, 'validation-checks')}
        {spine(Y.checks, DH, Y.released, 'checks-released', 'all checks passed')}
        {spine(Y.released, NH, Y.closed, 'released-closed')}

        {/* --- capture: straight to rejected ---------------------------- */}
        <Edge testId="procmap-edge-captured-rejected" color={LOOP}
          d={`M ${CX0 + CW} ${mid(Y.captured, NH)} L ${rcx} ${mid(Y.captured, NH)} L ${rcx} ${Y.meeting + 20}`}
          label="reject at capture (reason recorded)" lx={CX0 + CW + 10} ly={mid(Y.captured, NH) - 8} />

        {/* --- scoping: the meeting decides ----------------------------- */}
        <Edge testId="procmap-edge-meeting-rejected" color={LOOP}
          d={`M ${CX0 + CW} ${mid(Y.meeting, DH)} L ${RX} ${mid(Y.meeting, DH)}`}
          label="reject" lx={CX0 + CW + 8} ly={mid(Y.meeting, DH) - 7} />
        <Terminal x={RX} y={Y.meeting + 20} w={RW} name="Rejected"
          sub="reason + rejection letter · task: send_rejection" stroke={LOOP}
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
        <Gate y={Y.kickoff} name="Kickoff gate — description, attachment, quote-by date"
          testId="procmap-gate-kickoff" />
        <Gate y={Y.impactLock} hard
          name="HARD GATE — impacted set Development-locked (no deviation clears it)"
          testId="procmap-gate-impact-lock" />

        {/* --- assessment: register, deviation, recall, not feasible ---- */}
        <Edge testId="procmap-edge-assessment-risks"
          d={`M ${CX0 + CW} ${mid(Y.assessment, NH)} L ${RX} ${mid(Y.assessment, NH)}`} />
        <Box x={RX} y={Y.assessment} w={RW} h={NH} stroke="#94a3b8" badge="Team"
          name="Risk register" sub="typed risks, severity 1–3"
          testId="procmap-node-risk-register" />
        <Edge testId="procmap-edge-risk-carry" color={CROSS} dashed
          d={`M ${RX + RW} ${mid(Y.assessment, NH)} L ${LANE_R} ${mid(Y.assessment, NH)} L ${LANE_R} ${mid(Y.quoting, NH) - 12} L ${CX0 + CW} ${mid(Y.quoting, NH) - 12}`}
          label="severity 3 → stated on the offer" lx={LANE_R - 180} ly={mid(Y.quoting, NH) - 18} />

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
        <Terminal x={RX} y={mid(Y.verdict, DH) - TH / 2} w={RW} name="Rejected — not feasible"
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
          label="favorite vendor → Sales' binding choice" lx={LANE_R2 - 232} ly={mid(Y.quoting, NH) + 26} />
        <Box x={LX} y={Y.costGate - 8} w={LW} h={62} stroke="#94a3b8" dashed
          name="Nothing impacted" sub="no costing task, owes nothing"
          testId="procmap-node-nothing-impacted" />
        <Edge testId="procmap-edge-nothing-impacted" dashed
          d={`M ${LX + LW} ${Y.costGate + 23} L ${CX0 + 16} ${Y.costGate + 23}`}
          label="skips" lx={LX + LW + 8} ly={Y.costGate + 16} />
        <Gate y={Y.costGate} name="Costing gate — every first-stage R/A submitted"
          testId="procmap-gate-costing" />

        {/* --- quote, negotiation, go-ahead ----------------------------- */}
        <Decision y={Y.fork} name="Customer decision"
          lines={['declined · further round · accepted']} testId="procmap-decision-customer" />
        <Edge testId="procmap-edge-fork-negotiation" color={LOOP}
          d={`M ${CX0} ${mid(Y.fork, DH)} L ${LX + LW} ${mid(Y.fork, DH)}`}
          label="further round" lx={LX + LW + 6} ly={mid(Y.fork, DH) - 7} />
        <Box x={LX} y={mid(Y.fork, DH) - 31} w={LW} h={62} stroke={LOOP} badge="Sales"
          name="Negotiation round" sub="date, channel, result → final result"
          testId="procmap-node-negotiation" />
        <Edge testId="procmap-loop-negotiation" color={LOOP} dashed
          d={`M ${lcx} ${mid(Y.fork, DH) - 31} L ${lcx} ${mid(Y.quoted, NH)} L ${CX0} ${mid(Y.quoted, NH)}`} />
        <Edge testId="procmap-edge-fork-declined" color={LOOP}
          d={`M ${CX0 + CW} ${mid(Y.fork, DH)} L ${RX} ${mid(Y.fork, DH)}`}
          label="declined" lx={CX0 + CW + 8} ly={mid(Y.fork, DH) - 7} />
        <Terminal x={RX} y={mid(Y.fork, DH) - TH / 2} w={RW} name="Rejected — declined"
          sub="customer informed, change closed" stroke={LOOP}
          testId="procmap-node-rejected-declined" />
        <Edge testId="procmap-edge-approved-deadline"
          d={`M ${CX0 + CW} ${mid(Y.approved, NH)} L ${RX} ${mid(Y.approved, NH)}`} />
        <Box x={RX} y={Y.approved} w={RW} h={NH} stroke="#34d399"
          name="Release deadline born" sub="mandatory; quote date freezes on-time fact"
          testId="procmap-node-release-deadline" />

        {/* --- scheduling: running change or planned scrap -------------- */}
        <Decision y={Y.scrap} name="Running change or planned scrap?"
          lines={['scrap → the customer bears the cost']} testId="procmap-decision-scrap" />
        <Edge testId="procmap-edge-scrap-quote" color={LOOP}
          d={`M ${CX0 + CW} ${mid(Y.scrap, DH)} L ${RX} ${mid(Y.scrap, DH)}`}
          label="planned scrap" lx={CX0 + CW + 8} ly={mid(Y.scrap, DH) - 7} />
        <Box x={RX} y={mid(Y.scrap, DH) - 31} w={RW} h={62} stroke={LOOP} badge="Sales"
          name="Additional scrap quote" sub="scrapped stock quoted to the customer"
          testId="procmap-node-scrap-quote" />
        <Edge testId="procmap-loop-scrap" color={LOOP} dashed
          d={`M ${rcx} ${mid(Y.scrap, DH) + 31} L ${rcx} ${mid(Y.publish, NH)} L ${CX0 + CW} ${mid(Y.publish, NH)}`} />
        <Box x={CX0} y={Y.publish} w={CW} h={NH} stroke={STROKE.to_build} badge="Sales"
          name="Publish the plan" sub="samplings + blocked machines ride this timeline"
          testId="procmap-node-publish-plan" />

        {/* --- implementation: reports and escalation ------------------- */}
        <Box x={LX} y={Y.implementation} w={LW} h={NH} stroke="#94a3b8" badge="Team"
          name="Progress report 2×/week" sub="carries the at-risk flag"
          testId="procmap-node-progress-report" />
        <Edge testId="procmap-edge-progress" dashed both
          d={`M ${LX + LW} ${mid(Y.implementation, NH)} L ${CX0} ${mid(Y.implementation, NH)}`} />
        <Decision y={Y.atRisk} name="At risk?" lines={['flagged → Sales escalates']}
          testId="procmap-decision-atrisk" />
        <Edge testId="procmap-edge-atrisk-escalation" color={LOOP}
          d={`M ${CX0 + CW} ${mid(Y.atRisk, DH)} L ${RX} ${mid(Y.atRisk, DH)}`}
          label="flagged" lx={CX0 + CW + 8} ly={mid(Y.atRisk, DH) - 7} />
        <Box x={RX} y={mid(Y.atRisk, DH) - 31} w={RW} h={62} stroke={LOOP} badge="Sales"
          name="Sales escalation" sub="to the customer or internally"
          testId="procmap-node-sales-escalation" />
        <Edge testId="procmap-loop-atrisk" color={LOOP} dashed
          d={`M ${rcx} ${mid(Y.atRisk, DH) - 31} L ${rcx} ${Y.implementation + 22} L ${CX0 + CW} ${Y.implementation + 22}`} />

        {/* --- validation: weight delta and the escalation loop --------- */}
        <Edge testId="procmap-edge-weight-update" color={CROSS}
          d={`M ${CX0 + CW} ${mid(Y.validation, NH)} L ${RX} ${mid(Y.validation, NH)}`}
          label="weight delta → Sales" lx={CX0 + CW + 8} ly={mid(Y.validation, NH) - 7} />
        <Box x={RX} y={Y.validation} w={RW} h={NH} stroke={CROSS} badge="Sales"
          name="Quote update" sub="validated weight → additional cost"
          testId="procmap-node-weight-update" />
        <Decision y={Y.checks} name="Checks passed?"
          lines={['sampled · measured · cycle time · revision']}
          testId="procmap-decision-checks" />
        <Edge testId="procmap-edge-checks-escalation" color={LOOP}
          d={`M ${CX0 + CW} ${mid(Y.checks, DH)} L ${RX} ${mid(Y.checks, DH)}`}
          label="not passed" lx={CX0 + CW + 8} ly={mid(Y.checks, DH) - 7} />
        <Box x={RX} y={mid(Y.checks, DH) - 31} w={RW} h={62} stroke={LOOP} badge="PM"
          name="Escalation — PM + Sales"
          sub="replan timing, renegotiate commercial terms"
          testId="procmap-node-escalation" />
        <Edge testId="procmap-loop-escalation" color={LOOP} dashed
          d={`M ${RX + RW} ${mid(Y.checks, DH)} L ${LANE_R} ${mid(Y.checks, DH)} L ${LANE_R} ${Y.implementation + 44} L ${CX0 + CW} ${Y.implementation + 44}`}
          label="rework" lx={LANE_R - 56} ly={Y.implementation + 38} />

        {/* --- the P&L pair: planned at costing, actual at validation --- */}
        <Edge testId="procmap-edge-pnl-compare" color={CROSS} dashed both
          d={`M ${CX0} ${Y.costing + 54} L ${LANE_L - 40} ${Y.costing + 54} L ${LANE_L - 40} ${Y.validation + 54} L ${CX0} ${Y.validation + 54}`}
          label="P&L planned ↔ actuals" lx={LANE_L - 34} ly={(Y.costing + Y.validation) / 2} />

        {/* --- terminal states ------------------------------------------ */}
        <Terminal x={CX0 + 60} y={Y.closed} w={CW - 120} name="Closed"
          stroke={STROKE.built} testId="procmap-node-closed" />
        <Edge testId="procmap-edge-cancelled" color={LOOP} dashed
          d={`M ${CX0 + CW} ${mid(Y.released, NH)} L ${RX} ${mid(Y.released, NH)}`}
          label="cancel (irreversible)" lx={CX0 + CW + 8} ly={mid(Y.released, NH) - 7} />
        <Terminal x={RX} y={mid(Y.released, NH) - TH / 2} w={RW} name="Cancelled"
          sub="terminal — from any active stage" stroke="#f87171"
          testId="procmap-node-cancelled" />

        {/* --- what each stage owes, in its own gutter ------------------ */}
        <Artifacts y={Y.captured} testId="procmap-artifacts-captured"
          lines={['request + description', 'at least one attachment', 'quote-by date (customer changes)']} />
        <Artifacts y={Y.scoping} testId="procmap-artifacts-scoping"
          lines={['meeting decision + reason', 'concern rows', 'customer letters / questions']} />
        <Artifacts y={Y.assessment} testId="procmap-artifacts-assessment"
          lines={['Change PPT (per department)', 'RFQ (external modification)', 'customer mails (change level)']} />
        <Artifacts y={Y.costing} testId="procmap-artifacts-costing"
          lines={['tagged cost positions', 'vendor quotes + ★ favorite vote', 'lead times · weight estimate']} />
        <Artifacts y={Y.quoting} testId="procmap-artifacts-quoting"
          lines={['per-department wrap-up', 'quoted price']} />
        <Artifacts y={Y.quoted} testId="procmap-artifacts-quoted"
          lines={['negotiation record', 'final price']} />
        <Artifacts y={Y.scheduling} testId="procmap-artifacts-scheduling"
          lines={['bank-build plan', 'scrap decision + scrap quote', 'plan published to the customer']} />
        <Artifacts y={Y.implementation} testId="procmap-artifacts-implementation"
          lines={['progress reports (2×/week)', 'at-risk flags', 'escalation records']} />
        <Artifacts y={Y.validation} testId="procmap-artifacts-validation"
          lines={['measurements + cycle time', 'weight delta → quote update', 'revision bump · actuals P&L']} />

        {/* --- the stages themselves, drawn last so they sit on top ----- */}
        {STAGES.filter((s) => s.key !== 'released').map((s) => (
          // Stage keys carry the status vocabulary ("in_assessment"); the
          // coordinate map speaks plain names ("assessment") — strip the prefix
          // or the box lands at NaN and stacks over Capture.
          <Box key={s.key} x={CX0}
            y={Y[s.key.replace(/^in_/, '') as keyof typeof Y]} w={CW} h={NH}
            name={s.name} sub={s.sub} task={s.task} badge={s.badge}
            stroke={STROKE[s.state]} testId={`procmap-node-${s.key}`} />
        ))}
        <Box x={CX0} y={Y.released} w={CW} h={NH} name="Released" sub="implemented"
          badge="PM" stroke={STROKE.built} testId="procmap-node-released" />

        <Decision y={Y.meeting} name="Scoping meeting"
          lines={['proceed · needs info · reject']} testId="procmap-decision-meeting" />
        <Decision y={Y.verdict} name="Verdicts in?"
          lines={['feasible · with conditions · not feasible']}
          testId="procmap-decision-verdict" />
      </svg>
    </div>
  )
}

export default function ProcessMapPage() {
  const [expanded, setExpanded] = useState(false)
  // Escape leaves the full-window chart, like any overlay.
  useEffect(() => {
    if (!expanded) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setExpanded(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])
  return (
    <div className="max-w-6xl mx-auto p-6 space-y-4">
      <div className="flex items-baseline justify-between gap-3">
        <h1 className="text-2xl font-semibold text-slate-100">{t('procmap.title')}</h1>
        <Link to="/changes" className="text-sm text-sky-400 hover:underline">
          {t('procmap.backToChanges')}
        </Link>
      </div>

      <Flowchart expanded={expanded} onToggle={() => setExpanded((v) => !v)} />

      <p data-testid="procmap-legend"
        className="text-xs text-slate-400 flex flex-wrap gap-x-4 gap-y-1">
        {(Object.keys(STATE_LABEL) as BuildState[]).map((s) => (
          <span key={s} className="inline-flex items-center gap-1.5">
            <span aria-hidden className="inline-block w-3 h-0 border-t-2 rounded"
              style={{ borderColor: STROKE[s] }} />
            <span className={STATE_TEXT[s]}>{STATE_LABEL[s]}</span>
          </span>
        ))}
        <span className="text-slate-500">Box = stage · diamond = decision · hexagon = gate (red = unbypassable) · stadium = terminal state.</span>
        <span className="text-amber-300/80">Amber = the flow leaving or re-entering the main path.</span>
        <span className="text-cyan-300/80">Cyan = information carried into a later stage.</span>
        <span className="text-slate-500">Badge = who owns it · mono line = the task raised · right gutter = what the stage produces · left rail = which deadline is active.</span>
      </p>

      <section data-testid="procmap-detail" className="space-y-2">
        <h2 className="text-sm font-semibold text-slate-200">Stage by stage</h2>
        {STAGES.map((s, i) => (
          <div key={s.key} data-testid={`procmap-detail-${s.key}`}
            className="rounded border border-slate-700 bg-slate-800/50 px-3 py-2">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="text-slate-500 text-xs tabular-nums">{i + 1}</span>
              <span className="text-slate-100 text-sm font-medium">{s.name}</span>
              <span className="rounded border border-slate-600 px-1.5 py-0 text-[10px] leading-tight text-slate-300">
                {s.badge}
              </span>
              <span className="text-xs text-slate-500">{s.responsible}</span>
              <span className={`ml-auto text-[11px] font-semibold ${STATE_TEXT[s.state]}`}>
                {STATE_LABEL[s.state]}
              </span>
            </div>
            <p className="text-xs text-slate-300 mt-1">{s.what}</p>
            <p className="text-[11px] text-slate-500 mt-0.5">
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
                <span className="text-slate-600 tabular-nums flex-shrink-0">{i + 1}.</span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        </section>
      </div>

      <p className="text-[11px] text-slate-600">
        Source of truth: <span className="font-mono">docs/ECR_PROCESS_MAP.md</span> (stages, status)
        and <span className="font-mono">docs/CHANGE_MANAGEMENT_FLOW.md</span> (enforced mechanics).
      </p>
    </div>
  )
}
