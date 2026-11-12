/**
 * LopOverviewPage - the project LOPs (lists of open points) of every project
 * side by side, for whoever steers them (Cody's page). Control comes first:
 * how many open lines have a name and a date. Then what is stale, late or was
 * not touched in the last meeting, on-time closing and moved dates, per
 * project (with its current SEP gate and the PDB numbers) and per department,
 * and what is escalated. Every count of lines opens those lines in a side
 * list (GET /v1/lop/lines with the same filter); each line opens its
 * project's LOP page. Read-only; same hand-rolled Tailwind as the ECR KPI
 * board (no chart library).
 */
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { lopApi, lopOverviewKeys } from '../api/lop'
import Dialog from '../components/common/Dialog'
import { lopErrorMessage } from '../components/lop/useLopWrite'
import { dueLabel, shortDay, staleLabel } from '../lib/lop'
import type {
  LopDepartmentKpi, LopEscalation, LopEscalationReason, LopFlag, LopKpi, LopLinesQuery, LopProjectKpi,
} from '../types/lop'

/** "82 %", or "n/a" when there is nothing to measure against. */
const pctLabel = (v: number | null | undefined) => (v == null ? 'n/a' : `${v} %`)
const numLabel = (v: number | null | undefined) => (v == null ? 'n/a' : String(v))
const plural = (n: number, one: string, many: string) => (n === 1 ? one : many)

const FLAG_TITLE: Record<LopFlag, string> = {
  open: 'Open lines',
  stale: staleLabel(),
  late: 'Late',
  no_control: 'Without a name or a date',
  untouched: 'Not touched in the last meeting',
}

/** What a count means, for the button's accessible name. */
function countWords(flag: LopFlag, n: number): string {
  const lines = plural(n, 'line', 'lines')
  switch (flag) {
    case 'open': return `${n} open ${lines}`
    case 'stale': return `${n} ${lines} with no update for 14 days`
    case 'late': return `${n} late ${lines}`
    case 'no_control': return `${n} ${lines} without a name or a date`
    case 'untouched': return `${n} ${lines} not touched in the last meeting`
  }
}

/** A selection of lines to list: the query, the dialog title, and the number that opened it. */
interface Selection {
  query: LopLinesQuery
  title: string
}

type Open = (flag: LopFlag, scope: Scope) => (el: HTMLElement) => void

/** Who a count belongs to: all projects, one project or one department. */
interface Scope {
  label: string
  project_id?: number
  /** 0 = no department. */
  department_id?: number
}

const ALL: Scope = { label: 'all projects' }

const countBtn =
  'rounded tabular-nums underline decoration-slate-500 decoration-dotted underline-offset-4 ' +
  'hover:text-sky-300 hover:decoration-sky-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400'

/** A count of lines: a button that lists them, plain text when there is nothing to list.
 *  `shown` replaces the number on screen (a percentage whose missing part is listed). */
function Count({ n, flag, scope, onOpen, shown, tone = '' }: {
  n: number; flag: LopFlag; scope: Scope; onOpen: Open; shown?: string; tone?: string
}) {
  const text = shown ?? String(n)
  if (n <= 0) return <span className="tabular-nums">{text}</span>
  const words = countWords(flag, n)
  return (
    <button type="button" className={`${countBtn} ${tone}`}
      aria-label={shown ? `${shown}, ${scope.label}: ${words}` : `${scope.label}: ${words}`}
      title={`Show the ${words}`}
      onClick={(e) => onOpen(flag, scope)(e.currentTarget)}>
      {text}
    </button>
  )
}

const lateTone = (n: number) => (n > 0 ? 'text-red-400' : '')
const staleTone = (n: number) => (n > 0 ? 'text-amber-300' : '')

// ------------------------------------------------------------------ tiles
function Tile({ kpi, label, children, note, wide = false }: {
  kpi: string; label: string; children: ReactNode; note?: ReactNode; wide?: boolean
}) {
  return (
    <div data-testid="lop-tile" data-kpi={kpi}
      className={`min-w-0 px-4 py-3 ${wide ? 'col-span-2 md:col-span-1' : ''}`}>
      <dt className="text-xs leading-snug text-slate-400">{label}</dt>
      <dd className={`mt-1 font-semibold tabular-nums text-slate-100 ${wide ? 'text-4xl' : 'text-2xl'}`}>{children}</dd>
      {note && <dd className="mt-0.5 text-xs text-slate-400">{note}</dd>}
    </div>
  )
}

