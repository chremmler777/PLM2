/**
 * The ECR process map, in the app rather than in a document.
 *
 * It renders docs/ECR_PROCESS_MAP.md — the governing map from the process
 * walkthrough: ten stages with who owns each, what it produces, and how much of
 * it is actually built. The team reviews it in German, so the stage titles and
 * responsibles are German with the technical status key alongside; the notes
 * stay in the language the map was written in.
 *
 * Nothing here is fetched: the map is a statement of intent, and it changes when
 * the document changes, not when data does.
 */
import { Link } from 'react-router-dom'
import { t } from '../i18n/cmLabels'

type BuildState = 'built' | 'in_build' | 'partial' | 'to_build'

const STATE_STYLE: Record<BuildState, string> = {
  built: 'bg-emerald-900/70 text-emerald-200',
  in_build: 'bg-sky-900/70 text-sky-200',
  // The doc calls stage 6 PARTIAL — half of it is live, half is not, and
  // flattening that into either chip would misreport it.
  partial: 'bg-amber-900/70 text-amber-200',
  to_build: 'bg-slate-700 text-slate-300',
}

const STATE_LABEL: Record<BuildState, string> = {
  built: 'BUILT', in_build: 'IN BUILD', partial: 'PARTIAL', to_build: 'TO BUILD',
}

interface Stage {
  n: number
  /** The status key the engine uses, or the working name of a stage without one. */
  key: string
  state: BuildState
  /** What happens, straight from the map. */
  what: string
  artifacts: string
  /** The build caveat the map spells out, when there is one. */
  note?: string
  /** Where the flow can leave the straight line after this stage. */
  branch?: string
}

const STAGES: Stage[] = [
  {
    n: 1, key: 'captured', state: 'built',
    what: 'Request captured with description + attachment; quote-by deadline for customer changes.',
    artifacts: 'kickoff gate',
  },
  {
    n: 2, key: 'scoping', state: 'built',
    what: 'Impacted set built and Development-locked; scoping meeting decides who assesses.',
    artifacts: 'impact lock (hard gate), proceed decision',
  },
  {
    n: 3, key: 'in_assessment', state: 'built',
    what: 'Each department: impact checklist, verdict (feasible / with conditions / not feasible + Change PPT), '
      + 'typed risks 1–3, documents (Change PPT / RFQ / customer mails).',
    artifacts: 'risk register; severity-3 risks → offer; not-feasible gate',
    note: 'Reworked 2026-08-11/12.',
  },
  {
    n: 4, key: 'costing', state: 'in_build',
    what: 'Cost positions: internal effort (assessment time), implementation support estimate, external positions — '
      + 'estimate or vendor quotes (upload, cost, lead time, shipping separate/included, favorite vote). '
      + 'Tooling Engineer also quotes part WEIGHT (a guess — validated later). P&L starts here. '
      + 'Nothing-impacted departments owe nothing.',
    artifacts: 'tagged positions; vendor quote docs',
    note: 'Positions/vendors in build; weight quote still TO BUILD.',
  },
  {
    n: 5, key: 'quoting', state: 'in_build',
    what: 'Sales sees all costs wrapped per department and builds the quote. '
      + 'The timeline builder (MS-Project-like, parallel/serial) is FUTURE — placeholder for now.',
    artifacts: 'per-department wrap-up; quoted price',
  },
  {
    n: 6, key: 'quoted', state: 'partial',
    what: 'Quote submitted to the customer; negotiation tracked to a final result; Sales decides go-ahead.',
    artifacts: 'negotiation record; final price; go-ahead decision (acceptance carries the release deadline)',
    note: 'Acceptance built; negotiation loop TO BUILD.',
    branch: 'no deal → rejected',
  },
  {
    n: 7, key: 'scheduling', state: 'to_build',
    what: 'Real bank-build plan. Decision: running change vs planned scrap — the customer pays scrap, so scrapping '
      + 'means an additional cost quote. Sales publishes the plan to the customer. Samplings are planned on this '
      + 'timeline; blocked machines are part of it. The scheduling timeline leads everything downstream.',
    artifacts: 'bank-build plan; scrap decision + scrap quote; published plan',
    note: 'Bank-build basis exists.',
  },
  {
    n: 8, key: 'in_implementation', state: 'to_build',
    what: 'Simple time tracking per department. Progress report at least 2×/week with an at-risk flag; a flagged '
      + 'report means Sales escalates, to the customer or internally. Samplings happen per the scheduling timeline.',
    artifacts: 'progress reports; risk flags; escalations',
    note: 'Skeleton exists.',
  },
  {
    n: 9, key: 'in_validation', state: 'to_build',
    what: 'Tool sampled, measured, cycle time taken; weight validated against the costing guess → Sales updates the '
      + 'quote (additional cost); revision levels increased per customer statement and validated as correctly '
      + 'implemented; second P&L: real time spent + extra costs.',
    artifacts: 'check completion per department; weight delta; revision bump; actuals P&L',
    note: 'Check workflows exist as the basis.',
    branch: 'not good → escalation (PM + Sales: new timing / more money) → back to implementation',
  },
  {
    n: 10, key: 'released', state: 'built',
    what: 'Validation good → implemented / released.',
    artifacts: 'release',
    note: 'Transition built.',
  },
]

