/**
 * The ECR process flow, drawn.
 *
 * It renders docs/ECR_PROCESS_MAP.md as a flowchart: ten boxes down the main
 * path, the two places the flow leaves it (no deal → Rejected, checks not good →
 * Escalation and back into Implementation), and the build status of each stage
 * in the box's border. The table underneath carries the detail the boxes cannot
 * hold — who owns the stage and what it produces.
 *
 * The chart is hand-built SVG on purpose: no diagram library, no new dependency,
 * and the geometry stays something we can read and move.
 */
import { Link } from 'react-router-dom'
import { t } from '../i18n/cmLabels'

type BuildState = 'built' | 'in_build' | 'partial' | 'to_build'

/** Border colour is the build status — the one thing the chart must show at a glance. */
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

interface Stage {
  key: string
  name: string
  /** Who carries the stage, short enough to sit inside the box. */
  badge: 'Sales' | 'PM' | 'Team' | 'Customer'
  /** One line, no more — the table below carries the rest. */
  sub: string
  state: BuildState
  /** The full responsible, for the table. */
  responsible: string
  artifacts: string
  /** What actually happens in the stage — the description under the chart. */
  what: string
}

const STAGES: Stage[] = [
  {
    key: 'captured', name: 'Capture', badge: 'Sales', state: 'built',
    sub: 'Request, attachment, quote-by date',
    responsible: 'Sales', artifacts: 'kickoff gate',
    what: 'Request captured with description + attachment; quote-by deadline for customer changes.',
  },
  {
    key: 'scoping', name: 'Scoping', badge: 'PM', state: 'built',
    sub: 'Impacted set locked, meeting decides who assesses',
    responsible: 'PM (+ project team)', artifacts: 'impact lock (hard gate), proceed decision',
    what: 'Impacted set built and Development-locked; the scoping meeting decides who assesses.',
  },
  {
    key: 'in_assessment', name: 'Assessment', badge: 'Team', state: 'built',
    sub: 'Checklist, verdict, risks, documents',
    responsible: 'Routed departments (Sales exempt)',
    artifacts: 'risk register; severity-3 risks → offer; not-feasible gate',
    what: 'Each department: impact checklist, verdict (feasible / with conditions / not feasible + Change PPT), typed risks 1–3, documents (Change PPT / RFQ / customer mails).',
  },
  {
    key: 'costing', name: 'Costing', badge: 'Team', state: 'in_build',
    sub: 'Effort, support, external positions + vendor quotes',
    responsible: 'Departments; PM sees all',
    artifacts: 'tagged positions; vendor quote docs; weight quote (to build)',
    what: 'Cost positions: internal effort (assessment time), implementation support estimate, external positions — estimate or vendor quotes (upload, cost, lead time, shipping separate/included, favorite vote). Tooling Engineer also quotes part WEIGHT (a guess — validated later). P&L starts here. Nothing-impacted departments owe nothing.',
  },
  {
    key: 'quoting', name: 'Quote Creation', badge: 'Sales', state: 'in_build',
    sub: 'Per-department wrap-up; timeline builder is future',
    responsible: 'Sales only', artifacts: 'per-department wrap-up; quoted price',
    what: 'Sales sees all costs wrapped per department and builds the quote. The timeline builder (MS-Project-like, parallel/serial) is future — placeholder for now.',
  },
  {
    key: 'quoted', name: 'Quote & Negotiation', badge: 'Sales', state: 'partial',
    sub: 'Submitted, negotiated to a final result, go-ahead',
    responsible: 'Sales',
    artifacts: 'negotiation record; final price; go-ahead (acceptance built, loop to build)',
    what: 'Quote submitted to the customer; negotiation tracked to a final result; Sales decides go-ahead. No deal ends the change as rejected.',
  },
  {
    key: 'scheduling', name: 'Scheduling / Bank Build', badge: 'Team', state: 'to_build',
    sub: 'Bank-build plan, running change vs planned scrap, published',
    responsible: 'Scheduling (+ Sales publishes)',
    artifacts: 'bank-build plan; scrap decision + scrap quote; published plan',
    what: 'Real bank-build plan. Decision: running change vs planned scrap — the customer pays scrap, so scrapping means an additional cost quote. Sales publishes the plan to the customer. Samplings are planned on this timeline; blocked machines are part of it. The scheduling timeline leads everything downstream.',
  },
  {
    key: 'in_implementation', name: 'Implementation', badge: 'Team', state: 'to_build',
    sub: 'Time booking, progress 2×/week, at-risk flags',
    responsible: 'Implementing departments + vendors',
    artifacts: 'progress reports; risk flags; escalations',
    what: 'Simple time tracking per department. Progress report at least 2×/week with an at-risk flag; a flagged report means Sales escalates, to the customer or internally. Samplings happen per the scheduling timeline.',
  },
  {
    key: 'in_validation', name: 'Validation', badge: 'Team', state: 'to_build',
    sub: 'Sampled, measured, weight + revision checked, actuals P&L',
    responsible: 'Each department (its own checks)',
    artifacts: 'check completion; weight delta; revision bump; actuals P&L',
    what: 'Tool sampled, measured, cycle time taken; weight validated against the costing guess → Sales updates the quote (additional cost); revision levels increased per customer statement and validated as correctly implemented; second P&L: real time spent + extra costs. Checks not good → escalation with PM and Sales, back into implementation.',
  },
  {
    key: 'released', name: 'Released', badge: 'PM', state: 'built',
    sub: 'Implemented and closed out',
    responsible: 'PM', artifacts: 'release',
    what: 'Validation good → implemented and released.',
  },
]

