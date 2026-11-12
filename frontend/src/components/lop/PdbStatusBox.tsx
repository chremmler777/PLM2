/**
 * The project's live PDB status above the LOP: tools per status step and
 * one row per tool, read from GET /v1/lop/projects/{id}/pdb. PDB being down,
 * a missing status or a project without tools is said in words, never shown
 * as an empty table.
 */
import type { ReactNode } from 'react'
import type { LopLine, PdbResponse, PdbTool } from '../../types/lop'

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

function Step({ n, label, testId, warn = false }: { n: number; label: string; testId: string; warn?: boolean }) {
  return (
    <div data-testid={testId} className="min-w-[88px] flex-1 rounded border border-slate-700 bg-slate-900/40 px-2 py-1.5">
      <div className={`text-base font-semibold tabular-nums ${warn ? 'text-amber-300' : 'text-slate-100'}`}>{n}</div>
      <div className="text-[11px] text-slate-400">{label}</div>
    </div>
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

export default function PdbStatusBox({ pdb, loading = false, error = null }: {
  pdb?: PdbResponse; loading?: boolean; error?: string | null
}) {
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
        warn={escalated > 0}
        label={`${total === 1 ? 'open topic' : 'open topics'}${escalated ? ` · ${escalated} escalated` : ''}`}
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
    return (
      <>
        <div className="mb-2 flex flex-wrap gap-1.5">
          <Step testId="pdb-step-tools" n={status.tool_count} label="tools in project" />
          {STEPS.map((s) => (
            <Step key={s.key} testId={`pdb-step-${s.key}`} n={status.funnel?.[s.key] ?? 0} label={s.label} />
          ))}
          {topicsStep}
        </div>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-[11px] text-slate-400">
              <th className="py-1 pr-3 font-medium">Tool</th>
              <th className="py-1 pr-3 font-medium">Part</th>
              <th className="py-1 pr-3 font-medium">Process</th>
              <th className="py-1 pr-3 font-medium">Tool status</th>
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
                <td className="py-1 pr-3 tabular-nums">
                  {tool.open_topics ?? 0}
                  {esc > 0 && <span className="ml-1.5 rounded bg-red-900/50 px-1.5 text-[11px] text-red-200">{esc} escalated</span>}
                </td>
                <td className="py-1 tabular-nums text-slate-300">{oldest != null ? `${oldest} d` : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </>
    )
  }
  return (
    <section data-testid="pdb-status-box" aria-label="PDB status" className="mb-3 rounded-md border border-violet-800/60 bg-violet-950/20 px-3 py-2">
      <h4 className="mb-1.5 flex items-center gap-2 text-xs font-semibold text-slate-200">
        PDB status
        <span className="rounded border border-violet-700/70 px-1.5 text-[10px] font-normal text-violet-200">live from PDB, edited there</span>
      </h4>
      {body()}
    </section>
  )
}