/** The PDB total only counts projects PDB answered for: say which part is missing. */
function pdbTotal(projects: LopProjectKpi[], total: number): { value: string; note: string } {
  const down = projects.filter((p) => !p.pdb?.available).length
  if (projects.length > 0 && down === projects.length) return { value: 'n/a', note: 'PDB not reachable' }
  if (down > 0) return { value: String(total), note: `PDB not reachable for ${down} of ${projects.length} projects` }
  return { value: String(total), note: 'not pinned to a LOP' }
}

function Tiles({ totals, projects, onOpen }: {
  totals: LopKpi & { pdb_without_name_and_date: number }; projects: LopProjectKpi[]; onOpen: Open
}) {
  const controlled = totals.open - totals.no_control
  const pdb = pdbTotal(projects, totals.pdb_without_name_and_date)
  return (
    <section aria-label="All projects" className="mb-4 rounded-lg border border-slate-700 bg-slate-800">
      <dl className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-[1.4fr_repeat(7,minmax(0,1fr))] [&>div]:border-slate-700/70 max-xl:[&>div]:border-b xl:[&>div:not(:first-child)]:border-l">
        <Tile kpi="control" label="Lines with a name and a date" wide
          note={totals.open === 0 ? 'No open lines' : (
            <>
              {controlled} of {totals.open} open ·{' '}
              <Count n={totals.no_control} flag="no_control" scope={ALL} onOpen={onOpen} /> without
            </>
          )}>
          <span className="text-sky-300">{pctLabel(totals.with_name_and_date_pct)}</span>
        </Tile>
        <Tile kpi="stale" label={staleLabel()}>
          <Count n={totals.stale} flag="stale" scope={ALL} onOpen={onOpen} tone={staleTone(totals.stale)} />
        </Tile>
        <Tile kpi="late" label="Late"
          note={totals.late > 0 ? `avg ${totals.avg_days_late} days late` : undefined}>
          <Count n={totals.late} flag="late" scope={ALL} onOpen={onOpen} tone={lateTone(totals.late)} />
        </Tile>
        <Tile kpi="untouched" label="Not touched in the last meeting">
          <Count n={totals.untouched_last_meeting} flag="untouched" scope={ALL} onOpen={onOpen} />
        </Tile>
        <Tile kpi="on_time" label="Closed on time, last 4 weeks" note="against the first due date">
          {pctLabel(totals.on_time_pct_4w)}
        </Tile>
        <Tile kpi="moved" label="Dates moved, last 4 weeks">{totals.dates_moved_4w}</Tile>
        <Tile kpi="week" label="Opened / closed this week">
          {totals.opened_week} <span className="font-normal text-slate-500">/</span> {totals.closed_week}
        </Tile>
        <Tile kpi="pdb" label="PDB topics without name and date" note={pdb.note}>
          {pdb.value}
        </Tile>
      </dl>
    </section>
  )
}

// ------------------------------------------------------------- escalations
const REASON_TEXT: Record<LopEscalationReason, string> = {
  hand: 'escalated by the PM in the last meeting',
  late: 'late at two meetings in a row',
  stale: 'no update at two meetings in a row',
  late_or_stale: 'late or without update at two meetings in a row',
}

/** The server says why (LopMeetings.escalations); `since` is that meeting's day. */
function lineReason(e: Extract<LopEscalation, { kind: 'line' }>): string {
  const day = shortDay(e.since)
  if (e.reason === 'hand') return `${REASON_TEXT.hand} (${day})`
  return `${REASON_TEXT[e.reason] ?? 'escalated'} since ${day}`
}