const RULES = [
  'Scoped views everywhere: a department sees its own input only — at assessment AND costing. PM and Sales see all blocks.',
  'Tasks are mandatory — no accept/claim step; submitting names the owner.',
  'Sales owns the customer: mails tracked on the change (everyone uploads); escalations to the customer go through Sales.',
  'P&L twice: planned at costing/quoting, actuals at validation — the delta is the learning.',
  'The scheduling timeline is the leader from stage 7 on: samplings, blocked machines, department work and escalation all hang off it.',
]

const BUILD_ORDER = [
  'Finish in flight: costing positions + vendor quotes; the quoting stage.',
  'Weight quote at costing — Tooling Engineer states part weight (flagged as estimate), carried to validation.',
  'Negotiation loop at quoted — negotiation entries (date, channel, result), final result, Sales go-ahead (feeds existing acceptance).',
  'Scheduling block — bank-build plan on the change, running-change vs planned-scrap decision with scrap cost quote, "published to customer" stamp by Sales.',
  'Implementation tracking — per-department time booking, twice-weekly progress reports with at-risk flag, Sales escalation records (customer/internal).',
  'Validation checks — per-department checklist (sampled/measured/cycle time), weight validation with quote delta to Sales, revision-level bump validation, actuals P&L.',
  'Future tool: Sales timeline builder (MS-Project-like) — placeholder until then.',
]

function StageCard({ stage }: { stage: Stage }) {
  return (
    <section data-testid={`procmap-stage-${stage.key}`}
      className="rounded-lg border border-slate-700 bg-slate-800/60 px-4 py-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <span aria-hidden
          className="flex-shrink-0 rounded-full bg-slate-700 text-slate-300 w-6 h-6 inline-flex items-center justify-center text-xs font-semibold">
          {stage.n}
        </span>
        <h2 className="text-slate-100 font-medium">
          {t(`procmap.stage.${stage.key}`, 'de')}
        </h2>
        <span className="font-mono text-xs text-slate-500">{stage.key}</span>
        <span data-testid={`procmap-role-${stage.key}`}
          className="rounded border border-slate-600 px-1.5 py-0 text-[11px] leading-tight text-slate-300">
          {t(`procmap.role.${stage.key}`, 'de')}
        </span>
        <span data-testid={`procmap-status-${stage.key}`}
          className={`ml-auto rounded px-1.5 py-0 text-[10px] leading-tight font-semibold ${STATE_STYLE[stage.state]}`}>
          {STATE_LABEL[stage.state]}
        </span>
      </div>
      <p className="text-sm text-slate-300 mt-1">{stage.what}</p>
      <p className="text-xs text-slate-500 mt-1">
        <span className="uppercase tracking-wide">{t('procmap.artifacts')}</span>: {stage.artifacts}
      </p>
      {stage.note && (
        <p className="text-xs text-amber-200/80 mt-0.5"
          data-testid={`procmap-note-${stage.key}`}>
          {stage.note}
        </p>
      )}
    </section>
  )
}

export default function ProcessMapPage() {
  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      <div>
        <div className="flex items-baseline justify-between gap-3">
          <h1 className="text-2xl font-semibold text-slate-100">{t('procmap.title', 'de')}</h1>
          <Link to="/changes" className="text-sm text-sky-400 hover:underline">
            {t('procmap.backToChanges', 'de')}
          </Link>
        </div>
        <p className="text-sm text-slate-400 mt-1">
          The target state of the ECR module: who owns each stage, what it produces, and how much of it
          is built. Source of truth: <span className="font-mono">docs/ECR_PROCESS_MAP.md</span>.
        </p>
      </div>

      <div data-testid="procmap-flow" className="space-y-1">
        {STAGES.map((stage, i) => (
          <div key={stage.key}>
            <StageCard stage={stage} />
            {stage.branch && (
              <p data-testid={`procmap-branch-${stage.key}`}
                className="ml-8 mt-1 text-xs text-amber-300/90 border-l border-dashed border-amber-700/70 pl-3">
                ↳ {stage.branch}
              </p>
            )}
            {/* The straight line down the middle; a branch above it says where
                the flow can leave it. */}
            {i < STAGES.length - 1 && (
              <p aria-hidden className="text-center text-slate-600 leading-none py-1">▼</p>
            )}
          </div>
        ))}
      </div>

      <section data-testid="procmap-rules">
        <h2 className="text-lg font-semibold text-slate-100 mb-2">{t('procmap.rules', 'de')}</h2>
        <ul className="space-y-1 text-sm text-slate-300">
          {RULES.map((rule) => (
            <li key={rule} className="flex gap-2">
              <span aria-hidden className="text-slate-600">•</span>
              <span>{rule}</span>
            </li>
          ))}
        </ul>
      </section>

      <section data-testid="procmap-build-order">
        <h2 className="text-lg font-semibold text-slate-100 mb-2">{t('procmap.buildOrder', 'de')}</h2>
        <ol className="space-y-1 text-sm text-slate-300">
          {BUILD_ORDER.map((step, i) => (
            <li key={step} className="flex gap-2">
              <span className="text-slate-500 tabular-nums flex-shrink-0">{i + 1}.</span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}
