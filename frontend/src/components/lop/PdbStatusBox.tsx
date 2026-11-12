/**
 * The project's live PDB status above the LOP, read from
 * GET /v1/lop/projects/{id}/pdb. It opens small: the tools per status step,
 * the open topics and how many tools that are not A/A have no sampling
 * planned. "Show tools" opens one row per tool with its next planned
 * sampling (red when a tool that is not A/A has none); the choice is kept
 * per browser. The topics count, and each tool's count, open the list of
 * what is open. PDB being down, a missing status or a project without tools
 * is said in words, never shown as an empty table.
 */
import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { lopApi, lopKeys } from '../../api/lop'
import Dialog from '../common/Dialog'
import { escalationLabel, shortDay } from '../../lib/lop'
import type { LopLine, PdbResponse, PdbTool } from '../../types/lop'

const OPEN_KEY = 'plm2.lop.pdbBoxOpen'
function readOpen(): boolean {
  try { return window.localStorage.getItem(OPEN_KEY) === '1' } catch { return false }
}
function writeOpen(v: boolean) {
  try { window.localStorage.setItem(OPEN_KEY, v ? '1' : '0') } catch { /* private window: not kept */ }
}

/** Process and tool status both A: the tool needs no further sampling. */
const isAA = (t: PdbTool) => (t.ps ?? '').toUpperCase() === 'A' && (t.ts ?? '').toUpperCase() === 'A'
/** A tool that is not A/A and has no sampling on the calendar. */
export const needsSampling = (t: PdbTool) => !isAA(t) && !t.next_sampling

const STEPS: { key: 'sampling' | 'qualifying' | 'technical_handover' | 'ready' | 'series'; label: string }[] = [
  { key: 'sampling', label: 'Sampling' },
  { key: 'qualifying', label: 'Qualifying' },
  { key: 'technical_handover', label: 'Technical handover' },
  { key: 'ready', label: 'Ready' },
  { key: 'series', label: 'Series' },
]

const LETTER_TONE: Record<string, string> = {
  A: 'bg-emerald-800/70 text-emerald-100',
  B: 'bg-amber-700/70 text-amber-50',
  C: 'bg-red-800/70 text-red-50',
}

function Letter({ value, label }: { value: string | null | undefined; label: string }) {
  if (!value) return <span className="text-slate-500">-</span>
  const tone = LETTER_TONE[value.toUpperCase()] ?? 'bg-slate-700 text-slate-200'
  return (
    <span title={`${label} ${value}`} className={`inline-flex h-5 min-w-5 items-center justify-center rounded px-1 text-[11px] font-semibold ${tone}`}>
      {value}
    </span>
  )
}

type Tone = 'plain' | 'warn' | 'bad'
const STEP_TONE: Record<Tone, string> = { plain: 'text-slate-100', warn: 'text-amber-300', bad: 'text-red-300' }

/** A number with its label; with onClick it is a button that opens the lines behind it. */
function Step({ n, label, testId, tone = 'plain', onClick, title }: {
  n: number; label: string; testId: string; tone?: Tone; onClick?: () => void; title?: string
}) {
  const box = 'min-w-[88px] flex-1 rounded border border-slate-700 bg-slate-900/40 px-2 py-1.5 text-left'
  const inner = (
    <>
      <div className={`text-base font-semibold tabular-nums ${STEP_TONE[tone]}`}>{n}</div>
      <div className="text-[11px] text-slate-400">{label}</div>
    </>
  )
  if (!onClick) return <div data-testid={testId} className={box}>{inner}</div>
  return (
    <button type="button" data-testid={testId} title={title} onClick={onClick}
      className={`${box} hover:border-sky-600 hover:bg-slate-900/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400`}>
      {inner}
    </button>
  )
}

/** The "Next sampling" cell: the booked slot, or in red that a tool that is
 *  not A/A has none (with the open wish's week, when there is one). */
function NextSampling({ tool }: { tool: PdbTool }) {
  const s = tool.next_sampling
  if (s) {
    return (
      <span data-testid="pdb-next-sampling" className="tabular-nums text-slate-200">
        {shortDay(s.start_date)}
        {s.machine && <span className="text-slate-400">{` · ${s.machine}`}</span>}
        {s.state !== 'confirmed' && <span className="ml-1.5 rounded bg-amber-900/50 px-1.5 text-[11px] text-amber-200">not confirmed</span>}
      </span>
    )
  }
  if (isAA(tool)) return <span className="text-slate-500">-</span>
  return (
    <span data-testid="pdb-next-sampling" className="font-medium text-red-300">
      none planned
      {tool.sampling_requested_week && (
        <span className="font-normal">{` · requested for week of ${shortDay(tool.sampling_requested_week)}, no slot yet`}</span>
      )}
    </span>
  )
}

/** What is open in PDB, for a quick look: escalated first, then oldest. For
 *  one tool or for the whole project. Reads every open topic when the box
 *  only holds the first ones. */
