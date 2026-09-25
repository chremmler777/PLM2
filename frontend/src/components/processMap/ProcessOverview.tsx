/**
 * The ECR process on one page: the overview of the Process Flow.
 *
 * For auditors and staff who need the whole shape at a glance, not the
 * mechanics: every stage in one row with its owner, the gate into it and the
 * record it leaves behind, the two deadlines and the audit trail beneath, and
 * the three side tracks as slim lanes. Each box jumps into the detailed flow
 * and highlights the matching node there.
 *
 * Printable: the print stylesheet keeps only this sheet, black on white, on
 * one A4 landscape page. Plain HTML rather than SVG so the text wraps and
 * prints crisply at any scale.
 */
import type { MouseEvent } from 'react'
import {
  COLS, LANE_TONE, OVERVIEW_LANES, OVERVIEW_STAGES, type Gate,
} from './overviewData'

function GateChip({ gate }: { gate: Gate }) {
  return (
    <li className={`rounded border px-1 py-0.5 leading-snug ${gate.hard
      ? 'ov-hard border-red-400 bg-red-950/40 text-red-200'
      : 'ov-soft border-slate-500 text-slate-200'}`}>
      {gate.hard && <span className="font-bold">HARD </span>}
      {gate.text}
      {gate.soft && <span className="ov-muted text-slate-400"> (soft)</span>}
    </li>
  )
}

export default function ProcessOverview({ onJump }: { onJump: (target: string) => void }) {
  const jump = (target: string) => (e: MouseEvent) => {
    e.preventDefault()
    onJump(target)
  }
  return (
    <div id="procmap-overview" data-testid="procmap-overview"
      className="overflow-x-auto rounded-lg border border-slate-700 bg-slate-900/60 p-3 text-[11px] text-slate-300">
      <div className="min-w-[1000px] space-y-2.5">
        <header className="flex items-baseline justify-between gap-3">
          <h2 className="text-sm font-semibold text-slate-100">
            ECR process at a glance: stages, owners, gates, evidence
          </h2>
          <span className="ov-muted text-[11px] text-slate-400">
            Gate = condition to enter the stage · HARD = no deviation clears it · soft = overridable with a recorded reason
          </span>
        </header>

        <ol className="grid gap-1.5" style={{ gridTemplateColumns: COLS }}
          data-testid="procmap-overview-stages">
          {OVERVIEW_STAGES.map((s, i) => (
            <li key={s.key} className="flex">
              <a href={`#${s.target}`} onClick={jump(s.target)}
                data-testid={`procmap-ov-stage-${s.key}`}
                aria-label={`${s.name}: show in the detailed flow`}
                className="ov-soft group flex w-full flex-col gap-1.5 rounded-md border border-slate-600 bg-slate-800 p-1.5 hover:border-sky-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400">
                <div>
                  <div className="flex items-baseline gap-1">
                    <span className="ov-muted tabular-nums text-[11px] text-slate-400">{i + 1}</span>
                    <span className="text-[12px] font-semibold leading-tight text-slate-100 group-hover:text-sky-200">{s.name}</span>
                  </div>
                  <div className="ov-muted mt-0.5 text-[11px] leading-tight text-slate-400">{s.owner}</div>
                </div>
                <div>
                  <div className="ov-muted text-[11px] uppercase tracking-wide text-slate-400">Gate in</div>
                  <ul className="mt-0.5 space-y-0.5 text-[11px]">
                    {s.gates.map((g) => <GateChip key={g.text} gate={g} />)}
                  </ul>
                </div>
                <div>
                  <div className="ov-muted text-[11px] uppercase tracking-wide text-slate-400">Evidence</div>
                  <ul className="mt-0.5 space-y-0.5 text-[11px] leading-snug text-slate-300">
                    {s.evidence.map((ev) => <li key={ev}>{ev}</li>)}
                  </ul>
                </div>
              </a>
            </li>
          ))}
        </ol>

        {/* The two deadlines, under the stages they run through. */}
        <div className="grid gap-1.5 text-[11px]" style={{ gridTemplateColumns: COLS }}
          data-testid="procmap-overview-deadlines">
          <div className="ov-bar ov-soft rounded border border-sky-500/60 bg-sky-950/60 px-1.5 py-0.5 text-sky-200"
            style={{ gridColumn: '2 / 7' }}>
            Quote-by deadline active: Capture to Offer (customer changes); freezes the on-time fact
          </div>
          <div className="ov-bar ov-soft rounded border border-emerald-500/60 bg-emerald-950/60 px-1.5 py-0.5 text-emerald-200"
            style={{ gridColumn: '7 / 11' }}>
            Release-due deadline active: Timing to Release; moved only with an audited reason
          </div>
        </div>

        <p data-testid="procmap-overview-audit"
          className="ov-soft rounded border border-dashed border-slate-600 px-2 py-1 text-[11px] text-slate-300">
          <span className="font-semibold text-slate-100">Audit trail on every stage:</span>{' '}
          each decision writes its own entry (rejection, reopen, concern, meeting decision, deadline,
          offer, deviation, issue route and escalation), with who, when and why.
        </p>

        <section data-testid="procmap-overview-lanes" className="space-y-1">
          <h3 className="ov-muted text-[11px] uppercase tracking-wide text-slate-400">Side tracks</h3>
          {OVERVIEW_LANES.map((lane) => (
            <a key={lane.key} href={`#${lane.target}`} onClick={jump(lane.target)}
              data-testid={`procmap-ov-lane-${lane.key}`}
              aria-label={`${lane.name}: show in the detailed flow`}
              className={`ov-soft grid grid-cols-[180px_1fr] items-start gap-2 rounded-md border bg-slate-800/60 px-2 py-1 hover:border-sky-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400 ${LANE_TONE[lane.tone].border}`}>
              <div>
                <div className={`text-[11px] font-semibold leading-tight ${LANE_TONE[lane.tone].text}`}>{lane.name}</div>
                <div className="ov-muted text-[11px] text-slate-400">{lane.joins}</div>
              </div>
              <div>
                <ol className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-[11px] text-slate-200">
                  {lane.steps.map((step, i) => (
                    <li key={step} className="flex items-center gap-1">
                      {i > 0 && <span aria-hidden className="ov-muted text-slate-400">→</span>}
                      <span className="ov-soft rounded border border-slate-600 px-1 py-px">{step}</span>
                    </li>
                  ))}
                </ol>
                <p className="ov-muted mt-0.5 text-[11px] leading-snug text-slate-400">{lane.note}</p>
              </div>
            </a>
          ))}
        </section>

        <footer className="ov-muted flex justify-between gap-3 text-[11px] text-slate-400">
          <span>Source: docs/ECR_PROCESS_MAP.md, docs/CHANGE_MANAGEMENT_FLOW.md. The detailed flow on this page shows every decision, loop and exit.</span>
          <span>PLM v2 · ECR process overview</span>
        </footer>
      </div>
    </div>
  )
}