const RULES = [
  'Scoped views everywhere: a department sees its own input only — at assessment AND costing. PM and Sales see all blocks.',
  'Tasks are mandatory — no accept/claim step; submitting names the owner.',
  'Sales owns the customer: mails tracked on the change; escalations to the customer go through Sales.',
  'P&L twice: planned at costing/quoting, actuals at validation — the delta is the learning.',
  'The scheduling timeline is the leader from stage 7 on: samplings, blocked machines, department work and escalation all hang off it.',
]

const BUILD_ORDER = [
  'Finish in flight: costing positions + vendor quotes; the quoting stage.',
  'Weight quote at costing — Tooling Engineer states part weight (estimate), carried to validation.',
  'Negotiation loop at quoted — entries (date, channel, result), final result, Sales go-ahead.',
  'Scheduling block — bank-build plan, running-change vs planned-scrap with scrap quote, published stamp.',
  'Implementation tracking — time booking, twice-weekly progress with at-risk flag, Sales escalation records.',
  'Validation checks — per-department checklist, weight validation with quote delta, revision bump, actuals P&L.',
  'Future tool: Sales timeline builder (MS-Project-like) — placeholder until then.',
]

// --- chart geometry -------------------------------------------------------
// One column down the middle, branches to the right. Everything below is
// derived from these five numbers, so the chart moves as one piece.
const W = 300          // main node width
const H = 58           // node height
const GAP = 34         // vertical space between nodes
const X = 40           // main column left edge
const BX = 400         // branch column left edge

const nodeY = (i: number) => 16 + i * (H + GAP)
const CX = X + W / 2
const CHART_H = nodeY(STAGES.length - 1) + H + 20

const BRANCH_W = 250
const REJECTED_Y = nodeY(5)
const ESCALATION_Y = nodeY(8)
const IMPL_CY = nodeY(7) + H / 2

function Node({
  x, y, w, name, sub, badge, state, testId,
}: {
  x: number; y: number; w: number
  name: string; sub?: string; badge?: string; state: BuildState; testId: string
}) {
  const badgeW = badge ? badge.length * 6.2 + 14 : 0
  return (
    <g data-testid={testId}>
      <rect x={x} y={y} width={w} height={H} rx={9}
        fill="#1e293b" stroke={STROKE[state]} strokeWidth={1.75} />
      <text x={x + 13} y={y + (sub ? 24 : 34)} fill="#e2e8f0"
        fontSize={14} fontWeight={600}>
        {name}
      </text>
      {sub && (
        <text x={x + 13} y={y + 42} fill="#94a3b8" fontSize={10.5}>{sub}</text>
      )}
      {badge && (
        <g>
          <rect x={x + w - badgeW - 10} y={y + 9} width={badgeW} height={17} rx={8}
            fill="#0f172a" stroke="#475569" strokeWidth={1} />
          <text x={x + w - badgeW / 2 - 10} y={y + 21} fill="#cbd5e1"
            fontSize={10} textAnchor="middle">
            {badge}
          </text>
        </g>
      )}
    </g>
  )
}