function TopicsDialog({ projectId, pdb, tool, onClose }: {
  projectId?: number; pdb: PdbResponse; tool: string | null; onClose: () => void
}) {
  const needAll = (pdb.hidden ?? 0) > 0 && projectId != null
  const all = useQuery({
    queryKey: lopKeys.pdb(projectId ?? 0, true),
    queryFn: () => lopApi.pdb(projectId as number, true),
    enabled: needAll,
  })
  const source = needAll ? all.data?.topics : pdb.topics
  const rows = (source ?? []).filter((t) => tool == null || t.tool_number === tool)
  return (
    <Dialog open onClose={onClose} size="xl" data-testid="pdb-topics-dialog"
      title={tool ? `Open PDB topics · tool ${tool}` : 'Open PDB topics'}
      description="Live from PDB, escalated first, then oldest. Topics are worked on in PDB.">
      {needAll && all.isLoading ? (
        <p className="py-2 text-sm text-slate-400">Reading PDB…</p>
      ) : needAll && all.isError ? (
        <p role="alert" className="py-2 text-sm text-amber-300">The topics could not be read from PDB.</p>
      ) : rows.length === 0 ? (
        <p className="py-2 text-sm text-slate-400">No open topics.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-400">
              {tool == null && <th className="py-1.5 pr-3 font-medium">Tool</th>}
              <th className="py-1.5 pr-3 font-medium">Topic</th>
              <th className="py-1.5 pr-3 font-medium">Department</th>
              <th className="py-1.5 pr-3 font-medium text-right">Open</th>
              <th className="py-1.5 font-medium">Name and date</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => {
              const [issue, ...rest] = (t.text ?? t.title ?? '').split('\n')
              const level = escalationLabel(t.escalation_level)
              return (
                <tr key={t.ref_key ?? t.id} data-testid="pdb-topic-row" className="border-t border-slate-700/60 align-top text-slate-200">
                  {tool == null && <td className="py-1.5 pr-3 font-medium tabular-nums">{t.tool_number}</td>}
                  <td className="py-1.5 pr-3">
                    {issue}
                    {rest.length > 0 && <div className="text-xs text-slate-400">{rest.join(' ')}</div>}
                    {t.handover_impact && <span className="mr-1.5 text-xs text-amber-300">blocks handover</span>}
                  </td>
                  <td className="py-1.5 pr-3 text-xs text-slate-300">{t.pdb_department ?? t.department_name ?? '-'}</td>
                  <td className="py-1.5 pr-3 text-right text-xs tabular-nums whitespace-nowrap">
                    {t.age_days != null ? `${t.age_days} d` : ''}
                    {level && <span className={`ml-1.5 rounded px-1.5 text-[11px] ${t.escalated ? 'bg-red-900/50 text-red-200' : 'bg-amber-900/50 text-amber-200'}`}>{level}</span>}
                  </td>
                  <td className="py-1.5 text-xs">
                    {t.pinned
                      ? <span className="text-slate-200">{t.responsible_name ?? 'no name'}{t.due_date ? ` · ${shortDay(t.due_date)}` : ''}</span>
                      : <span className="text-slate-500">not pinned</span>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </Dialog>
  )
}

function toolRows(tools: PdbTool[], topics: LopLine[]) {
  return tools.map((t) => {
    const mine = topics.filter((x) => x.tool_number === t.tool_number)
    const ages = mine.map((x) => x.age_days).filter((a): a is number => a != null)
    return {
      tool: t,
      escalated: mine.filter((x) => x.escalated).length,
      oldest: ages.length ? Math.max(...ages) : null,
    }
  })
}

function Note({ children, tone = 'muted' }: { children: ReactNode; tone?: 'muted' | 'warn' }) {
  return <p className={`text-xs ${tone === 'warn' ? 'text-amber-300' : 'text-slate-400'}`}>{children}</p>
}

export default function PdbStatusBox({ pdb, loading = false, error = null, projectId }: {
  pdb?: PdbResponse; loading?: boolean; error?: string | null
  /** Lets the topics list read every open topic when the box holds only the first ones. */
  projectId?: number
}) {
  const [open, setOpen] = useState(readOpen)
  /** undefined: closed; null: all tools; else one tool number. */
  const [topicsOf, setTopicsOf] = useState<string | null | undefined>(undefined)
  const toggle = () => setOpen((v) => { writeOpen(!v); return !v })
  let canExpand = false

  const body = () => {
    if (error) return <Note tone="warn">PDB cannot be reached: {error}</Note>
    if (loading || !pdb) return <Note>Reading PDB…</Note>
    if (!pdb.available) {
      return <Note tone="warn">PDB cannot be reached{pdb.reason ? `: ${pdb.reason}` : ''}. Tool status and PDB topics are missing here.</Note>
    }
    const total = pdb.topics.length + (pdb.hidden ?? 0)
    const escalated = pdb.topics.filter((t) => t.escalated).length
    const topicsStep = (
      <Step
        testId="pdb-step-topics"
        n={total}
        tone={escalated > 0 ? 'warn' : 'plain'}
        label={`${total === 1 ? 'open topic' : 'open topics'}${escalated ? ` · ${escalated} escalated` : ''}`}
        onClick={total > 0 ? () => setTopicsOf(null) : undefined}
        title="Show what is open"
      />
    )
    const status = pdb.status
    if (!status) {
      return (
        <>
          <Note tone="warn">The PDB status could not be read{pdb.status_reason ? `: ${pdb.status_reason}` : ''}. The topics below are live.</Note>
          <div className="mt-2 flex flex-wrap gap-1.5">{topicsStep}</div>
        </>
      )
    }
    if (status.tool_count === 0 || status.tools.length === 0) return <Note>No tools in TWOS/PDB yet.</Note>
    canExpand = true
    const notAA = status.tools.filter((t) => !isAA(t)).length
    const unplanned = status.tools.filter(needsSampling).length
    return (
      <>
        <div className="flex flex-wrap gap-1.5">
          <Step testId="pdb-step-tools" n={status.tool_count} label="tools in project" />
          {STEPS.map((s) => (
            <Step key={s.key} testId={`pdb-step-${s.key}`} n={status.funnel?.[s.key] ?? 0} label={s.label} />
          ))}
          {topicsStep}
          <Step testId="pdb-step-unplanned" n={unplanned} tone={unplanned > 0 ? 'bad' : 'plain'}
            label={`of ${notAA} not A/A without planned sampling`}
            onClick={open ? undefined : toggle} title="Show the tools" />
        </div>
        {open && (
        <table className="mt-2 w-full text-xs">
          <thead>
            <tr className="text-left text-[11px] text-slate-400">
              <th className="py-1 pr-3 font-medium">Tool</th>
              <th className="py-1 pr-3 font-medium">Part</th>
              <th className="py-1 pr-3 font-medium">Process</th>
              <th className="py-1 pr-3 font-medium">Tool status</th>
              <th className="py-1 pr-3 font-medium">Next sampling</th>
              <th className="py-1 pr-3 font-medium">Open topics</th>
              <th className="py-1 font-medium">Oldest</th>
            </tr>
          </thead>
          <tbody>
            {toolRows(status.tools, pdb.topics).map(({ tool, escalated: esc, oldest }) => (
              <tr key={tool.tool_number} data-testid="pdb-tool-row" className="border-t border-slate-700/60 text-slate-200">
                <td className="py-1 pr-3 font-medium tabular-nums">{tool.tool_number}</td>
                <td className="py-1 pr-3">{tool.tool_name ?? ''}</td>
                <td className="py-1 pr-3"><Letter value={tool.ps} label="Process status" /></td>
                <td className="py-1 pr-3"><Letter value={tool.ts} label="Tool status" /></td>
                <td className="py-1 pr-3"><NextSampling tool={tool} /></td>
                <td className="py-1 pr-3 tabular-nums">
                  {(tool.open_topics ?? 0) > 0 ? (
                    <button type="button" data-testid="pdb-tool-topics" title="Show what is open on this tool"
                      onClick={() => setTopicsOf(tool.tool_number)}
                      className="rounded px-1 text-sky-300 underline decoration-dotted underline-offset-2 hover:text-sky-200">
                      {tool.open_topics}
                    </button>
                  ) : 0}
                  {esc > 0 && <span className="ml-1.5 rounded bg-red-900/50 px-1.5 text-[11px] text-red-200">{esc} escalated</span>}
                </td>
                <td className="py-1 tabular-nums text-slate-300">{oldest != null ? `${oldest} d` : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
        )}
      </>
    )
  }
  const content = body()
  return (
    <section data-testid="pdb-status-box" aria-label="PDB status" className="mb-3 rounded-md border border-violet-800/60 bg-violet-950/20 px-3 py-2">
      <h4 className="mb-1.5 flex items-center gap-2 text-xs font-semibold text-slate-200">
        PDB status
        <span className="rounded border border-violet-700/70 px-1.5 text-[10px] font-normal text-violet-200">live from PDB, edited there</span>
        {canExpand && (
          <button type="button" data-testid="pdb-box-toggle" aria-expanded={open} onClick={toggle}
            className="ml-auto inline-flex items-center gap-1 rounded border border-slate-600 px-2 py-0.5 text-[11px] font-normal text-slate-200 hover:bg-slate-700/60">
            {open ? <ChevronUp aria-hidden="true" size={12} /> : <ChevronDown aria-hidden="true" size={12} />}
            {open ? 'Hide tools' : 'Show tools'}
          </button>
        )}
      </h4>
      {content}
      {topicsOf !== undefined && pdb?.available && (
        <TopicsDialog projectId={projectId} pdb={pdb} tool={topicsOf} onClose={() => setTopicsOf(undefined)} />
      )}
    </section>
  )
}