function Escalations({ rows }: { rows: LopEscalation[] }) {
  const headingId = useId()
  return (
    <section aria-labelledby={headingId} className="mb-4 rounded-lg border border-slate-700 bg-slate-800 p-4">
      <h2 id={headingId} className="mb-2 text-sm font-semibold text-slate-200">
        Escalated{rows.length > 0 && <span className="font-normal text-slate-400"> ({rows.length})</span>}
      </h2>
      {rows.length === 0 ? (
        <p className="text-sm text-slate-400">Nothing escalated.</p>
      ) : (
        <ul aria-label="Escalated" className="divide-y divide-slate-700/60 text-sm text-slate-300">
          {rows.map((e) => {
            const link = (
              <Link to={`/projects/${e.project_id}/lop`} className="font-medium tabular-nums text-sky-400 hover:text-sky-300 hover:underline">
                {e.project_code}
              </Link>
            )
            if (e.kind === 'no_meeting') {
              return (
                <li key={`m-${e.project_id}`} className="py-1.5">
                  {link}
                  {` · no LOP meeting since ${shortDay(e.since)} · PM ${e.pm_name ?? 'not named'}`}
                </li>
              )
            }
            const l = e.line
            return (
              <li key={`l-${l.id}`} className="py-1.5">
                {link}
                <span className="text-slate-100">{` · #${l.id} ${l.text ?? l.title ?? ''}`}</span>
                {l.department_name && ` · ${l.department_name}`}
                {` · ${l.responsible_name ?? 'no name'} · `}
                <span className="text-red-300">{lineReason(e)}</span>
                {l.days_late > 0 && <span className="tabular-nums">{` · ${l.days_late} d late`}</span>}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

// ------------------------------------------------------------------ tables
const th = 'py-1.5 pr-3 font-normal whitespace-nowrap'
const thNum = `${th} text-right`
const td = 'py-1.5 pr-3 align-top'
const tdNum = `${td} text-right tabular-nums whitespace-nowrap`

/** Open, name + date %, stale, late, not touched, on time %, moved: the KPI columns both tables share. */
function KpiHeads() {
  return (
    <>
      <th scope="col" className={thNum}>Open</th>
      <th scope="col" className={thNum}>Name + date %</th>
      <th scope="col" className={thNum}>Stale</th>
      <th scope="col" className={thNum}>Late</th>
      <th scope="col" className={thNum}>Not touched</th>
      <th scope="col" className={thNum}>On time %</th>
      <th scope="col" className={thNum}>Moved</th>
    </>
  )
}

function KpiCells({ row, scope, onOpen }: { row: LopKpi; scope: Scope; onOpen: Open }) {
  return (
    <>
      <td className={tdNum}><Count n={row.open} flag="open" scope={scope} onOpen={onOpen} /></td>
      <td className={tdNum}>
        <Count n={row.no_control} flag="no_control" scope={scope} onOpen={onOpen} shown={pctLabel(row.with_name_and_date_pct)} />
      </td>
      <td className={tdNum}><Count n={row.stale} flag="stale" scope={scope} onOpen={onOpen} tone={staleTone(row.stale)} /></td>
      <td className={tdNum}>
        <Count n={row.late} flag="late" scope={scope} onOpen={onOpen} tone={lateTone(row.late)} />
        {row.late > 0 && <span className="text-xs text-slate-500"> · avg {row.avg_days_late} d</span>}
      </td>
      <td className={tdNum}><Count n={row.untouched_last_meeting} flag="untouched" scope={scope} onOpen={onOpen} /></td>
      <td className={tdNum}>{pctLabel(row.on_time_pct_4w)}</td>
      <td className={tdNum}>{row.dates_moved_4w}</td>
    </>
  )
}

function gateLabel(gate: LopProjectKpi['gate']): string {
  if (!gate) return 'no gate'
  return `${gate.code} · ${pctLabel(gate.done_pct)} · ${gate.target_date ? shortDay(gate.target_date) : 'no gate date'}`
}

function TableSection({ title, children }: { title: string; children: (headingId: string) => ReactNode }) {
  const headingId = useId()
  return (
    <section aria-labelledby={headingId} className="mb-4 rounded-lg border border-slate-700 bg-slate-800 p-4">
      <h2 id={headingId} className="mb-3 text-sm font-semibold text-slate-200">{title}</h2>
      <div className="overflow-x-auto">{children(headingId)}</div>
    </section>
  )
}

function ProjectTable({ rows, onOpen }: { rows: LopProjectKpi[]; onOpen: Open }) {
  return (
    <TableSection title="By project">
      {(id) => rows.length === 0 ? (
        <p className="text-sm text-slate-400">No project has its LOP switched on.</p>
      ) : (
        <table aria-labelledby={id} className="w-full text-sm">
          <thead>
            <tr className="text-[11px] uppercase tracking-wide text-slate-500">
              <th scope="col" className={th}><span className="sr-only">Project</span></th>
              <th scope="colgroup" colSpan={7} className={`${th} border-b border-slate-700/70 text-center`}>LOP lines</th>
              <th scope="col" className={`${th} border-b border-slate-700/70 pl-3`}>SEP</th>
              <th scope="colgroup" colSpan={4} className={`${th} border-b border-slate-700/70 text-center`}>PDB</th>
            </tr>
            <tr className="border-b border-slate-700 text-left text-xs text-slate-400">
              <th scope="col" className={th}>Project</th>
              <KpiHeads />
              <th scope="col" className={`${th} pl-3`}>Current gate</th>
              <th scope="col" className={thNum}>Tools C / B / A</th>
              <th scope="col" className={thNum}>Topics open</th>
              <th scope="col" className={thNum}>Escalated</th>
              <th scope="col" className={thNum}>Without name and date</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => {
              const scope: Scope = { label: `${p.code} ${p.name}`, project_id: p.project_id }
              const pdb = p.pdb
              return (
                <tr key={p.project_id} className="border-b border-slate-700/50 last:border-0 hover:bg-slate-700/20">
                  <td className={`${td} whitespace-nowrap`}>
                    <Link to={`/projects/${p.project_id}/lop`} className="font-medium tabular-nums text-sky-400 hover:text-sky-300 hover:underline">
                      {p.code}
                    </Link>
                    <span className="text-slate-400"> {p.name}</span>
                  </td>
                  <KpiCells row={p} scope={scope} onOpen={onOpen} />
                  <td className={`${td} whitespace-nowrap pl-3 tabular-nums text-slate-300`}>{gateLabel(p.gate)}</td>
                  {pdb.available ? (
                    <>
                      <td className={tdNum}>{numLabel(pdb.tools_c)} / {numLabel(pdb.tools_b)} / {numLabel(pdb.tools_a)}</td>
                      <td className={tdNum}>{numLabel(pdb.open_topics)}</td>
                      <td className={`${tdNum} ${(pdb.escalated ?? 0) > 0 ? 'text-red-400' : ''}`}>{numLabel(pdb.escalated)}</td>
                      <td className={tdNum}>{numLabel(pdb.pdb_without_name_and_date)}</td>
                    </>
                  ) : (
                    <td colSpan={4} className={`${td} text-right text-slate-500`}>PDB not reachable</td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </TableSection>
  )
}

function DepartmentTable({ rows, onOpen }: { rows: LopDepartmentKpi[]; onOpen: Open }) {
  return (
    <TableSection title="By department">
      {(id) => rows.length === 0 ? (
        <p className="text-sm text-slate-400">No lines yet.</p>
      ) : (
        <table aria-labelledby={id} className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700 text-left text-xs text-slate-400">
              <th scope="col" className={th}>Department</th>
              <KpiHeads />
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => {
              const scope: Scope = { label: d.name, department_id: d.department_id ?? 0 }
              return (
                <tr key={d.department_id ?? 'none'} className="border-b border-slate-700/50 last:border-0 hover:bg-slate-700/20">
                  <td className={`${td} whitespace-nowrap ${d.department_id == null ? 'text-slate-400' : 'text-slate-200'}`}>{d.name}</td>
                  <KpiCells row={d} scope={scope} onOpen={onOpen} />
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </TableSection>
  )
}

// -------------------------------------------------------------- side list
function LinesDialog({ selection, onClose }: { selection: Selection | null; onClose: () => void }) {
  const query = selection?.query ?? {}
  const lines = useQuery({
    queryKey: lopOverviewKeys.lines(query),
    queryFn: () => lopApi.lines(query),
    enabled: !!selection,
  })
  const rows = Array.isArray(lines.data) ? lines.data : []
  return (
    <Dialog open={!!selection} onClose={onClose} size="lg" title={selection?.title ?? ''}
      description={lines.isSuccess ? `${rows.length} ${plural(rows.length, 'line', 'lines')}; a line opens its project's LOP.` : undefined}
      className="sm:mr-4" data-testid="lop-lines-dialog">
      {lines.isLoading ? (
        <p className="py-2 text-slate-400">Loading the lines…</p>
      ) : lines.isError ? (
        <p role="alert" className="py-2 text-red-300">{lopErrorMessage(lines.error, 'The lines could not be loaded.')}</p>
      ) : rows.length === 0 ? (
        <p className="py-2 text-slate-400">Nothing to show.</p>
      ) : (
        <ul className="divide-y divide-slate-700/60 pb-2">
          {rows.map((l) => (
            <li key={l.id ?? `${l.project_code}-${l.ref_key}`} className="grid grid-cols-[4rem_minmax(0,1fr)] gap-x-3 py-2">
              <span className="tabular-nums text-slate-400">{l.project_code}</span>
              <span className="min-w-0">
                <Link to={`/projects/${l.project_id}/lop`} className="text-slate-100 hover:text-sky-300 hover:underline">
                  {l.text ?? l.title}
                </Link>
                <span className="mt-0.5 block text-xs text-slate-400">
                  {l.department_name ?? 'No department'} · {l.responsible_name ?? 'no name'} ·{' '}
                  <span className={`tabular-nums ${l.late ? 'text-red-300' : ''}`}>{dueLabel(l)}</span>
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  )
}

// -------------------------------------------------------------------- page
export default function LopOverviewPage() {
  const overview = useQuery({ queryKey: lopOverviewKeys.overview, queryFn: lopApi.overview })
  const [selection, setSelection] = useState<Selection | null>(null)
  const trigger = useRef<HTMLElement | null>(null)
  const wasOpen = useRef(false)

  // Back to the number that opened the list (also where a click does not focus a button).
  useEffect(() => {
    if (selection) { wasOpen.current = true; return }
    if (wasOpen.current) {
      wasOpen.current = false
      if (trigger.current?.isConnected) trigger.current.focus({ preventScroll: true })
    }
  }, [selection])

  const open: Open = (flag, scope) => (el) => {
    trigger.current = el
    const query: LopLinesQuery = {}
    if (scope.project_id != null) query.project_id = scope.project_id
    if (scope.department_id != null) query.department_id = scope.department_id
    query.flag = flag
    setSelection({ query, title: `${FLAG_TITLE[flag]} · ${scope.label}` })
  }

  const data = overview.data
  return (
    <div className="mx-auto max-w-7xl p-6">
      <div className="mb-5">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">LOP overview</h1>
        <p className="mt-1 text-sm text-slate-400">
          Open points of every project LOP: who has a name and a date, what is late, what nobody touched.
          A number opens its lines.
        </p>
      </div>

      {overview.isError ? (
        <div className="rounded-lg border border-red-900/50 bg-slate-800 p-4">
          <p role="alert" className="text-sm text-red-300">
            The overview could not be loaded: {lopErrorMessage(overview.error, 'no answer from the server')}
          </p>
          <button type="button" onClick={() => void overview.refetch()} className="mt-2 text-xs text-sky-400 hover:underline">
            Retry
          </button>
        </div>
      ) : overview.isLoading || !data ? (
        <p className="text-sm text-slate-400">Loading the overview… (it asks PDB for every project)</p>
      ) : (
        <>
          <Tiles totals={data.totals} projects={Array.isArray(data.projects) ? data.projects : []} onOpen={open} />
          <Escalations rows={Array.isArray(data.escalations) ? data.escalations : []} />
          <ProjectTable rows={Array.isArray(data.projects) ? data.projects : []} onOpen={open} />
          <DepartmentTable rows={Array.isArray(data.departments) ? data.departments : []} onOpen={open} />
        </>
      )}

      <LinesDialog selection={selection} onClose={() => setSelection(null)} />
    </div>
  )
}