function Flowchart() {
  return (
    <div className="overflow-auto rounded-lg border border-slate-700 bg-slate-900/50 p-2">
      <svg viewBox={`0 0 700 ${CHART_H}`} width="100%"
        style={{ minWidth: 660, maxWidth: 900 }} height={CHART_H}
        role="img" aria-label="ECR process flow" data-testid="procmap-chart">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b" />
          </marker>
          <marker id="arrow-amber" viewBox="0 0 10 10" refX="9" refY="5"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#f59e0b" />
          </marker>
        </defs>

        {/* The main path: each stage flows into the next. */}
        {STAGES.slice(0, -1).map((s, i) => (
          <path key={`edge-${s.key}`}
            data-testid={`procmap-edge-${s.key}-${STAGES[i + 1].key}`}
            d={`M ${CX} ${nodeY(i) + H} L ${CX} ${nodeY(i + 1)}`}
            stroke="#64748b" strokeWidth={1.5} fill="none" markerEnd="url(#arrow)" />
        ))}

        {/* No deal: the change stops here. */}
        <path data-testid="procmap-edge-quoted-rejected"
          d={`M ${X + W} ${REJECTED_Y + H / 2} L ${BX} ${REJECTED_Y + H / 2}`}
          stroke="#f59e0b" strokeWidth={1.5} fill="none" markerEnd="url(#arrow-amber)" />
        <text x={X + W + 12} y={REJECTED_Y + H / 2 - 6} fill="#fbbf24" fontSize={10}>
          no deal
        </text>
        <Node x={BX} y={REJECTED_Y} w={BRANCH_W} name="Rejected" badge="Sales"
          sub="Customer told, change closed" state="built"
          testId="procmap-node-rejected" />

        {/* Checks not good: PM and Sales find new timing or more money, and the
            work goes back into implementation. */}
        <path data-testid="procmap-edge-validation-escalation"
          d={`M ${X + W} ${ESCALATION_Y + H / 2} L ${BX} ${ESCALATION_Y + H / 2}`}
          stroke="#f59e0b" strokeWidth={1.5} fill="none" markerEnd="url(#arrow-amber)" />
        <text x={X + W + 12} y={ESCALATION_Y + H / 2 - 6} fill="#fbbf24" fontSize={10}>
          not good
        </text>
        <Node x={BX} y={ESCALATION_Y} w={BRANCH_W} name="Escalation" badge="PM"
          sub="PM + Sales: new timing / more money" state="to_build"
          testId="procmap-node-escalation" />
        <path data-testid="procmap-loop-edge"
          d={`M ${BX + BRANCH_W / 2} ${ESCALATION_Y} L ${BX + BRANCH_W / 2} ${IMPL_CY} L ${X + W} ${IMPL_CY}`}
          stroke="#f59e0b" strokeWidth={1.5} strokeDasharray="5 4" fill="none"
          markerEnd="url(#arrow-amber)" />
        <text x={BX + 8} y={IMPL_CY - 8} fill="#fbbf24" fontSize={10}>
          rework
        </text>

        {STAGES.map((s, i) => (
          <Node key={s.key} x={X} y={nodeY(i)} w={W} name={s.name} sub={s.sub}
            badge={s.badge} state={s.state} testId={`procmap-node-${s.key}`} />
        ))}
      </svg>
    </div>
  )
}

export default function ProcessMapPage() {
  return (
    <div className="max-w-5xl mx-auto p-6 space-y-4">
      <div className="flex items-baseline justify-between gap-3">
        <h1 className="text-2xl font-semibold text-slate-100">{t('procmap.title')}</h1>
        <Link to="/changes" className="text-sm text-sky-400 hover:underline">
          {t('procmap.backToChanges')}
        </Link>
      </div>

      <Flowchart />

      {/* One line of legend — colour is status, the pill inside a box is who owns it. */}
      <p data-testid="procmap-legend" className="text-xs text-slate-400 flex flex-wrap gap-x-4 gap-y-1">
        {(Object.keys(STATE_LABEL) as BuildState[]).map((s) => (
          <span key={s} className="inline-flex items-center gap-1.5">
            <span aria-hidden className="inline-block w-3 h-0 border-t-2 rounded"
              style={{ borderColor: STROKE[s] }} />
            <span className={STATE_TEXT[s]}>{STATE_LABEL[s]}</span>
          </span>
        ))}
        <span className="text-slate-500">Badge inside a box = who owns the stage.</span>
        <span className="text-slate-500">Amber = the flow leaving the main path.</span>
      </p>

      {/* The diagram says where each stage sits; this says what happens in it.
          Both, because the chart cannot hold a paragraph and the paragraph
          cannot show a loop. */}
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
                <td className="px-3 py-2 text-slate-300"
                  data-testid={`procmap-role-${s.key}`}>
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
        Source of truth: <span className="font-mono">docs/ECR_PROCESS_MAP.md</span>
      </p>
    </div>
  )
}
